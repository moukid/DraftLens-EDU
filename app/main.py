from __future__ import annotations
import html,os,uuid
from pathlib import Path
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment,FileSystemLoader,select_autoescape
from pydantic import BaseModel, Field
from .analysis import analyze_assignment
from .dxf import DXFParseError,parse_dxf_bytes
from .feedback import generate_feedback
from .review_service import PipelineContractError, build_review_response, reference_fingerprint, run_grading_pipeline
from .rubric import Rubric, default_rubric
from .validator import validate_reference
ROOT=Path(__file__).parent; templates=Environment(loader=FileSystemLoader(ROOT/"templates"),autoescape=select_autoescape())
app=FastAPI(title="DraftLens EDU",version="0.2.0"); app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
RUBRICS: dict[str, Rubric] = {}
REFERENCE_RUBRICS: dict[str, str] = {}
RUBRIC_REFERENCES: dict[str, str] = {}

class RubricApprovalRequest(BaseModel):
    reference_id: str = Field(min_length=64, max_length=64)
    rubric: Rubric

def render(name,**ctx): return templates.get_template(name).render(**ctx)
async def read_upload(f:UploadFile):
    if not f.filename or not f.filename.lower().endswith(".dxf"): raise HTTPException(400,"Only .dxf files are accepted.")
    data=await f.read(); limit=int(os.getenv("MAX_UPLOAD_MB","10"))*1024*1024
    if len(data)>limit: raise HTTPException(413,"DXF exceeds the upload size limit.")
    return data
@app.exception_handler(DXFParseError)
def dxf_parse_error_handler(_request, exc: DXFParseError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})
@app.get("/",response_class=HTMLResponse)
def index(): return render("index.html")
@app.get("/health")
def health(): return {"status":"ok"}
async def run_uploaded_pipeline(
    reference: UploadFile,
    student: UploadFile,
    rubric_id: str | None,
    allow_fallback: bool,
    position_tolerance: float,
    length_tolerance: float,
    angle_tolerance: float,
    dimension_tolerance: float,
    radius_tolerance: float,
    rubric: UploadFile | None,
):
    reference_bytes = await read_upload(reference)
    student_bytes = await read_upload(student)
    if rubric and rubric.filename:
        raise HTTPException(409, "Inline rubric uploads are no longer accepted. Approve and associate the rubric before grading.")
    try:
        return run_grading_pipeline(
            reference_bytes,
            student_bytes,
            rubric_id=rubric_id,
            allow_fallback=allow_fallback,
            position_tolerance=position_tolerance,
            length_tolerance=length_tolerance,
            angle_tolerance=angle_tolerance,
            dimension_tolerance=dimension_tolerance,
            radius_tolerance=radius_tolerance,
            rubrics=RUBRICS,
            reference_rubrics=REFERENCE_RUBRICS,
            rubric_references=RUBRIC_REFERENCES,
        )
    except PipelineContractError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@app.post("/api/grade")
async def grade(
    reference: UploadFile = File(...),
    student: UploadFile = File(...),
    rubric_id: str | None = Form(None),
    allow_fallback: bool = Form(False),
    position_tolerance: float = Form(2),
    length_tolerance: float = Form(1),
    angle_tolerance: float = Form(3),
    dimension_tolerance: float = Form(1),
    radius_tolerance: float = Form(1),
    rubric: UploadFile | None = File(None),
):
    output = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric,
    )
    result = output.comparison
    feedback = None
    try:
        feedback = generate_feedback(result)
    except Exception:
        feedback = None
    result.update({
        "reference": output.reference.to_dict(), "student": output.student.to_dict(),
        "feedback": feedback or local_feedback(result), "ai_used": feedback is not None,
        "reference_id": output.reference_id,
        "rubric_selection": output.rubric_selection,
        "rubric": output.rubric.model_dump(),
    })
    return result


@app.post("/api/review")
async def review(
    reference: UploadFile = File(...),
    student: UploadFile = File(...),
    rubric_id: str | None = Form(None),
    allow_fallback: bool = Form(False),
    position_tolerance: float = Form(2),
    length_tolerance: float = Form(1),
    angle_tolerance: float = Form(3),
    dimension_tolerance: float = Form(1),
    radius_tolerance: float = Form(1),
    rubric: UploadFile | None = File(None),
):
    output = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric,
    )
    return build_review_response(output)
@app.post("/api/reference/validate")
async def reference_validate(reference: UploadFile = File(...)):
    drawing = parse_dxf_bytes(await read_upload(reference), source="reference")
    return {"validation": validate_reference(drawing), "reference": drawing.to_dict()}

@app.post("/api/assignment/analyze")
async def assignment_analyze(reference: UploadFile = File(...)):
    drawing = parse_dxf_bytes(await read_upload(reference), source="reference")
    return analyze_assignment(drawing)

@app.post("/api/rubric/suggest")
async def rubric_suggest(reference: UploadFile = File(...)):
    reference_bytes = await read_upload(reference)
    drawing = parse_dxf_bytes(reference_bytes, source="reference")
    suggested_rubric = default_rubric(
        reference.filename or "Assignment rubric"
    ).model_copy(update={"completion_scoring_mode": "proportional"})
    return {
        "reference_id": reference_fingerprint(reference_bytes),
        "analysis": analyze_assignment(drawing),
        "rubric": suggested_rubric.model_dump(),
        "provisional": True,
        "requires_instructor_approval": True,
    }

@app.post("/api/rubric/approve")
def rubric_approve(request: RubricApprovalRequest):
    approved = request.rubric.model_copy(update={"approved": True})
    rubric_id = str(uuid.uuid4())
    RUBRICS[rubric_id] = approved
    RUBRIC_REFERENCES[rubric_id] = request.reference_id
    REFERENCE_RUBRICS[request.reference_id] = rubric_id
    return {"rubric_id": rubric_id, "reference_id": request.reference_id, "rubric": approved.model_dump()}
@app.post("/api/report",response_class=HTMLResponse)
async def report(payload:dict):
    return render("report.html",data_json=json.dumps(payload).replace("</","<\\/"),score=payload.get("score",0),issues=payload.get("issues",[]),feedback=payload.get("feedback",[]))
def local_feedback(result):
    if not result["issues"]: return ["Excellent geometric match. Verify annotation style and submission requirements before finalizing."]
    return [f"{i['category'].replace('_', ' ').title()}: {i.get('technical_feedback') or i['message']}" for i in result["issues"]]


