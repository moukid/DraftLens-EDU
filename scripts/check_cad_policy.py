"""Reject CAD files in the Git index, or in every reachable commit tree.

Diagnostics report counts only: a filename can itself contain private data.
Standard library only; usable by hooks before application dependencies exist.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, check=False
        )
    except OSError:
        raise RuntimeError("CAD policy: Git could not be started.") from None
    if result.returncode:
        raise RuntimeError("CAD policy: Git inspection failed; refusing to continue.")
    return result.stdout


def cad_count(paths: bytes) -> int:
    return sum(p.lower().endswith((b".dxf", b".dwg")) for p in paths.split(b"\0") if p)


def check(repo: Path, *, history: bool = False) -> tuple[int, int]:
    count = cad_count(git(repo, "ls-files", "--cached", "-z"))
    commits = 0
    if history:
        if git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise RuntimeError("CAD policy: full history required; shallow checkout rejected.")
        for commit in git(repo, "rev-list", "--all").splitlines():
            commits += 1
            count += cad_count(git(repo, "ls-tree", "-r", "--name-only", "-z", commit.decode("ascii")))
    return count, commits


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also inspect all reachable commits; requires full history.")
    args = parser.parse_args(argv)
    try:
        count, commits = check(Path.cwd(), history=args.history)
    except RuntimeError as exc:
        print(str(exc))
        return 2
    if count:
        print(f"CAD policy FAIL: {count} prohibited DXF/DWG path entries. Keep drawings outside the repository.")
        return 1
    print(f"CAD policy PASS: no tracked DXF/DWG files; {commits} historical commits inspected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
