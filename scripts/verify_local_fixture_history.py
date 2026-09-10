#!/usr/bin/env python3
"""Explicit local audit command for historical DXF fixture privacy verification.

This script performs an explicit local audit against a specific historical Git commit
to verify that historical fixture blobs are rejected by the privacy scanner and
safely redacted.

This audit is NOT part of the automated CI test suite and is never collected by pytest.
Users running normal tests or CI do not need old private history.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Add repository root to sys.path to import shared privacy scanner and verification logic
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_fixture_privacy import (
    HISTORICAL_TARGET_PATHS,
    load_historical_fixtures_from_git,
    verify_historical_fixture_bytes,
)


def redact_diagnostics(message: str) -> str:
    """Ensure no absolute paths or private directory patterns leak into error diagnostics."""
    cleaned = message.replace("\\", "/")
    # Redact any drive letters or path roots
    cleaned = re.sub(r"\b[A-Za-z]:/[^\s:]+", "[REDACTED_PATH]", cleaned)
    # Redact any UNC paths
    cleaned = re.sub(r"//[A-Za-z0-9._-]+/[^\s:]+", "[REDACTED_UNC]", cleaned)
    return cleaned


def audit_historical_fixtures(commit_sha: str, target_paths: list[str] | None = None) -> int:
    """Execute fail-closed historical audit against the specified commit SHA.

    Returns:
        0 on complete success where all expected inputs are loaded and verified.
        1 on any failure (missing commit, read error, empty input, count mismatch, clean fixture).
    """
    if target_paths is None:
        target_paths = HISTORICAL_TARGET_PATHS

    expected_count = len(target_paths)
    if expected_count == 0:
        print("[ERROR] Historical target list is empty.", file=sys.stderr)
        return 1

    try:
        loaded = load_historical_fixtures_from_git(commit_sha, target_paths)
        loaded_count, checked_count = verify_historical_fixture_bytes(loaded, expected_count=expected_count)
    except Exception as exc:
        safe_msg = redact_diagnostics(str(exc))
        print(f"[ERROR] Historical verification failed: {safe_msg}", file=sys.stderr)
        return 1

    print(
        f"[PASS] Historical fixture verification succeeded.\n"
        f"  Commit: {commit_sha}\n"
        f"  Expected: {expected_count}\n"
        f"  Loaded: {loaded_count}\n"
        f"  Checked: {checked_count}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify historical DXF fixtures from a local Git commit against the privacy scanner.",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="Local Git commit SHA to inspect (e.g. 5b8df0f). Requires locally available objects; do not fetch remote history.",
    )
    args = parser.parse_args()

    exit_code = audit_historical_fixtures(args.commit)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
