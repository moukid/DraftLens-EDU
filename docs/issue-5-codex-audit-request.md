# DraftLens EDU — Codex Audit Request: Issue #5 Re-Audit

## Task Description
Resolve the two confirmed Codex acceptance blockers for Issue #5 (Partial Ellipse Rendering & Extrusion Normal Handling).
- **F-01**: Correct bounding box calculation for full ellipses in `app/reviewed_dxf.py`.
- **F-02**: Apply OCS-to-WCS projection logic during ellipse rendering (bounds, SVG, PDF) to handle arbitrary extrusion vectors and major_axis Z-components.

## Commit Identifiers
- **Branch**: `fix/issue-5-partial-ellipse-rendering`
- **Baseline Commit**: `31c94a4f6b5d3feae8448654459e384612da2b83`
- **Tested HEAD SHA**: Pending commit
- **Changes**: 
  - `app/dxf.py`: Removed truncation of Z-axis for ellipse `major_axis` and included `extrusion` properties.
  - `app/compare.py`: Stripped `extrusion` property and clamped 3D axes to 2D for matching signatures.
  - `app/reviewed_dxf.py`: Added `project_ellipse_2d` using `ezdxf.math.ConstructionEllipse` to project arbitrary OCS ellipses to the XY plane for bounds and radii calculation.
  - `app/svg_renderer.py`, `app/pdf_report.py`: Used `project_ellipse_2d` to generate 2D SVGs/PDFs for 3D ellipses. Fixed rotation signs.
  - `tests/test_dxf.py`: Added synthetic test confirming 3D properties and projection.

## Gates Executed
1. **CAD Repository Policy**: PASS
   `& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" scripts/check_cad_policy.py` -> exit 0
2. **Targeted Pytest Verification**: PASS
   `& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -B -m pytest tests/test_dxf.py tests/test_compare.py -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"` -> exit 0
3. **UI / Frontend / PDF Verification**: PASS
   `& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -B -m pytest tests/test_ui.py tests/test_pdf_export.py -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"` -> exit 0

## Codex Verification Command
Run the tests on the final commit and verify that the ellipse bounds and render dimensions are mathematically correct and conform to ezdxf standards, maintaining signature match semantics:
```powershell
& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"
```
