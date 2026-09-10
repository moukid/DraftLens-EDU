"""Regression tests for DXF fixture privacy.

Scans DXF test fixtures for generic identifying paths:
- Windows absolute user and workstation paths
- Unix home-directory paths
- Local file:// URIs
- Common user-profile path patterns

Ensures failure reports redact sensitive paths and usernames, and ordinary
DXF geometry and numeric data do not produce false positives.
"""

from __future__ import annotations

import pathlib
import re
from typing import List, Tuple

# Known baseline fixture directories committed prior to release/competition-v2
LEGACY_BASELINE_DIRS = {"simple_audit", "simple_audit-II"}

# Generic patterns for identifying workstation/user paths
PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Windows User Profile Path",
        re.compile(r'[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\r\n\x00]+', re.IGNORECASE),
    ),
    (
        "Windows Workstation Absolute Path",
        re.compile(r'[A-Za-z]:\\(?:[^\s\r\n\\/:*?"<>|]+\\)+[^\s\r\n\\/:*?"<>|]*', re.IGNORECASE),
    ),
    (
        "Unix Home Directory Path",
        re.compile(r'/(?:home|Users)/[^\s\r\n\x00]+', re.IGNORECASE),
    ),
    (
        "Local File URI",
        re.compile(r'file://[^\s\r\n\x00]+', re.IGNORECASE),
    ),
    (
        "User Profile Environment Pattern",
        re.compile(r'(?:%USERPROFILE%|%APPDATA%|~[/\\])[^\s\r\n\x00]*', re.IGNORECASE),
    ),
]


def redact_sensitive_match(pattern_name: str, match_text: str) -> str:
    """Safely redact matched path to prevent leaking usernames or full paths in reports."""
    # Redact Windows user profile segments (e.g. C:\Users\<username>\...)
    redacted = re.sub(
        r'([A-Za-z]:\\(?:Users|Documents and Settings)\\[^\\]+)',
        r'[REDACTED_USER_PROFILE]',
        match_text,
        flags=re.IGNORECASE,
    )
    # Redact Unix home segments (e.g. /home/<username>/...)
    redacted = re.sub(
        r'(/(?:home|Users)/[^/]+)',
        r'[REDACTED_HOME]',
        redacted,
        flags=re.IGNORECASE,
    )
    # Redact general Windows directory hierarchies
    redacted = re.sub(
        r'([A-Za-z]:\\)(?:[^\r\n\\/]+\\)+',
        r'\1[REDACTED_DIR]\\',
        redacted,
    )
    # Redact file:// URIs
    redacted = re.sub(
        r'(file://)[^\r\n]+',
        r'\1[REDACTED_URI]',
        redacted,
        flags=re.IGNORECASE,
    )
    return f"[{pattern_name}] -> {redacted}"


def scan_text_for_privacy_violations(content: str) -> list[str]:
    """Scan string content for identifying path patterns, returning redacted findings."""
    findings: list[str] = []
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pat_name, pattern in PATH_PATTERNS:
            for match in pattern.finditer(line):
                raw_match = match.group(0)
                # Avoid false positives on plain relative or numeric lines
                if len(raw_match.strip()) > 3:
                    redacted = redact_sensitive_match(pat_name, raw_match)
                    findings.append(f"Line {line_no}: {redacted}")
    return findings


def scan_fixture_file(path: pathlib.Path) -> list[str]:
    """Read a fixture file and return any privacy findings."""
    raw_bytes = path.read_bytes()
    content = raw_bytes.decode("latin1", errors="replace")
    return scan_text_for_privacy_violations(content)


# --- Test Suite ---


def test_ref01_fixtures_are_privacy_safe():
    """Verify that all newly tracked Ref-01 fixtures are free of identifying paths."""
    fixtures_dir = pathlib.Path(__file__).parent / "fixtures" / "ref_01"
    assert fixtures_dir.is_dir(), f"Ref-01 fixtures directory not found: {fixtures_dir}"

    dxf_files = sorted(fixtures_dir.glob("*.dxf"))
    assert len(dxf_files) == 9, f"Expected 9 Ref-01 DXF fixtures, found {len(dxf_files)}"

    all_violations: dict[str, list[str]] = {}
    for dxf_path in dxf_files:
        violations = scan_fixture_file(dxf_path)
        if violations:
            all_violations[dxf_path.name] = violations

    assert not all_violations, (
        f"Privacy violations found in Ref-01 fixtures:\n"
        + "\n".join(f"  {fname}: {v}" for fname, v in all_violations.items())
    )


def test_future_tracked_fixtures_privacy():
    """Verify that any newly tracked fixture outside legacy baseline is privacy safe."""
    fixtures_root = pathlib.Path(__file__).parent / "fixtures"
    dxf_files = sorted(fixtures_root.rglob("*.dxf"))

    candidate_files = [
        f for f in dxf_files
        if not any(part in LEGACY_BASELINE_DIRS for part in f.parts)
    ]

    all_violations: dict[str, list[str]] = {}
    for dxf_path in candidate_files:
        violations = scan_fixture_file(dxf_path)
        if violations:
            all_violations[str(dxf_path.relative_to(fixtures_root))] = violations

    assert not all_violations, (
        f"Privacy violations found in candidate fixtures:\n"
        + "\n".join(f"  {fname}: {v}" for fname, v in all_violations.items())
    )


def test_privacy_scanner_detects_windows_user_profile():
    """Verify scanner catches Windows user paths and redacts the username."""
    sensitive_line = r"C:\Users\test_user_smith\AppData\Local\Autodesk\plot.pc3"
    violations = scan_text_for_privacy_violations(sensitive_line)
    assert len(violations) > 0
    # Crucially, the raw username must NOT appear in the report
    assert "test_user_smith" not in violations[0]
    assert "[REDACTED" in violations[0]


def test_privacy_scanner_detects_documents_and_settings():
    """Verify scanner catches Documents and Settings paths and redacts username."""
    sensitive_line = r"C:\Documents and Settings\old_operator\Application Data\test.pc3"
    violations = scan_text_for_privacy_violations(sensitive_line)
    assert len(violations) > 0
    assert "old_operator" not in violations[0]
    assert "[REDACTED" in violations[0]


def test_privacy_scanner_detects_unix_home():
    """Verify scanner catches Unix home directory paths and redacts username."""
    sensitive_line = "/home/john_doe/assignments/cad/final.dxf"
    violations = scan_text_for_privacy_violations(sensitive_line)
    assert len(violations) > 0
    assert "john_doe" not in violations[0]
    assert "[REDACTED" in violations[0]


def test_privacy_scanner_detects_file_uri():
    """Verify scanner catches file:// URIs and redacts path."""
    sensitive_line = "file:///C:/Users/alice/projects/drawing.dxf"
    violations = scan_text_for_privacy_violations(sensitive_line)
    assert len(violations) > 0
    assert "alice" not in violations[0]
    assert "[REDACTED" in violations[0]


def test_privacy_scanner_ignores_ordinary_dxf_geometry():
    """Verify that ordinary DXF entities and numerical data are not flagged."""
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
250.000000
 21
100.000000
 31
0.000000
  0
CIRCLE
  5
2AD
  8
Layer1
 10
0.000000
 20
0.000000
 30
0.000000
 40
15.750000
  0
ENDSEC
  0
EOF
"""
    violations = scan_text_for_privacy_violations(ordinary_dxf)
    assert violations == []
