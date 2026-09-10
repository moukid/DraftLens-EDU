"""Policy checks run in disposable Git repositories, never the user's checkout."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.check_cad_policy import check
from scripts.generate_samples import make
from tests.synthetic_data import data_root

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    assert git(repo, "init").returncode == 0
    assert git(repo, "config", "user.name", "Synthetic QA").returncode == 0
    assert git(repo, "config", "user.email", "qa@example.invalid").returncode == 0
    (repo / ".githooks").mkdir()
    (repo / "scripts").mkdir()
    for name in [".gitignore", ".githooks/pre-commit", "scripts/check_cad_policy.py",
                 "scripts/install_git_hooks.py"]:
        shutil.copyfile(ROOT / name, repo / name)
    (repo / ".githooks/pre-commit").chmod(0o755)
    assert git(repo, "add", ".").returncode == 0
    assert git(repo, "commit", "-m", "Synthetic policy baseline").returncode == 0
    result = subprocess.run([sys.executable, str(repo / "scripts/install_git_hooks.py")], capture_output=True)
    assert result.returncode == 0
    return repo


@pytest.mark.parametrize("name", ["new.dxf", "new.dwg", "UPPER.DXF", "UPPER.DWG",
                                  "nested space/mixed.DxF", "nested/deep/mixed.dWg"])
def test_new_cad_files_are_ignored_and_force_staged_commits_are_rejected(repository, name):
    path = repository / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic policy probe", encoding="utf-8")
    assert git(repository, "check-ignore", "--quiet", "--", name).returncode == 0
    assert git(repository, "add", "--", name).returncode != 0
    assert git(repository, "add", "-f", "--", name).returncode == 0
    assert check(repository)[0] == 1
    before = git(repository, "rev-parse", "HEAD").stdout
    result = git(repository, "commit", "-m", "Must be rejected")
    assert result.returncode != 0
    assert b"CAD policy FAIL" in result.stdout + result.stderr
    assert name.encode() not in result.stdout + result.stderr
    assert git(repository, "rev-parse", "HEAD").stdout == before


def test_safe_commit_is_allowed(repository):
    (repository / "safe.txt").write_text("safe")
    assert git(repository, "add", "safe.txt").returncode == 0
    assert git(repository, "commit", "-m", "Safe text").returncode == 0
    assert check(repository, history=True)[0] == 0


def test_history_check_detects_deleted_cad_in_old_commit(repository):
    (repository / "old.DWG").write_text("synthetic")
    assert git(repository, "add", "-f", "old.DWG").returncode == 0
    # Deliberate bypass only in this disposable test, to exercise CI's history check.
    assert git(repository, "-c", "core.hooksPath=", "commit", "-m", "Historical probe").returncode == 0
    assert git(repository, "rm", "old.DWG").returncode == 0
    assert git(repository, "commit", "-m", "Remove current drawing").returncode == 0
    assert check(repository)[0] == 0
    count, commits = check(repository, history=True)
    assert count == 1
    assert commits == 3


def test_guard_fails_closed_outside_git(tmp_path):
    with pytest.raises(RuntimeError, match="inspection failed"):
        check(tmp_path)


def test_history_guard_rejects_shallow_clone(repository, tmp_path):
    clone = tmp_path / "shallow"
    assert subprocess.run(["git", "clone", "--depth", "1", repository.as_uri(), str(clone)],
                          capture_output=True).returncode == 0
    with pytest.raises(RuntimeError, match="shallow"):
        check(clone, history=True)


def test_installer_does_not_replace_another_hook_configuration(repository):
    assert git(repository, "config", "core.hooksPath", "custom-hooks").returncode == 0
    result = subprocess.run([sys.executable, str(repository / "scripts/install_git_hooks.py")], capture_output=True)
    assert result.returncode != 0
    assert git(repository, "config", "--get", "core.hooksPath").stdout.strip() == b"custom-hooks"


def test_repository_index_contains_no_cad():
    assert check(ROOT)[0] == 0


def test_generated_data_is_complete_and_external():
    root = data_root()
    assert ROOT not in root.parents
    assert root != ROOT
    assert len(list(root.rglob("*.dxf"))) == 36


def test_generator_rejects_output_inside_repository():
    with pytest.raises(ValueError, match="outside the repository"):
        make(ROOT / "must-not-exist.dxf")
    assert not (ROOT / "must-not-exist.dxf").exists()


def test_generator_requires_explicit_external_destination():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/generate_samples.py")], capture_output=True)
    assert result.returncode != 0
