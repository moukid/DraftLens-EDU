# DraftLens EDU — Codex Audit Request

## Role

Act as the independent verification gate. Do not become the primary implementation agent.

## Scope

PDF reporting, explanation, and visual acceptance repair following manual inspection of the nine square test PDFs (`pdf-visual-acceptance-20261018T200306Z.zip`).

## Baseline & Target

- **Branch**: `release/v0.3.0-alpha.1`
- **Baseline Commit**: `2dc3e08a57f0a4447b8506f7ee0099a34534e256`
- **Working Changes**: 13 tracked modified files (`app/compare.py`, `app/compatibility.py`, `app/correction_guidance.py`, `app/grading_adjustments.py`, `app/models.py`, `app/pdf_report.py`, `app/reviewed_dxf.py`, `app/rubric.py`, `app/scoring.py`, `app/static/app.js`, `app/svg_renderer.py`, `app/templates/index.html`, `tests/test_pdf_export.py`) plus untracked implementation files in `docs/` and `tests/test_square_grading_repair.py`. Zero staged files; uncommitted.

## Acceptance Criteria

1. **Compact unique badge identifiers**: Issues are assigned compact, deterministic badge identifiers (e.g., `M1`, `M2`, `E1`, `I1`, `C1`, `W1`, `X1`) per visual role in `ReviewedIssue.badge_label`. `assign_badge_labels` tracks `used_labels` and `seen_prelabelled` so mixing pre-labelled and unlabelled issues never produces duplicate badges.
2. **Full package provenance**: `manifest.json` records `source_identity` (`head`, `branch`, `working_tree_status`, `application_file_sha256`, `application_inventory_sha256`), UTC generation start/completion times, review IDs, approved rubric ID and canonical SHA-256 (`approved_rubric.json`), upload SHA-256s, PDF subjects, badge lists, and linkage checks.
3. **Collision-free badge layout**: Page 2 drawing badges use a collision-avoidance layout algorithm testing prioritized candidate levels, horizontal offsets, viewport boundary containment, and leader lines with anchor dots when displaced, preventing badge overlap (particularly verified on Case 04 page 2 and Cases 07–09 page 2).
4. **Explicit issue-to-drawing mapping**: Page 2 renders an Issue-to-Drawing Mapping Table below the legend with `Badge` as the first column (`M1`, `M2`), explicitly mapping compact badges to full issue IDs, drawing roles, descriptions, and applied deductions. Badges are styled using native ReportLab font styling (`styles["badge"]` with `fontName=FONT_BOLD`) without literal HTML markup (`<b>`/`</b>`).
5. **Coordinated finding titles and browser overlay**: Finding detail headings on Page 3+ display `[Badge M1]` alongside the full issue ID. The browser UI card identity displays `${issue.issue_id} [${issue.badge_label}]`.
6. **Missing-object highlighting**: When a whole object is missing (e.g. Case 03 loses square `OBJ-010`), all four absent edges are highlighted in orange dashed style on the drawing overlay (`ReviewedDrawingFlowable` and SVG), while retaining a single object deduction.
7. **Deduction attribution reconciliation**: In finding detail tables and mapping summaries, the combined loss and category allocation are explicitly shown (e.g., `Score category: Geometry (6.5) + Completion (2.5)`, `Applied deduction: 9 (Geometry: -6.5, Completion: -2.5)`), resolving contradiction with the summary score breakdown.
8. **Correction guidance differentiation**: Completely missing objects receive whole-object guidance (`RECTANG`/`PLINE`, explaining entire object absence), distinguishing them from single missing edges (`LINE`/`PLINE`, partial object completion).
9. **Layout polish**: Drawing height adapts dynamically to drawing aspect ratio (`height = clamp(150, (width - 24) * aspect + 36, 340)`), eliminating excessive blank white space. Headings are bound to their first finding via `KeepTogether` and `keepWithNext=True`, preventing orphan headings from separating across pages.
10. **Grades preserved**: All nine target square cases produce exact scores (100, 100, 91, 90, 89, 82, 55, 46, 44) through live `/api/review` and PDF export via TestClient.

## Evidence Produced

- **PDF Visual Acceptance Archive**:
  - `<<private-evidence>-root>` (SHA-256: `58ac414e9d2197aec2de7ce13969c02b14ed7b8cff8c010afacf9df62b030703`)
  - Contains all 9 freshly generated PDFs (39 pages total), `manifest.json` with full source/rubric/review provenance, `approved_rubric.json`, `REVIEW_SUMMARY.md`, and `generate_package.py`.
  - Generated via `fastapi.testclient.TestClient(app)` under strict-placement acceptance policy (weights 65/25/10, p=1, geometry_only).
- **Targeted Pytest**: `PASS`
  - Command: `& .venv\Scripts\python.exe -B -m pytest tests/test_square_grading_repair.py tests/test_pdf_export.py -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"`
  - Result: 43 passed in 5.28s.
- **Full Pytest Suite**: `PASS`
  - Command: `& .venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"`
  - Result: 471 passed in 40.45s.
- **UI DOM Tests**: `PASS`
  - Command: `& .venv\Scripts\python.exe -B -m pytest tests/test_ui.py -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"`
  - Result: 31 passed in 1.33s.
- **Syntax & CAD Policy**: `PASS`
  - `git diff --check`: exit 0.
  - `python scripts/check_cad_policy.py`: exit 0 (0 tracked DXF/DWG).

## Reproduction Commands

- **Verify CAD Policy & Whitespace**:
  ```powershell
  & "<repo-root>\.venv\Scripts\python.exe" -B scripts/check_cad_policy.py
  git diff --check
  ```
- **Run Targeted Pytest**:
  ```powershell
  & "<repo-root>\.venv\Scripts\python.exe" -B -m pytest tests/test_square_grading_repair.py tests/test_pdf_export.py -q -p no:cacheprovider -W "ignore::pyparsing.exceptions.PyparsingDeprecationWarning"
  ```
- **Inspect Generated Case 03 PDF**:
  ```powershell
  & "<repo-root>\.venv\Scripts\python.exe" -B -c "
  from pypdf import PdfReader
  reader = PdfReader(r'<<private-evidence>-root>')
  for i, p in enumerate(reader.pages, 1):
      print(f'=== PAGE {i} ===\n', p.extract_text()[:400])
  "
  ```
