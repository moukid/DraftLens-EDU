# Permanent CAD-file repository policy

No DXF or DWG files are included or permitted in the repository, in any
capitalization, directory, branch, tag, or newly published history.
Sanitizing metadata is not an exception. Do not embed personal drawings as
base64, archives, LFS objects, or renamed files to evade this policy.

## Personal and manual testing

Keep reference drawings and student drawings in a local directory **outside**
the checkout. Testers must provide their own files. Do not use confidential
or personal information. Do not attach drawings to commits, pull requests,
issue comments, releases, or CI artifacts.

The application still accepts DXF uploads through its existing browser/API
workflow; repository restrictions do not disable uploads. DWG support has not
been added. Uploaded files are not Git fixtures.

## Developer setup

After cloning and installing Python, run:

```powershell
python scripts/install_git_hooks.py
python scripts/check_cad_policy.py
python -B -m pytest -q -p no:cacheprovider
```

The installer enables the versioned pre-commit guard in this clone only.
It refuses to replace a different hook configuration. Integrate the guard
manually if another hook framework is already in use.

Case-insensitive ignore rules prevent ordinary staging. The hook checks the
entire index, so a CAD file force-staged with `git add -f` still blocks a
normal commit. New clones must install hooks; Git does not install them
automatically. A determined user can bypass local hooks. The CI job also
checks the index and all reachable commit trees, and runs the full suite.
The repository owner must require that job in branch protection to enforce
the merge gate remotely. No local tool can promise to prevent deliberate
bypasses or uploads made outside Git.

## Automated data and privacy checks

All repository tests run without downloaded or historical drawing files.
`tests/synthetic_data.py` builds 36 fresh drawings from elementary geometric
specifications in a process-owned temporary directory outside the checkout.
They are not copies or encodings of removed personal fixtures and are deleted
when the process exits. Historical scenario filenames are labels only.
Assertions still cover exact matches, defects, topology, repeated geometry,
translation tolerance, compatibility, API uploads, review export and PDF/UI
behavior. Some coordinate assertions use the documented synthetic coordinates;
production grading code is unchanged.

`tests/test_fixture_privacy.py` checks generated metadata and the generic
redaction/detection helpers. Ordinary pytest never needs old Git objects.
Policy tests exercise both DXF and DWG, mixed-case/nested filenames, ignored
staging, forced staging, rejected commits, safe commits, deleted historical
files, shallow clones and fail-closed behavior.

For an optional synthetic manual demo, explicitly choose an external directory:

```powershell
python scripts/generate_samples.py --output-dir C:\Temp\DraftLensSyntheticDemo
```

The generator refuses destinations inside the repository.

## Release and history audit

With a full clone:

```powershell
python scripts/check_cad_policy.py --history
git status --short
```

A pass covers the index and all commits reachable from local refs. A shallow
clone is rejected for history auditing; ordinary tests remain shallow-clone
compatible. Audit the exact refs that will be published. Remote branches,
tags, forks, cached PR refs, LFS, releases and previously downloaded copies
require separate owner-controlled review; a local rewrite cannot erase them.

The former metadata-only repair and its local verification procedure are
superseded for publication by complete CAD-path removal. The optional legacy
`scripts/verify_local_fixture_history.py` is forensic tooling for private
pre-removal recovery copies only, not a release gate or ordinary CI test.
Do not restore old fixture blobs to run it in a cleaned repository.
