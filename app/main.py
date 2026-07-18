from __future__ import annotations
import html,json,os,uuid
from pathlib import Path
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment,FileSystemLoader,select_autoescape
from .analysis import analyze_assignment
from .compare import Tolerances,compare_drawings
from .dxf import DXFParseError,parse_dxf_bytes
from .feedback import generate_feedback
from .rubric import Rubric, default_rubric
from .validator import validate_reference
ROOT=Path(__file__).parent; templates=Environment(loader=FileSystemLoader(ROOT/"templates"),autoescape=select_autoescape())
app=FastAPI(title="DraftLens EDU",version="0.2.0"); app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
RUBRICS: dict[str, Rubric] = {}
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
async def grade(reference:UploadFile=File(...),student:UploadFile=File(...),position_tolerance:float=Form(2),length_tolerance:float=Form(1),angle_tolerance:float=Form(3),dimension_tolerance:float=Form(1),rubric:UploadFile|None=File(None)):
    try:
        ref=parse_dxf_bytes(await read_upload(reference), source="reference"); stu=parse_dxf_bytes(await read_upload(student), source="student")
        config=json.loads((await rubric.read()).decode("utf-8")) if rubric and rubric.filename else None
        result=compare_drawings(ref,stu,Tolerances(position_tolerance,length_tolerance,angle_tolerance,dimension_tolerance),config)
    except DXFParseError as exc: raise HTTPException(422,str(exc)) from exc
    except (json.JSONDecodeError,KeyError,TypeError) as exc: raise HTTPException(422,f"Invalid rubric: {exc}") from exc
    feedback = None
    try:
        feedback = generate_feedback(result)
    except Exception:
        feedback = None
    result.update({"reference":ref.to_dict(),"student":stu.to_dict(),"feedback":feedback or local_feedback(result),"ai_used":feedback is not None})
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
    drawing = parse_dxf_bytes(await read_upload(reference), source="reference")
    return {"analysis": analyze_assignment(drawing), "rubric": default_rubric(reference.filename or "Assignment rubric").model_dump(), "provisional": True, "requires_instructor_approval": True}

@app.post("/api/rubric/approve")
def rubric_approve(rubric: Rubric):
    approved = rubric.model_copy(update={"approved": True})
    rubric_id = str(uuid.uuid4())
    RUBRICS[rubric_id] = approved
    return {"rubric_id": rubric_id, "rubric": approved.model_dump()}
@app.post("/api/report",response_class=HTMLResponse)
async def report(payload:dict):
    return render("report.html",data_json=json.dumps(payload).replace("</","<\\/"),score=payload.get("score",0),issues=payload.get("issues",[]),feedback=payload.get("feedback",[]))
def local_feedback(result):
    if not result["issues"]: return ["Excellent geometric match. Verify annotation style and submission requirements before finalizing."]
    return [f"{i['category'].replace('_', ' ').title()}: {i.get('technical_feedback') or i['message']}" for i in result["issues"]]


