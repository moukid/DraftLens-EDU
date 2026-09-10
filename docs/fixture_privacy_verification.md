# DXF Fixture Privacy Verification and CI Separation

DraftLens EDU separates automated continuous integration (CI) testing from explicit historical privacy audits.

## 1. Automated Continuous Integration (Default Pytest)

Default `pytest` execution is completely **independent of private Git history**.

- All permanent CI privacy regression tests run against current repository files and in-memory synthetic buffers.
- Default CI requires no historical Git objects, shallow clone workarounds, or access to sensitive pre-release commits.
- Users and automated CI runners must **not** fetch, pull, or publish sensitive historical Git commits to execute test suites.

To run the standard automated privacy suite:

```powershell
python -m pytest tests/test_fixture_privacy.py -v
```

## 2. Explicit Local Historical Audit Command

Auditing historical DXF fixture privacy against past commits is an **explicit, optional local audit** performed outside the pytest suite.

### Usage

```powershell
python -B scripts/verify_local_fixture_history.py --commit <LOCAL_COMMIT_SHA>
```

### Key Properties

- **Explicit invocation**: The audit script is located in `scripts/verify_local_fixture_history.py` (outside `tests/`) and is never collected or executed by `pytest`.
- **Requires local Git objects**: The specified `<LOCAL_COMMIT_SHA>` must already exist in your local Git repository. The script does not automatically fetch or download remote history.
- **Fail-closed verification**: If Git is unavailable, the commit does not exist, any fixture cannot be read, input counts mismatch, or fixtures fail to trigger expected scanner detections, the command exits with a nonzero exit code (1). Missing inputs cause a failure, never a silent skip.
- **Redacted diagnostics**: All diagnostics suppress raw historical bytes, personal usernames, local workstation paths, and subprocess output.
