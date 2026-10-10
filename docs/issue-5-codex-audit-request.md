# DraftLens EDU — Codex Audit Request: Issue #5 Re-Audit

## Task Description
Resolve the two confirmed Codex acceptance blockers for Issue #5 (Partial Ellipse Rendering & Extrusion Normal Handling).
- **F-01**: Correct bounding box calculation for full ellipses in `app/reviewed_dxf.py`.
- **F-02**: Apply OCS-to-WCS projection logic during ellipse rendering (bounds, SVG, PDF) to handle arbitrary extrusion vectors and major_axis Z-components.
- **F-03**: Fix edge-on SVG/PDF rendering logic to render as a `<line>` primitive when semi-axes map to zero after projection, preventing zero visible pixels.
- **F-04**: Fix SVG rendering bug where small valid ellipses disappeared due to degeneracy checks occurring before viewport scaling.

## Commit Identifiers
- **Branch**: `fix/issue-5-partial-ellipse-rendering`
- **Baseline Commit**: `31c94a4f6b5d3feae8448654459e384612da2b83`
- **Tested HEAD SHA**: `0e95098` (with uncommitted changes)
- **Uncommitted Changes**:
  - `app/svg_renderer.py` (fixed scale cutoff)
  - `tests/test_ellipse_rendering.py` (added scale regression test)
- **Changes**: 
  - `app/dxf.py`: Removed truncation of Z-axis for ellipse `major_axis` and included `extrusion` properties.
  - `app/compare.py`: Stripped `extrusion` property and clamped 3D axes to 2D for matching signatures, maintaining correct pair logic.
  - `app/reviewed_dxf.py`: Added `project_ellipse_2d` using `ezdxf.math.ConstructionEllipse` to project arbitrary OCS ellipses to the XY plane for bounds and radii calculation. Computed precise bounding box tightly containing rotated projected ellipses.
  - `app/svg_renderer.py`, `app/pdf_report.py`: Used `project_ellipse_2d` to generate 2D SVGs/PDFs for 3D ellipses. Addressed degenerate edge-on rendering (rx < 1e-5 or ry < 1e-5) by emitting explicit `<line>` primitives to maintain visibility. Ensured scaling happens before degeneracy checks in SVG.
  - `tests/test_ellipse_rendering.py`: Updated synthetic tests and backwards-compatibility logic for the exact new bound calculations. Added scale regression tests.

## Gates Executed
1. **CAD Repository Policy**: PASS
   `python scripts/check_cad_policy.py` -> exit 0
2. **Targeted Pytest Verification**: PASS
   `& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -B -m pytest tests/test_ellipse_rendering.py -q -p no:cacheprovider` -> exit 0 (22 tests)
3. **Full Regression Suite**: PASS (430 tests)
   `& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning" -B -m pytest -q -p no:cacheprovider` -> exit 0

## Codex Verification Command
Run the tests on the final commit and verify that the ellipse bounds and render dimensions are mathematically correct and conform to ezdxf standards, maintaining signature match semantics:
```powershell
& "d:\MOUKID_CODEX\03_TEACHING_APPS\DraftLens EDU\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"
```
