# Reference Object Tagging and Unit/Scale Review - Independent Final Audit

## Verdict and target

**PASS - current object-information, units, assignment-setup and review-usability stage only.**
Verified on 2026-09-20. This is not combined-release approval. Actual private T3 acceptance remains pending; equivalent synthetic coverage passes.

- Worktree: `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags`
- Branch: `feature/reference-object-tags-v1`.
- Remote: `https://github.com/moukid/DraftLens-EDU.git`.
- Implementation base: `8de5c78460ae321e5ad52ee13fb851768678debc`.
- Submitted Antigravity HEAD: `4c291d143a3283bc5ccf43ad2ed2d1716f45ecd6`.
- Prior Codex checkpoint `98dc3fc` and subsequent `3ccdbc9`, `14f7ce5`, `4c291d1` remain preserved.
- **Tested application commit: `4e68ba53e094ade29a33d7a7ad6daf845d09a26e`.**
- This report is a subsequent documentation-only commit. Application/test content is unchanged from the tested commit.
- Target was clean before audit repairs. The unrelated dirty root checkout on `fix/issue-5-partial-ellipse-rendering` remains untouched.

The previous report is retained in Git history; its totals and readiness claims are superseded by the independently executed evidence below.

## Findings repaired

No unresolved mandatory blocker or open P1/P2 defect remains within the tested stage.

1. **P1: stale assignment approval.** Changing inspected mappings, custom layers or legend exclusion immediately invalidates associated approval and obsolete saved definitions. Direct review with the old rubric returns 409; existing report snapshots remain immutable.
2. **P1: custom metadata reaching grading before group confirmation.** Grading now uses the current inspected custom-layer configuration. Distant metadata is excluded even before object confirmation; an otherwise matching student scores 100.
3. **P2: object editing lifecycle and preview.** Server-reported saved state, explicit unresolved/excluded choices, immutable submission payload on rejected saves, dirty-state review invalidation, numeric bounds, preserved zoom during membership edits, actual arc rendering, expanded-preview Escape and wrapping narrow cards were repaired.
4. **P2: overstated physical-unit consistency.** A low-support extents ratio no longer establishes physical consistency; high/verified confidence and at least three supporting matches are required. Insufficient evidence is explicitly described. No source geometry is rescaled.
5. **P2: translated diagnostic regions.** Comparison locations are transformed to the student frame even when the finding has a source entity. A translated 3 mm gap checks actual endpoints and region coordinates.
6. **P2: false gaps on dense identical geometry.** Rendered PDF inspection exposed two gap markers on an identical tall drawing. A transitive tolerance cluster was being treated as an all-pairs junction. Comparison now checks only reference-required local contacts and reports the measured violating endpoint pair. Identical dense chains produce no gaps; a broken local link still produces the correct evidence. Scoring policies and deduction rules are unchanged.
7. **P2: PDF default detail and provenance.** Default reports collapse linked supporting records to a count/appendix pointer. Intended/declared units and confirmation are recorded. Reference counts are explicitly expectations; member correspondence is described as a preview, not automatic object recognition/scoring.
8. **P2: invalid legend bounds.** NaN/infinite coordinates now return 422.

Added seven endpoint/PDF regressions, two topology regressions, procedural synthetic uploads and an eight-group live acceptance harness. Existing PDF tests now explicitly check default-vs-appendix behavior without weakening score assertions.

## Functional verification

| Area | Independently checked result |
| --- | --- |
| Information layers | Case-insensitive DL-Info prefix, suffixes and near-matches pass. Metadata remains interpretable but excluded from assessed reference geometry, matching, normalization, scale evidence and extents. |
| Student boundary | Student geometry on reserved layers remains assessed. Custom-layer isolation and distant-metadata grading invariance pass through actual endpoints. |
| Legends and unknowns | Legend layers/regions do not inflate plan counts; malformed/descriptive text is not promoted to markers; unknowns remain unresolved. |
| Object authority | Actual member add/remove, confirm, exclude, unresolved and saved reopen pass. API rejects stale tokens, foreign/empty groups and unacknowledged overlaps; changes require renewed approval. |
| Assignment | Explicit type required in UI/API; choice appears in review/PDF and resets for replacement reference. Translation is the new-assignment default; explicit strict and existing snapshots remain supported. |
| Units | Direct-API withholding/acknowledgment cannot be bypassed by normal review requests. Live declared mismatch gives null/withheld score before acknowledgment and 100 afterward for unchanged coordinate geometry; PDF records the decision. |
| Overlays | All nine legend choices, six diagnostic student underlays, empty categories, layer-name collisions and issue/legend synchronization pass actual SVG checks. Missing and gap evidence use the correct student frame after translation. |
| Navigation | Button/wheel/keyboard zoom, pan, Fit, Locate, expanded/Escape pass. Filters and selection preserve navigation; Locate deliberately navigates. Translation adds no rotation or scaling. |
| Connections | Genuine 4 mm gap at 2 mm tolerance uses real endpoint rings/short connector and readable underlay. Correct connections and intentional reference openings are not errors. Large regions are technical-only. Supporting findings have zero added deduction. |
| UI/export | Supporting evidence is collapsed by default; unsupported coverage remains visible. Filtering does not change grades/PDF bytes. Bold headings, aligned tolerance inputs and exact two-line footer pass rendered checks. |

## Final automated evidence

- **475 passed, 9 warnings in 27.98 seconds** on final application/test code.
- Warnings: seven ezdxf/pyparsing import-time deprecations and two query-API deprecations in a new test; no failures.
- JavaScript syntax (app and new harness), Python compilation (app/tests), working/staged diff checks: PASS.
- CAD policy before final commits: PASS, no tracked DXF/DWG paths in **59 reachable historical commits**. Repair-commit hook also passed.
- Exact staged source/tests and outgoing commit paths inspected. All new geometry is procedural/synthetic; no CAD files, PDFs, screenshots or private geometry were staged.
- Bounded credential-pattern scans of outgoing/staged additions found zero matches. This is not a general security certification.

The first regression runs caught test-authoring mistakes (result-field name and misplaced existing assertions); these were corrected without removing assertions. The complete passing final run supersedes them.

## Actual browser and PDF acceptance

The primary in-app runtime failed with "trusted Node process exited unexpectedly". The authorized local Playwright/Microsoft Edge fallback used temporary profiles, no personal credentials and no repeated retries of the broken runtime.

Final server: http://127.0.0.1:8021/ from the audited worktree. Served JavaScript was compared with the worktree byte-for-byte, normalizing line endings. All suites were rerun after the last production change:

| Harness | Passing groups |
| --- | ---: |
| scripts/qa_reference_object_tags.cjs | 6 |
| scripts/qa_interactive_legend.cjs | 12 |
| scripts/qa_review_usability.cjs | 11 |
| scripts/qa_connectivity_presentation.cjs | 7 |
| scripts/qa_final_stage_audit.cjs | 8 |
| Total | **44** |

Desktop 1440/1366, narrow 760 and mobile-width 390 layouts were exercised. The independent harness uses real uploads/endpoints and pointer interactions, not injected review/object state. Other harnesses also use controlled rendering fixtures: these are 44 check groups, not 44 independent assignments. No uncaught browser errors were observed; the independent harness asserts no console errors. UI downloads, appendix synchronization and byte-identical PDFs across filters pass.

Seven synthetic PDF cases were regenerated on final code: standard, dense evidence, wide, tall, coverage warnings, appendix and long metadata. All are deterministic on repeated generation and vector-only (no image XObjects). Six ordinary cases have 3 pages; appendix has 4. All seven contact sheets were visually inspected: no clipped text, overlapping tables or large obscuring diagnostic rectangles. Extreme 20:1000 geometry stays proportionally narrow rather than stretched, limiting fine detail at whole-page fit.

Actual browser-generated unit report: 3 pages; gap default: 3; gap appendix: 4. Visually checked declarations/acknowledgment, reference expectations, drawing/legend, primary length deduction, collapsed support and full measured gap evidence with zero added deduction. Snapshot determinism survives later configuration changes.

Local scratch evidence (not committed; temp cleanup may remove it): %TEMP%\draftlens-final-stage-c1oJ9h and %TEMP%\draftlens-pdf-qa-reiimhc6.

## T3 and product limitations

Requested actual T3 files were not found in bounded searches of accessible Downloads, Desktop, Documents, the project collection and available E: location. Protected paths were inaccessible; this is not an exhaustive whole-disk claim.

Synthetic T3 equivalent passes **27 plan markers separated from six legend samples**, with expected per-code counts. Real private-T3 acceptance remains pending instructor execution outside Git; per the request, equivalent synthetic coverage permits scoped acceptance.

- Grouping is instructor-confirmed; student correspondence is a preview, not automatic door/window recognition or object scoring.
- Assignment type is explicit and consistent, but does not implement full assignment-specific rubric automation. Baseline/instructor-modified rubric still governs scoring.
- Assignment/approval/report stores are process-local. Server restart requires re-upload/reapproval; report snapshots are immutable within the running store.
- This is local stage QA, not production persistence, multi-user concurrency or a general security audit.
- Ellipse integration and combined-release acceptance remain separate; no ellipse work was imported.

## GitHub issue scope

Current relevant descriptions/comments were read using GitHub CLI. Final refresh: #1/#3/#4/#8/#9 OPEN, no comments. No issue mutations were made.

| Issue | Stage evidence / boundary |
| --- | --- |
| #1 - Idea: Critical issues and warnings information | Reference validation source/severity evidence and visibility outside filters covered by validation/API and browser tests; not a claim that every future CAD diagnostic is complete. |
| #3 - Idea: Hide supporting topology findings from the default issue list/pdf | Collapsed linked UI evidence; default PDF summary/appendix detail; zero extra deductions. |
| #4 - Idea: Hide Unsupported Entity warnings from the default issue list/pdf | Visible assessment-coverage notice, individual records in technical/appendix detail. |
| #8 - Idea: Add zoom and pan support to the drawing viewer | Actual pointer/wheel/keyboard, Fit/Locate, expanded/Escape and navigation-preservation checks pass. |
| #9 - Idea: Improve PDF report layout and drawing scaling | Seven rendered cases, vector aspect-preserving drawings, wrapped metadata/notices and actual downloads verified. |
| #2 | Partial only: reserved/custom reference information layers, not complete general layer exclusion. |
| #6, #7, #10 | Outside this stage; existing related tests are not issue acceptance. |
| #5, #11 | Separate untouched ellipse workstream; not blockers for this stage. |

## Reproduce and instructor acceptance

Use the existing environment; no dependency installation was needed.

```powershell
Set-Location 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags'
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m pytest -q
node --check app/static/app.js
node --check scripts/qa_final_stage_audit.cjs
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m compileall -q app tests
git diff --check
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B scripts/check_cad_policy.py --history
```

Launch only if the audit server is no longer running; do not start a duplicate on an occupied port:

```powershell
Set-Location 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags'
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m uvicorn app.main:app --host 127.0.0.1 --port 8021
```

Open http://127.0.0.1:8021/. In another PowerShell window at the same worktree:

```powershell
$env:DRAFTLENS_QA_PYTHON = 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe'
$env:DRAFTLENS_PLAYWRIGHT_MODULE = 'C:\Users\mouki\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$env:DRAFTLENS_QA_URL = 'http://127.0.0.1:8021'
node scripts/qa_reference_object_tags.cjs
node scripts/qa_interactive_legend.cjs
node scripts/qa_review_usability.cjs
node scripts/qa_connectivity_presentation.cjs
node scripts/qa_final_stage_audit.cjs
$env:DRAFTLENS_PDFTOPPM = 'C:\Users\mouki\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
& $env:DRAFTLENS_QA_PYTHON -B -m scripts.qa_review_pdf
```

Manual T3 follow-up: upload from outside Git; select assignment type/intended unit; inspect actual 27/6 separation and members; confirm/exclude or leave unresolved; approve; review student; explicitly resolve unit notices; check filters/navigation; download both PDF variants. Never commit private evidence.

Publication is a normal feature-branch push to verified origin, followed by remote-HEAD equality verification. The final task response records the documentation commit SHA and push outcome. No force-push, merge, tag, release, issue mutation or ellipse integration. If recovery is later needed, use an explicitly authorized scoped revert; no automatic reset/history rewrite was performed.
