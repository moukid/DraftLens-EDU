from __future__ import annotations
import hashlib,html,json,math,os,uuid
from dataclasses import dataclass
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Any
from pydantic import BaseModel, Field
from .analysis import analyze_assignment
from .dxf import DXFParseError,parse_dxf_bytes
from .feedback import generate_feedback
from .pdf_report import content_disposition, generate_pdf
from .reference_objects import (
    DEFAULT_CODE_MAPPINGS,
    MARKER_CODE_RE,
    build_proposed_reference_objects,
    extract_reference_markers_and_legend,
)
from .review_service import GradingPipelineOutput, PipelineContractError, build_review_artifacts, compatibility_message, normalization_decision, review_withholding_message, reference_fingerprint, run_grading_pipeline
from .review_snapshot import (
    ReviewSnapshotStore, SnapshotCapacityError, SnapshotExpired, SnapshotNotFound,
    StudentMetadataError, normalize_student_metadata,
)
from .rubric import (
    BASELINE_RUBRIC_TEMPLATE, Rubric, default_rubric, rubric_contract,
    suggest_assignment_title,
)
from .validator import validate_reference
ROOT=Path(__file__).parent; templates=Environment(loader=FileSystemLoader(ROOT/"templates"),autoescape=select_autoescape())
app=FastAPI(title="DraftLens EDU",version="0.2.0"); app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
RUBRICS: dict[str, Rubric] = {}
REFERENCE_RUBRICS: dict[str, str] = {}
RUBRIC_REFERENCES: dict[str, str] = {}
REFERENCE_OBJECTS: dict[str, dict[str, Any]] = {}
REFERENCE_OBJECT_INSPECTIONS: dict[str, dict[str, Any]] = {}
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


class ObjectConfirmationRequest(BaseModel):
    reference_id: str = Field(min_length=64, max_length=64)
    inspection_token: str = Field(min_length=64, max_length=64)
    rubric_id: str | None = None
    objects: list[dict[str, Any]]
    overlap_acknowledged: bool = False


ObjectConfirmationRequest.model_rebuild()

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
    instructor_override: bool = False,
):
    reference_bytes = await read_upload(reference)
    student_bytes = await read_upload(student)
    ref_id = reference_fingerprint(reference_bytes)
    selected_assignment_id = rubric_id or REFERENCE_RUBRICS.get(ref_id)
    object_record = REFERENCE_OBJECTS.get(ref_id)
    confirmed_objects = (
        object_record["objects"]
        if object_record and object_record.get("rubric_id") == selected_assignment_id
        else None
    )
    custom_info_layers = (
        set(REFERENCE_OBJECT_INSPECTIONS.get(ref_id, object_record or {}).get("configuration", {}).get("custom_info_layers", []))
    )
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
            instructor_override=instructor_override,
            confirmed_reference_objects=confirmed_objects,
            custom_info_layers=custom_info_layers,
            enforce_unit_decision=True,
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
    grade_anyway: bool = Form(False),
):
    uploaded = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric, grade_anyway,
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
        "grading_status": (
            "withheld" if output.grading_withheld else "graded"
        ),
        "compatibility": output.compatibility.to_dict(),
        **output.compatibility.to_dict(),
        "grading_withheld": output.grading_withheld,
        "scale_diagnostic": output.scale_diagnostic.to_dict(),
        **output.scale_diagnostic.to_dict(),
        **rubric_contract(output.rubric),
    })
    if output.unit_scale_review:
        result["unit_scale_review"] = output.unit_scale_review.to_dict()
    if output.reference_objects_summary is not None:
        result["reference_objects_summary"] = output.reference_objects_summary
    if output.student_object_correspondence is not None:
        result["student_object_correspondence"] = output.student_object_correspondence
    if output.grading_withheld:
        message = review_withholding_message(output)
        result["compatibility_message"] = message
        result["available_actions"] = (
            ["choose_another_file", "grade_anyway"]
            if output.compatibility.compatibility_status != "empty_or_ungradable"
            else ["choose_another_file"]
        )
        result["feedback"] = [message]
        result["ai_used"] = False
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
    grade_anyway: bool = Form(False),
):
    uploaded = await run_uploaded_pipeline(
        reference, student, rubric_id, allow_fallback, position_tolerance,
        length_tolerance, angle_tolerance, dimension_tolerance, radius_tolerance, rubric, grade_anyway,
    )
    try:
        metadata = normalize_student_metadata(student_name, student_id, course_section)
    except StudentMetadataError as exc:
        raise HTTPException(422, str(exc)) from exc
    artifacts = build_review_artifacts(uploaded.output)
    if uploaded.output.grading_withheld:
        return artifacts.response
    try:
        snapshot = REVIEW_SNAPSHOTS.create(
            reference_filename=uploaded.reference_filename,
            reference_bytes=uploaded.reference_bytes,
            student_filename=uploaded.student_filename,
            student_bytes=uploaded.student_bytes,
            student_metadata=metadata,
            approved_rubric_id=uploaded.output.rubric_id,
            approved_rubric=uploaded.output.rubric.model_dump(),
            assignment_title=uploaded.output.rubric.assignment_title,
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
def download_pdf_report(
    review_id: str,
    include_appendix: bool = Query(False),
):
    try:
        snapshot = REVIEW_SNAPSHOTS.get(review_id)
    except SnapshotExpired as exc:
        raise HTTPException(410, "The review report has expired. Generate a new review.") from exc
    except SnapshotNotFound as exc:
        raise HTTPException(404, "The review report was not found.") from exc
    pdf = generate_pdf(snapshot, include_appendix=include_appendix)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(snapshot), "Cache-Control": "no-store"},
    )
@app.post("/api/reference/validate")
async def reference_validate(reference: UploadFile = File(...)):
    drawing = parse_dxf_bytes(await read_upload(reference), source="reference", exclude_info_layers=True)
    return {"validation": validate_reference(drawing), "reference": drawing.to_dict()}

@app.post("/api/assignment/analyze")
async def assignment_analyze(reference: UploadFile = File(...)):
    drawing = parse_dxf_bytes(await read_upload(reference), source="reference", exclude_info_layers=True)
    return analyze_assignment(drawing)

@app.post("/api/reference/objects/inspect")
async def reference_objects_inspect(
    reference: UploadFile = File(...),
    legend_bbox: str | None = Form(None),
    code_mappings: str | None = Form(None),
    custom_info_layers: str | None = Form(None),
):
    reference_bytes = await read_upload(reference)
    ref_id = reference_fingerprint(reference_bytes)

    legend_region = None
    if legend_bbox:
        try:
            parts = [float(x.strip()) for x in legend_bbox.split(",")]
        except ValueError as exc:
            raise HTTPException(422, "Legend exclusion region must contain four numeric coordinates.") from exc
        if len(parts) != 4 or not all(math.isfinite(value) for value in parts) or parts[0] >= parts[2] or parts[1] >= parts[3]:
            raise HTTPException(422, "Legend exclusion region must be x_min, y_min, x_max, y_max.")
        legend_region = (parts[0], parts[1], parts[2], parts[3])

    mappings: dict[str, str] = {}
    if code_mappings:
        try:
            parsed_mappings = json.loads(code_mappings)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "Code mappings must be a JSON object such as {\"X1\":\"Custom object\"}.") from exc
        if not isinstance(parsed_mappings, dict):
            raise HTTPException(422, "Code mappings must be a JSON object.")
        for raw_code, raw_meaning in parsed_mappings.items():
            code = str(raw_code).strip().upper()
            meaning = str(raw_meaning).strip()
            if not MARKER_CODE_RE.fullmatch(code) or not meaning or len(meaning) > 80:
                raise HTTPException(422, f"Invalid code mapping for {raw_code!r}.")
            mappings[code] = meaning

    custom_layers = {
        layer.strip()
        for layer in (custom_info_layers or "").split(",")
        if layer.strip()
    }

    full_drawing = parse_dxf_bytes(
        reference_bytes,
        source="reference",
        normalize=False,
        exclude_info_layers=False,
    )
    base_drawing = parse_dxf_bytes(
        reference_bytes,
        source="reference",
        normalize=False,
        exclude_info_layers=True,
        custom_info_layers=custom_layers,
    )

    plan_markers, legend_markers, meta = extract_reference_markers_and_legend(
        full_drawing.entities,
        full_drawing.unsupported_entities,
        custom_info_layers=custom_layers,
        code_mappings=mappings,
        legend_region_bbox=legend_region,
    )
    objects, summary = build_proposed_reference_objects(
        plan_markers,
        base_drawing.entities,
        code_mappings=mappings,
    )
    configuration = {
        "legend_region": legend_region,
        "code_mappings": mappings,
        "custom_info_layers": sorted(custom_layers, key=str.lower),
    }
    inspection_token = hashlib.sha256(
        (ref_id + json.dumps(configuration, sort_keys=True, separators=(",", ":"))).encode("utf-8")
    ).hexdigest()
    proposals = {obj.occurrence_id: obj.to_dict() for obj in objects}
    entity_by_id = {entity.id: entity for entity in base_drawing.entities}
    previous_inspection = REFERENCE_OBJECT_INSPECTIONS.get(ref_id)
    stored = REFERENCE_OBJECTS.get(ref_id)
    previous_token = (previous_inspection or stored or {}).get("inspection_token")
    configuration_changed = previous_token != inspection_token and (
        previous_token is not None or bool(legend_region or mappings or custom_layers)
    )
    approval_invalidated = False
    if configuration_changed:
        previous_rubric_id = REFERENCE_RUBRICS.pop(ref_id, None)
        if previous_rubric_id and previous_rubric_id in RUBRICS:
            RUBRICS[previous_rubric_id] = RUBRICS[previous_rubric_id].model_copy(update={"approved": False})
            approval_invalidated = True
        REFERENCE_OBJECTS.pop(ref_id, None)
        stored = None
    REFERENCE_OBJECT_INSPECTIONS[ref_id] = {
        "inspection_token": inspection_token,
        "configuration": configuration,
        "proposals": proposals,
        "entity_by_id": entity_by_id,
    }

    object_payload = (
        stored["objects"]
        if stored and stored.get("inspection_token") == inspection_token
        else [obj.to_dict() for obj in objects]
    )
    if stored and stored.get("inspection_token") == inspection_token:
        summary["counts_by_status"] = {
            status: sum(obj.get("status") == status for obj in object_payload)
            for status in ("detected", "proposed", "confirmed", "unresolved", "excluded")
        }

    return {
        "reference_id": ref_id,
        "inspection_token": inspection_token,
        "approval_invalidated": approval_invalidated,
        "definitions_saved": bool(stored and stored.get("inspection_token") == inspection_token),
        "declared_units": full_drawing.units,
        "units_code": full_drawing.units_code,
        "plan_markers": [marker.to_dict() for marker in plan_markers],
        "legend_markers": [marker.to_dict() for marker in legend_markers],
        "objects": object_payload,
        "summary": summary,
        "metadata": meta,
        "configuration": configuration,
        "reference_bbox": list(base_drawing.bbox),
        "available_entities": [entity.to_dict() for entity in base_drawing.entities],
    }


@app.post("/api/reference/objects/confirm")
def reference_objects_confirm(request: ObjectConfirmationRequest):
    inspection = REFERENCE_OBJECT_INSPECTIONS.get(request.reference_id)
    if inspection is None:
        raise HTTPException(409, "Inspect this exact reference before confirming object definitions.")
    if inspection["inspection_token"] != request.inspection_token:
        raise HTTPException(409, "The object proposal is stale. Reinspect the reference before confirming.")

    current_rubric_id = REFERENCE_RUBRICS.get(request.reference_id)
    if request.rubric_id != current_rubric_id:
        raise HTTPException(409, "The object definitions are not associated with the current assignment approval.")

    proposals: dict[str, dict[str, Any]] = inspection["proposals"]
    submitted_ids = [str(obj.get("occurrence_id", "")) for obj in request.objects]
    if len(submitted_ids) != len(set(submitted_ids)) or set(submitted_ids) != set(proposals):
        raise HTTPException(422, "Submit every inspected marker exactly once; object identities cannot be added or removed.")

    valid_member_ids = set(inspection["entity_by_id"])
    confirmed_membership: dict[str, list[str]] = {}
    sanitized_objects: list[dict[str, Any]] = []
    for submitted in request.objects:
        occurrence_id = str(submitted["occurrence_id"])
        proposal = proposals[occurrence_id]
        status = str(submitted.get("status", "unresolved"))
        if status not in {"confirmed", "unresolved", "excluded"}:
            raise HTTPException(422, f"{occurrence_id} must be confirmed, unresolved, or excluded.")

        raw_members = submitted.get("member_entity_ids", [])
        if not isinstance(raw_members, list) or any(not isinstance(member_id, str) for member_id in raw_members):
            raise HTTPException(422, f"{occurrence_id} has an invalid member list.")
        member_ids = list(dict.fromkeys(raw_members))
        foreign_ids = sorted(set(member_ids) - valid_member_ids)
        if foreign_ids:
            raise HTTPException(422, f"{occurrence_id} contains member IDs outside this reference: {', '.join(foreign_ids[:3])}.")
        if status == "confirmed" and not member_ids:
            raise HTTPException(422, f"{occurrence_id} cannot be confirmed without reference geometry.")
        if status == "confirmed" and str(proposal["meaning"]).startswith("Unmapped ("):
            raise HTTPException(422, f"{occurrence_id} requires an instructor code mapping before confirmation.")

        if status == "confirmed":
            for member_id in member_ids:
                confirmed_membership.setdefault(member_id, []).append(occurrence_id)
        entity_by_id = inspection["entity_by_id"]
        selected_boxes = [
            entity_by_id[member_id].bbox
            for member_id in member_ids
            if entity_by_id[member_id].bbox is not None
        ]
        selected_bounds = (
            [min(box[0] for box in selected_boxes), min(box[1] for box in selected_boxes),
             max(box[2] for box in selected_boxes), max(box[3] for box in selected_boxes)]
            if selected_boxes
            else None
        )
        sanitized_objects.append({
            "occurrence_id": occurrence_id,
            "type_code": proposal["type_code"],
            "meaning": proposal["meaning"],
            "marker_location": proposal["marker_location"],
            "member_entity_ids": member_ids,
            "member_handles": [
                entity_by_id[member_id].source_handle
                for member_id in member_ids
                if entity_by_id[member_id].source_handle
            ],
            "bounds": selected_bounds,
            "status": status,
            "exclusion_reason": (
                str(submitted.get("exclusion_reason") or "").strip()[:240]
                if status == "excluded"
                else None
            ),
            "notes": str(submitted.get("notes") or "").strip()[:500],
            "shared_entity_ids": [],
        })

    overlaps = {
        member_id: occurrence_ids
        for member_id, occurrence_ids in confirmed_membership.items()
        if len(occurrence_ids) > 1
    }
    if overlaps and not request.overlap_acknowledged:
        raise HTTPException(409, "Overlapping confirmed memberships require explicit instructor acknowledgment.")
    for obj in sanitized_objects:
        obj["shared_entity_ids"] = sorted(
            member_id
            for member_id, occurrence_ids in overlaps.items()
            if obj["occurrence_id"] in occurrence_ids
        )

    definition_revision = hashlib.sha256(
        json.dumps(sanitized_objects, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    previous = REFERENCE_OBJECTS.get(request.reference_id)
    unchanged = bool(
        previous
        and previous.get("definition_revision") == definition_revision
        and previous.get("inspection_token") == request.inspection_token
    )
    approval_invalidated = bool(current_rubric_id and not unchanged)
    if approval_invalidated:
        approved_rubric = RUBRICS.get(current_rubric_id)
        if approved_rubric is not None:
            RUBRICS[current_rubric_id] = approved_rubric.model_copy(update={"approved": False})
        REFERENCE_RUBRICS.pop(request.reference_id, None)
        current_rubric_id = None

    REFERENCE_OBJECTS[request.reference_id] = {
        "reference_id": request.reference_id,
        "rubric_id": current_rubric_id,
        "inspection_token": request.inspection_token,
        "configuration": inspection["configuration"],
        "definition_revision": definition_revision,
        "overlap_acknowledged": bool(overlaps and request.overlap_acknowledged),
        "objects": sanitized_objects,
    }
    counts = {
        status: sum(obj["status"] == status for obj in sanitized_objects)
        for status in ("confirmed", "unresolved", "excluded")
    }
    return {
        "status": "ok",
        "reference_id": request.reference_id,
        "assignment_id": current_rubric_id,
        "definition_revision": definition_revision,
        "total_objects": len(sanitized_objects),
        "confirmed_count": counts["confirmed"],
        "unresolved_count": counts["unresolved"],
        "excluded_count": counts["excluded"],
        "overlap_acknowledged": bool(overlaps and request.overlap_acknowledged),
        "approval_invalidated": approval_invalidated,
        "objects": sanitized_objects,
    }

@app.post("/api/rubric/suggest")
async def rubric_suggest(reference: UploadFile = File(...)):
    reference_bytes = await read_upload(reference)
    drawing = parse_dxf_bytes(reference_bytes, source="reference", exclude_info_layers=True)
    analysis = analyze_assignment(drawing)
    assignment_title = suggest_assignment_title(reference.filename)
    intended_unit = drawing.units if drawing.units in {"mm", "cm", "m", "in", "ft"} else "unspecified"
    suggested_rubric = default_rubric().model_copy(
        update={
            "assignment_title": assignment_title,
            "normalization_mode": "translation",
            "intended_unit": intended_unit,
        }
    )
    return {
        "reference_id": reference_fingerprint(reference_bytes),
        "analysis": analysis,
        "suggested_assignment_type": analysis["suggested_assignment_type"],
        "assignment_type": suggested_rubric.assignment_type,
        "detected_features": analysis["detected_features"],
        "completion_scoring_mode": suggested_rubric.completion_scoring_mode,
        "normalization_mode": suggested_rubric.normalization_mode,
        "declared_units": drawing.units,
        "units_code": drawing.units_code,
        "intended_unit": intended_unit,
        "rubric": suggested_rubric.model_dump(),
        "provisional": True,
        "requires_instructor_approval": True,
        **rubric_contract(suggested_rubric),
    }

@app.post("/api/rubric/approve")
def rubric_approve(request: RubricApprovalRequest):
    if not request.rubric.assignment_type or not str(request.rubric.assignment_type).strip():
        raise HTTPException(422, "Instructor confirmation of the assignment type is required before rubric approval.")
    if request.rubric.intended_unit not in {"mm", "cm", "m", "in", "ft"}:
        raise HTTPException(422, "Confirm the intended assignment unit before rubric approval.")
    baseline_weights = {
        category.id: category.weight for category in default_rubric().categories
    }
    submitted_weights = {
        category.id: category.weight for category in request.rubric.categories
    }
    modified = request.rubric.rubric_modified_by_instructor or any(
        abs(float(submitted_weights.get(category_id, -1)) - float(weight)) > 0.001
        for category_id, weight in baseline_weights.items()
    )
    approved = request.rubric.model_copy(
        update={
            "approved": True,
            "rubric_source": "instructor_modified" if modified else "baseline_template",
            "rubric_template_name": BASELINE_RUBRIC_TEMPLATE,
            "rubric_modified_by_instructor": modified,
            "intended_unit_confirmed": True,
        }
    )
    rubric_id = str(uuid.uuid4())
    previous_rubric_id = REFERENCE_RUBRICS.get(request.reference_id)
    if previous_rubric_id and previous_rubric_id != rubric_id:
        previous_rubric = RUBRICS.get(previous_rubric_id)
        if previous_rubric is not None:
            RUBRICS[previous_rubric_id] = previous_rubric.model_copy(update={"approved": False})
    RUBRICS[rubric_id] = approved
    RUBRIC_REFERENCES[rubric_id] = request.reference_id
    REFERENCE_RUBRICS[request.reference_id] = rubric_id
    object_record = REFERENCE_OBJECTS.get(request.reference_id)
    if object_record is not None:
        object_record["rubric_id"] = rubric_id
    return {
        "rubric_id": rubric_id,
        "reference_id": request.reference_id,
        "assignment_type": approved.assignment_type,
        "completion_scoring_mode": approved.completion_scoring_mode,
        "normalization_mode": approved.normalization_mode,
        "rubric": approved.model_dump(),
        "object_definition_revision": (object_record or {}).get("definition_revision"),
        **rubric_contract(approved),
    }
@app.post("/api/report",response_class=HTMLResponse)
async def report(payload:dict):
    return render("report.html",data_json=json.dumps(payload).replace("</","<\\/"),score=payload.get("score",0),issues=payload.get("issues",[]),feedback=payload.get("feedback",[]))
def local_feedback(result):
    if not result["issues"]: return ["Excellent geometric match. Verify annotation style and submission requirements before finalizing."]
    return [f"{i['category'].replace('_', ' ').title()}: {i.get('technical_feedback') or i['message']}" for i in result["issues"]]


