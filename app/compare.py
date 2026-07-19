from __future__ import annotations
from copy import deepcopy
import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any
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

MIN_TRANSLATION_SUPPORT = 3
MIN_TRANSLATION_SUPPORT_RATIO = 0.60
MIN_TRANSLATION_ERROR_REDUCTION = 0.25
GEOMETRY_PRECISION = 6

def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), GEOMETRY_PRECISION)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float):
        return _rounded(value)
    return value


def _canonical_points(entity: Entity, *, relative: bool) -> tuple[tuple[float, float], ...]:
    points = [(float(x), float(y)) for x, y in entity.points]
    if relative and points:
        anchor_x, anchor_y = _center(entity)
        points = [(x - anchor_x, y - anchor_y) for x, y in points]
    rounded = [(_rounded(x), _rounded(y)) for x, y in points]
    if entity.kind == "line" and len(rounded) == 2:
        rounded.sort()
    elif entity.closed and rounded:
        variants = []
        for sequence in (rounded, list(reversed(rounded))):
            for start in range(len(sequence)):
                variants.append(tuple(sequence[start:] + sequence[:start]))
        rounded = list(min(variants))
    elif entity.kind in {"polyline", "spline"} and rounded:
        rounded = list(min(tuple(rounded), tuple(reversed(rounded))))
    return tuple(rounded)


def _geometry_signature(entity: Entity, *, relative: bool) -> tuple[Any, ...]:
    return (
        entity.kind,
        entity.layer,
        _canonical_points(entity, relative=relative),
        _rounded(entity.radius),
        _rounded(entity.start_angle),
        _rounded(entity.end_angle),
        _rounded(entity.measurement),
        entity.closed,
        entity.text,
        _freeze(entity.properties),
    )


def _group_by_signature(
    entities: list[Entity], *, relative: bool
) -> dict[tuple[Any, ...], list[Entity]]:
    groups: dict[tuple[Any, ...], list[Entity]] = defaultdict(list)
    for entity in entities:
        groups[_geometry_signature(entity, relative=relative)].append(entity)
    for group in groups.values():
        group.sort(key=lambda entity: entity.id)
    return groups


def _exact_entity_pairs(reference: Drawing, student: Drawing) -> list[tuple[Entity, Entity]]:
    reference_groups = _group_by_signature(reference.entities, relative=False)
    student_groups = _group_by_signature(student.entities, relative=False)
    pairs = []
    for signature in sorted(reference_groups, key=repr):
        reference_group = reference_groups[signature]
        student_group = student_groups.get(signature, [])
        pairs.extend(zip(reference_group, student_group))
    return pairs


def _translation_evidence(
    reference: Drawing, student: Drawing
) -> tuple[list[tuple[Entity, Entity]], list[tuple[Entity, Entity]]]:
    exact_pairs = _exact_entity_pairs(reference, student)
    exact_reference_ids = {reference_entity.id for reference_entity, _ in exact_pairs}
    exact_student_ids = {student_entity.id for _, student_entity in exact_pairs}
    reference_remaining = [
        entity for entity in reference.entities if entity.id not in exact_reference_ids
    ]
    student_remaining = [
        entity for entity in student.entities if entity.id not in exact_student_ids
    ]
    reference_groups = _group_by_signature(reference_remaining, relative=True)
    student_groups = _group_by_signature(student_remaining, relative=True)
    intrinsic_pairs = []
    for signature in sorted(reference_groups, key=repr):
        reference_group = reference_groups[signature]
        student_group = student_groups.get(signature, [])
        if len(reference_group) == 1 and len(student_group) == 1:
            intrinsic_pairs.append((reference_group[0], student_group[0]))
    return exact_pairs + intrinsic_pairs, exact_pairs


def _normalization_confidence(support_count: int, support_ratio: float) -> str:
    if support_count >= 4 and support_ratio >= 0.90:
        return "verified"
    if support_count >= MIN_TRANSLATION_SUPPORT and support_ratio >= 0.75:
        return "high"
    if support_count >= MIN_TRANSLATION_SUPPORT:
        return "moderate"
    return "none"

def _estimate_translation(
    reference: Drawing, student: Drawing, tolerance: ToleranceProfile
) -> dict[str, Any]:
    evidence, exact_pairs = _translation_evidence(reference, student)
    empty_result = {
        "candidate_translation": (0.0, 0.0),
        "selected_translation": (0.0, 0.0),
        "support_count": 0,
        "support_ratio": 0.0,
        "confidence": "none",
        "rejection_reason": "no_confident_intrinsic_matches",
        "error_before": 0.0,
        "error_after": 0.0,
        "error_reduction_ratio": 0.0,
        "evidence_count": 0,
    }
    if not evidence:
        return empty_result

    displacements = [
        (
            _center(reference_entity)[0] - _center(student_entity)[0],
            _center(reference_entity)[1] - _center(student_entity)[1],
        )
        for reference_entity, student_entity in evidence
    ]
    agreement_radius = max(float(tolerance.position), 1e-9)
    candidates = []
    for seed_x, seed_y in sorted(set(displacements)):
        preliminary = [
            displacement
            for displacement in displacements
            if math.dist(displacement, (seed_x, seed_y)) <= agreement_radius
        ]
        candidate_x = float(median(displacement[0] for displacement in preliminary))
        candidate_y = float(median(displacement[1] for displacement in preliminary))
        inliers = [
            displacement
            for displacement in displacements
            if math.dist(displacement, (candidate_x, candidate_y)) <= agreement_radius
        ]
        residual = sum(
            math.dist(displacement, (candidate_x, candidate_y))
            for displacement in inliers
        )
        candidates.append(
            (
                -len(inliers),
                round(residual, GEOMETRY_PRECISION),
                _rounded(candidate_x),
                _rounded(candidate_y),
                inliers,
            )
        )
    _, _, candidate_x, candidate_y, inliers = min(candidates)
    candidate = (float(candidate_x), float(candidate_y))
    support_count = len(inliers)
    support_ratio = support_count / len(evidence)

    error_before = sum(_distance(reference_entity, student_entity) for reference_entity, student_entity in evidence)
    error_after = sum(
        math.dist(
            _center(reference_entity),
            (
                _center(student_entity)[0] + candidate[0],
                _center(student_entity)[1] + candidate[1],
            ),
        )
        for reference_entity, student_entity in evidence
    )
    reduction_ratio = (
        max(0.0, (error_before - error_after) / error_before)
        if error_before > 1e-9
        else 0.0
    )

    rejection_reason = None
    if support_count < MIN_TRANSLATION_SUPPORT:
        rejection_reason = "insufficient_support"
    elif support_ratio < MIN_TRANSLATION_SUPPORT_RATIO:
        rejection_reason = "insufficient_support_ratio"
    elif math.dist(candidate, (0.0, 0.0)) <= tolerance.position:
        rejection_reason = "consensus_translation_within_position_tolerance"
    else:
        disrupted_exact = sum(
            math.dist(
                _center(reference_entity),
                (
                    _center(student_entity)[0] + candidate[0],
                    _center(student_entity)[1] + candidate[1],
                ),
            )
            > tolerance.position
            for reference_entity, student_entity in exact_pairs
        )
        if exact_pairs and disrupted_exact > len(exact_pairs) / 2:
            rejection_reason = "would_disrupt_majority_of_exact_matches"
        elif reduction_ratio < MIN_TRANSLATION_ERROR_REDUCTION:
            rejection_reason = "insufficient_total_error_reduction"

    selected = candidate if rejection_reason is None else (0.0, 0.0)
    return {
        "candidate_translation": candidate,
        "selected_translation": selected,
        "support_count": support_count,
        "support_ratio": round(support_ratio, GEOMETRY_PRECISION),
        "confidence": _normalization_confidence(support_count, support_ratio),
        "rejection_reason": rejection_reason,
        "error_before": round(error_before, GEOMETRY_PRECISION),
        "error_after": round(error_after, GEOMETRY_PRECISION),
        "error_reduction_ratio": round(reduction_ratio, GEOMETRY_PRECISION),
        "evidence_count": len(evidence),
    }


def _normalization_record(
    mode: str,
    translation: tuple[float, float],
    *,
    candidate: tuple[float, float] = (0.0, 0.0),
    support_count: int = 0,
    support_ratio: float = 0.0,
    confidence: str = "none",
    rejection_reason: str | None = None,
    error_before: float = 0.0,
    error_after: float = 0.0,
    error_reduction_ratio: float = 0.0,
    evidence_count: int = 0,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "translation": [_rounded(translation[0]), _rounded(translation[1])],
        "candidate_translation": [_rounded(candidate[0]), _rounded(candidate[1])],
        "rotation_degrees": 0,
        "scale": 1,
        "support_count": support_count,
        "support_ratio": round(float(support_ratio), GEOMETRY_PRECISION),
        "confidence": confidence,
        "rejection_reason": rejection_reason,
        "error_before": round(float(error_before), GEOMETRY_PRECISION),
        "error_after": round(float(error_after), GEOMETRY_PRECISION),
        "error_reduction_ratio": round(float(error_reduction_ratio), GEOMETRY_PRECISION),
        "evidence_count": evidence_count,
    }


def _translated_drawing(
    drawing: Drawing,
    translation: tuple[float, float],
    normalization: dict[str, Any],
) -> Drawing:
    translated = deepcopy(drawing)
    dx, dy = translation
    if dx or dy:
        for entity in translated.entities:
            entity.points = [
                (_rounded(x + dx), _rounded(y + dy)) for x, y in entity.points
            ]
            if entity.centroid is not None:
                entity.centroid = (
                    _rounded(entity.centroid[0] + dx),
                    _rounded(entity.centroid[1] + dy),
                )
            if entity.bbox is not None:
                entity.bbox = (
                    _rounded(entity.bbox[0] + dx),
                    _rounded(entity.bbox[1] + dy),
                    _rounded(entity.bbox[2] + dx),
                    _rounded(entity.bbox[3] + dy),
                )
        translated.bbox = (
            _rounded(translated.bbox[0] + dx),
            _rounded(translated.bbox[1] + dy),
            _rounded(translated.bbox[2] + dx),
            _rounded(translated.bbox[3] + dy),
        )
    translated.normalization = deepcopy(normalization)
    return translated


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
    exact_pairs = _exact_entity_pairs(reference, student)
    used_r = {reference_entity.id for reference_entity, _ in exact_pairs}
    used_s = {student_entity.id for _, student_entity in exact_pairs}
    matched = [
        (reference_entity, student_entity, 1.0)
        for reference_entity, student_entity in exact_pairs
    ]
    pairs = sorted(
        (
            (
                _candidate_cost(reference_entity, student_entity),
                _geometry_signature(reference_entity, relative=False),
                _geometry_signature(student_entity, relative=False),
                reference_entity,
                student_entity,
            )
            for reference_entity in reference.entities
            for student_entity in student.entities
            if reference_entity.id not in used_r
            and student_entity.id not in used_s
            and _compatible(reference_entity, student_entity)
        ),
        key=lambda item: (item[0], repr(item[1]), repr(item[2]), item[3].id, item[4].id),
    )
    extent = max(
        reference.bbox[2] - reference.bbox[0],
        reference.bbox[3] - reference.bbox[1],
        1,
    )
    threshold = max(tolerance.position * 5, extent * 0.08)
    for cost, _, _, reference_entity, student_entity in pairs:
        if reference_entity.id in used_r or student_entity.id in used_s:
            continue
        length_delta = abs(
            (entity_length(reference_entity) or 0)
            - (entity_length(student_entity) or 0)
        )
        distance = _distance(reference_entity, student_entity)
        plausible = distance <= threshold or (
            reference_entity.kind in {"line", "polyline"}
            and distance <= max(threshold, length_delta + tolerance.position)
        )
        if plausible:
            used_r.add(reference_entity.id)
            used_s.add(student_entity.id)
            confidence = max(0.0, min(1.0, 1 - cost / (extent + 1)))
            matched.append((reference_entity, student_entity, confidence))
    reference_order = {
        entity.id: index for index, entity in enumerate(reference.entities)
    }
    matched.sort(key=lambda item: (reference_order[item[0].id], item[1].id))
    missing = [entity for entity in reference.entities if entity.id not in used_r]
    extra = [entity for entity in student.entities if entity.id not in used_s]
    return matched, missing, extra


def _prepare_comparison_geometry(
    reference: Drawing,
    student: Drawing,
    rubric: Rubric,
    tolerance: ToleranceProfile,
) -> tuple[Drawing, dict[str, Any], dict[str, Any]]:
    mode = rubric.normalization_mode
    if mode == "strict":
        strict_record = _normalization_record(
            "strict",
            (0.0, 0.0),
            confidence="not_applicable",
            rejection_reason="strict_mode",
        )
        return (
            _translated_drawing(student, (0.0, 0.0), strict_record),
            deepcopy(strict_record),
            deepcopy(strict_record),
        )
    if mode != "translation":
        raise ValueError(f"normalization mode '{mode}' is not implemented")

    estimate = _estimate_translation(reference, student, tolerance)
    reference_record = _normalization_record(
        "translation",
        (0.0, 0.0),
        support_count=estimate["support_count"],
        support_ratio=estimate["support_ratio"],
        confidence="reference_anchor",
        evidence_count=estimate["evidence_count"],
    )
    student_record = _normalization_record(
        "translation",
        estimate["selected_translation"],
        candidate=estimate["candidate_translation"],
        support_count=estimate["support_count"],
        support_ratio=estimate["support_ratio"],
        confidence=estimate["confidence"],
        rejection_reason=estimate["rejection_reason"],
        error_before=estimate["error_before"],
        error_after=estimate["error_after"],
        error_reduction_ratio=estimate["error_reduction_ratio"],
        evidence_count=estimate["evidence_count"],
    )
    matching_student = _translated_drawing(
        student, estimate["selected_translation"], student_record
    )
    return matching_student, reference_record, student_record

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
    (
        matching_student,
        reference_normalization,
        student_normalization,
    ) = _prepare_comparison_geometry(reference, student, rubric, tolerance)
    matched, missing, extra = _match_entities(reference, matching_student, tolerance)
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
        "normalization":{"reference":reference_normalization,"student":student_normalization},
        "match_count":len(matched), "matches":[{"reference_entity_id":r.id,"student_entity_id":s.id,"confidence":round(c,3)} for r,s,c in matched],
        "audit_trail":audit,
        "tolerances":tolerance.model_dump(),
        "rubric_application":{"approved":rubric.approved,"normalization_mode":rubric.normalization_mode,"category_weights":{c.id:c.weight for c in rubric.categories}},
    }
