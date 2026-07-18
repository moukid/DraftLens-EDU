from __future__ import annotations
import hashlib,html,os,uuid
from pathlib import Path
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment,FileSystemLoader,select_autoescape
from pydantic import BaseModel, Field
from .analysis import analyze_assignment
from .compare import compare_drawings
from .dxf import DXFParseError,parse_dxf_bytes
from .feedback import generate_feedback
from .rubric import Rubric, ToleranceProfile, default_rubric
from .validator import validate_reference
ROOT=Path(__file__).parent; templates=Environment(loader=FileSystemLoader(ROOT/"templates"),autoescape=select_autoescape())
app=FastAPI(title="DraftLens EDU",version="0.2.0"); app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
RUBRICS: dict[str, Rubric] = {}
REFERENCE_RUBRICS: dict[str, str] = {}
RUBRIC_REFERENCES: dict[str, str] = {}

class RubricApprovalRequest(BaseModel):
    reference_id: str = Field(min_length=64, max_length=64)
    rubric: Rubric

def reference_fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
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
    reference_bytes = await read_upload(reference)
    student_bytes = await read_upload(student)
    if rubric and rubric.filename:
        raise HTTPException(409, "Inline rubric uploads are no longer accepted. Approve and associate the rubric before grading.")
    reference_id = reference_fingerprint(reference_bytes)
    selected_id = rubric_id or REFERENCE_RUBRICS.get(reference_id)
    if selected_id:
        selected_rubric = RUBRICS.get(selected_id)
        if selected_rubric is None or not selected_rubric.approved:
            raise HTTPException(409, "The selected rubric does not exist or is not approved.")
        if RUBRIC_REFERENCES.get(selected_id) != reference_id:
            raise HTTPException(409, "The selected rubric is not associated with this reference drawing.")
        rubric_source = "explicit_approved" if rubric_id else "associated_approved"
    elif allow_fallback:
        selected_rubric = default_rubric("Explicit 65/25/10 fallback").model_copy(update={"approved": True})
        selected_rubric.tolerances = ToleranceProfile(
            position=position_tolerance, length=length_tolerance, angle=angle_tolerance,
            radius=radius_tolerance, dimension=dimension_tolerance, vertex=position_tolerance,
        )
        rubric_source = "explicit_fallback"
    else:
        raise HTTPException(409, "No approved rubric is associated with this reference. Approve a rubric or explicitly enable fallback mode.")
    if selected_rubric.normalization_mode not in {"strict", "translation"}:
        raise HTTPException(422, f"Normalization mode '{selected_rubric.normalization_mode}' is not implemented in V1 foundation grading.")
    normalize = selected_rubric.normalization_mode == "translation"
    ref = parse_dxf_bytes(reference_bytes, source="reference", normalize=normalize)
    stu = parse_dxf_bytes(student_bytes, source="student", normalize=normalize)
    result = compare_drawings(ref, stu, rubric=selected_rubric)
    feedback = None
    try:
        feedback = generate_feedback(result)
    except Exception:
        feedback = None
    result.update({
        "reference": ref.to_dict(), "student": stu.to_dict(),
        "feedback": feedback or local_feedback(result), "ai_used": feedback is not None,
        "reference_id": reference_id,
        "rubric_selection": {"rubric_id": selected_id, "source": rubric_source},
        "rubric": selected_rubric.model_dump(),
    })
    return result
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
    return {
        "reference_id": reference_fingerprint(reference_bytes),
        "analysis": analyze_assignment(drawing),
        "rubric": default_rubric(reference.filename or "Assignment rubric").model_dump(),
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


