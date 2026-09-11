# Local usability acceptance and ellipse integration plan

Inspection date: **2026-09-11, Africa/Cairo**. This is a plan and read-only integration investigation, not execution of integration or implementation of #11.

## Separate statuses

**A. Usability: ready for MOUKID's local acceptance** of #8, #9, #3, #4, and focused UI improvements, on the basis of the already reported 423 passing tests, eleven live-browser groups, and rendered-PDF inspection. Human acceptance remains pending. No full suite was rerun for this setup.

**B. Combined release: pending ellipse integration and verification.** #5 and #11 are outside usability scope. Missing ellipse work is not a usability regression. This investigation neither approves nor performs a merge, cherry-pick, rebase, push, issue closure, or new feature implementation.

## Exact sources and branch state

| Source | Resolved commit | State and meaning |
| --- | --- | --- |
| `feature/review-usability-v1` | `6e620fadac57f778dc4765dcc3766367aab4b83e` | Current usability HEAD, including the original review-report documentation commit. |
| Usability repair code | `1041bea996b1be39af98c6358af696368c5a3301` | Last independently fully tested usability code; parent of the original report commit. |
| Antigravity usability UI | `f834795c392d0e69cb106d5357f46d2628c66791` | Committed UI/viewer implementation. |
| Antigravity PDF/findings | `04d61c25d292208155d89ec42b93786ca07d239a` | Committed PDF/presentation implementation. |
| `release-candidate/draftlens-v0.3.0` and `release-candidate/issue1-ref01-sanitized-v1` | `55c8d9bf1dc25279af5505c1237d6a333d56ec92` | Shared base; both matching remote-tracking refs and live remote heads resolve here. |
| `fix/issue-5-partial-ellipse-rendering` | `31c94a4f6b5d3feae8448654459e384612da2b83` | Initial #5 implementation only; parent is `55c8d9b`. Later repairs remain uncommitted. |
| `release/competition-v2`, `origin/release/competition-v2`, and remote default branch | `3345025a1227a725c8c9abfea5a4b13d36724ff9` | Published merge history; tree is identical to `55c8d9b`, so this adds neither ellipse fix. |
| `origin/fix/compatibility-coherence-v1` | `cff61dedb1e297ab3345da49e1e24b036e1247d8` | Available older compatibility source, not a missing ellipse-size fix. |
| #11 complete size-comparison implementation | No source commit found | Parsing/rendering infrastructure exists; required comparison behavior is absent in the inspected sources. |

Inspected all 34 local/remote-tracking ref entries and eight local tags for ellipse-related comparison code/tests, plus relevant history diffs. A live read-only `git ls-remote --heads origin` returned the four remote branches listed above; no remote usability or ellipse-fix branch is advertised. No fetch or ref update was performed. This does not claim knowledge of unpublished work outside these available sources.

The root remains at `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU`, on the #5 branch. The usability checkout is its separate worktree at `.worktrees/review-usability`. The only new changes from this task are this plan and an additive clarification in the original review document; they are left uncommitted. Current branch HEAD remains exactly `6e620fa`.

## Local acceptance server and checklist

Open **http://127.0.0.1:8766/**. Dedicated server launcher PID: **96388**; listening Python child PID: **91728**, parent 96388. Verified listener address `127.0.0.1`, explicit usability `--app-dir`, imported module path inside the usability worktree, HTTP 200, correct `review-usability-2` marker, and served JavaScript equal to the usability file. These PIDs/URL are session observations, not permanent service configuration.

To launch this exact version again, use the existing Python environment, from a PowerShell terminal. Port 8766 is already occupied by the acceptance server while it runs; use the existing URL or choose another unused port rather than killing an unrelated process.

```powershell
Set-Location 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\review-usability'
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m uvicorn app.main:app --app-dir 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\review-usability' --host 127.0.0.1 --port 8766
```

No existing server was stopped. The dedicated acceptance server is intentionally left running for MOUKID.

- Upload nonconfidential local reference/student files, kept outside the repository. Approve the reference and run a review.
- Test wheel/buttons zoom, drag pan, Fit, issue Locate, expanded view/Escape, and both drawing modes. Selection should preserve zoom; dragging should not accidentally select an issue.
- Open linked supporting details and unsupported notices. Check meaningful IDs/text and that unsupported content is explicitly described as not assessed.
- Download PDF with technical details off, then on. Compare score/IDs, dedicated drawing page, essential notices, and added supporting/unsupported detail. Browser zoom should not crop the PDF.
- Collapse/reopen setup and confirm student controls remain usable. Edit reference/rubric settings and confirm required reapproval before the next review.

## What is committed for #5

Commit `31c94a4` adds `sample_ellipse_arc`, partial-curve bounds, SVG open-path rendering, ReportLab open-vector paths, and 13 initial tests. It changes `app/reviewed_dxf.py`, `app/svg_renderer.py`, `app/pdf_report.py`, and `tests/test_ellipse_rendering.py`.

It is not the final corrected version: its full-turn tests use fixed tolerances (`1e-5` and `1e-7`), and it does not pass ellipse extrusion through the rendering path. Integrating this commit alone would omit later corrections for tiny wrapped arcs, reversed normals, and representable near-full intervals.

## What exists only in the root working tree

Read the actual diff for all five files; no file was staged, committed, stashed, reset, discarded, or copied to another branch.

| File | Additional uncommitted behavior | Overlaps usability changes? |
| --- | --- | --- |
| `app/dxf.py` | `_xyz` and extraction/defaulting of ellipse extrusion; preserved in properties. | No. |
| `app/reviewed_dxf.py` | Normal-sign-aware minor axis; exact full-turn boundary; `nextafter` sweep guards; strict equal-endpoint handling; endpoint evaluation; extrusion-aware bounds. | No. |
| `app/svg_renderer.py` | Passes extrusion into the shared sampler. | No. |
| `app/pdf_report.py` | Passes extrusion into the shared sampler in the ellipse drawing branch. | **Yes**, same file, principally different functional areas. |
| `tests/test_ellipse_rendering.py` | Eight additional tests, PDF content-stream checks, tiny-arc/negative-normal/float-boundary regressions; total 21 tests. | No; usability adds different test files. |

The current root diff is 540 insertions and 18 deletions relative to `31c94a4`. Source SHA-256 fingerprints before/after investigation match:

```text
app/dxf.py                     1F92B1A1FFAD007BA18C05A5B3B8E3E504CF108700D149698C8FD59E902EACEA
app/pdf_report.py              5AF8AEDE81EE41512843F9DFCA745A99A79CB90C40F7C627C375A20F6245C36C
app/reviewed_dxf.py            DC417A38911FE8E2CB2C13ADA9265DADA4894BB3C3B2D027683EAC01197BE25C
app/svg_renderer.py            904D5C5168019473CBCD918F94C23C6A9CC2EDCC60A66F2C9C8AFAEE8CDBA3F0
tests/test_ellipse_rendering.py 3E45F6F1E4EF247A2147F58AA86AFEC47D1CBFF10F8AA124EE9084F700179767
```

### Last-tested evidence

Antigravity's local `C:\Users\mouki\.gemini\antigravity\brain\ee306106-f916-49e3-ae77-cdeda8a0782a\walkthrough.md` describes exactly the final `sp + math.tau` / `nextafter` implementation and reports 21 focused tests and 428 full-suite tests passing. It provides no immutable commit/hash for those uncommitted files; its full-suite total is reported historical evidence, not a fresh result from this task.

This investigation independently ran only `python -B -m pytest tests/test_ellipse_rendering.py -q -p no:cacheprovider --disable-warnings --tb=short -rN` against the fingerprinted root version: **21 passed, seven warnings, 0.47 seconds**. This establishes the current focused-tested version as `31c94a4` plus the five exact working-tree files above. It does not certify a combined build or repeat the full-suite claim.

## #11: code and behavior trace, not message inference

Confirmed supporting infrastructure:

1. `app/dxf.py` parses `major_axis`, `ratio`, and start/end parameters into `Entity.properties`; the uncommitted patch additionally preserves extrusion.
2. `app/compare.py:69` includes properties in exact geometry signatures, so unequal axes can prevent an exact-signature match.
3. Viewer/PDF rendering uses axes; #5 concerns rendering the selected arc, not detecting size errors.

Missing size-comparison behavior:

1. `entity_length` (`app/dxf.py:142` in the current root) has no ellipse case and returns `None`.
2. `_intrinsic_match_quality` (`app/compare.py:497`) has no ellipse branch. It falls back to length values treated as zero, giving same-layer ellipse pairs quality 1 even when axes differ.
3. `_candidate_cost` (`app/compare.py:621`) uses distance, length, angle, and radius; same-center ellipse pairs have no axis-size cost.
4. `analyze_comparison` (`app/causal_analysis.py:386`, matched-pair logic around lines 504-630) cannot derive ellipse length/radius/axis differences from these fields. There is no dedicated major/minor-axis observation or finding.
5. `app/compare.py` and `app/causal_analysis.py` have identical Git blob IDs on the release candidate, usability HEAD, committed #5 branch, and published release. Relevant all-ref history searches and actual code/test searches found rendering tests only, not a size-comparison repair hidden behind another commit message. All eight tags likewise yielded only the generic renderer test.

Fresh in-memory DXF probes, using `compare_drawings` with an approved default rubric in strict mode (not claiming a browser/API compatibility test), show:

| Reference semiaxes | Student semiaxes | Change | Result |
| --- | --- | --- | --- |
| 20, 10 | 20, 10 | Control | Score 100; no issues. |
| 20, 10 | 40, 10 | Major only | Score 100; no issues. |
| 20, 10 | 20, 16 | Minor only | Score 100; no issues. |
| 20, 10 | 40, 20 | Both | Score 100; no issues. |

All have center (50,50), same layer, intrinsic quality 1 and candidate cost 0. The changed axes survive parsing. Thus **partial infrastructure is confirmed; a complete #11 fix is not found, and the tested size-error behavior is absent**. #11 was not implemented in this task.

## Proposed integration sequence — for review only

Proposed branch: **`codex/integration-draftlens-v0.3.0`**, in a new dedicated worktree, based on **`6e620fadac57f778dc4765dcc3766367aab4b83e`**. This preserves all verified usability commits by ancestry. The common workstream base is `55c8d9b`. No branch/worktree was created during this investigation.

1. Complete MOUKID's usability acceptance. Preserve these documentation-only changes with an explicitly scoped documentation commit if desired; if included as the integration base, record its new exact hash before branching. Do not silently substitute a moving branch name for the reviewed base.
2. In the separately owned #5 workflow, obtain approval to commit the fingerprinted five-file correction on top of `31c94a4`. Recheck fingerprints/status first and inspect any new edits. Record the resulting immutable correction commit as `ELLIPSE_CORRECTION_COMMIT`; this hash does not yet exist and must not be invented. No root staging/commit is authorized by this plan alone.
3. After integration approval, create the dedicated integration branch/worktree from the exact accepted usability HEAD. Merge the pinned #5 correction commit (a descendant of `31c94a4`) once. This brings in both the original rendering work and the corrections; do not merge/cherry-pick only `31c94a4` and claim the complete fix.
4. Inspect the resulting full diff and PDF behavior as described below. Run focused #5/usability checks before any next integration.
5. For #11, obtain the separately developed, committed, reviewed size-comparison implementation and pin its hash. No existing available branch can supply it. If #11 remains a release requirement, stop combined-release promotion until this source exists and is verified. Integrate it only after authorization and after reviewing its grading/rubric/compatibility consequences; do not implement it as part of usability cleanup.
6. Run focused #11 and combined geometry/presentation checks, then the complete release gates. Record exact integrated HEAD and results. Keep all work local; publication/merging to a release branch still requires the owner's separate decision.

This is an exact source/base strategy for the available commits and a deliberately gated sequence for the two as-yet nonexistent source hashes. It is not an executable claim that #11 can currently be merged. Pending owner decision: **must #11 remain a gate for v0.3.0, or may it be explicitly deferred while #5 and usability are integrated?**

### PDF overlap and conflict handling

`app/pdf_report.py` is the only changed-file intersection between usability and the current complete #5 work. The usability diff adds presentation imports and changes `_issue_story`, `_finding_summary_story`, and `generate_pdf`; AST comparison confirms `ReviewedDrawingFlowable` is unchanged from the common base. #5 changes the sampler import and the ellipse branch of that drawing class; its working-tree follow-up adds the extrusion argument.

An automatic merge may succeed because the function-body edits are separate; import-context conflicts remain possible. No actual merge/conflict simulation was performed. The major risk is whole-file conflict resolution discarding one side. Never select the entire older ellipse PDF file or the entire usability PDF file blindly.

Preserve together:

- Shared arc sampler, negative-normal propagation, open stroke-only vector paths, no closing chord, and full-ellipse fallback.
- Dedicated drawing page, proportional fit, frame width/padding correction, full extents, overlays and legend.
- Technical appendix option, deterministic snapshot export, default essential warnings, complete actionable IDs, linked evidence, long-row splitting and compact-report limits.
- API option validation, no-store/variant behavior, progress/error handling, and browser navigation independence.

No current textual overlap exists in the other #5 files. Future #11 conflicts cannot be predicted exactly without its diff; likely review surfaces are parser properties, matching/causal observations, correction guidance, and tests. New ellipse findings must remain visible and correctly scored in both browser and PDF without changing unrelated grading contracts.

## Post-integration verification gates

Run these only on the future integrated snapshot, not as another usability implementation:

1. Focused tests: `tests/test_ellipse_rendering.py`, `tests/test_reviewed_dxf.py`, `tests/test_pdf_export.py`, `tests/test_review_usability.py`, `tests/test_review_usability_repairs.py`, and `tests/test_ui.py`.
2. #5 behavior: full, partial, wrapped, tiny nonzero, degenerate, near-full `nextafter` boundaries, reversed normal, rotated major axis; parser/serialization, bounds/Locate, both viewer modes, PDF open-path operators/endpoints and vector parity. Render real combined PDFs with both appendix settings and dense/wide/tall cases.
3. #11, if in scope for the candidate: equal-ellipse control, major-only/minor-only/both changes, rotated/translated equivalents, tolerance boundaries, deterministic pairing, partial ellipses, explicit units/normalization and compatibility behavior. Verify authoritative evidence, IDs, rubric mapping/caps, deductions, correction guidance, and browser/PDF consistency. Use the approved #11 contract; do not invent a new grading rule during integration.
4. Regression focus: `tests/test_compare.py`, `tests/test_causal_analysis.py`, `tests/test_compatibility.py`, `tests/test_compatibility_api.py`, `tests/test_normalization_transparency.py`, `tests/test_ref01_adversarial.py`, `tests/test_ref01_diagnosis.py`, and Issue #1 validation/approval tests. Compare identical synthetic baseline inputs to isolate intentional #11 changes from accidental grading changes.
5. Full release gates from `.github/workflows`: `python -B -m pytest -q -p no:cacheprovider` and `python scripts/check_cad_policy.py --history`; also `node --check app/static/app.js`, `git diff --check`, no tracked/on-disk CAD fixtures, mixed-case ignore probes, and an explicitly clean committed integration worktree.
6. Re-run the live browser acceptance and rendered PDF checks on the integration server, not the old usability server. Check branch/module/asset identity and record exact HEAD, test counts, visual results and remaining limitations. No PASS for a combined release while a required source or gate is missing.

All synthetic/private testing files remain outside the repository. No DXF/DWG files may be added, tracked, or uploaded to GitHub. The acceptance server remains local-only; normal user upload functionality is unchanged.
