# DraftLens EDU — Reference Object Tagging and Unit/Scale Review Handoff

## Status: READY FOR CODEX REVIEW

---

## 1. Executive Summary & Verification Gates

- **Worktree**: `D:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.worktrees\reference-object-tags`
- **Branch**: `feature/reference-object-tags-v1`
- **Base Commit**: `8de5c78460ae321e5ad52ee13fb851768678debc`
- **Root Ellipse Branch**: `fix/issue-5-partial-ellipse-rendering` (untouched, preserved in primary repo checkout).
- **CAD File Policy**: PASS (0 tracked `.dxf`/`.dwg` files in Git index or working tree; all test fixtures are procedural/in-memory).
- **Regression Test Suite**: PASS (447 passed, 7 warnings in full regression suite).

---

## 2. Implemented Capabilities

### A. Reference Information-Layer Import & Architectural Object Tagging
1. **Layer Recognition**:
   - Case-normalized exact layer matching for `DL-Info`, `DL-INFO-TAGS`, `DL-INFO-LEGEND`, and `DL-INFO-REGIONS`.
   - Extracted text entities and surrounding marker outline geometry.
   - Non-info drawing layers (`WALLS`, `DOORS`, `0`, etc.) remain assessable drawing geometry.
2. **Standard Architectural Codes**:
   - `D1` -> Door
   - `W1` -> Window
   - `C1` -> Column
   - `DD1` -> Double Door
   - `SD1` -> Sliding Door
   - `S1` -> Stairs
   - Unmapped codes are classified as `Unmapped ({code})` and given status `unresolved` with no invented semantics.
3. **Legend Separation & Table Exclusion**:
   - Markers on `DL-INFO-LEGEND` or located within an identified legend region bounding box are classified as legend samples (`is_legend: True`) with explicit exclusion reasons.
   - `ACAD_TABLE` entities (e.g. on layer 0) and their insert locations are detected in unsupported entities and separated from plan markers.
4. **Deterministic Sequencing & Candidate Grouping**:
   - Plan markers are deterministically sorted (descending Y, ascending X, then code).
   - Assigned deterministic sequential IDs: `D1-001`, `D1-002`, `W1-001`, etc.
   - Candidate reference base geometry within a conservative search radius is proposed as member entities.
5. **Overlapping Membership Warnings**:
   - When a base geometry entity is within candidate radius of multiple markers, `has_overlapping_memberships` is flagged, `shared_between_objects` lists conflicting occurrence IDs, and a prominent warning banner is displayed in the UI.
6. **Confirmation States**:
   - Object states: `detected` -> `proposed` -> `confirmed` / `unresolved` / `excluded`.
   - Explicit confirmation endpoint `POST /api/reference/objects/confirm` records confirmed objects per reference fingerprint.
7. **Read-Only Student Correspondence Preview**:
   - Evaluates confirmed reference object member entities against intrinsic geometric matches.
   - Classifies student correspondence into `present`, `partial`, `missing`, or `uncertain`.
   - Strictly read-only: does not alter geometric scoring, deductions, or rubric calculations.

### B. Unit Settings & Geometry Scale Warnings
1. **Four-Part Evidence Separation**:
   - Reference declared units (`$INSUNITS`).
   - Student declared units (`$INSUNITS`).
   - Instructor-confirmed intended unit ("One drawing unit represents...").
   - Measured geometric scale factor from corresponding geometry.
2. **Diagnostic State Classification**:
   - `declared_units_differ`
   - `units_unspecified`
   - `geometry_scale_mismatch`
   - `units_scale_physically_consistent`
   - `insufficient_evidence`
   - `matching_and_consistent`
3. **Clear Directional Factor Explanations**:
   - Unambiguous explanations of scale factor direction (e.g. "Student lengths are approximately 10 times reference lengths", "Student lengths are approximately 0.1 times reference lengths").
   - Identifies physically consistent unit conventions (e.g. reference declared in mm, student in cm, measured scale factor 0.1).
4. **Prominent Review Notice & Acknowledgment**:
   - UI displays a prominent warning card above drawing viewport when notices exist.
   - Requires instructor acknowledgment before finality when ambiguous unit settings exist.
5. **Authoritative PDF Report Integration**:
   - Page 1 prominent Unit Setting & Scale Diagnostic callout cell.
   - Architectural Object Correspondence table before the technical appendix.

### C. Strict Boundaries & Grading Invariance
- Reference information layers and legend entities are filtered out before ordinary geometry comparison.
- **Scoring Invariance Verified**: Identical base geometry with vs. without `DL-Info` tags yields identical geometric scores, deductions, and issue counts (0.0 score difference).
- Unresolved or missing objects produce no automatic penalties.

---

## 3. Key Files Modified & Created

- `app/reference_objects.py`: Parser, marker extraction, legend separation, deterministic occurrence IDs, candidate grouping, overlapping detection, correspondence preview.
- `app/unit_scale_review.py`: Unit header parsing, 5 diagnostic states, directional scale factor explanations, physical consistency evaluator.
- `app/models.py`: Added `info_entities` to `Drawing`.
- `app/dxf.py`: Added `exclude_info_layers` parameter to `parse_dxf_bytes` and `parse_dxf_path`, preserves info layers in `info_entities`.
- `app/rubric.py`: Added `intended_unit` and `intended_unit_confirmed` to `Rubric`.
- `app/review_service.py`: Integrated `unit_scale_review` and `student_object_correspondence` into pipeline output and artifacts.
- `app/main.py`: Added `/api/reference/objects/inspect` and `/api/reference/objects/confirm` endpoints; integrated intended units into rubric suggestions and reviews.
- `app/pdf_report.py`: Page 1 unit/scale warning cell and Architectural Object Correspondence table.
- `app/templates/index.html`: Intended unit dropdown in rubric setup, reference objects panel in Step 1, unit/scale warning card above drawing panel, and object correspondence table.
- `app/static/app.js`: State management, inspection, object confirmation, legend re-filtering, unit/scale warnings, and object correspondence rendering.
- `app/static/style.css`: Styling for reference object cards, warning banners, unit/scale card, and correspondence badges.
- `tests/test_unit_scale_review.py`: Comprehensive tests for diagnostic states, directional factors, and physical consistency.
- `tests/test_reference_objects.py`: Tests for info layers, legend separation, deterministic sequencing, overlapping memberships, correspondence, and grading invariance.

---

## 4. Verification & CAD Policy Check

```bash
# 1. Full regression test suite
python -m pytest -q -p no:cacheprovider
# Result: 447 passed, 7 warnings

# 2. Reference objects & unit scale tests
python -m pytest -q -p no:cacheprovider tests/test_reference_objects.py tests/test_unit_scale_review.py
# Result: 14 passed, 7 warnings

# 3. CAD File Policy check
python scripts/check_cad_policy.py --history
# Result: CAD policy PASS: no tracked DXF/DWG files
```
