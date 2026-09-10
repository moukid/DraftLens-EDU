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
# Historical Red-Test (In-Memory Git Blob Verification)
# =============================================================================

def test_historical_unsanitized_fixtures_are_rejected():
    """Verify that historical unsanitized fixtures from base commit 5b8df0f are rejected by scanner."""
    historical_targets = [
        "tests/fixtures/simple_audit/00_reference_000-Simple.dxf",
        "tests/fixtures/simple_audit-II/01-ARC-Reference.dxf",
        "samples/basic_geometry/reference.dxf",
    ]

    for target_path in historical_targets:
        try:
            raw_bytes = subprocess.check_output(
                ["git", "show", f"5b8df0f:{target_path}"],
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue

        content = raw_bytes.decode("latin1", errors="replace")
        findings = scan_text_for_privacy_violations(content, rel_filename=target_path)
        # Historical unsanitized version MUST trigger findings
        assert len(findings) > 0, f"Expected historical {target_path} to be rejected"
        # Findings must be safely redacted
        for f in findings:
            assert "[REDACTED]" in f


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
