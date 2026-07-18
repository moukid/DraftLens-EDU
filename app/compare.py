from __future__ import annotations
import math
from dataclasses import dataclass
from collections import defaultdict
from shapely.geometry import LineString
from .dxf import entity_length
from .models import Drawing, Entity, Issue
from .rubric import Rubric, ToleranceProfile, default_rubric, rubric_rule_map

@dataclass(slots=True)
class Tolerances:
    position: float = 2.0
    length: float = 1.0
    angle: float = 3.0
    dimension: float = 1.0
    radius: float = 1.0

def _center(entity: Entity) -> tuple[float, float]:
    return entity.centroid or (entity.points[0] if entity.points else (0.0, 0.0))

def _angle(entity: Entity) -> float | None:
    if len(entity.points) < 2:
        return None
    a, b = entity.points[0], entity.points[-1]
    return math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 180

def _angle_delta(a: float, b: float) -> float:
    delta = abs(a-b) % 180
    return min(delta, 180-delta)

def _distance(a: Entity, b: Entity) -> float:
    return math.dist(_center(a), _center(b))

def _compatible(a: Entity, b: Entity) -> bool:
    if a.kind == b.kind:
        return True
    return {a.kind, b.kind} <= {"line", "polyline"}

def _candidate_cost(reference: Entity, student: Entity) -> float:
    distance = _distance(reference, student)
    lr, ls = entity_length(reference), entity_length(student)
    size = abs((lr or 0)-(ls or 0))
    angle = _angle_delta(_angle(reference), _angle(student)) if _angle(reference) is not None and _angle(student) is not None else 0
    radius = abs((reference.radius or 0)-(student.radius or 0))
    return distance + size*0.35 + angle*0.08 + radius*0.5

def _match_entities(reference: Drawing, student: Drawing, tolerance: ToleranceProfile):
    pairs = sorted(
        (( _candidate_cost(r,s), r, s) for r in reference.entities for s in student.entities if _compatible(r,s)),
        key=lambda item: item[0],
    )
    used_r, used_s, matched = set(), set(), []
    extent = max(reference.bbox[2]-reference.bbox[0], reference.bbox[3]-reference.bbox[1], 1)
    threshold = max(tolerance.position*5, extent*0.08)
    for cost, r, s in pairs:
        if r.id in used_r or s.id in used_s:
            continue
        length_delta = abs((entity_length(r) or 0)-(entity_length(s) or 0))
        plausible = _distance(r,s) <= threshold or (r.kind in {"line","polyline"} and _distance(r,s) <= max(threshold, length_delta+tolerance.position))
        if plausible:
            used_r.add(r.id); used_s.add(s.id); matched.append((r,s,max(0.0, min(1.0, 1-cost/(extent+1)))))
    return matched, [r for r in reference.entities if r.id not in used_r], [s for s in student.entities if s.id not in used_s]

def _legacy_code(category: str, ref: Entity | None, stu: Entity | None) -> str:
    layer = ((ref or stu).layer if (ref or stu) else "").lower()
    if "wall" in layer:
        return {"missing_geometry":"MISSING_WALL","extra_geometry":"EXTRA_WALL"}.get(category,"WALL_GEOMETRY")
    if "door" in layer:
        return "DOOR_SWING"
    if "window" in layer:
        return "WINDOW_GEOMETRY"
    if (ref or stu) and (ref or stu).kind == "dimension":
        return "DIMENSION"
    return category.upper()

def compare_drawings(reference: Drawing, student: Drawing, t: Tolerances | None = None, rubric: Rubric | dict | None = None):
    if rubric is None:
        rubric = default_rubric().model_copy(update={"approved": True})
    elif not isinstance(rubric, Rubric):
        raise TypeError("rubric must be a validated Rubric instance")
    elif not rubric.approved:
        raise ValueError("grading requires an approved rubric")
    if t:
        rubric.tolerances = ToleranceProfile(position=t.position,length=t.length,angle=t.angle,radius=t.radius,dimension=t.dimension,vertex=t.position)
    tolerance = rubric.tolerances
    rules = rubric_rule_map(rubric)
    matched, missing, extra = _match_entities(reference, student, tolerance)
    issues: list[Issue] = []

    def add(category, ref=None, stu=None, prop=None, expected=None, actual=None, tolerance_value=None, confidence="verified"):
        rule_pair = rules.get(category)
        if rule_pair:
            rule, _ = rule_pair
            deduction, severity, rule_id, commands = rule.deduction, rule.severity, rule.id, rule.commands
        else:
            deduction, severity, rule_id, commands = 0.0, "warning", None, []
        location = _center(ref or stu) if ref is not None or stu is not None else None
        deviation = None
        if isinstance(expected, (int,float)) and isinstance(actual, (int,float)):
            deviation = actual-expected
        measurement = {"property": prop, "expected": expected, "actual": actual, "deviation": deviation, "tolerance": tolerance_value, "unit": reference.units} if prop else None
        action = {
            "missing_geometry": "Add the required geometry at the ghosted location.",
            "extra_geometry": "Remove the unmatched construction geometry if it is not an accepted alternative.",
            "incorrect_position": f"Move the entity by {abs(deviation or 0):.3f} drawing units toward the expected location.",
            "incorrect_length": "Adjust the entity length to the expected value.",
            "incorrect_angle": "Rotate the entity to the expected angle.",
            "incorrect_radius": "Change the entity to the expected radius.",
            "incorrect_shape": "Edit the vertices or curve so it follows the reference ghost.",
            "open_polyline": "Close the required boundary.",
            "duplicate_geometry": "Remove the coincident duplicate entity.",
            "unsupported_entity": "Review this unsupported entity manually.",
        }.get(category, "Review this finding.")
        if category in {"incorrect_length", "incorrect_angle", "incorrect_radius"} and isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            labels = {"incorrect_length": ("length", ""), "incorrect_angle": ("angle", " degrees"), "incorrect_radius": ("radius", "")}
            label, suffix = labels[category]
            action = f"Adjust the {label} from {actual:.3f}{suffix} to {expected:.3f}{suffix}."
        issue = Issue(
            id=f"E-{len(issues)+1:03d}", category=category, code=_legacy_code(category,ref,stu),
            severity=severity, confidence=confidence, deduction=deduction,
            reference_entity_id=ref.id if ref else None, student_entity_id=stu.id if stu else None,
            location=location, measurement=measurement, rubric_rule_id=rule_id,
            technical_feedback=action, recommended_commands=list(commands), expected=expected, actual=actual,
            message=action,
        )
        issues.append(issue)

    for ref in missing:
        add("missing_geometry", ref=ref)
    for stu in extra:
        add("extra_geometry", stu=stu)
    for ref, stu, confidence_value in matched:
        confidence = "verified" if confidence_value >= .85 else "high" if confidence_value >= .55 else "moderate"
        position = _distance(ref,stu)
        if position > tolerance.position:
            add("incorrect_position",ref,stu,"centroid_distance",0.0,position,tolerance.position,confidence)
        lr, ls = entity_length(ref), entity_length(stu)
        if lr is not None and ls is not None and abs(lr-ls) > tolerance.length:
            add("incorrect_length",ref,stu,"length",lr,ls,tolerance.length,confidence)
        ar, ass = _angle(ref), _angle(stu)
        if ar is not None and ass is not None and _angle_delta(ar,ass) > tolerance.angle:
            add("incorrect_angle",ref,stu,"angle",ar,ass,tolerance.angle,confidence)
        if ref.kind == "dimension" and ref.measurement is not None and stu.measurement is not None and abs(ref.measurement-stu.measurement) > tolerance.dimension:
            add("incorrect_length",ref,stu,"dimension_measurement",ref.measurement,stu.measurement,tolerance.dimension,confidence)
        if ref.radius is not None and stu.radius is not None and abs(ref.radius-stu.radius) > tolerance.radius:
            add("incorrect_radius",ref,stu,"radius",ref.radius,stu.radius,tolerance.radius,confidence)
        if ref.kind == "arc" and stu.kind == "arc":
            span_r = ((ref.end_angle or 0)-(ref.start_angle or 0))%360
            span_s = ((stu.end_angle or 0)-(stu.start_angle or 0))%360
            if abs(span_r-span_s) > tolerance.angle:
                add("incorrect_angle",ref,stu,"arc_span",span_r,span_s,tolerance.angle,confidence)
        if ref.kind == "polyline":
            if ref.closed and not stu.closed:
                add("open_polyline",ref,stu,"closed",True,False,0,confidence)
            if len(ref.points) != len(stu.points):
                add("incorrect_shape",ref,stu,"vertex_count",len(ref.points),len(stu.points),0,confidence)
        if ref.kind == "spline" and len(ref.points)>1 and len(stu.points)>1:
            hausdorff = LineString(ref.points).hausdorff_distance(LineString(stu.points))
            if hausdorff > tolerance.position:
                add("incorrect_shape",ref,stu,"sampled_hausdorff",0.0,hausdorff,tolerance.position,"moderate")

    signatures = defaultdict(list)
    for entity in student.entities:
        signature = (entity.kind, tuple(entity.points), round(entity.radius or 0,6), entity.closed)
        signatures[signature].append(entity)
    for group in signatures.values():
        for duplicate in group[1:]:
            add("duplicate_geometry",stu=duplicate)

    for unsupported in student.unsupported_entities:
        add("unsupported_entity", expected="supported entity", actual=unsupported["entity_type"], confidence="instructor_review_required")

    matched_required = len(matched)
    completion = round(100*matched_required/max(len(reference.entities),1),1)
    by_type = {}
    for kind in sorted({e.kind for e in reference.entities}):
        total = sum(e.kind==kind for e in reference.entities)
        count = sum(r.kind==kind for r,_,_ in matched)
        by_type[kind] = round(100*count/max(total,1),1)

    category_deductions, rule_deductions = defaultdict(float), defaultdict(float)
    audit = []
    for issue in issues:
        if issue.confidence not in {"verified","high"} or issue.status == "rejected":
            audit.append({"issue_id":issue.id,"applied":False,"reason":"requires instructor confirmation"})
            continue
        pair = rules.get(issue.category)
        if not pair:
            continue
        rule, category = pair
        remaining_rule = max(0,(rule.repeat_cap if rule.repeat_cap is not None else 100)-rule_deductions[rule.id])
        remaining_category = max(0,(category.max_deduction if category.max_deduction is not None else category.weight)-category_deductions[category.id])
        applied = min(issue.deduction, remaining_rule, remaining_category)
        rule_deductions[rule.id] += applied
        category_deductions[category.id] += applied
        audit.append({"issue_id":issue.id,"rule_id":rule.id,"requested":issue.deduction,"applied":applied})
    completion_category = next(c for c in rubric.categories if c.id=="completion")
    completion_deduction = round((100-completion)/100*completion_category.weight,2)
    category_deductions["completion"] = completion_deduction
    deduction = round(sum(category_deductions.values()),2)
    score = max(0.0,round(100-deduction,1))
    breakdown = []
    for category in rubric.categories:
        deducted = round(category_deductions[category.id],2)
        breakdown.append({"id":category.id,"name":category.name,"weight":category.weight,"deduction":deducted,"score":round(max(0,category.weight-deducted),2)})

    return {
        "score":score, "system_score":score, "deduction":deduction,
        "issues":[i.to_dict() for i in issues],
        "summary":{"issue_count":len(issues),"by_category":dict(category_deductions)},
        "rubric_breakdown":breakdown,
        "completion":{"overall":completion,"by_entity_type":by_type,"by_region":{"all":completion},"by_category":{"completion":completion}},
        "normalization":{"reference":reference.normalization,"student":student.normalization},
        "match_count":len(matched), "matches":[{"reference_entity_id":r.id,"student_entity_id":s.id,"confidence":round(c,3)} for r,s,c in matched],
        "audit_trail":audit,
        "tolerances":tolerance.model_dump(),
        "rubric_application":{"approved":rubric.approved,"normalization_mode":rubric.normalization_mode,"category_weights":{c.id:c.weight for c in rubric.categories}},
    }
