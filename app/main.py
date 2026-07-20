from __future__ import annotations
import html,os,uuid
from dataclasses import dataclass
from pathlib import Path
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment,FileSystemLoader,select_autoescape
from pydantic import BaseModel, Field
from .analysis import analyze_assignment
from .dxf import DXFParseError,parse_dxf_bytes
from .feedback import generate_feedback
from .pdf_report import content_disposition, generate_pdf
from .review_service import GradingPipelineOutput, PipelineContractError, build_review_artifacts, normalization_decision, reference_fingerprint, run_grading_pipeline
from .review_snapshot import (
    ReviewSnapshotStore, SnapshotCapacityError, SnapshotExpired, SnapshotNotFound,
    StudentMetadataError, normalize_student_metadata,
)
from .rubric import Rubric, default_rubric
from .validator import validate_reference
ROOT=Path(__file__).parent; templates=Environment(loader=FileSystemLoader(ROOT/"templates"),autoescape=select_autoescape())
app=FastAPI(title="DraftLens EDU",version="0.2.0"); app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
RUBRICS: dict[str, Rubric] = {}
REFERENCE_RUBRICS: dict[str, str] = {}
RUBRIC_REFERENCES: dict[str, str] = {}
REVIEW_SNAPSHOTS = ReviewSnapshotStore()

@dataclass(frozen=True, slots=True)
class UploadedPipelineResult:
    output: GradingPipelineOutput
    reference_filename: str
    reference_bytes: bytes
    student_filename: str
    student_bytes: bytes



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
        output = run_grading_pipeline(
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
        return UploadedPipelineResult(
            output=output,
            reference_filename=reference.filename or "reference.dxf",
            reference_bytes=reference_bytes,
            student_filename=student.filename or "student.dxf",
            student_bytes=student_bytes,
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
    uploaded = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric,
    )
    output = uploaded.output
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
        "suggested_assignment_type": output.analysis["suggested_assignment_type"],
        "assignment_type": output.rubric.assignment_type,
        "detected_features": output.analysis["detected_features"],
        "normalization_mode": output.rubric.normalization_mode,
        "normalization_decision": normalization_decision(output),
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
    student_name: str | None = Form(None),
    student_id: str | None = Form(None),
    course_section: str | None = Form(None),
):
    uploaded = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric,
    )
    try:
        metadata = normalize_student_metadata(student_name, student_id, course_section)
    except StudentMetadataError as exc:
        raise HTTPException(422, str(exc)) from exc
    artifacts = build_review_artifacts(uploaded.output)
    try:
        snapshot = REVIEW_SNAPSHOTS.create(
            reference_filename=uploaded.reference_filename,
            reference_bytes=uploaded.reference_bytes,
            student_filename=uploaded.student_filename,
            student_bytes=uploaded.student_bytes,
            student_metadata=metadata,
            approved_rubric_id=uploaded.output.rubric_id,
            approved_rubric=uploaded.output.rubric.model_dump(),
            assignment_type=uploaded.output.rubric.assignment_type,
            suggested_assignment_type=uploaded.output.analysis["suggested_assignment_type"],
            detected_features=uploaded.output.analysis["detected_features"],
            reviewed_drawing=artifacts.reviewed_drawing,
            review_response=artifacts.response,
        )
    except SnapshotCapacityError as exc:
        raise HTTPException(413, str(exc)) from exc
    return snapshot.review_response

@app.get("/api/reviews/{review_id}/report.pdf")
def download_pdf_report(review_id: str):
    try:
        snapshot = REVIEW_SNAPSHOTS.get(review_id)
    except SnapshotExpired as exc:
        raise HTTPException(410, "The review report has expired. Generate a new review.") from exc
    except SnapshotNotFound as exc:
        raise HTTPException(404, "The review report was not found.") from exc
    pdf = generate_pdf(snapshot)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(snapshot)},
    )
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
    analysis = analyze_assignment(drawing)
    suggested_rubric = default_rubric(reference.filename or "Assignment rubric").model_copy(
        update={"normalization_mode": "strict"}
    )
    return {
        "reference_id": reference_fingerprint(reference_bytes),
        "analysis": analysis,
        "suggested_assignment_type": analysis["suggested_assignment_type"],
        "assignment_type": suggested_rubric.assignment_type,
        "detected_features": analysis["detected_features"],
        "completion_scoring_mode": suggested_rubric.completion_scoring_mode,
        "normalization_mode": suggested_rubric.normalization_mode,
        "rubric": suggested_rubric.model_dump(),
        "provisional": True,
        "requires_instructor_approval": True,
    }

@app.post("/api/rubric/approve")
def rubric_approve(request: RubricApprovalRequest):
    if request.rubric.assignment_type is None:
        raise HTTPException(422, "Instructor confirmation of the assignment type is required before rubric approval.")
    approved = request.rubric.model_copy(update={"approved": True})
    rubric_id = str(uuid.uuid4())
    RUBRICS[rubric_id] = approved
    RUBRIC_REFERENCES[rubric_id] = request.reference_id
    REFERENCE_RUBRICS[request.reference_id] = rubric_id
    return {
        "rubric_id": rubric_id,
        "reference_id": request.reference_id,
        "assignment_type": approved.assignment_type,
        "completion_scoring_mode": approved.completion_scoring_mode,
        "normalization_mode": approved.normalization_mode,
        "rubric": approved.model_dump(),
    }
@app.post("/api/report",response_class=HTMLResponse)
async def report(payload:dict):
    return render("report.html",data_json=json.dumps(payload).replace("</","<\\/"),score=payload.get("score",0),issues=payload.get("issues",[]),feedback=payload.get("feedback",[]))
def local_feedback(result):
    if not result["issues"]: return ["Excellent geometric match. Verify annotation style and submission requirements before finalizing."]
    return [f"{i['category'].replace('_', ' ').title()}: {i.get('technical_feedback') or i['message']}" for i in result["issues"]]


