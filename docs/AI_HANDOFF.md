# DraftLens EDU — AI Handoff

> Keep this file concise (~50 lines). Overwrite at meaningful checkpoints; do not append a diary.

## Baseline
- Branch: `release/v0.3.0-alpha.1`
- Baseline HEAD: Milestone commit (`fix(grading): implement canonical geometry matching, square grading repair, and PDF reporting recovery`)
- Working Tree: Clean (approved recovery changes committed; untracked instructions, templates, and evidence excluded)
- Status: **COMMITTED LOCALLY**

## Current Milestone
Square Grading Repair & PDF Reporting Acceptance (`object_part_deduction`)

## Current Task
Independent Codex audit of PDF reporting, explanation, and visual acceptance fixes.

## Acceptance Criteria
- [x] Compact unique badge identifiers (`M1`, `M2`, `E1`, `I1`, `C1`, etc.) assigned deterministically per visual role in `ReviewedIssue.badge_label`, with `used_labels` deduplication when mixing pre-labelled and unlabelled issues
- [x] Full package provenance in `manifest.json`, `approved_rubric.json`, and `REVIEW_SUMMARY.md` (`source_identity`, UTC generation times, review IDs, approved rubric ID/SHA-256, and linkage checks)
- [x] Collision avoidance layout for Page 2 drawing badges: candidate vertical levels, horizontal offsets, viewport containment, and leader lines with anchor dots when displaced
- [x] Issue-to-Drawing Mapping Table on Page 2 includes `Badge` as primary column (`M1`, `M2`), rendered with clean labels without literal markup (`<b>`/`</b>`), mapping explicitly to full issue IDs, drawing roles, descriptions, and applied deductions
- [x] Finding titles on Page 3+ show `[Badge M1]` alongside full issue ID; browser UI card identity displays `${issue.issue_id} [${issue.badge_label}]`
- [x] All four absent edges highlighted for missing objects in `ReviewedIssue.expected_geometries` and PDF/SVG renderers, retaining 1 single object deduction
- [x] Deduction attribution shows combined loss and actual category allocation: e.g. `Geometry (6.5) + Completion (2.5)`, applied deduction `9 (Geometry: -6.5, Completion: -2.5)`
- [x] Correction guidance distinguishes whole missing object (`RECTANG`/`PLINE`, explaining whole object absent) from single missing edge (`LINE`/`PLINE`, partial object completion)
- [x] Dynamic drawing height eliminates excessive blank drawing space; headings bound to first finding with `KeepTogether` and `keepWithNext=True`
- [x] All 9 real CAD `Square-test` files match target scores exactly (100, 100, 91, 90, 89, 82, 55, 46, 44) through live review API and PDF reports
- [x] Full pytest suite: 472/472 PASS; targeted pytest suite: 74/74 PASS (`test_square_grading_repair.py`, `test_pdf_export.py`, `test_ui.py`)
- [x] CAD Policy & Privacy: `scripts/check_cad_policy.py` PASS (0 tracked CAD files)
- [x] Zero DXF/DWG tracked; working tree uncommitted; no push/merge/deploy

## Relevant Components / Files
- `app/models.py`, `app/scoring.py` (category split attribution, score categories)
- `app/correction_guidance.py` (whole object vs. single part guidance)
- `app/reviewed_dxf.py`, `app/svg_renderer.py` (all expected geometries for missing objects)
- `app/pdf_report.py` (dynamic drawing height, callouts, issue mapping table, heading grouping)
- Evidence archive: `<<private-evidence>-root>`

## Verification
- Targeted Pytest: `pytest tests/test_square_grading_repair.py tests/test_pdf_export.py` (43 passed)
- Full Pytest Suite: `pytest` (471 passed)
- UI DOM Tests: `pytest tests/test_ui.py` (31 passed)
- Live API 9 Square Targets & PDF Extraction: all 9 files match scores and produce verified PDFs (39 total pages)
- CAD Policy & Git Diff Check: `check_cad_policy.py` (PASS, 0 tracked CAD), `git diff --check` (PASS)

## Codex Readiness
`AUDITED & COMMITTED`: Audited by Codex (`docs/verification/codex-formatting-audit-2026-10-22.md`), authorized local star commit completed.

## Next Action
Await user instruction for subsequent milestone/stage. Do not push, merge, deploy, or begin HATCH work.
