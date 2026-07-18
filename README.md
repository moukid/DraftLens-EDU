# DraftLens EDU

DraftLens EDU is an explainable web grader for AutoCAD DXF assignments, built for the OpenAI Build Week Education track. It measures drawings deterministically, displays the evidence, applies a rubric, and can turn structured findings into pedagogical language. The model is never asked to measure geometry.

## Quick start

Requires Python 3.12+.

```powershell
py -3.12 -m venv .venv
+.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts\generate_samples.py
uvicorn app.main:app --reload
+```

Open `http://127.0.0.1:8000`. Run tests with `pytest -q`.

## Architecture

`app/dxf.py` parses LINE, LWPOLYLINE, ARC, TEXT/MTEXT, and DIMENSION entities using ezdxf. It translates each drawing's bounding-box minimum to `(0, 0)`; scale and orientation are unchanged. `app/compare.py` uses Shapely point distances plus explicit length/angle calculations and configurable tolerances. Layer names containing `WALL`, `DOOR`, `WINDOW`, and `DIMENSION` provide semantic classification. The FastAPI API validates uploads, returns issue JSON and drawing geometry, and renders a self-contained downloadable report. Vanilla JS converts normalized geometry to SVG and overlays issue locations.

The issue contract includes code, category, severity, message, deduction, reference/student entity IDs, expected and actual values, and location. Rubric deductions are capped per category and the score cannot fall below zero.

## Samples and demo

`samples/reference.dxf` is the instructor drawing. Three submissions demonstrate a perfect match, a missing wall, and door/window errors. Upload the reference with each student file, show the SVG evidence and exact deductions, adjust tolerances, then download the standalone HTML report. `sample_rubric.json` is editable and can be uploaded in the UI.

## GPT-5.6 and privacy

The MVP works without an API key and provides deterministic local feedback. When `OPENAI_API_KEY` is set, `app/feedback.py` calls the Responses API and falls back safely if the provider is unavailable. `.env.example` defines `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-5.6` for deployment integration. A production adapter must send only the structured issue array, score, and rubric—not DXF bytes, entity coordinates, names, or other drawing content—and must instruct GPT-5.6 to explain remediation without measuring or changing deductions. Do not enable external feedback without institutional approval, disclosure, retention review, and a human appeal path.

DXFs are processed in memory and are not persisted. There is no database, authentication, analytics, or account system. Deploy behind an institution's access controls if student work is sensitive.

## Limitations

This MVP depends on conventional semantic layer names; it does not infer walls from arbitrary layers. Bounding-box translation handles global displacement but intentionally does not rotate, scale, or optimize alignment. Matching is nearest-midpoint based and best for clean 2D educational plans. Blocks, splines, hatches, 3D entities, units reconciliation, mirrored-door semantics, dimension style compliance, overlapping candidates, and binary DWG are out of scope. Instructors must review results; automated scores are evidence, not final authority.

## Error handling and security

Only `.dxf` uploads are accepted, files default to a 10 MB limit, malformed/empty/unsupported drawings return actionable 4xx errors, and invalid rubrics return 422. Configure `MAX_UPLOAD_MB` in the environment. The standalone report escapes template content and stores the raw result only as inert JSON.

## Codex usage

Codex was used to scaffold the implementation, create synthetic DXFs, design deterministic comparison tests, build the accessible interface, and run the verification loop. Human judgment defined the grading contract and scope; generated code remains reviewable and the geometry engine is covered by unit and integration tests.

## Judging walkthrough

1. Start the server and open the upload page.
2. Grade `student_good.dxf` to establish the 100-point baseline.
3. Grade `student_missing_wall.dxf`; click between reference and student views and inspect the issue marker.
4. Grade `student_door_window_errors.dxf`; connect each deduction to expected/actual structured values.
5. Change an angle tolerance and re-grade to demonstrate instructor control.
6. Download the report, disconnect from the server, and open the HTML to prove it is standalone.




## Rubric approval and fallback grading

Rubric suggestions are provisional. The client must approve a rubric with `POST /api/rubric/approve`, including the `reference_id` returned by `POST /api/rubric/suggest`. Approved rubrics are associated with the SHA-256 fingerprint of the exact reference DXF. Grading selects an explicitly supplied approved `rubric_id` or the latest approved rubric associated with that fingerprint.

If no approved rubric exists, `POST /api/grade` returns HTTP 409. The documented 65/25/10 rubric is used only when the multipart field `allow_fallback=true` is explicitly supplied. Legacy inline rubric uploads are rejected because they bypass instructor approval. Position, length, angle, radius, dimension, and vertex tolerances come from the selected rubric; legacy tolerance form fields affect only explicit fallback mode.

Rubrics are stored in process memory for Competition V1. Restarting the FastAPI application clears approved rubrics and reference associations, so the instructor must approve them again. Strict and translation normalization are supported by the foundation grader. Translation-and-rotation and instructor-defined transforms are rejected clearly until their deterministic transformation records are implemented.
