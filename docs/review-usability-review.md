# Independent usability review and targeted repair

## Status clarification — 2026-09-11 (Africa/Cairo)

This dated addendum applies MOUKID's clarified scope. The original report and findings below are preserved as historical evidence; its combined-release verdict must not be read as rejection of the usability work.

- **A. Usability acceptance: verified according to the reported checks; ready for MOUKID's local acceptance.** Scope: #8, #9, #3, #4, and focused UI improvements. The prior 423-test, live-browser, and rendered-PDF results apply to reviewed code commit `1041bea996b1be39af98c6358af696368c5a3301`. No full-suite rerun was performed merely to start acceptance.
- **B. Combined release: pending ellipse integration and verification; not release-ready.** #5 and #11 are separate workstreams, outside usability acceptance. Their absence is not a regression introduced by this usability implementation.
- Resolved current usability branch HEAD, including the original documentation commit: `6e620fadac57f778dc4765dcc3766367aab4b83e` on `feature/review-usability-v1`. This addendum and the integration plan are documentation-only working-tree changes, deliberately uncommitted in this bounded investigation; no branch tip or root change was staged or committed.
- Exact acceptance worktree: `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\review-usability`. Dedicated acceptance URL started on this date: `http://127.0.0.1:8766/`. HTTP 200, the `review-usability-2` asset marker, and byte-for-text equality of served JavaScript with this worktree were verified. The server is bound only to loopback and explicitly uses this worktree; unrelated servers were not terminated.
- Further code inspection resolves the earlier #11 uncertainty more precisely: ellipse parsing/rendering and generic property signatures exist, but ellipse-axis size comparison and its regression coverage were not found in the available sources. Three changed-axis comparison probes still return score 100 with no issues. This is a separate comparison gap, not completed #11 integration.

See [the dated acceptance and integration plan](review-usability-integration-plan.md) for source commits, root-file fingerprints, current focused #5 evidence, the exact launch command, acceptance checklist, and proposed gated integration sequence. The original historical wording below is retained rather than silently rewritten.

## Verdict

**FAIL — release blockers remain.** The approved usability repairs pass the checks below, but this branch does not include the verified Issue #5 baseline and the required Issue #11 integration source is unidentified. This is not approval to push, merge, close issues, or start a release.

## Reviewed identity

- Repository: `moukid/DraftLens-EDU`.
- Worktree: `.worktrees/review-usability`; branch: `feature/review-usability-v1`.
- Recorded base: `55c8d9b`.
- Antigravity submitted HEAD: `f834795c392d0e69cb106d5357f46d2628c66791` (preceded by `04d61c2`).
- Final reviewed code HEAD: `1041bea996b1be39af98c6358af696368c5a3301`.
- A separate documentation-only commit records this report. Resolve that final handoff HEAD with `git log -1 --format=%H -- docs/review-usability-review.md`; its hash is also supplied in the handoff response.
- Work was local only. No push, merge, publication, or GitHub issue closure was performed.

## Scope and invariants

Completed review and targeted repairs for #8 viewer navigation, #9 PDF layout, #3 supporting findings, #4 unsupported-content presentation, and focused UI usability. No work was added for #2, #6, #7, or #10. No frontend migration or dependency change was made.

Compared with the recorded base, the parser, reviewed-DXF geometry, SVG geometry renderer, comparison, normalization, compatibility, rubric, validator, and grading-adjustment modules remain unchanged. Dependency manifests remain unchanged. Issue #1 validation remains present and covered by passing tests.

Baseline and repaired review responses were independently compared using identical synthetic inputs, excluding only additive `finding_presentation` metadata. All three pairs matched, including authoritative issues, IDs, deductions, score breakdown, normalization, compatibility, and SVG output: door/window errors (88, four issues), good student (100, zero issues), missing wall (95, one issue).

## Findings, impact, and disposition

| Priority | Finding and user impact | Disposition |
| --- | --- | --- |
| P1 | Mandatory #5 integration is absent. The baseline still renders whole ellipses and cannot certify the partial-ellipse/reversed-normal repairs. | OPEN; integration prerequisite, not a new usability regression. |
| P1 | Required integrated #11 work cannot be identified in the available local history. Its preservation cannot be certified. | OPEN; owner must identify the intended baseline/source. |
| P1 | Supporting links treated string IDs as objects, displaying undefined labels; test inputs masked the production mismatch. | Fixed by resolving authoritative IDs, valid sibling disclosure controls, and regression coverage. |
| P1 | Dense supporting evidence or a long table cell could cause PDF LayoutError; overlarge keep-together blocks orphaned headings. | Fixed using splittable tables, repeated headings, correct frame width, and bounded grouping. |
| P1 | Default presentation hid capped primary issues and essential nonprimary findings; PDF omitted some warning/info content. | Fixed with additive default visibility, essential notices, complete primary-ID correction tables, and linked optional detail. |
| P2 | Letterboxing invalidated pointer mapping; pan could accidentally select; zero-height issue bounds distorted Locate. | Fixed with inverse SVG screen transforms, sticky drag suppression, capture handling, and aspect-preserving Locate. |
| P2 | Expanded-view focus could escape and advertised keyboard controls were incomplete. | Fixed keyboard zoom/pan/Home, focus containment, Escape, and focus restoration. |
| P2 | Collapsed setup hid student controls, approval labels became stale, and narrow layouts overflowed. | Fixed workflow visibility, approval-aware labels, responsive layout, and focus outlines. |
| P2 | Expired PDF downloads navigated away; loading/error handling and asset cache invalidation were inadequate. | Fixed fetch/blob downloads, recoverable errors, progress, synchronized options, no-store responses, and versioned assets. |

Original compaction representatives/counters remain intact. Complete actionable primary IDs remain available; compact PDF summaries do not silently remove correction obligations. Optional evidence retains its primary relationship. Unsupported-content notices do not imply successful assessment.

## Automated verification

- Submitted tree: **417 passed**, seven warnings.
- Final repaired code: **423 passed, zero failed, zero skipped**, seven warnings; last full run 26.22 seconds.
- Six additional independent regression cases cover dense/long PDF evidence, complete essential/default visibility, older snapshot fallback, PDF option/cache isolation and invalid parameters, and zero-height Locate bounds.
- Corrected misleading existing tests to use real supporting-ID strings and asynchronous downloads. Existing compact-report page limits were not weakened.
- Large scale-override and incompatible-circle reports: seven pages each. The 140-reference/eight-student partial-work case retains all 132 primary issue IDs in six pages, within the existing ten-page limit.
- `node --check app/static/app.js`: passed.
- `git diff --check`: passed; normal Windows line-ending notices are not test failures.

## Real browser verification

Eleven live check groups passed in a fresh headless Microsoft Edge/Playwright session against a loopback server. The app-browser plugin could not bootstrap (trusted Node process exited); the independent fresh-browser fallback completed the required checks without using a personal browser profile.

1. Reference upload, rubric approval, student upload, authoritative review (score 97).
2. Button zoom, fit, drawing-mode and issue-selection preservation.
3. Wheel anchor and drag pan without accidental selection at 1366 by 768.
4. The same pointer behavior at 760 by 900.
5. Keyboard zoom, arrows, Home, expand/Escape, focus containment and restoration.
6. Actual PDF download, synchronized appendix controls, deterministic option isolation.
7. Loading state and simulated expired-report 410: error shown without losing review state.
8. Editing requires reapproval; three repeated reviews reset navigation without duplicated handlers.
9. Correct supporting-ID links, valid interactive markup, essential notices, optional raw findings.
10. No horizontal overflow at widths 1366, 760, and 390; screenshots inspected.
11. SVG script/foreignObject/event-handler sanitization; no uncaught browser errors.

## PDF verification

Seven synthetic production-export cases were generated, checked, rendered with Poppler, and visually inspected: standard (3 pages), 60 linked evidence rows (7), wide (3), tall (3), unsupported notices without appendix (3), with appendix (4), and long metadata (3). All 26 pages were inspected for clipping, overlap, missing content, and pagination. An additional final six-page compact partial-work report was checked for all 132 primary IDs; its detailed findings pages were rendered and inspected after the final wording adjustments.

Drawing pages preserve vector output (no image XObjects), proportional scaling, full bounds, overlays and legend. Essential unsupported warnings remain visible without the appendix; the detailed appendix includes all 20 synthetic unsupported records. Identical snapshots/options produce identical PDF bytes. Browser navigation does not mutate the authoritative export snapshot.

Fixed A4 fitting necessarily makes extreme 1:50 geometry physically narrow; vector zoom remains available. No tiling or altered geometry was introduced. Scratch PDFs/screenshots were created in process-owned Windows temporary directories outside the repository, not as deliverables or repository fixtures.

## Privacy, Git, and isolation

The CAD-policy history scan passed before the repair commit (48 historical commits); the pre-commit CAD gate also passed. Final history/status checks are repeated after the report commit and included in the handoff. No tracked or on-disk DXF/DWG fixtures were found in the implementation worktree. Ignore probes for `.dxf`, `.DWG`, nested `.DxF`, and nested `.dWg` all passed. These rules and gates prevent ordinary accidental additions; a user deliberately bypassing Git protections is not technically impossible.

Synthetic uploads use memory buffers and local temporary fixtures outside the repository. No personal teaching examples, DXF/DWG files, or new dependencies were committed or uploaded to a remote service.

The root checkout remains on `fix/issue-5-partial-ellipse-rendering` at `31c94a4f6b5d3feae8448654459e384612da2b83`. Its pre-existing five unstaged files were left untouched: `app/dxf.py`, `app/pdf_report.py`, `app/reviewed_dxf.py`, `app/svg_renderer.py`, and `tests/test_ellipse_rendering.py`.

Evidence for the integration blocker: `git merge-base --is-ancestor 31c94a4 HEAD` exits 1 in this worktree; no tracked ellipse-test file or `sample_ellipse_arc` implementation is present. Local all-ref commit-message searches for #11/issue-11/Issue 11 return no matches. Absence of such labels does not prove #11 never existed; it means its required source has not been established. Root changes were not copied or merged implicitly.

## Reproduction

Run from this implementation worktree, with the repository Python environment and Node installed:

```powershell
$reviewPython = 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe'
& $reviewPython -B -m pytest -q -p no:cacheprovider --disable-warnings --tb=short -rN
& $reviewPython -B scripts/check_cad_policy.py --history
node --check app/static/app.js
git diff --check
```

Optional reproducible browser QA requires Playwright and Microsoft Edge. Start `& $reviewPython -B -m uvicorn app.main:app --host 127.0.0.1 --port 8766` in a separate terminal, then run:

```powershell
$env:DRAFTLENS_QA_PYTHON = $reviewPython
$env:DRAFTLENS_PLAYWRIGHT_MODULE = 'C:\Users\mouki\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
node scripts/qa_review_usability.cjs
```

Optional PDF rendering requires Pillow, pypdf, and Poppler in the QA environment (not new application dependencies):

```powershell
$env:PYTHONPATH = '.'
$env:DRAFTLENS_PDFTOPPM = 'C:\Users\mouki\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
& $reviewPython -B scripts/qa_review_pdf.py
```

The scripts print temporary artifact locations. Stop only the QA server you started when finished. These host-specific runtime paths may need adjustment elsewhere. Browser automation covers Chromium desktop/narrow layouts, not Safari, touch hardware, or screen-reader certification. Seven existing test warnings remain; no new failing or skipped tests were concealed.

## MOUKID local acceptance checklist

- Use nonconfidential reference/student files kept outside the repository; approve the reference and run a review.
- Collapse/reopen setup; edit a setting and verify reapproval is required while student controls remain usable.
- Exercise zoom, pan, Fit, Locate, both drawing modes, expanded view, and keyboard/Escape at desktop and narrow widths.
- Open supporting links, capped actionable findings, and unsupported notices; confirm IDs and actual deductions match the review.
- Download PDFs with and without detail, inspect the full drawing and long findings, and confirm unchanged scores/IDs.
- Resolve the #5/#11 integration prerequisites and re-run relevant regression/full acceptance checks before considering release readiness.

## Remaining action and rollback

The owner must identify the intended #11 source/integrated baseline and explicitly authorize integrating the verified #5 work into the intended branch. This report does not authorize importing the root's uncommitted work. No additional feature or release work should be inferred from successful usability tests alone.

If these usability repairs must be rolled back, review and revert local repair commit `1041bea` only with owner approval; do not reset or overwrite unrelated work. No rollback was performed.
