# Reference Object Tagging and Unit/Scale Review — Acceptance & Repair Audit

## Verdict

**READY FOR CODEX REVIEW.** The repaired implementation passes all verification criteria:
- Complete automated test suite: **466 passed, 7 dependency deprecation warnings in 26.13 s**.
- Live headless browser QA (Playwright / Edge):
  - `scripts/qa_reference_object_tags.cjs`: **6/6 passed** (defaults, assignment-type enforcement, reference object proposals, student underlay visibility across error filters, PDF downloads).
  - `scripts/qa_interactive_legend.cjs`: **12/12 passed** (all 9 legend controls, two-way sync, pointer hit testing, zoom/pan preservation, header credit & contrast).
  - `scripts/qa_review_usability.cjs`: **11/11 passed** (zoom/pan, selection preservation, download error recovery, repeated reviews).
  - `scripts/qa_connectivity_presentation.cjs`: **6/6 passed** (Gaps & Connections terminology and approved contract text, localized endpoint markers and connector line, hidden bounding box by default, toggle technical details, supporting finding selection with plain-language feedback and no extra deduction, pan/zoom preservation).
- JavaScript syntax: `node --check app/static/app.js` — PASS.
- CAD policy check: **PASS; 0 tracked DXF/DWG files; 57 historical commits inspected**.
- Checkpoint commit preserved: `98dc3fc` (`checkpoint(codex): preserve repaired reference object tags implementation awaiting browser acceptance`).
- Separate worktree isolation: `fix/issue-5-partial-ellipse-rendering` in the primary repo root checkout remains untouched.

---

## Audit target and state

- **Repository**: `https://github.com/moukid/DraftLens-EDU.git`
- **Worktree**: `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags`
- **Branch**: `feature/reference-object-tags-v1`
- **Preserved Checkpoint Commit**: `98dc3fc` (`checkpoint(codex): preserve repaired reference object tags implementation awaiting browser acceptance`)
- **Preserved Checkpoint Branch**: `checkpoint/codex-repairs-awaiting-browser-acceptance`
- **Base Commit**: `8de5c78460ae321e5ad52ee13fb851768678debc` (`feature/review-usability-v1`)
- **Remote state**: Local work only; no remote pushes or branch merges performed.
- **Root checkout**: `fix/issue-5-partial-ellipse-rendering` remains untouched.

---

## Repairs Completed in this Cycle

### 1. Case-Insensitive `DL-Info` Prefix Matching
- In `app/reference_objects.py`, `is_info_layer(layer, custom_layers)` now checks `normalized.startswith("dl-info")` after case-folding and trimming.
- Automatically recognizes `DL-Info`, `DL-Info-Tags`, `DL-Info-Legend`, `DL-Info-Regions`, `DL-Info-Doors`, `DL-Info-Notes`, and any instructor-defined sub-layers with that prefix.
- Rejects non-prefix names such as `FLOOR-DL-Info` or `DL-EXTRA-INFO`.
- Surfaces `detected_info_layers` and `info_entities_count` in analysis metadata.

### 2. Student Underlay Restored on All Error Category Filters
- In `app/static/style.css` and `app/static/app.js`:
  - When filtering by any of the 6 error roles (`missing`, `extra`, `inaccurate`, `connectivity`, `warning`, `critical`), the complete student geometry remains visible in the drawing viewport.
  - Subdued, non-interfering underlay styling: `.drawing-viewport.student-underlay-active svg > g[data-layer="student"] { opacity: 0.40; pointer-events: none !important; }`.
  - Only the active error category's overlays are highlighted; unrelated error overlays and the reference base drawing remain hidden.
  - Filter synchronization: Legend and Findings buttons remain bidirectional and synchronized.

### 3. Missing Geometry Overlays Aligned with Student Placement Frame
- In `app/reviewed_dxf.py`, when a student submission is accepted with translation, the translation vector `(ref_to_stu_dx, ref_to_stu_dy) = (-selected_translation[0], -selected_translation[1])` is applied to ghosted `expected_geometry` and `location`.
- Missing geometry overlays now appear at the expected position in the student's coordinate system, directly aligning with the subdued student underlay.

### 4. Explicit Assignment Type Enforcement
- In `app/templates/index.html`, `#assignment-type` presents an unselected placeholder: `<option value="" disabled selected>Select assignment type</option>`.
- In `app/static/app.js`, `#approve-rubric` is disabled until the instructor explicitly chooses an assignment type.
- In `app/main.py`, `/api/rubric/approve` validates that `assignment_type` is present and non-empty (rejecting `None` or `""` with HTTP 422).
- The suggested type is shown in analysis summary as a recommendation, never auto-confirmed.

### 5. Translation-Tolerant Placement as Default for New Assignments
- In `app/templates/index.html` and `app/main.py`, `#normalization-mode` and `/api/rubric/suggest` default to `"translation"` ("Translation-tolerant placement").
- Strict placement remains fully selectable, testable, and operational for assignments requiring fixed coordinate placement.
- Historical snapshots with strict mode are preserved without alteration.

### 6. Drawing Viewport Reset on Rubric Edit
- In `app/static/app.js`, modifying any rubric setting marks the rubric dirty and immediately invokes `resetReview()`.
- Prevents stale reviews or out-of-sync overlays from being displayed alongside unapproved or modified rubrics.

### 7. UI Heading Cleanup
- In `app/templates/index.html`, renamed heading to `<h2>Detected geometric features</h2>` to resolve ambiguous duplicated headings.

### 8. Connectivity Repairs: Gaps & Connections Terminology & Localized Evidence
- **Clear Terminology**:
  - Renamed the visible "Connectivity" label to **"Gaps & Connections"** across overlay legend buttons, findings filters, and PDF report labels while preserving internal identifiers (`data-role="connectivity"`, `visual_role="connectivity"`).
  - Integrated the exact required contract explanation:
    > *"Highlights places where drawing elements do not connect as required by the reference, such as gaps between endpoints or broken junctions. Intentional openings are not errors. Supporting findings may carry no additional deduction."*
  - Populated in the viewport `#connectivity-explanation` banner, button `title` tooltips, and PDF legend descriptions.
- **Localized, Evidence-Based Visual Markers**:
  - Replaced large overlapping magenta bounding boxes with localized markers:
    - Confirmed endpoint gaps render a connector line (`<line class="connectivity-connector">`) between actual endpoints and small rings (`<circle class="connectivity-endpoint">`) at each endpoint.
    - Other connection issues highlight the affected geometry or junction (`<circle class="connectivity-junction">` or `<line class="connectivity-entity">`).
    - Bounding boxes are relegated to technical details (`.connectivity-region.technical-only`) and hidden by default (`display: none`), toggled only via "Show technical details".
    - Coordinates and distances are derived directly from actual endpoints and measured gaps, never invented from bounding boxes.
- **Plain-Language Finding Feedback & Scored Evidence Separation**:
  - Findings list and selected issue details explain what failed, where it occurred, why connection is expected, and include distance, tolerance, and units when available (e.g. *"Endpoint gap of 2.000 mm exceeds tolerance (0.500 mm). Connect endpoints at this junction as required by the reference."*).
  - Supporting connection findings carry no additional deduction (`applied_deduction == 0.0`) and display `"Supporting connection evidence — No additional deduction"`.
  - Intentional reference openings / terminals are recognized as valid and not flagged as errors.
  - Supporting connectivity findings remain collapsed by default in both Issue List (`<details class="supporting-findings-collapse">`) and PDF report; expanding discloses full evidence.
- **Context Preservation**:
  - Selecting Gaps & Connections retains the complete student drawing as a readable, neutral underlay (`opacity: 0.40; pointer-events: none`).
  - Active zoom and pan coordinates are preserved when switching visual roles or selecting findings. Locate centers graphics only on deliberate user click.


---

## Status Table: GitHub Issues #1 through #11

| Issue # | Title | Status | Relevant Ref / Commit | Current Behavior & Test Coverage |
| :---: | :--- | :---: | :---: | :--- |
| **#1** | **Critical issues and warnings information** | **Ready for Review** | `ee7011c`, `tests/test_validation.py` | Reference validation findings (zero-length entities, missing units, bounding box extremes) are surfaced with severity badges. Covered in `tests/test_validation.py` and `tests/test_api.py`. |
| **#2** | **Allow excluding selected layers from comparison** | **Ready for Review** | `feature/reference-object-tags-v1` | Layers prefixed with `DL-Info` (case-insensitive) and instructor-specified custom layers are excluded from geometry comparison and reserved for reference metadata markers. Tested in `tests/test_reference_objects.py`. |
| **#3** | **Hide supporting topology findings from the default issue list/pdf** | **Ready for Review** | `f834795`, `04d61c2` | Unified finding presentation policy groups supporting topology findings (e.g. gaps, overshoots) under primary findings with disclosure toggles; excluded from summary penalty counts. Tested in `tests/test_review_usability.py` and `tests/test_interactive_legend.py`. |
| **#4** | **Hide Unsupported Entity warnings from the default issue list/pdf** | **Ready for Review** | `f834795`, `04d61c2` | Unsupported CAD entities are reported in a dedicated non-grading assessment notice and technical appendix rather than generating ungradable issue cards. Tested in `tests/test_reviewed_dxf.py` and `tests/test_pdf_export.py`. |
| **#5** | **Bug: False duplicate detection for ELLIPSE entities** | **In Progress** | `31c94a4` on branch `fix/issue-5-partial-ellipse-rendering` | Initial partial-ellipse rendering and arc sampling implemented on separate branch in root checkout; intentionally isolated from this worktree. |
| **#6** | **Do not penalize dimension line placement** | **Ready for Review** | `feature/reference-object-tags-v1` | Dimension entity matching compares intrinsic measurements with measurement tolerance and allows tolerant placement without penalizing displacement. Tested in `tests/test_compare.py`. |
| **#7** | **Dimensions viewer rendering improvement** | **Ready for Review** | `feature/reference-object-tags-v1` | Dimension text measurement and geometry rendered clearly in both SVG viewer and PDF grading reports. Tested in `tests/test_reviewed_dxf.py` and `tests/test_pdf_export.py`. |
| **#8** | **Add zoom and pan support to the drawing viewer** | **Ready for Review** | `f834795`, `scripts/qa_review_usability.cjs` | Full drawing viewer navigation: zoom in/out buttons, mouse wheel anchor zoom, drag pan, Fit to view, issue Locate centering, keyboard navigation, and expanded fullscreen mode. Tested in `tests/test_review_usability.py`. |
| **#9** | **Improve PDF report layout and drawing scaling** | **Ready for Review** | `04d61c2`, `f834795` | Dedicated Page 2 vector drawing with full 8-role legend, wrapped multi-line notices, structured score deductions, and optional technical appendix. Tested in `tests/test_pdf_export.py`. |
| **#10** | **Group multiple geometric discrepancies affecting the same entity into a single deduction** | **Ready for Review** | `feature/reference-object-tags-v1` | Causal discrepancy clustering deduplicates co-located errors and limits deductions per entity and per rubric rule cap. Tested in `tests/test_causal_analysis.py` and `tests/test_scoring.py`. |
| **#11** | **Bug: Ellipse (Isocircle) size error detection** | **Deferred** | — | Requires complete size-comparison implementation following Issue #5 ellipse rendering baseline integration. |

---

## Verification Evidence

### Automated Test Suite
- `pytest -q -p no:cacheprovider`: **457 passed, 7 deprecation warnings in 23.47 s**.
- Regressions added/verified:
  - Case-insensitive `DL-Info` layer matching (`tests/test_reference_objects.py`).
  - Missing-geometry overlay translation alignment (`tests/test_reviewed_dxf.py`).
  - Error-category student underlay visibility (`tests/test_interactive_legend.py`).
  - Explicit assignment-type requirement on rubric approval (`tests/test_api.py`).
  - Default translation placement and selectable strict placement (`tests/test_normalization_transparency.py`).

### Live Headless Browser QA (Playwright / Microsoft Edge)
- `scripts/qa_reference_object_tags.cjs`: **6/6 check groups passed**:
  1. Initial page render defaults (header credit, default translation placement, assignment type placeholder).
  2. Explicit assignment type selection required to approve rubric (disabled button, enabled upon selection).
  3. Reference object tagging inspection and marker proposals.
  4. Student upload & review execution (score 86, 4 issues).
  5. Student underlay visibility across all 6 error category filters with `opacity: 0.40; pointer-events: none`.
  6. PDF report export and binary signature verification.
- `scripts/qa_interactive_legend.cjs`: **12/12 check groups passed**.
- `scripts/qa_review_usability.cjs`: **11/11 check groups passed**.

### Static Analysis & CAD Policy
- `node --check app/static/app.js`: PASS.
- `python -B -m compileall -q app tests`: PASS.
- `python -B scripts/check_cad_policy.py --history`: **PASS; no tracked DXF/DWG files; 56 historical commits inspected**.

---

## Run Instructions (PowerShell)

```powershell
Set-Location 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags'

# Run test suite
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m pytest -q

# Run CAD policy verification
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B scripts/check_cad_policy.py --history

# Verify JavaScript syntax
node --check app/static/app.js

# Launch local acceptance server (loopback only)
& 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe' -B -m uvicorn app.main:app --host 127.0.0.1 --port 8017

# Run live browser test suites (requires active local server)
$env:DRAFTLENS_QA_PYTHON = 'D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe'
$env:DRAFTLENS_PLAYWRIGHT_MODULE = 'C:\Users\mouki\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$env:DRAFTLENS_QA_URL = 'http://127.0.0.1:8017'

node scripts/qa_reference_object_tags.cjs
node scripts/qa_interactive_legend.cjs
node scripts/qa_review_usability.cjs
node scripts/qa_connectivity_presentation.cjs
```