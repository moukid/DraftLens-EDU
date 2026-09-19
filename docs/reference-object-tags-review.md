# Reference Object Tagging and Unit/Scale Review — Independent Audit

## Verdict

**BLOCKED for verified delivery.** The repaired implementation passes the complete automated regression, JavaScript/Python syntax, CAD policy, server-side adversarial, and rendered-PDF checks. The mandatory actual-browser workflow could not be executed because the Codex browser-control Node runtime exits immediately, including after a kernel reset and a one-line health check. Per the audit brief, the repaired files remain local and uncommitted; the feature branch was not pushed.

## Audit target and state

- Repository: `https://github.com/moukid/DraftLens-EDU.git`
- Worktree: `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags`
- Branch: `feature/reference-object-tags-v1`
- Expected/base commit: `8de5c78460ae321e5ad52ee13fb851768678debc` (`feature/review-usability-v1`)
- Submitted implementation HEAD: `240d7368f0078461946fe54fabbcc8f9a69a3d6b`
- Submitted implementation range: `8de5c78460ae321e5ad52ee13fb851768678debc..240d7368f0078461946fe54fabbcc8f9a69a3d6b` (one commit)
- Final reviewed code commit: **none**; the repairs are an uncommitted local diff because mandatory browser verification is blocked.
- Remote state after `git fetch origin --prune`: no `origin/feature/reference-object-tags-v1` exists. No remote work was overwritten and no push was attempted.
- Separate root checkout: `fix/issue-5-partial-ellipse-rendering` remained untouched; none of its uncommitted ellipse work was imported.

## Findings and repairs

### High — untrusted object confirmation could cross reference/assignment boundaries

The submitted confirmation endpoint accepted client-authored meanings, marker positions, handles, bounds, and membership identities without an inspection-bound token. It did not reliably reject stale proposals, foreign member IDs, empty confirmed groups, duplicated/missing occurrences, or confirmation against another assignment.

Repair: inspections now create a configuration/reference fingerprint token and cache authoritative proposals/entities. Confirmation requires that token and the current assignment identity, accepts only known occurrence/member IDs, requires every inspected marker exactly once, rejects invalid/empty/unmapped confirmed objects, and derives all stored authoritative fields server-side. Confirmed bounds are recomputed from the selected members. Overlapping confirmed memberships require explicit instructor acknowledgment.

### High — required unit interpretation could be bypassed

The review API and page could expose a final numerical result while a required unit decision remained unresolved, and rubric approval did not require a concrete intended assignment unit.

Repair: API reviews now enforce unit-decision withholding; approval rejects `unspecified` intended units and records confirmation. The explicit `grade_anyway` path records acknowledgment, restores grading only after that decision, and does not rescale or modify source geometry. Browser state and response fields now use the server's actual diagnostic names. PDF reports explicitly state that the instructor decision was recorded and no source geometry was rescaled or modified.

### High — the submitted UI did not provide an auditable member-adjustment workflow

The original controls did not deliver a complete selectable geometry preview for adding/removing object members, reopening saved definitions, or requiring overlap acknowledgment. Several unit/object field names also did not match the API.

Repair: the page now renders a read-only selectable SVG reference preview with selected-member emphasis, add/remove behavior, per-object status/notes/exclusion, Fit/zoom/pan/expanded controls, and explicit overlap acknowledgment. Inspection configuration includes a bounded legend region, custom information layers, and instructor code mappings. Saved confirmed members reopen when the same reference/configuration is inspected. Reference changes clear stale client state.

**Browser acceptance remains pending** because the required browser-control runtime was unavailable; these controls have not been claimed as rendered-interaction verified.

### Medium — parsing and state semantics were over-permissive

Arbitrary descriptive or malformed information-layer text could become an object marker; known markers without geometry were conflated with proposals; custom mappings/layers and ignored text were not adequately surfaced. Object definition changes could leave an approved rubric associated with stale state.

Repair: marker codes are restricted to normalized `A-Z`/numeric identifiers, ignored descriptive text is reported, known markers without candidates remain `detected`, unknown codes remain `unresolved`, and only nonempty known candidates become `proposed`. Custom mappings/layers are included in the inspection fingerprint. Changed object definitions invalidate the relevant approval; unchanged definitions reopen without invalidation.

The test reset fixture now clears the new inspection and object stores before and after every test, preventing order-dependent state from concealing failures.

### Medium — grading and metadata isolation needed authoritative integration

Stored groups were not consistently restricted to the current reference/rubric during review, and object availability/counts did not clearly distinguish incomplete definitions.

Repair: review uses only groups bound to the selected reference and approved rubric, applies the stored custom information-layer configuration, keeps information entities out of ordinary reference geometry, preserves student geometry even when it uses a reserved layer, and reports detected/proposed/confirmed/unresolved/excluded states separately. The optional student correspondence remains preview-only and does not award or deduct marks.

### Low — report decision evidence was incomplete

The report displayed a unit notice but did not explicitly record the instructor's acknowledgment or the no-rescaling invariant.

Repair: the rendered notice now includes both facts, with wrapping verified on page 1.

## Verification evidence

- Full final suite: **456 passed, 7 dependency deprecation warnings in 27.47 s**.
- JavaScript syntax: `node --check app/static/app.js` — PASS.
- Python byte compilation: `python -B -m compileall -q app tests` — PASS.
- Git whitespace validation: `git diff --check` — PASS (line-ending conversion notices only).
- CAD policy: **PASS; no tracked DXF/DWG files; 55 historical commits inspected**.
- Production hard-code scan: no T3 filename/count/coordinate/handle behavior in `app/`; architectural codes such as `DD1` and `SD1` are generic mappings.
- Server-side regressions cover stale tokens, foreign IDs, missing/duplicate occurrences, empty confirmations, cross-assignment confirmation, overlap acknowledgment, approval invalidation/reopen, malformed/descriptive text, reserved-layer student geometry, custom mappings/layers, grading invariance, and unit withholding/acknowledgment.
- PDF: synthetic private-data-free report regenerated from final code (46,560 bytes); extracted text assertions passed. Page 1 was rendered at 150 DPI and visually inspected: the long unit warning and recorded-decision text wrap without clipping, score tables align, and footer/credits remain intact. Earlier representative appendix rendering was also inspected without overlap/clipping.
- Local server startup: Uvicorn bound to loopback at `http://127.0.0.1:8017/`; HTTP confirmation is recorded separately in the final audit handoff.
- Browser workflow: **BLOCKED**. The current in-app browser skill was loaded as required, but the trusted Node REPL process exited on documentation initialization, after reset/retry, and on a minimal health check. Therefore desktop/narrow viewport interaction, console, zoom/pan/resize/expanded alignment, filters, and report-download behavior are not accepted.

The 7 test warnings are pre-existing `ezdxf`/`pyparsing` deprecation warnings, not failures.

## T3 acceptance

The real `T3-Ref_DL-INFO.dxf`, `T3-Ref.dxf`, and `T3-003.dxf` files were not available in the searched local locations outside the repository. Actual-file acceptance is **pending**.

A generated synthetic equivalent verifies that six legacy legend samples are excluded and produces the required 27 plan-marker counts: D1 7, W1 9, C1 7, DD1 1, SD1 1, S1 2. This is parsing/count evidence only, not proof of confirmed object correctness. No T3 fixtures, coordinates, handles, object maps, screenshots, or filenames were added to production behavior or committed.

## Remaining limitations

- Mandatory actual-browser acceptance is pending; this is the delivery blocker.
- Reference-object/rubric/inspection state is process-local. A server restart or session loss requires the instructor to re-upload, reinspect, reconfirm, and reapprove; stale browser tokens are rejected rather than recovered silently.
- Actual T3 file acceptance remains pending.
- Automatic object scoring/deductions are intentionally absent. Student correspondence is an informational preview.
- Arbitrary architectural-object recognition and CAD editing are outside scope.
- Combined-release ellipse integration and its regression verification remain separate work and are not a failure of this feature audit.

## Run instructions (PowerShell)

```powershell
Set-Location 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags'

& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m pytest -q
node --check app/static/app.js
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B scripts/check_cad_policy.py --history

& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m uvicorn app.main:app --host 127.0.0.1 --port 8017
```

Open `http://127.0.0.1:8017/` only from the local machine.

## Manual acceptance checklist after browser control is restored

1. Upload a synthetic tagged reference; set any needed legend bounds, custom layer names, and code mappings; inspect it.
2. Confirm ignored legend/descriptive text and counts for detected, proposed, unresolved, confirmed, and excluded markers.
3. Select a proposed marker; add and remove geometry; verify selection changes only membership, never source geometry.
4. Confirm one object, exclude or leave another unresolved, acknowledge any overlap, reinspect, and verify saved members reopen.
5. Change mapping or membership; verify rubric approval is invalidated and stale tokens/cross-assignment submissions are rejected.
6. Upload student geometry including a reserved-layer entity; verify it is still graded and reference metadata does not affect ordinary results.
7. Exercise declared-unit difference, matching headers with actual scale difference, unspecified units, physical-unit consistency, insufficient evidence, and explicit acknowledgment. Verify no final grade before required acknowledgment.
8. At desktop and narrow widths, exercise Fit, zoom, pan, resize, expanded view, Locate, Findings filters, underlays/legends, and PDF downloads; check overlay alignment and the browser console.
9. Compare browser notices/counts with the downloaded PDF and confirm filters do not change PDF content.
10. When real T3 files are available, verify the 27-marker distribution independently and inspect object proposals rather than treating counts as correctness.