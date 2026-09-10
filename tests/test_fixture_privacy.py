"""Regression and enforcement tests for DXF fixture and sample privacy.

Scans all public DXF files (samples and test fixtures) for generic identifying paths:
- Windows absolute user and workstation paths (backslash and forward-slash)
- Windows user profile and legacy Documents and Settings paths
- Extended Windows paths (\\?\\...)
- Unix and macOS user/home directory paths
- UNC server/share paths
- Local file:// URIs
- Email addresses
- Environment / user-profile references (%USERPROFILE%, %APPDATA%, ~/)

Guarantees safe redacted diagnostics that never echo sensitive usernames,
workstation directories, server names, or raw source lines.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from typing import List, Tuple
from unittest import mock

import pytest

# Base patterns for generic identifying metadata (specific patterns first)
PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Extended Windows Path",
        re.compile(r'\\\\\?\\[^\s\r\n\x00]+'),
    ),
    (
        "Local File URI",
        re.compile(r'file://[^\s\r\n\x00]+', re.IGNORECASE),
    ),
    (
        "UNC Server/Share Path",
        re.compile(r'(?:^|[\s"\'`])(?:\\\\[A-Za-z0-9._-]+\\[^\s\r\n\x00]+|//[A-Za-z0-9._-]+/[^\s\r\n\x00]+)'),
    ),
    (
        "Windows User Profile Path",
        re.compile(r'\b[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\r\n\x00]+', re.IGNORECASE),
    ),
    (
        "Windows Absolute Path",
        re.compile(r'\b[A-Za-z]:[\\/][^\s\r\n\x00]+'),
    ),
    (
        "Unix/macOS Home Directory",
        re.compile(r'(?:^|[\s"\'`])/(?:home|Users)/[^\s\r\n\x00]+'),
    ),
    (
        "Email Address",
        re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    ),
    (
        "User Profile Environment Pattern",
        re.compile(r'(?:%USERPROFILE%|%APPDATA%|~[/\\])[^\s\r\n\x00]*', re.IGNORECASE),
    ),
]


def format_safe_finding(rel_path: str, line_no: int, category: str) -> str:
    """Format finding safely without echoing sensitive text or raw lines."""
    clean_rel = rel_path.replace("\\", "/")
    return f"{clean_rel}:{line_no} [{category}] [REDACTED]"


def scan_text_for_privacy_violations(content: str, rel_filename: str = "memory_buffer") -> list[str]:
    """Scan string content for identifying patterns, returning strictly redacted diagnostics."""
    findings: list[str] = []
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for cat_name, pattern in PATH_PATTERNS:
            if pattern.search(line):
                findings.append(format_safe_finding(rel_filename, line_no, cat_name))
                break  # Record one redacted finding per offending line
    return findings


def get_repo_root() -> pathlib.Path:
    """Return the repository root directory."""
    return pathlib.Path(__file__).resolve().parent.parent


def safe_read_file(path: pathlib.Path, repo_root: pathlib.Path) -> str:
    """Safely read and decode file content without exposing absolute paths on error."""
    try:
        rel_path = str(path.relative_to(repo_root)).replace("\\", "/")
    except Exception:
        rel_path = path.name
    try:
        raw_bytes = path.read_bytes()
        return raw_bytes.decode("latin1", errors="replace")
    except Exception:
        raise RuntimeError(f"Read error for {rel_path}: failed to read or decode file") from None


def discover_public_dxf_files(repo_root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Discover all public DXF files under samples/ and tests/fixtures/ without exclusions."""
    if repo_root is None:
        repo_root = get_repo_root()

    scan_dirs = [repo_root / "samples", repo_root / "tests" / "fixtures"]
    dxf_files: list[pathlib.Path] = []
    for d in scan_dirs:
        if not d.is_dir():
            raise FileNotFoundError(f"Required scan directory not found: {d.name}")
        for p in sorted(d.rglob("*.dxf")):
            if p.is_file():
                dxf_files.append(p)
    return dxf_files


# =============================================================================
# Core Test Suite
# =============================================================================

def test_all_public_dxf_files_are_privacy_safe():
    """Verify every public DXF file across samples and fixtures is free of identifying metadata."""
    repo_root = get_repo_root()
    files = discover_public_dxf_files(repo_root)

    # Verify coverage baselines (minimum counts, no permanent ceiling)
    sample_files = [f for f in files if "samples" in f.parts]
    legacy_files = [f for f in files if any(p in {"simple_audit", "simple_audit-II"} for p in f.parts)]
    ref01_files = [f for f in files if "ref_01" in f.parts]

    assert len(sample_files) >= 12, f"Expected at least 12 sample DXFs, found {len(sample_files)}"
    assert len(legacy_files) >= 23, f"Expected at least 23 legacy test fixtures, found {len(legacy_files)}"
    assert len(ref01_files) >= 9, f"Expected at least 9 Ref-01 fixtures, found {len(ref01_files)}"

    all_findings: list[str] = []
    for p in files:
        rel_path = str(p.relative_to(repo_root)).replace("\\", "/")
        content = safe_read_file(p, repo_root)
        findings = scan_text_for_privacy_violations(content, rel_filename=rel_path)
        if findings:
            all_findings.extend(findings)

    assert not all_findings, (
        f"Privacy violations found in public DXF files ({len(all_findings)} occurrences):\n"
        + "\n".join(f"  {finding}" for finding in all_findings)
    )


# =============================================================================
# Detection Capability Tests
# =============================================================================

def test_detection_windows_user_profile():
    line = r"C:\Users\synth_operator\AppData\Local\Autodesk\plot.pc3"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Windows User Profile Path]" in findings[0]
    assert "[REDACTED]" in findings[0]


def test_detection_arbitrary_drive_path():
    line = r"E:\Internal_CAD_Builds\Project_Alpha\drawing.dxf"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Windows Absolute Path]" in findings[0]
    assert "[REDACTED]" in findings[0]


def test_detection_forward_slash_windows_path():
    line = "D:/Project_Repository/DraftLens/models/fixture.dxf"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Windows Absolute Path]" in findings[0]


def test_detection_legacy_documents_and_settings():
    line = r"C:\Documents and Settings\legacy_admin\Application Data\test.pc3"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Windows User Profile Path]" in findings[0]


def test_detection_unix_and_macos_home():
    unix_line = "/home/developer_cad/assignments/part1.dxf"
    mac_line = "/Users/designer_mac/workspace/part2.dxf"
    findings_unix = scan_text_for_privacy_violations(unix_line)
    findings_mac = scan_text_for_privacy_violations(mac_line)
    assert len(findings_unix) == 1
    assert len(findings_mac) == 1
    assert "[Unix/macOS Home Directory]" in findings_unix[0]
    assert "[Unix/macOS Home Directory]" in findings_mac[0]


def test_detection_file_uri():
    line = "file:///C:/Users/alice/projects/drawing.dxf"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Local File URI]" in findings[0]


def test_detection_unc_path():
    unc_backslash = r"\\engineering-server\shared_drawings\assembly.dxf"
    unc_forward = "//cad-cluster/blueprints/chassis.dxf"
    findings_bs = scan_text_for_privacy_violations(unc_backslash)
    findings_fw = scan_text_for_privacy_violations(unc_forward)
    assert len(findings_bs) == 1
    assert len(findings_fw) == 1
    assert "[UNC Server/Share Path]" in findings_bs[0]
    assert "[UNC Server/Share Path]" in findings_fw[0]


def test_detection_extended_windows_path():
    line = r"\\?\C:\Restricted\Drafting\layout.dxf"
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Extended Windows Path]" in findings[0]


def test_detection_email_address():
    line = "Contact drafting supervisor at cad_lead@university-dept.edu for review."
    findings = scan_text_for_privacy_violations(line)
    assert len(findings) == 1
    assert "[Email Address]" in findings[0]


# =============================================================================
# Redaction and Output Safety Tests
# =============================================================================

def test_redaction_does_not_leak_usernames():
    synth_user = "classified_operator_99"
    line = f"C:\\Users\\{synth_user}\\AppData\\Local\\plot.pc3"
    findings = scan_text_for_privacy_violations(line, rel_filename="tests/sample.dxf")
    assert synth_user not in findings[0]
    assert "AppData" not in findings[0]
    assert "plot.pc3" not in findings[0]
    assert line not in findings[0]


def test_redaction_does_not_leak_project_directories():
    synth_dir = "TopSecret_CAD_Project_2026"
    line = f"D:\\{synth_dir}\\drawings\\part.dxf"
    findings = scan_text_for_privacy_violations(line, rel_filename="tests/sample.dxf")
    assert synth_dir not in findings[0]
    assert "drawings" not in findings[0]
    assert "part.dxf" not in findings[0]


def test_redaction_does_not_leak_server_shares():
    synth_server = "classified-nas-01"
    synth_share = "defense_blueprints"
    line = f"\\\\{synth_server}\\{synth_share}\\part.dxf"
    findings = scan_text_for_privacy_violations(line, rel_filename="tests/sample.dxf")
    assert synth_server not in findings[0]
    assert synth_share not in findings[0]


def test_redaction_does_not_leak_emails():
    synth_email = "lead_designer_classified@subcontractor.corp"
    line = f"Authored by: {synth_email}"
    findings = scan_text_for_privacy_violations(line, rel_filename="tests/sample.dxf")
    assert synth_email not in findings[0]
    assert "subcontractor.corp" not in findings[0]


def test_read_error_diagnostics_do_not_leak_absolute_paths():
    repo_root = get_repo_root()
    fake_path = repo_root / "samples" / "non_existent_file.dxf"
    try:
        safe_read_file(fake_path, repo_root)
    except RuntimeError as exc:
        msg = str(exc)
        # Verify repository-relative name is used, not absolute path with drive letter
        assert "samples/non_existent_file.dxf" in msg
        assert str(repo_root) not in msg
        assert ":\\" not in msg


# =============================================================================
# Coverage and Directory Inclusion Tests
# =============================================================================

def test_coverage_detects_violation_in_sample_file():
    synth_sample_content = "  0\nSECTION\n  2\nOBJECTS\n  303\nC:\\Users\\student\\sample.dxf\n  0\nENDSEC\n"
    findings = scan_text_for_privacy_violations(synth_sample_content, rel_filename="samples/test_sample.dxf")
    assert len(findings) == 1
    assert "samples/test_sample.dxf:6" in findings[0]


def test_coverage_detects_violation_in_legacy_fixture():
    synth_legacy_content = "  0\nSECTION\n  2\nOBJECTS\n  2\nC:\\Documents and Settings\\admin\\plot.pc3\n  0\nENDSEC\n"
    findings = scan_text_for_privacy_violations(synth_legacy_content, rel_filename="tests/fixtures/simple_audit/test.dxf")
    assert len(findings) == 1
    assert "tests/fixtures/simple_audit/test.dxf:6" in findings[0]


def test_coverage_former_excluded_and_nested_directories_not_bypassed():
    synth_content = "  303\nC:\\Users\\engineer\\nested_fixture.dxf\n"
    findings_nested = scan_text_for_privacy_violations(
        synth_content,
        rel_filename="tests/fixtures/simple_audit/nested_sub/extra.dxf"
    )
    assert len(findings_nested) == 1
    assert "tests/fixtures/simple_audit/nested_sub/extra.dxf:2" in findings_nested[0]

    findings_ii = scan_text_for_privacy_violations(
        synth_content,
        rel_filename="tests/fixtures/simple_audit-II/future/extra.dxf"
    )
    assert len(findings_ii) == 1
    assert "tests/fixtures/simple_audit-II/future/extra.dxf:2" in findings_ii[0]


# =============================================================================
# Historical and Synthetic Verification (Fail-Closed Architecture)
# =============================================================================

def verify_historical_fixture_bytes(
    inputs: list[tuple[str, bytes]],
    expected_count: int,
) -> tuple[int, int]:
    """Verify that expected historical inputs are present, rejected by scanner, and safely redacted."""
    if expected_count <= 0:
        raise ValueError("Expected count must be greater than zero")
    if len(inputs) != expected_count:
        raise AssertionError(
            f"Historical input collection mismatch: expected {expected_count}, got {len(inputs)}"
        )

    checked_count = 0
    for rel_path, raw_bytes in inputs:
        if not raw_bytes:
            raise AssertionError(f"Empty input bytes for historical fixture: {rel_path}")
        content = raw_bytes.decode("latin1", errors="replace")
        findings = scan_text_for_privacy_violations(content, rel_filename=rel_path)
        if not findings:
            raise AssertionError(
                f"Historical fixture failed to trigger expected privacy findings: {rel_path}"
            )
        for f in findings:
            if "[REDACTED]" not in f:
                raise AssertionError(f"Finding missing redaction marker for: {rel_path}")
        checked_count += 1

    if checked_count != expected_count or checked_count == 0:
        raise AssertionError(
            f"Failed to verify all required inputs: checked {checked_count} of {expected_count}"
        )
    return len(inputs), checked_count


def load_historical_fixtures_from_git(
    commit_sha: str,
    target_rel_paths: list[str],
) -> list[tuple[str, bytes]]:
    """Load historical DXF fixture bytes from git commit without checking out files."""
    if not target_rel_paths:
        raise ValueError("Target path list must not be empty")

    loaded: list[tuple[str, bytes]] = []
    for rel_path in target_rel_paths:
        try:
            raw_bytes = subprocess.check_output(
                ["git", "show", f"{commit_sha}:{rel_path}"],
                stderr=subprocess.DEVNULL,
            )
            if not raw_bytes:
                raise AssertionError(f"Historical blob is empty: {rel_path}")
            loaded.append((rel_path, raw_bytes))
        except subprocess.CalledProcessError:
            raise AssertionError(f"Failed to load required historical fixture from git: {rel_path}") from None
        except FileNotFoundError:
            raise AssertionError(f"Git executable unavailable to read historical fixture: {rel_path}") from None
        except Exception:
            raise AssertionError(f"Historical fixture load error: {rel_path}") from None

    if len(loaded) != len(target_rel_paths):
        raise AssertionError(
            f"Incomplete historical load: expected {len(target_rel_paths)}, loaded {len(loaded)}"
        )
    return loaded


def test_local_historical_unsanitized_fixtures_are_rejected():
    """Verify local historical unsanitized fixtures from base commit 5b8df0f fail closed if unreadable or clean."""
    targets = [
        "tests/fixtures/simple_audit/00_reference_000-Simple.dxf",
        "tests/fixtures/simple_audit-II/01-ARC-Reference.dxf",
        "samples/basic_geometry/reference.dxf",
    ]
    loaded = load_historical_fixtures_from_git("5b8df0f", targets)
    loaded_count, checked_count = verify_historical_fixture_bytes(loaded, expected_count=len(targets))
    assert loaded_count == len(targets)
    assert checked_count == len(targets)


def test_permanent_ci_synthetic_objects_metadata_rejected():
    """Verify synthetic DXF fixtures containing group 303 and group 2 identifying metadata are rejected.

    This permanent CI regression test has zero Git history dependencies and runs in any CI/CD environment.
    """
    synthetic_fixtures = [
        (
            "samples/synthetic_xrecord_303.dxf",
            b"  0\r\nSECTION\r\n  2\r\nOBJECTS\r\n  0\r\nACDBXRECORD\r\n"
            b"  303\r\nC:\\Synthetic_Workstation\\CAD\\part_01.dxf\r\n  0\r\nENDSEC\r\n",
        ),
        (
            "tests/fixtures/synthetic_plotsettings_user_profile.dxf",
            b"  0\r\nSECTION\r\n  2\r\nOBJECTS\r\n  0\r\nACDBPLOTSETTINGS\r\n"
            b"  2\r\nC:\\Users\\synth_drafter\\AppData\\plotters\\test.pc3\r\n  0\r\nENDSEC\r\n",
        ),
        (
            "tests/fixtures/synthetic_plotsettings_legacy_profile.dxf",
            b"  0\r\nSECTION\r\n  2\r\nOBJECTS\r\n  0\r\nLAYOUT\r\n"
            b"  2\r\nC:\\Documents and Settings\\synth_admin\\Application Data\\test.pc3\r\n  0\r\nENDSEC\r\n",
        ),
        (
            "samples/synthetic_unc_share.dxf",
            b"  0\r\nSECTION\r\n  2\r\nOBJECTS\r\n  0\r\nACDBXRECORD\r\n"
            b"  303\r\n\\\\synth-nas\\engineering_drawings\\chassis.dxf\r\n  0\r\nENDSEC\r\n",
        ),
    ]
    loaded_count, checked_count = verify_historical_fixture_bytes(
        synthetic_fixtures, expected_count=len(synthetic_fixtures)
    )
    assert loaded_count == len(synthetic_fixtures)
    assert checked_count == len(synthetic_fixtures)


# =============================================================================
# Fault-Injection Test Suite
# =============================================================================

def test_fault_injection_all_reads_fail():
    """Fault injection: when all git reads fail, load must fail closed with an AssertionError."""
    targets = ["samples/file1.dxf", "tests/file2.dxf"]
    with mock.patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
        with pytest.raises(AssertionError) as exc_info:
            load_historical_fixtures_from_git("5b8df0f", targets)
        assert "Failed to load required historical fixture from git: samples/file1.dxf" in str(exc_info.value)


def test_fault_injection_one_read_fails():
    """Fault injection: when one git read fails among multiple, load must fail closed."""
    targets = ["samples/file1.dxf", "samples/file2.dxf", "samples/file3.dxf"]
    def mock_check_output(cmd, **kwargs):
        if "file2.dxf" in cmd[2]:
            raise subprocess.CalledProcessError(1, "git")
        return b"dummy content"

    with mock.patch("subprocess.check_output", side_effect=mock_check_output):
        with pytest.raises(AssertionError) as exc_info:
            load_historical_fixtures_from_git("5b8df0f", targets)
        assert "Failed to load required historical fixture from git: samples/file2.dxf" in str(exc_info.value)


def test_fault_injection_empty_input_collection():
    """Fault injection: empty inputs or zero expected count must fail immediately."""
    with pytest.raises(AssertionError) as exc_info:
        verify_historical_fixture_bytes([], expected_count=3)
    assert "Historical input collection mismatch" in str(exc_info.value)

    with pytest.raises(ValueError):
        verify_historical_fixture_bytes([], expected_count=0)


def test_fault_injection_sensitive_content_not_detected():
    """Fault injection: if clean content is provided, verify_historical_fixture_bytes must fail."""
    clean_bytes = b"  0\r\nSECTION\r\n  2\r\nENTITIES\r\n  0\r\nENDSEC\r\n"
    with pytest.raises(AssertionError) as exc_info:
        verify_historical_fixture_bytes([("samples/clean.dxf", clean_bytes)], expected_count=1)
    assert "failed to trigger expected privacy findings: samples/clean.dxf" in str(exc_info.value)


def test_fault_injection_valid_inputs_succeed():
    """Fault injection control: verified sensitive inputs must succeed with accurate counts."""
    synth_input = [(
        "samples/valid_synth.dxf",
        b"  303\r\nC:\\Test_Build\\file.dxf\r\n"
    )]
    loaded, checked = verify_historical_fixture_bytes(synth_input, expected_count=1)
    assert loaded == 1
    assert checked == 1


def test_fault_injection_failure_messages_are_redacted():
    """Fault injection: verify failure diagnostics never contain absolute drive paths."""
    targets = ["samples/file1.dxf"]
    with mock.patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
        try:
            load_historical_fixtures_from_git("5b8df0f", targets)
        except AssertionError as exc:
            msg = str(exc)
            assert ":\\" not in msg
            assert "git" in msg or "samples/file1.dxf" in msg
            assert "C:" not in msg
            assert "D:" not in msg


# =============================================================================
# False-Positive Control Tests
# =============================================================================

def test_ordinary_dxf_geometry_permitted():
    ordinary_dxf = """  0
SECTION
  2
ENTITIES
  0
LINE
  5
2AC
  8
0
 10
125.500000
 20
-45.250000
 30
0.000000
 11
2.500000e+02
 21
-1.000000e-05
 31
0.000000
  0
CIRCLE
  5
2AD
  8
Layer_1
 10
0.000000
 20
0.000000
 30
0.000000
 40
15.750000
  0
LWPOLYLINE
  5
2AE
  8
Layer_2
 90
4
 70
1
 10
0.0
 20
0.0
 10
10.0
 20
0.0
 10
10.0
 20
10.0
 10
0.0
 20
10.0
  0
ENDSEC
  0
EOF
"""
    findings = scan_text_for_privacy_violations(ordinary_dxf)
    assert findings == []


def test_generic_printer_and_relative_paths_permitted():
    content = """  0
AcDbPlotSettings
  2
Default Windows System Printer.pc3
  0
AcDbXrecord
  303
000-Simple.dxf
  303
Ref-01.dxf
  303
Abstract Geometrical Shapes.dxf
"""
    findings = scan_text_for_privacy_violations(content)
    assert findings == []


def test_ordinary_urls_permitted():
    content = """
Reference specification: https://example.com/standards/cad-spec.html
Repository link: http://standards.iso.org/iso/13567/
"""
    findings = scan_text_for_privacy_violations(content)
    assert findings == []
