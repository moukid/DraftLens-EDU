from __future__ import annotations
from copy import deepcopy
import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any, get_args
from shapely.geometry import LineString
from .canonical_geometry import (
    estimate_canonical_translation,
    match_canonical_geometry,
)
from .causal_analysis import CausalFinding, analyze_comparison
from .correction_guidance import correction_guidance
from .dxf import entity_length
from .models import Drawing, Entity, Issue
from .rubric import (
    AssignmentType,
    Rubric,
    ToleranceProfile,
    default_rubric,
    rubric_rule_map,
)

SUPPORTED_CANONICAL_ASSIGNMENT_TYPES: frozenset[str] = frozenset(
    set(get_args(AssignmentType)) | {"Geometry only"}
)
from .scoring import score_issues

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
MIN_GLOBAL_TRANSLATION_SUPPORT_RATIO = 0.75
MIN_GLOBAL_TRANSLATION_SUPPORT = 8
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


def _canonical_points(
    entity: Entity,
    *,
    relative: bool,
    precision: int = GEOMETRY_PRECISION,
) -> tuple[tuple[float, float], ...]:
    points = [(float(x), float(y)) for x, y in entity.points]
    if relative and points:
        anchor_x, anchor_y = _center(entity)
        points = [(x - anchor_x, y - anchor_y) for x, y in points]
    rounded = [(round(x, precision), round(y, precision)) for x, y in points]
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


def _geometry_signature(
    entity: Entity,
    *,
    relative: bool,
    precision: int = GEOMETRY_PRECISION,
) -> tuple[Any, ...]:
    filtered_properties = {
        key: (value[:2] if key == "major_axis" and isinstance(value, (tuple, list)) else value)
        for key, value in entity.properties.items()
        if key != "extrusion"
    }
    return (
        entity.kind,
        entity.layer,
        _canonical_points(entity, relative=relative, precision=precision),
        None if entity.radius is None else round(float(entity.radius), precision),
        None if entity.start_angle is None else round(float(entity.start_angle), precision),
        None if entity.end_angle is None else round(float(entity.end_angle), precision),
        None if entity.measurement is None else round(float(entity.measurement), precision),
        entity.closed,
        entity.text,
        _freeze(filtered_properties),
    )


def _group_by_signature(
    entities: list[Entity],
    *,
    relative: bool,
    precision: int = GEOMETRY_PRECISION,
) -> dict[tuple[Any, ...], list[Entity]]:
    groups: dict[tuple[Any, ...], list[Entity]] = defaultdict(list)
    for entity in entities:
        groups[
            _geometry_signature(entity, relative=relative, precision=precision)
        ].append(entity)
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


def _assignment_entity_key(entity: Entity) -> tuple[str, str]:
    return (repr(_geometry_signature(entity, relative=False)), entity.id)


def _rectangular_assignment(costs: list[list[float]]) -> list[tuple[int, int]]:
    """Return a deterministic minimum-cost assignment for rows <= columns."""

    row_count = len(costs)
    column_count = len(costs[0]) if costs else 0
    if row_count == 0 or column_count == 0:
        return []
    if row_count > column_count or any(len(row) != column_count for row in costs):
        raise ValueError("assignment matrix must be rectangular with rows <= columns")

    row_potential = [0.0] * (row_count + 1)
    column_potential = [0.0] * (column_count + 1)
    matched_row = [0] * (column_count + 1)
    previous_column = [0] * (column_count + 1)
    epsilon = 1e-12

    for row in range(1, row_count + 1):
        matched_row[0] = row
        minimum = [math.inf] * (column_count + 1)
        used = [False] * (column_count + 1)
        column = 0
        while True:
            used[column] = True
            current_row = matched_row[column]
            delta = math.inf
            next_column = 0
            for candidate_column in range(1, column_count + 1):
                if used[candidate_column]:
                    continue
                reduced = (
                    costs[current_row - 1][candidate_column - 1]
                    - row_potential[current_row]
                    - column_potential[candidate_column]
                )
                if reduced < minimum[candidate_column] - epsilon:
                    minimum[candidate_column] = reduced
                    previous_column[candidate_column] = column
                if minimum[candidate_column] < delta - epsilon:
                    delta = minimum[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(column_count + 1):
                if used[candidate_column]:
                    row_potential[matched_row[candidate_column]] += delta
                    column_potential[candidate_column] -= delta
                else:
                    minimum[candidate_column] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            prior = previous_column[column]
            matched_row[column] = matched_row[prior]
            column = prior
            if column == 0:
                break

    assignment = [
        (matched_row[column] - 1, column - 1)
        for column in range(1, column_count + 1)
        if matched_row[column]
    ]
    return sorted(assignment)


def _minimum_cost_pairs(
    reference_entities: list[Entity], student_entities: list[Entity]
) -> list[tuple[Entity, Entity]]:
    references = sorted(reference_entities, key=_assignment_entity_key)
    students = sorted(student_entities, key=_assignment_entity_key)
    if not references or not students:
        return []
    if len(references) <= len(students):
        costs = [
            [_candidate_cost(reference, student) for student in students]
            for reference in references
        ]
        pairs = [
            (references[reference_index], students[student_index])
            for reference_index, student_index in _rectangular_assignment(costs)
        ]
    else:
        costs = [
            [_candidate_cost(reference, student) for reference in references]
            for student in students
        ]
        pairs = [
            (references[reference_index], students[student_index])
            for student_index, reference_index in _rectangular_assignment(costs)
        ]
    return sorted(
        pairs,
        key=lambda pair: (
            _assignment_entity_key(pair[0]),
            _assignment_entity_key(pair[1]),
        ),
    )


def _intrinsic_entity_pairs(
    reference_entities: list[Entity],
    student_entities: list[Entity],
    *,
    precision: int = GEOMETRY_PRECISION,
) -> list[tuple[Entity, Entity]]:
    reference_groups = _group_by_signature(
        reference_entities, relative=True, precision=precision
    )
    student_groups = _group_by_signature(
        student_entities, relative=True, precision=precision
    )
    pairs: list[tuple[Entity, Entity]] = []
    for signature in sorted(reference_groups, key=repr):
        pairs.extend(
            _minimum_cost_pairs(
                reference_groups[signature], student_groups.get(signature, [])
            )
        )
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
    intrinsic_pairs = _intrinsic_entity_pairs(reference_remaining, student_remaining)
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
    reference: Drawing,
    student: Drawing,
    tolerance: ToleranceProfile,
    use_canonical: bool = False,
) -> dict[str, Any]:
    evidence, exact_pairs = _translation_evidence(reference, student)
    if use_canonical or not evidence:
        canonical = estimate_canonical_translation(
            reference, student, tolerance.position
        )
        if (
            canonical
            and canonical["support_count"] >= MIN_TRANSLATION_SUPPORT
            and (
                canonical["support_ratio"] >= MIN_TRANSLATION_SUPPORT_RATIO
                or canonical.get("length_support_ratio", 0.0) >= MIN_TRANSLATION_SUPPORT_RATIO
            )
        ):
            candidate = canonical["candidate_translation"]
            disrupted = sum(
                math.dist(
                    _center(r),
                    (_center(t)[0] + candidate[0], _center(t)[1] + candidate[1]),
                )
                > tolerance.position
                for r, t in exact_pairs
            )
            if not exact_pairs or disrupted <= len(exact_pairs) / 2:
                reason = (
                    "consensus_translation_within_position_tolerance"
                    if math.dist(candidate, (0, 0)) <= tolerance.position
                    else "insufficient_total_error_reduction"
                    if canonical["error_reduction_ratio"]
                    < MIN_TRANSLATION_ERROR_REDUCTION
                    else None
                )
                effective_ratio = max(
                    canonical["support_ratio"],
                    canonical.get("length_support_ratio", 0.0),
                )
                return {
                    **canonical,
                    "selected_translation": candidate
                    if reason is None
                    else (0.0, 0.0),
                    "confidence": _normalization_confidence(
                        canonical["support_count"], effective_ratio
                    ),
                    "rejection_reason": reason,
                }
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
        if use_canonical:
            canonical = estimate_canonical_translation(
                reference, student, tolerance.position
            )
            if canonical:
                count = canonical["support_count"]
                ratio = canonical["support_ratio"]
                len_ratio = canonical.get("length_support_ratio", 0.0)
                effective_ratio = max(ratio, len_ratio)
                reason = (
                    "insufficient_support"
                    if count < MIN_TRANSLATION_SUPPORT
                    else "insufficient_support_ratio"
                    if effective_ratio < MIN_TRANSLATION_SUPPORT_RATIO
                    else "consensus_translation_within_position_tolerance"
                    if math.dist(canonical["candidate_translation"], (0, 0))
                    <= tolerance.position
                    else "insufficient_total_error_reduction"
                    if canonical["error_reduction_ratio"]
                    < MIN_TRANSLATION_ERROR_REDUCTION
                    else None
                )
                return {
                    **canonical,
                    "selected_translation": canonical["candidate_translation"]
                    if reason is None
                    else (0.0, 0.0),
                    "confidence": _normalization_confidence(count, effective_ratio),
                    "rejection_reason": reason,
                }
        return empty_result

    displacements = [
        (
            _center(reference_entity)[0] - _center(student_entity)[0],
            _center(reference_entity)[1] - _center(student_entity)[1],
        )
        for reference_entity, student_entity in evidence
    ]
    agreement_radius = max(float(tolerance.position), 1e-9)
    total_ref_len = sum(entity_length(r) or 0.0 for r in reference.entities)
    candidates = []
    for seed_x, seed_y in sorted(set(displacements)):
        preliminary = [
            displacement
            for displacement in displacements
            if math.dist(displacement, (seed_x, seed_y)) <= agreement_radius
        ]
        candidate_x = float(median(displacement[0] for displacement in preliminary))
        candidate_y = float(median(displacement[1] for displacement in preliminary))
        inlier_indices = [
            idx
            for idx, displacement in enumerate(displacements)
            if math.dist(displacement, (candidate_x, candidate_y)) <= agreement_radius
        ]
        inliers = [displacements[idx] for idx in inlier_indices]
        inlier_len = sum(
            entity_length(evidence[idx][0]) or 0.0
            for idx in inlier_indices
        )
        majority_len = inlier_len >= 0.5 * total_ref_len if total_ref_len > 0 else False
        residual = sum(
            math.dist(displacement, (candidate_x, candidate_y))
            for displacement in inliers
        )
        candidates.append(
            (
                not majority_len,
                -len(inliers),
                -round(inlier_len, GEOMETRY_PRECISION),
                round(residual, GEOMETRY_PRECISION),
                _rounded(candidate_x),
                _rounded(candidate_y),
                inliers,
                inlier_len,
            )
        )
    _, _, _, _, candidate_x, candidate_y, inliers, inlier_len = min(candidates)
    candidate = (float(candidate_x), float(candidate_y))
    support_count = len(inliers)
    support_ratio = support_count / len(evidence)
    total_ev_len = sum(entity_length(r) or 0.0 for r, _ in evidence)
    length_ratio = inlier_len / max(total_ev_len, 1e-9) if total_ev_len > 0 else 0.0
    effective_support_ratio = max(support_ratio, length_ratio)

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
    has_ev_len = any((entity_length(r) or 0.0) > 1e-6 for r, _ in evidence)
    if has_ev_len:
        weighted_before = sum(
            _distance(reference_entity, student_entity) * max(entity_length(reference_entity) or 0.0, 1e-3)
            for reference_entity, student_entity in evidence
        )
        weighted_after = sum(
            math.dist(
                _center(reference_entity),
                (
                    _center(student_entity)[0] + candidate[0],
                    _center(student_entity)[1] + candidate[1],
                ),
            )
            * max(entity_length(reference_entity) or 0.0, 1e-3)
            for reference_entity, student_entity in evidence
        )
    else:
        weighted_before = error_before
        weighted_after = error_after
    assign_reduction = (
        max(0.0, (weighted_before - weighted_after) / weighted_before)
        if weighted_before > 1e-9
        else 0.0
    )
    inlier_before = sum(
        _distance(evidence[idx][0], evidence[idx][1])
        for idx in inlier_indices
    )
    inlier_after = sum(
        math.dist(
            _center(evidence[idx][0]),
            (
                _center(evidence[idx][1])[0] + candidate[0],
                _center(evidence[idx][1])[1] + candidate[1],
            ),
        )
        for idx in inlier_indices
    )
    inlier_reduction = (
        max(0.0, (inlier_before - inlier_after) / inlier_before)
        if inlier_before > 1e-9
        else 0.0
    )
    reduction_ratio = (
        max(assign_reduction, inlier_reduction)
        if (effective_support_ratio >= MIN_TRANSLATION_SUPPORT_RATIO or majority_len)
        else assign_reduction
    )

    rejection_reason = None
    if support_count < MIN_TRANSLATION_SUPPORT:
        rejection_reason = "insufficient_support"
    elif effective_support_ratio < MIN_TRANSLATION_SUPPORT_RATIO:
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
        "length_support_ratio": round(length_ratio, GEOMETRY_PRECISION),
        "confidence": _normalization_confidence(support_count, effective_support_ratio),
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
    length_support_ratio: float = 0.0,
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
        "length_support_ratio": round(float(length_support_ratio), GEOMETRY_PRECISION),
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

def _compatible(a: Entity, b: Entity, *, exact_kind: bool = False) -> bool:
    if a.kind == b.kind:
        return True
    if exact_kind:
        return False
    return {a.kind, b.kind} <= {"line", "polyline"}


def _polyline_curve_centroid(points: list[tuple[float, float]], *, closed: bool) -> tuple[float, float]:
    n = len(points)
    if n <= 1:
        return (float(points[0][0]), float(points[0][1])) if points else (0.0, 0.0)
    num_segs = n if closed else n - 1
    total_len = 0.0
    cx, cy = 0.0, 0.0
    for i in range(num_segs):
        p1 = points[i]
        p2 = points[(i + 1) % n]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        total_len += seg_len
        cx += seg_len * (p1[0] + p2[0]) / 2.0
        cy += seg_len * (p1[1] + p2[1]) / 2.0
    if total_len > 1e-9:
        return (cx / total_len, cy / total_len)
    return (float(points[0][0]), float(points[0][1]))


def _polyline_characteristic_radius(points: list[tuple[float, float]]) -> float:
    if not points:
        return 1e-9
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    return max(diag / 2.0, 1e-9)


def _intrinsic_match_quality(reference_entity: Entity, student_entity: Entity) -> float:
    if reference_entity.kind != student_entity.kind:
        return 0.0

    layer_sim = 1.0 if reference_entity.layer == student_entity.layer else 0.85

    if reference_entity.kind == "line":
        lr = entity_length(reference_entity)
        ls = entity_length(student_entity)
        len_sim = max(0.0, 1.0 - abs((lr or 0.0) - (ls or 0.0)) / max(lr or 0.0, ls or 0.0, 1e-9))
        ar = _angle(reference_entity)
        as_ = _angle(student_entity)
        if ar is not None and as_ is not None:
            delta = _angle_delta(ar, as_)
            ang_sim = max(0.0, 1.0 - delta / 90.0)
        else:
            ang_sim = 1.0
        return len_sim * ang_sim * layer_sim

    if reference_entity.kind == "circle":
        rr = reference_entity.radius or 0.0
        rs = student_entity.radius or 0.0
        rad_sim = max(0.0, 1.0 - abs(rr - rs) / max(rr, rs, 1e-9))
        return rad_sim * layer_sim

    if reference_entity.kind == "arc":
        rr = reference_entity.radius or 0.0
        rs = student_entity.radius or 0.0
        rad_sim = max(0.0, 1.0 - abs(rr - rs) / max(rr, rs, 1e-9))

        ref_span = ((reference_entity.end_angle or 0.0) - (reference_entity.start_angle or 0.0)) % 360.0
        if ref_span == 0.0:
            ref_span = 360.0
        stu_span = ((student_entity.end_angle or 0.0) - (student_entity.start_angle or 0.0)) % 360.0
        if stu_span == 0.0:
            stu_span = 360.0
        span_delta = abs(ref_span - stu_span)
        span_sim = max(0.0, 1.0 - span_delta / 360.0)

        if reference_entity.start_angle is not None and student_entity.start_angle is not None:
            start_delta = abs((reference_entity.start_angle - student_entity.start_angle) % 360.0)
            start_delta = min(start_delta, 360.0 - start_delta)
            ang_sim = max(0.0, 1.0 - start_delta / 180.0)
        else:
            ang_sim = 1.0

        return rad_sim * span_sim * ang_sim * layer_sim

    if reference_entity.kind == "spline":
        closed_sim = 1.0 if reference_entity.closed == student_entity.closed else 0.5
        lr = entity_length(reference_entity)
        ls = entity_length(student_entity)
        len_sim = max(0.0, 1.0 - abs((lr or 0.0) - (ls or 0.0)) / max(lr or 0.0, ls or 0.0, 1e-9))
        vr = len(reference_entity.points)
        vs = len(student_entity.points)
        pts_sim = max(0.0, 1.0 - abs(vr - vs) / max(vr, vs, 1))
        return len_sim * pts_sim * closed_sim * layer_sim

    if reference_entity.kind == "polyline":
        closed_sim = 1.0 if reference_entity.closed == student_entity.closed else 0.5
        lr = entity_length(reference_entity)
        ls = entity_length(student_entity)
        len_sim = max(0.0, 1.0 - abs((lr or 0.0) - (ls or 0.0)) / max(lr or 0.0, ls or 0.0, 1e-9))
        vr = len(reference_entity.points)
        vs = len(student_entity.points)

        if vr == 2 and vs == 2 and not reference_entity.closed and not student_entity.closed:
            ar = _angle(reference_entity)
            as_ = _angle(student_entity)
            if ar is not None and as_ is not None:
                ang_sim = max(0.0, 1.0 - _angle_delta(ar, as_) / 90.0)
            else:
                ang_sim = 1.0
            return len_sim * ang_sim * layer_sim * closed_sim

        if vr >= 2 and vs >= 2:
            c_r = _polyline_curve_centroid(reference_entity.points, closed=reference_entity.closed)
            c_s = _polyline_curve_centroid(student_entity.points, closed=student_entity.closed)
            r_ring = (
                (reference_entity.points + [reference_entity.points[0]])
                if reference_entity.closed and reference_entity.points[0] != reference_entity.points[-1]
                else list(reference_entity.points)
            )
            s_ring = (
                (student_entity.points + [student_entity.points[0]])
                if student_entity.closed and student_entity.points[0] != student_entity.points[-1]
                else list(student_entity.points)
            )
            r_c = [(p[0] - c_r[0], p[1] - c_r[1]) for p in r_ring]
            s_c = [(p[0] - c_s[0], p[1] - c_s[1]) for p in s_ring]
            try:
                ls_r = LineString(r_c)
                ls_s = LineString(s_c)
                hausdorff = float(ls_r.hausdorff_distance(ls_s))
            except Exception:
                hausdorff = float("inf")
            rad_r = _polyline_characteristic_radius(reference_entity.points)
            rad_s = _polyline_characteristic_radius(student_entity.points)
            char_rad = max(rad_r, rad_s, 1e-9)
            shape_sim = max(0.0, 1.0 - hausdorff / char_rad)
            return len_sim * shape_sim * closed_sim * layer_sim

        pts_sim = 1.0 if vr == vs else 0.0
        return len_sim * pts_sim * closed_sim * layer_sim

    if reference_entity.kind == "text":
        text_sim = 1.0 if reference_entity.text == student_entity.text else 0.0
        return text_sim * layer_sim

    if reference_entity.kind == "dimension":
        rm = reference_entity.measurement
        sm = student_entity.measurement
        if rm is not None and sm is not None:
            meas_sim = max(0.0, 1.0 - abs(rm - sm) / max(abs(rm), abs(sm), 1e-9))
        else:
            meas_sim = 1.0 if rm == sm else 0.5
        return meas_sim * layer_sim

    lr = entity_length(reference_entity)
    ls = entity_length(student_entity)
    len_sim = max(0.0, 1.0 - abs((lr or 0.0) - (ls or 0.0)) / max(lr or 0.0, ls or 0.0, 1e-9))
    return len_sim * layer_sim


def _candidate_cost(reference: Entity, student: Entity, *, ignore_position: bool = False) -> float:
    distance = _distance(reference, student)
    lr, ls = entity_length(reference), entity_length(student)
    angle = (
        _angle_delta(_angle(reference), _angle(student))
        if _angle(reference) is not None and _angle(student) is not None
        else 0
    )
    radius = abs((reference.radius or 0) - (student.radius or 0))
    if ignore_position:
        size = 0.0 if reference.kind in {"circle", "arc"} else abs((lr or 0) - (ls or 0))
        layer_penalty = 0.0 if reference.layer == student.layer else 5.0
        return size * 0.35 + angle * 0.08 + radius * 0.5 + layer_penalty + min(distance * 0.001, 1.0)
    size = abs((lr or 0) - (ls or 0))
    return distance + size * 0.35 + angle * 0.08 + radius * 0.5


def _match_entities(
    reference: Drawing,
    student: Drawing,
    tolerance: ToleranceProfile,
    *,
    mode: str = "strict",
):
    exact_pairs = _exact_entity_pairs(reference, student)
    used_r = {reference_entity.id for reference_entity, _ in exact_pairs}
    used_s = {student_entity.id for _, student_entity in exact_pairs}
    match_qualities: dict[str, float] = {}
    for r, s in exact_pairs:
        match_qualities[r.id] = 1.0
    matched = [
        (reference_entity, student_entity, 1.0)
        for reference_entity, student_entity in exact_pairs
    ]
    extent = max(
        reference.bbox[2] - reference.bbox[0],
        reference.bbox[3] - reference.bbox[1],
        1,
    )
    prec = 4 if mode == "translation" else GEOMETRY_PRECISION
    intrinsic_pairs = _intrinsic_entity_pairs(
        [entity for entity in reference.entities if entity.id not in used_r],
        [entity for entity in student.entities if entity.id not in used_s],
        precision=prec,
    )
    ignore_pos = (mode == "translation")
    for reference_entity, student_entity in intrinsic_pairs:
        used_r.add(reference_entity.id)
        used_s.add(student_entity.id)
        if ignore_pos:
            confidence = 1.0
            match_qualities[reference_entity.id] = 1.0
        else:
            cost = _candidate_cost(reference_entity, student_entity, ignore_position=False)
            confidence = max(0.0, min(1.0, 1 - cost / (extent + 1)))
            match_qualities[reference_entity.id] = confidence
        matched.append((reference_entity, student_entity, confidence))
    pairs = sorted(
        (
            (
                _candidate_cost(reference_entity, student_entity, ignore_position=ignore_pos),
                _geometry_signature(reference_entity, relative=False, precision=prec),
                _geometry_signature(student_entity, relative=False, precision=prec),
                reference_entity,
                student_entity,
            )
            for reference_entity in reference.entities
            for student_entity in student.entities
            if reference_entity.id not in used_r
            and student_entity.id not in used_s
            and _compatible(reference_entity, student_entity, exact_kind=ignore_pos)
        ),
        key=lambda item: (item[0], repr(item[1]), repr(item[2]), item[3].id, item[4].id),
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
        if ignore_pos:
            plausible = True
            if reference_entity.kind in {"line", "polyline"}:
                angle_diff = (
                    _angle_delta(_angle(reference_entity), _angle(student_entity))
                    if _angle(reference_entity) is not None and _angle(student_entity) is not None
                    else 0.0
                )
                plausible = (
                    length_delta <= max(
                        tolerance.length * 5,
                        (entity_length(reference_entity) or 0) * 0.6,
                    )
                    and angle_diff <= 60.0
                )
            elif reference_entity.kind in {"circle", "arc"}:
                rad_delta = abs((reference_entity.radius or 0) - (student_entity.radius or 0))
                plausible = rad_delta <= max(
                    tolerance.radius * 5,
                    (reference_entity.radius or 0) * 0.6,
                )
                if plausible and reference_entity.kind == "arc":
                    ref_span = ((reference_entity.end_angle or 0.0) - (reference_entity.start_angle or 0.0)) % 360.0
                    if ref_span == 0.0:
                        ref_span = 360.0
                    stu_span = ((student_entity.end_angle or 0.0) - (student_entity.start_angle or 0.0)) % 360.0
                    if stu_span == 0.0:
                        stu_span = 360.0
                    span_delta = abs(ref_span - stu_span)
                    plausible = (span_delta <= 60.0 or span_delta >= 300.0)
            elif reference_entity.kind == "dimension":
                rm = reference_entity.measurement or 0.0
                sm = student_entity.measurement or 0.0
                plausible = abs(rm - sm) <= max(tolerance.dimension * 5, abs(rm) * 0.6)
        else:
            plausible = distance <= threshold or (
                reference_entity.kind in {"line", "polyline"}
                and distance <= max(threshold, length_delta + tolerance.position)
            )
        if plausible:
            used_r.add(reference_entity.id)
            used_s.add(student_entity.id)
            if ignore_pos:
                quality = _intrinsic_match_quality(reference_entity, student_entity)
                match_qual = round(max(0.0, min(1.0, quality)), 3)
                match_qualities[reference_entity.id] = match_qual
                confidence = round(max(0.60, min(1.0, 0.60 + 0.40 * match_qual)), 3)
            else:
                confidence = max(0.0, min(1.0, 1 - cost / (extent + 1)))
                match_qualities[reference_entity.id] = confidence
            matched.append((reference_entity, student_entity, confidence))
    reference_order = {
        entity.id: index for index, entity in enumerate(reference.entities)
    }
    matched.sort(key=lambda item: (reference_order[item[0].id], item[1].id))
    missing = [entity for entity in reference.entities if entity.id not in used_r]
    extra = [entity for entity in student.entities if entity.id not in used_s]
    return matched, missing, extra, match_qualities


def _prepare_comparison_geometry(
    reference: Drawing,
    student: Drawing,
    rubric: Rubric,
    tolerance: ToleranceProfile,
) -> tuple[Drawing, dict[str, Any], dict[str, Any]]:
    mode = rubric.normalization_mode
    use_canonical = (
        rubric.rubric_version == "2.0"
        or rubric.completion_scoring_mode == "object_part_deduction"
    )
    if mode == "strict":
        estimate = _estimate_translation(
            reference, student, tolerance, use_canonical=use_canonical
        )
        robust = (
            bool(estimate["selected_translation"] != (0.0, 0.0))
            and estimate["support_count"] >= MIN_GLOBAL_TRANSLATION_SUPPORT
            and estimate["support_ratio"] >= MIN_GLOBAL_TRANSLATION_SUPPORT_RATIO
        )
        matching_translation = (
            tuple(estimate["selected_translation"])
            if robust
            else (0.0, 0.0)
        )
        displacement = (-matching_translation[0], -matching_translation[1])
        magnitude = math.dist(displacement, (0.0, 0.0))
        strict_record = _normalization_record(
            "strict",
            (0.0, 0.0),
            candidate=estimate["candidate_translation"],
            support_count=estimate["support_count"],
            support_ratio=estimate["support_ratio"],
            confidence=estimate["confidence"],
            rejection_reason=(
                "strict_mode_disallows_transform"
                if robust
                else "strict_mode"
            ),
            error_before=estimate["error_before"],
            error_after=estimate["error_after"],
            error_reduction_ratio=estimate["error_reduction_ratio"],
            evidence_count=estimate["evidence_count"],
        )
        strict_record["matching_translation"] = list(matching_translation)
        strict_record["global_displacement"] = {
            "detected": robust,
            "displacement_x": _rounded(displacement[0]),
            "displacement_y": _rounded(displacement[1]),
            "magnitude": _rounded(magnitude),
            "support_count": estimate["support_count"],
            "evidence_count": estimate["evidence_count"],
            "support_ratio": estimate["support_ratio"],
            "position_tolerance": float(tolerance.position),
            "displacement_to_tolerance_ratio": _rounded(
                magnitude / max(float(tolerance.position), 1e-9)
            ),
        }
        return (
            _translated_drawing(student, matching_translation, strict_record),
            deepcopy(strict_record),
            deepcopy(strict_record),
        )
    if mode != "translation":
        raise ValueError(f"normalization mode '{mode}' is not implemented")

    estimate = _estimate_translation(
        reference, student, tolerance, use_canonical=use_canonical
    )
    reference_record = _normalization_record(
        "translation",
        (0.0, 0.0),
        support_count=estimate["support_count"],
        support_ratio=estimate["support_ratio"],
        length_support_ratio=estimate.get("length_support_ratio", 0.0),
        confidence="reference_anchor",
        evidence_count=estimate["evidence_count"],
    )
    student_record = _normalization_record(
        "translation",
        estimate["selected_translation"],
        candidate=estimate["candidate_translation"],
        support_count=estimate["support_count"],
        support_ratio=estimate["support_ratio"],
        length_support_ratio=estimate.get("length_support_ratio", 0.0),
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
        return {
            "missing_geometry": "MISSING_WALL",
            "extra_geometry": "EXTRA_WALL",
        }.get(category, "WALL_GEOMETRY")
    if "door" in layer:
        return "DOOR_SWING"
    if "window" in layer:
        return "WINDOW_GEOMETRY"
    if (ref or stu) and (ref or stu).kind == "dimension":
        return "DIMENSION"
    return category.upper()


def compare_drawings(
    reference: Drawing,
    student: Drawing,
    t: Tolerances | None = None,
    rubric: Rubric | dict | None = None,
    confirmed_objects: list[dict[str, Any]] | None = None,
):
    if rubric is None:
        rubric = default_rubric().model_copy(update={"approved": True})
    elif not isinstance(rubric, Rubric):
        raise TypeError("rubric must be a validated Rubric instance")
    elif not rubric.approved:
        raise ValueError("grading requires an approved rubric")
    if t:
        rubric.tolerances = ToleranceProfile(
            position=t.position,
            length=t.length,
            angle=t.angle,
            radius=t.radius,
            dimension=t.dimension,
            vertex=t.position,
        )
    tolerance = rubric.tolerances
    rules = rubric_rule_map(rubric)
    (
        matching_student,
        reference_normalization,
        student_normalization,
    ) = _prepare_comparison_geometry(reference, student, rubric, tolerance)

    is_canonical_mode = (
        rubric.rubric_version in {"2.0", "2.1"}
        or rubric.completion_scoring_mode == "object_part_deduction"
        or getattr(rubric, "assignment_type", None) in SUPPORTED_CANONICAL_ASSIGNMENT_TYPES
    )
    is_object_part_mode = (
        rubric.completion_scoring_mode == "object_part_deduction"
    )
    legacy_tolerant_placement = (
        rubric.normalization_mode == "translation"
        and getattr(rubric, "rubric_source", None) != "explicit_fallback"
        and not is_canonical_mode
    )
    matching_mode = "translation" if legacy_tolerant_placement else "strict"
    matched, missing, extra, match_qualities = _match_entities(
        reference, matching_student, tolerance, mode=matching_mode
    )
    canonical_match = match_canonical_geometry(
        reference,
        matching_student,
        tolerance,
        confirmed_objects=confirmed_objects
        or getattr(rubric, "confirmed_objects", None),
        normalization_mode=rubric.normalization_mode,
    )

    ref_comp_presence: dict[str, float] = {}
    ref_comp_counts: dict[str, int] = {}
    for cm in canonical_match.component_matches:
        c = cm.reference_component
        src_ids = c.source_entity_ids or [c.source_entity_id]
        for r_id in src_ids:
            ref_comp_presence[r_id] = (
                ref_comp_presence.get(r_id, 0.0) + cm.presence
            )
            ref_comp_counts[r_id] = ref_comp_counts.get(r_id, 0) + 1

    fully_drawn_ref_ids = {
        r.id
        for r in reference.entities
        if ref_comp_counts.get(r.id, 0) > 0
        and ref_comp_presence.get(r.id, 0.0) >= ref_comp_counts[r.id] - 1e-4
    }
    fully_correct_canonical_refs = {
        r_id
        for r_id, count in ref_comp_counts.items()
        if count > 0
        and ref_comp_presence.get(r_id, 0.0) >= count - 1e-4
        and all(
            cm.correctness >= 1.0 - 1e-4 and not cm.errors
            for cm in canonical_match.component_matches
            if r_id
            in (
                cm.reference_component.source_entity_ids
                or [cm.reference_component.source_entity_id]
            )
        )
    }
    stu_comp_presence: dict[str, float] = {}
    stu_comp_counts: dict[str, int] = {}
    for cm in canonical_match.component_matches:
        for sc in cm.student_components:
            src_ids = sc.source_entity_ids or [sc.source_entity_id]
            for s_id in src_ids:
                if s_id:
                    stu_comp_presence[s_id] = stu_comp_presence.get(s_id, 0.0) + cm.presence
                    stu_comp_counts[s_id] = stu_comp_counts.get(s_id, 0) + 1

    fully_drawn_stu_ids = {
        s.id
        for s in matching_student.entities
        if stu_comp_counts.get(s.id, 0) > 0
        and stu_comp_presence.get(s.id, 0.0) >= stu_comp_counts[s.id] - 1e-4
    }

    has_cross_rep = is_canonical_mode and (
        any(r.kind != s.kind for r, s, _ in matched)
        or (
            bool(fully_drawn_ref_ids)
            and any(e.id in fully_drawn_ref_ids for e in missing)
            and {e.kind for e in reference.entities}
            != {e.kind for e in matching_student.entities}
        )
    )
    use_canonical_reconciliation = is_canonical_mode

    if use_canonical_reconciliation:
        canonical_matched_ref_ids = {
            r_eid
            for cm in canonical_match.component_matches
            if cm.presence > 0.0
            for r_eid in (cm.reference_component.source_entity_ids or [cm.reference_component.source_entity_id])
            if r_eid
        }
        canonical_matched_stu_ids = {
            s_eid
            for cm in canonical_match.component_matches
            if cm.presence > 0.0
            for sc in cm.student_components
            for s_eid in (sc.source_entity_ids or [sc.source_entity_id])
            if s_eid
        }
        ambiguous_stu_eids = {
            eid
            for grp in getattr(canonical_match, "ambiguous_groups", [])
            for eid in grp.get("candidate_student_entity_ids", [])
        }
        ambiguous_ref_eids = {
            eid
            for grp in getattr(canonical_match, "ambiguous_groups", [])
            for eid in grp.get("reference_entity_ids", [])
        }
        canonical_extra_ids = (
            set(canonical_match.extra_student_entities)
            - set(canonical_match.duplicate_student_entities)
            - fully_drawn_stu_ids
            - canonical_matched_stu_ids
            - ambiguous_stu_eids
        )
        extra = [
            entity
            for entity in matching_student.entities
            if entity.id in canonical_extra_ids
        ]
        missing = [
            entity for entity in missing
            if entity.id not in fully_drawn_ref_ids
            and entity.id not in canonical_matched_ref_ids
            and entity.id not in ambiguous_ref_eids
        ]
        analysis_matched = []
        composite_polyline_open_boundaries = []
        for r, s, conf in matched:
            if r.kind != s.kind:
                continue
            r_stu_comps = [
                sc
                for cm in canonical_match.component_matches
                if r.id in (cm.reference_component.source_entity_ids or [cm.reference_component.source_entity_id])
                for sc in cm.student_components
            ]
            s_ref_comps = [
                cm.reference_component
                for cm in canonical_match.component_matches
                if any(s.id in (sc.source_entity_ids or [sc.source_entity_id]) for sc in cm.student_components)
            ]
            is_canonical_pair = any(
                s.id in (sc.source_entity_ids or [sc.source_entity_id])
                for sc in r_stu_comps
            )
            if not is_canonical_pair:
                continue
            ref_sources = {
                eid
                for rc in s_ref_comps
                for eid in (rc.source_entity_ids or [rc.source_entity_id])
                if eid
            }
            stu_sources = {
                eid
                for sc in r_stu_comps
                for eid in (sc.source_entity_ids or [sc.source_entity_id])
                if eid
            }
            is_composite = (
                len(ref_sources) > 1
                or len(stu_sources) > 1
                or len(r_stu_comps) > 1
                or len(s_ref_comps) > 1
                or ref_comp_counts.get(r.id, 0) > 1
                or stu_comp_counts.get(s.id, 0) > 1
            )
            effective_conf = next(
                (
                    1.0 if cm.correctness >= 1.0 - 1e-4 else 0.85
                    for cm in canonical_match.component_matches
                    if r.id in (cm.reference_component.source_entity_ids or [cm.reference_component.source_entity_id])
                    and any(s.id in (sc.source_entity_ids or [sc.source_entity_id]) for sc in cm.student_components)
                ),
                conf,
            )
            # If either entity participates in segmented / composite / junction correspondence, skip 1-to-1 entity length check
            if is_composite:
                if r.kind == "polyline" and s.kind == "polyline" and r.closed and not s.closed:
                    composite_polyline_open_boundaries.append((r, s, effective_conf))
                continue
            if r.id in fully_correct_canonical_refs:
                if len(r_stu_comps) == 1 and len(s_ref_comps) == 1 and r.kind != "polyline":
                    analysis_matched.append((r, s, effective_conf))
            else:
                analysis_matched.append((r, s, effective_conf))
    else:
        analysis_matched = matched
        composite_polyline_open_boundaries = []

    analysis = analyze_comparison(
        reference,
        matching_student,
        analysis_matched,
        missing,
        extra,
        tolerance,
    )

    for r, s, eff_conf in composite_polyline_open_boundaries:
        unit = reference.units
        closed_obs = analysis.observe(
            "closed",
            True,
            False,
            0,
            unit,
            r,
            s,
        )
        conf_label = "verified" if eff_conf >= 0.85 else ("high" if eff_conf >= 0.55 else "moderate")
        analysis.findings.append(
            CausalFinding(
                "open_polyline",
                r,
                s,
                {
                    k: v
                    for k, v in closed_obs.items()
                    if k in {"property", "expected", "actual", "deviation", "tolerance", "unit"}
                },
                True,
                False,
                conf_label,
            )
        )

    ref_entity_to_obj: dict[str, str] = {}
    ref_entity_to_comp: dict[str, list] = {}
    if canonical_match and canonical_match.reference_objects:
        for obj in canonical_match.reference_objects:
            for c in obj.components:
                for eid in c.source_entity_ids or [c.source_entity_id]:
                    ref_entity_to_obj[eid] = obj.object_id
                    ref_entity_to_comp.setdefault(eid, []).append(c)

    objs_with_missing_parts: set[str] = {
        mc.parent_object_id
        for mc in canonical_match.missing_components
        if mc.parent_object_id
    }
    objs_with_endpoint_gaps: set[str] = {
        cm.reference_component.parent_object_id
        for cm in canonical_match.component_matches
        if cm.reference_component.parent_object_id
        and any(e["category"] == "endpoint_gap" for e in cm.errors)
    }

    issues: list[Issue] = []

    def add(finding: CausalFinding) -> None:
        rule_pair = rules.get(finding.category)
        if rule_pair:
            rule, _ = rule_pair
            deduction = rule.deduction
            severity = rule.severity
            rule_id = rule.id
        else:
            deduction = 0.0
            severity = "warning"
            rule_id = None

        reference_entity = finding.reference_entity
        student_entity = finding.student_entity
        location_entity = student_entity if finding.category == "incorrect_position" else (reference_entity or student_entity)
        location = finding.location or (
            _center(location_entity) if location_entity is not None else None
        )
        measurement = deepcopy(finding.measurement)
        action = {
            "missing_geometry": "Add the required geometry at the ghosted location.",
            "extra_geometry": "Remove the unmatched construction geometry if it is not an accepted alternative.",
            "incorrect_position": "Move the entity toward the expected location.",
            "incorrect_length": "Adjust the entity length to the expected value.",
            "incorrect_angle": "Rotate the entity to the expected angle.",
            "incorrect_radius": "Change the entity to the expected radius.",
            "incorrect_shape": "Edit the vertices or curve so it follows the reference ghost.",
            "open_polyline": "Close the required boundary.",
            "duplicate_geometry": "Remove the coincident duplicate entity.",
            "unsupported_entity": "Review this unsupported entity manually.",
            "endpoint_gap": "Restore the expected endpoint connection at this junction.",
        }.get(finding.category, "Review this finding.")
        if (
            finding.category
            in {"incorrect_length", "incorrect_angle", "incorrect_radius"}
            and isinstance(finding.expected, (int, float))
            and isinstance(finding.actual, (int, float))
        ):
            labels = {
                "incorrect_length": ("length", ""),
                "incorrect_angle": ("angle", " degrees"),
                "incorrect_radius": ("radius", ""),
            }
            label, suffix = labels[finding.category]
            action = (
                f"Adjust the {label} from {finding.actual:.3f}{suffix} "
                f"to {finding.expected:.3f}{suffix}."
            )
        elif (
            finding.category == "incorrect_position"
            and measurement is not None
            and isinstance(measurement.get("actual"), (int, float))
        ):
            action = (
                f"Move the entity by {abs(measurement['actual']):.3f} "
                "drawing units toward the expected location."
            )

        ref_id = reference_entity.id if reference_entity else None
        parent_obj_id = ref_entity_to_obj.get(ref_id) if ref_id else None
        components = ref_entity_to_comp.get(ref_id, []) if ref_id else []
        candidates = (
            [
                cm.reference_component
                for cm in canonical_match.component_matches
                if cm.reference_component in components
                and (cm.presence < 1 or cm.correctness < 1)
            ]
            if canonical_match
            else []
        )
        components = candidates or components
        selected_component = (
            min(components, key=lambda c: math.dist(c.centroid, location))
            if components and location
            else (components[0] if len(components) == 1 else None)
        )
        comp_id = selected_component.id if selected_component else None
        if selected_component:
            parent_obj_id = selected_component.parent_object_id

        issues.append(
            Issue(
                id=finding.issue_id or f"E-{len(issues) + 1:03d}",
                category=finding.category,
                code=_legacy_code(
                    finding.category, reference_entity, student_entity
                ),
                severity=severity,
                confidence=finding.confidence,
                classification=finding.classification,
                deduction=deduction,
                reference_entity_id=(
                    reference_entity.id if reference_entity else None
                ),
                student_entity_id=(
                    student_entity.id if student_entity else None
                ),
                parent_object_id=parent_obj_id,
                component_id=comp_id,
                location=location,
                measurement=measurement,
                rubric_rule_id=rule_id,
                technical_feedback=action,
                recommended_commands=[],
                expected=finding.expected,
                actual=finding.actual,
                derived_evidence=deepcopy(finding.derived_evidence),
                supporting_evidence=deepcopy(finding.supporting_evidence),
                suppressed_findings=deepcopy(finding.suppressed_findings),
                message=action,
            )
        )

    for finding in analysis.findings:
        if is_canonical_mode and finding.category == "missing_geometry":
            continue
        ref_id = (
            finding.reference_entity.id
            if finding.reference_entity
            else None
        )
        ref_obj_id = ref_entity_to_obj.get(ref_id) if ref_id else None
        obj_t = (
            canonical_match.object_translations.get(ref_obj_id)
            if canonical_match and ref_obj_id
            else None
        )
        is_obj_translated = (
            is_canonical_mode
            and getattr(rubric, "normalization_mode", "strict") == "translation"
            and obj_t is not None
            and math.hypot(obj_t[0], obj_t[1]) > tolerance.position
        )
        is_mixed_comp = (
            getattr(rubric, "assignment_type", None) == "Mixed Geometric Composition"
        )
        global_trans = tuple(student_normalization.get("translation", [0.0, 0.0]))
        is_global_accepted = (
            student_normalization.get("rejection_reason") is None
            and student_normalization.get("confidence") in {"high", "verified", "reference_anchor"}
        )
        matches_global = (
            is_global_accepted
            and obj_t is not None
            and math.hypot(obj_t[0] - global_trans[0], obj_t[1] - global_trans[1]) <= tolerance.position
        )
        is_local_movement = is_obj_translated and not matches_global
        should_suppress_pos = False
        if legacy_tolerant_placement:
            should_suppress_pos = True
        elif is_obj_translated:
            should_suppress_pos = True

        if should_suppress_pos and finding.category == "incorrect_position":
            analysis.suppressed_findings.append(
                {
                    "category": "incorrect_position",
                    "classification": "suppressed",
                    "reference_entity_id": ref_id,
                    "student_entity_id": (
                        finding.student_entity.id
                        if finding.student_entity
                        else None
                    ),
                    "primary_category": "translation_tolerant_placement",
                    "suppression_reason": "canonical_object_translation" if is_obj_translated else "translation_tolerant_mode",
                    "observation": finding.measurement,
                }
            )
            continue
        if is_canonical_mode and finding.category in {
            "open_polyline",
            "endpoint_gap",
            "disconnected_geometry",
        }:
            ref_id = (
                finding.reference_entity.id
                if finding.reference_entity
                else None
            )
            ref_obj_id = ref_entity_to_obj.get(ref_id) if ref_id else None
            if ref_obj_id and ref_obj_id in objs_with_missing_parts:
                analysis.suppressed_findings.append(
                    {
                        "category": finding.category,
                        "classification": "suppressed",
                        "reference_entity_id": ref_id,
                        "student_entity_id": (
                            finding.student_entity.id
                            if finding.student_entity
                            else None
                        ),
                        "primary_category": "missing_geometry",
                        "suppression_reason": "consequence_of_missing_part",
                        "observation": finding.measurement,
                    }
                )
                continue
            if (
                finding.category == "open_polyline"
                and rubric.construction_requirement == "geometry_only"
                and ref_obj_id
                and ref_obj_id not in objs_with_missing_parts
                and ref_obj_id not in objs_with_endpoint_gaps
            ):
                analysis.suppressed_findings.append(
                    {
                        "category": "open_polyline",
                        "classification": "suppressed",
                        "reference_entity_id": ref_id,
                        "student_entity_id": (
                            finding.student_entity.id
                            if finding.student_entity
                            else None
                        ),
                        "primary_category": "construction_representation",
                        "suppression_reason": "geometry_only_construction_policy",
                        "observation": finding.measurement,
                    }
                )
                continue
        add(finding)

    reference_by_id = {entity.id: entity for entity in reference.entities}
    student_by_id = {entity.id: entity for entity in matching_student.entities}

    if is_object_part_mode:
        w_geom = next(
            (c.weight for c in rubric.categories if c.id == "geometry"), 65.0
        )
        w_comp = next(
            (c.weight for c in rubric.categories if c.id == "completion"), 25.0
        )
        w_content = float(w_geom) + float(w_comp)
        rule_pair = rules.get("missing_geometry")
        rule_id = rule_pair[0].id if rule_pair else "RULE-MISSING-01"

        for obj in canonical_match.reference_objects:
            obj_cms = [
                cm
                for cm in canonical_match.component_matches
                if cm.reference_component.parent_object_id == obj.object_id
            ]
            total_parts = len(obj_cms)
            missing_cms = [cm for cm in obj_cms if cm.presence == 0.0]
            missing_count = len(missing_cms)
            if total_parts == 0 or missing_count == 0:
                continue

            if missing_count == total_parts:
                obj_budget = round(float(obj.weight) * w_content, 2)
                issues.append(
                    Issue(
                        id=f"ISSUE-{obj.object_id}",
                        category="missing_geometry",
                        code="MISSING_OBJECT",
                        severity="major",
                        confidence="verified",
                        classification="primary",
                        deduction=obj_budget,
                        parent_object_id=obj.object_id,
                        component_id=None,
                        location=obj.centroid,
                        measurement={
                            "object_id": obj.object_id,
                            "missing_part_count": missing_count,
                            "total_part_count": total_parts,
                            "missing_component_ids": [
                                cm.reference_component.id for cm in missing_cms
                            ],
                            "source_entity_ids": list(obj.source_entity_ids),
                        },
                        supporting_evidence=[
                            {
                                "component_id": cm.reference_component.id,
                                "kind": cm.reference_component.kind,
                                "length": round(
                                    cm.reference_component.length, 4
                                ),
                                "reference_entity_id": cm.reference_component.source_entity_id,
                            }
                            for cm in missing_cms
                        ],
                        technical_feedback=(
                            f"Missing required object {obj.object_id} "
                            f"({missing_count}/{total_parts} required parts absent)."
                        ),
                        message=f"Add the missing required object {obj.object_id} at the reference location.",
                        reference_entity_id=(
                            obj.source_entity_ids[0]
                            if obj.source_entity_ids
                            else None
                        ),
                        rubric_rule_id=rule_id,
                    )
                )
            else:
                for cm in missing_cms:
                    mc = cm.reference_component
                    derived_ev = (
                        [
                            {
                                "observation": "open_boundary",
                                "reason": "consequence_of_missing_part",
                                "object_id": obj.object_id,
                            }
                        ]
                        if obj.is_closed
                        else []
                    )
                    issues.append(
                        Issue(
                            id=f"ISSUE-{mc.id}",
                            category="missing_geometry",
                            code="MISSING_PART",
                            severity="minor",
                            confidence="verified",
                            classification="primary",
                            deduction=float(rubric.missing_part_deduction),
                            parent_object_id=obj.object_id,
                            component_id=mc.id,
                            location=mc.centroid,
                            measurement={
                                "object_id": obj.object_id,
                                "component_id": mc.id,
                                "kind": mc.kind,
                                "length": round(mc.length, 4),
                                "missing_part_count": missing_count,
                                "total_part_count": total_parts,
                            },
                            derived_evidence=derived_ev,
                            technical_feedback=(
                                f"Missing required part {mc.id} of object {obj.object_id} "
                                f"({mc.kind} of length {round(mc.length, 2)})."
                            ),
                            message=f"Add the missing {mc.kind} part ({mc.id}) to complete object {obj.object_id}.",
                            reference_entity_id=mc.source_entity_id,
                            rubric_rule_id=rule_id,
                        )
                    )
    elif is_canonical_mode:
        for mc in canonical_match.missing_components:
            rule_pair = rules.get("missing_geometry")
            rule, _ = rule_pair if rule_pair else (None, None)
            ded = rule.deduction if rule else 5.0
            rule_id = rule.id if rule else None
            ref_ent = reference_by_id.get(mc.source_entity_id)
            code = _legacy_code("missing_geometry", ref_ent, None)
            issues.append(
                Issue(
                    id=f"ISSUE-{mc.id}",
                    category="missing_geometry",
                    code=code,
                    severity="major",
                    confidence="verified",
                    classification="primary",
                    deduction=ded,
                    parent_object_id=mc.parent_object_id,
                    component_id=mc.id,
                    location=mc.centroid,
                    measurement=None,
                    expected=None,
                    actual=None,
                    technical_feedback=(
                        f"Missing required reference geometry ({mc.kind} of length {round(mc.length, 2)})."
                    ),
                    message="Add the required geometry at the reference location.",
                    reference_entity_id=mc.source_entity_id,
                    rubric_rule_id=rule_id,
                )
            )

    if use_canonical_reconciliation:
        # Emit component-level geometric/connectivity errors not already emitted by entity-level analysis
        for cm in canonical_match.component_matches:
            if cm.presence <= 0.0 or not cm.errors:
                continue
            rc = cm.reference_component
            for err in cm.errors:
                cat = err["category"]
                stu_eid = err.get("student_entity_id")
                already_present = any(
                    i.category == cat
                    and (
                        i.component_id == rc.id
                        or (
                            i.reference_entity_id == rc.source_entity_id
                            and i.student_entity_id == stu_eid
                        )
                    )
                    for i in issues
                )
                if already_present:
                    continue
                if cat == "incorrect_length":
                    rc_eids = rc.source_entity_ids or ([rc.source_entity_id] if rc.source_entity_id else [])
                    if rc_eids:
                        all_sources_exact = True
                        for eid in rc_eids:
                            m_match = next(((r, s, c) for r, s, c in matched if r.id == eid), None)
                            if not m_match:
                                all_sources_exact = False
                                break
                            r_ent, s_ent, m_conf = m_match
                            if m_conf < 0.85:
                                all_sources_exact = False
                                break
                            r_l = entity_length(r_ent)
                            s_l = entity_length(s_ent)
                            if r_l is None or s_l is None or abs(r_l - s_l) > tolerance.length:
                                all_sources_exact = False
                                break
                            r_pt = _center(r_ent)
                            s_pt = _center(s_ent)
                            if math.dist(r_pt, s_pt) > tolerance.position:
                                all_sources_exact = False
                                break
                            if r_ent.kind != s_ent.kind:
                                all_sources_exact = False
                                break
                        if all_sources_exact:
                            continue
                if cat == "incorrect_position":
                    is_intrinsic_consequence = any(
                        s.get("category") == "incorrect_position"
                        and s.get("suppression_reason") in {
                            "centroid displacement is a consequence of an aligned-pivot intrinsic edit",
                            "centroid displacement is a consequence of contained partial geometry",
                        }
                        and (
                            s.get("student_entity_id") == stu_eid
                            or s.get("reference_entity_id") == rc.source_entity_id
                        )
                        for s in analysis.suppressed_findings
                    )
                    has_intrinsic = any(
                        i.category in {"incorrect_length", "incorrect_angle", "incorrect_radius"}
                        and (
                            i.component_id == rc.id
                            or (stu_eid and i.student_entity_id == stu_eid)
                            or (rc.source_entity_id and i.reference_entity_id == rc.source_entity_id)
                        )
                        for i in issues
                    )
                    if is_intrinsic_consequence or has_intrinsic:
                        continue
                if (
                    cat == "endpoint_gap"
                    and rc.parent_object_id in objs_with_missing_parts
                ):
                    continue
                rule_pair = rules.get(cat)
                if rule_pair is None and cat == "endpoint_gap":
                    rule_pair = rules.get("open_polyline") or rules.get(
                        "incorrect_position"
                    )
                rule = rule_pair[0] if rule_pair else None
                ded = rule.deduction if rule else 2.0
                sev = rule.severity if rule else "moderate"
                r_id = rule.id if rule else None
                exp_val = err.get("expected")
                act_val = err.get("actual")
                tol_val = err.get("tolerance")
                stu_comp_loc = (
                    cm.student_components[0].centroid
                    if cm.student_components and cm.student_components[0].centroid
                    else None
                )
                loc = (
                    tuple(err["location"])
                    if err.get("location")
                    else (stu_comp_loc if stu_comp_loc is not None else rc.centroid)
                )
                if cat in {"incorrect_length", "incorrect_angle", "incorrect_radius"} and isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                    labels = {
                        "incorrect_length": ("length", ""),
                        "incorrect_angle": ("angle", " degrees"),
                        "incorrect_radius": ("radius", ""),
                    }
                    label, suffix = labels[cat]
                    msg = err.get("message") or err.get("technical_feedback") or f"Adjust the {label} from {act_val:.3f}{suffix} to {exp_val:.3f}{suffix}."
                elif cat == "incorrect_position" and isinstance(act_val, (int, float)):
                    msg = err.get("message") or err.get("technical_feedback") or f"Move the entity by {abs(act_val):.3f} drawing units toward the expected location."
                elif cat == "endpoint_gap" and isinstance(act_val, (int, float)):
                    msg = err.get("message") or err.get("technical_feedback") or f"Endpoint gap of {act_val:.3f} drawing units at this junction. Restore the expected connection."
                else:
                    msg = err.get("message") or err.get("technical_feedback") or f"Correct {cat} on component {rc.id}."

                # For endpoint_gap, make it primary only if no primary geometry error already exists on this component
                has_primary_on_comp = any(
                    i.classification == "primary"
                    and (
                        i.component_id == rc.id
                        or (
                            i.reference_entity_id == rc.source_entity_id
                            and i.student_entity_id == stu_eid
                        )
                    )
                    for i in issues
                )
                is_assembly_trans = False
                if cat == "incorrect_position" and rc.parent_object_id:
                    p_obj_t = canonical_match.object_translations.get(rc.parent_object_id, (0.0, 0.0))
                    if math.hypot(p_obj_t[0], p_obj_t[1]) > tolerance.position:
                        is_assembly_trans = True

                classification = (
                    "supporting_evidence"
                    if (
                        (cat == "endpoint_gap" and has_primary_on_comp)
                        or (cat == "incorrect_position" and is_assembly_trans)
                    )
                    else "primary"
                )
                if cat == "endpoint_gap":
                    sel_trans = student_normalization.get("translation") or (0.0, 0.0)
                    sel_tx, sel_ty = float(sel_trans[0]), float(sel_trans[1])
                    if loc and len(loc) >= 2 and (sel_tx or sel_ty):
                        loc = [
                            round(float(loc[0]) - sel_tx, 6),
                            round(float(loc[1]) - sel_ty, 6),
                        ]
                    raw_act_pts = err.get("actual_points")
                    act_pts = (
                        [
                            [
                                round(float(p[0]) - sel_tx, 6),
                                round(float(p[1]) - sel_ty, 6),
                            ]
                            for p in raw_act_pts
                            if isinstance(p, (list, tuple)) and len(p) >= 2
                        ]
                        if raw_act_pts
                        else None
                    )
                    raw_exp_pt = err.get("expected_point")
                    exp_pt = (
                        [
                            round(float(raw_exp_pt[0]) - sel_tx, 6),
                            round(float(raw_exp_pt[1]) - sel_ty, 6),
                        ]
                        if isinstance(raw_exp_pt, (list, tuple)) and len(raw_exp_pt) >= 2
                        else None
                    )
                else:
                    act_pts = None
                    exp_pt = None

                issues.append(
                    Issue(
                        id=f"ERR-{rc.id}-{cat.upper()}",
                        category=cat,
                        code=cat.upper(),
                        severity=sev,
                        confidence="verified",
                        classification=classification,
                        deduction=ded if classification == "primary" else 0.0,
                        reference_entity_id=rc.source_entity_id,
                        student_entity_id=stu_eid,
                        parent_object_id=rc.parent_object_id,
                        component_id=rc.id,
                        location=loc,
                        measurement={
                            "property": cat,
                            "expected": exp_val,
                            "actual": act_val,
                            "deviation": (
                                err.get("deviation")
                                if err.get("deviation") is not None
                                else (
                                    round(abs(act_val - exp_val), 4)
                                    if isinstance(exp_val, (int, float))
                                    and isinstance(act_val, (int, float))
                                    else act_val
                                )
                            ),
                            "tolerance": tol_val,
                            "component_id": rc.id,
                            "object_id": rc.parent_object_id,
                            **({"actual_points": act_pts} if act_pts is not None else {}),
                            **({"expected_point": exp_pt} if exp_pt is not None else {}),
                            **({"coordinate_frame": "student"} if cat == "endpoint_gap" else {}),
                            **({"sub_property": err["sub_property"]} if err.get("sub_property") is not None else {}),
                            **({"vector": err["vector"]} if err.get("vector") is not None else {}),
                            **({"unit": err["unit"]} if err.get("unit") is not None else ({"unit": getattr(reference, "units", "drawing_units")} if hasattr(reference, "units") else {})),
                        },
                        rubric_rule_id=r_id,
                        expected=exp_val,
                        actual=act_val,
                        technical_feedback=msg,
                        message=msg,
                    )
                )

        # Check for local object movement across assessment objects
        for obj in canonical_match.reference_objects:
            obj_t = canonical_match.object_translations.get(obj.object_id, (0.0, 0.0))
            mag = math.hypot(obj_t[0], obj_t[1])
            if mag <= tolerance.position:
                continue

            is_mixed_comp = (
                getattr(rubric, "assignment_type", None) == "Mixed Geometric Composition"
            )
            global_trans = tuple(student_normalization.get("translation", [0.0, 0.0]))
            is_global_accepted = (
                student_normalization.get("rejection_reason") is None
                and student_normalization.get("confidence") in {"high", "verified", "reference_anchor"}
            )
            matches_global = (
                is_global_accepted
                and math.hypot(obj_t[0] - global_trans[0], obj_t[1] - global_trans[1]) <= tolerance.position
            )
            is_strict_mode = getattr(rubric, "normalization_mode", None) == "strict"
            is_assembly_obj = len(obj.components) >= 2
            is_local_movement = (
                (is_strict_mode or is_assembly_obj)
                and not matches_global
                and is_mixed_comp
            )
            if not is_local_movement:
                continue

            if any(i.id == f"ISSUE-{obj.object_id}-POS" for i in issues):
                continue

            has_primary_pos = any(
                i.category == "incorrect_position"
                and i.classification == "primary"
                and (
                    i.parent_object_id == obj.object_id
                    or (i.reference_entity_id and i.reference_entity_id in obj.source_entity_ids)
                )
                for i in issues
            )
            if has_primary_pos:
                continue

            obj_cms = [
                cm for cm in canonical_match.component_matches
                if cm.reference_component.parent_object_id == obj.object_id
            ]
            present_cms = [cm for cm in obj_cms if cm.presence > 0.0]
            if not present_cms:
                continue

            stu_eids = [
                sc.source_entity_id
                for cm in present_cms
                for sc in cm.student_components
                if sc.source_entity_id
            ]
            first_stu_eid = stu_eids[0] if stu_eids else None
            first_ref_eid = obj.source_entity_ids[0] if obj.source_entity_ids else None
            stu_loc = (obj.centroid[0] + obj_t[0], obj.centroid[1] + obj_t[1])

            rule_pair = rules.get("incorrect_position")
            rule = rule_pair[0] if rule_pair else None
            pos_ded = float(rule.deduction if rule else 3.0)
            rule_id = rule.id if rule else "RULE-POSITION-01"

            issues.append(
                Issue(
                    id=f"ISSUE-{obj.object_id}-POS",
                    category="incorrect_position",
                    code="INCORRECT_POSITION",
                    severity="major",
                    confidence="verified",
                    classification="primary",
                    deduction=pos_ded,
                    parent_object_id=obj.object_id,
                    component_id=None,
                    location=stu_loc,
                    measurement={
                        "property": "centroid_shift",
                        "expected": 0.0,
                        "actual": round(mag, 4),
                        "deviation": round(mag, 4),
                        "tolerance": float(tolerance.position),
                        "vector": [round(obj_t[0], 4), round(obj_t[1], 4)],
                        "student_entity_id": first_stu_eid,
                        "source_entity_ids": list(obj.source_entity_ids),
                        "student_entity_ids": list(dict.fromkeys(stu_eids)),
                        "object_id": obj.object_id,
                    },
                    expected=0.0,
                    actual=round(mag, 4),
                    technical_feedback=f"Move object {obj.object_id} by {mag:.3f} drawing units toward the expected location.",
                    message=f"Move object {obj.object_id} by {mag:.3f} drawing units toward the expected location.",
                    reference_entity_id=first_ref_eid,
                    student_entity_id=first_stu_eid,
                    rubric_rule_id=rule_id,
                )
            )

        # Construction requirement check when explicitly set to closed_polyline
        if rubric.construction_requirement == "closed_polyline":
            rule_pair = rules.get("construction_policy") or rules.get(
                "open_polyline"
            )
            rule = rule_pair[0] if rule_pair else None
            ded = rule.deduction if rule else 2.0
            sev = rule.severity if rule else "moderate"
            r_id = rule.id if rule else "RULE-OPEN-01"
            check_cat = (
                "construction_policy"
                if "construction_policy" in rules
                else "open_polyline"
            )
            for obj in canonical_match.reference_objects:
                if not obj.is_closed:
                    continue
                obj_cms = [
                    cm
                    for cm in canonical_match.component_matches
                    if cm.reference_component.parent_object_id == obj.object_id
                ]
                if not obj_cms or any(
                    cm.presence < 1.0 - 1e-4 for cm in obj_cms
                ):
                    continue
                stu_eids = sorted(
                    {
                        sc.source_entity_id
                        for cm in obj_cms
                        for sc in cm.student_components
                    }
                )
                stu_ents = [
                    student_by_id[eid]
                    for eid in stu_eids
                    if eid in student_by_id
                ]
                is_single_closed_polyline = (
                    len(stu_ents) == 1
                    and stu_ents[0].kind == "polyline"
                    and stu_ents[0].closed
                )
                if not is_single_closed_polyline:
                    if not any(
                        i.parent_object_id == obj.object_id
                        and i.code == "CONSTRUCTION_POLICY"
                        for i in issues
                    ):
                        issues.append(
                            Issue(
                                id=f"CONSTR-{obj.object_id}",
                                category=check_cat,
                                code="CONSTRUCTION_POLICY",
                                severity=sev,
                                confidence="verified",
                                classification="primary",
                                deduction=ded,
                                reference_entity_id=(
                                    obj.source_entity_ids[0]
                                    if obj.source_entity_ids
                                    else None
                                ),
                                student_entity_id=(
                                    stu_eids[0] if stu_eids else None
                                ),
                                parent_object_id=obj.object_id,
                                location=obj.centroid,
                                measurement={
                                    "object_id": obj.object_id,
                                    "required_construction": "closed_polyline",
                                    "actual_student_entity_ids": stu_eids,
                                    "actual_kinds": [e.kind for e in stu_ents],
                                },
                                rubric_rule_id=r_id,
                                technical_feedback=(
                                    f"Object {obj.object_id} is geometrically complete "
                                    "but must be constructed as a single closed LWPOLYLINE."
                                ),
                                message=(
                                    "Join and close the boundary segments into a single closed LWPOLYLINE."
                                ),
                            )
                        )

        for dup_id in sorted(canonical_match.duplicate_student_entities):
            if not any(
                i.student_entity_id == dup_id
                and i.category == "duplicate_geometry"
                for i in issues
            ):
                dup_entity = student_by_id.get(dup_id)
                if dup_entity:
                    rule_pair = rules.get("duplicate_geometry")
                    rule = rule_pair[0] if rule_pair else None
                    ded = rule.deduction if rule else 1.0
                    issues.append(
                        Issue(
                            id=f"DUP-{dup_id}",
                            category="duplicate_geometry",
                            code="DUPLICATE_GEOMETRY",
                            severity=rule.severity if rule else "minor",
                            confidence="verified",
                            classification="primary",
                            deduction=ded,
                            student_entity_id=dup_id,
                            location=_center(dup_entity),
                            technical_feedback="Remove the coincident duplicate entity.",
                            message="Remove the coincident duplicate entity.",
                        )
                    )

        if canonical_match and getattr(canonical_match, "ambiguous_groups", None):
            for group in canonical_match.ambiguous_groups:
                g_id = group.get("id", "AMB-1")
                ref_eids = group.get("reference_entity_ids", [])
                stu_eids = group.get("candidate_student_entity_ids", [])
                ref_radii = group.get("reference_radii", [])
                comp_subsets = group.get("competing_subsets", [])
                loc = tuple(group.get("location") or group.get("centroid") or (0.0, 0.0))
                subsets_str = ", ".join(f"[{', '.join(str(r) for r in sub)}]" for sub in comp_subsets)
                ref_str = f"[{', '.join(str(r) for r in ref_radii)}]"
                ref_eid = ref_eids[0] if ref_eids else None
                stu_eid = stu_eids[0] if stu_eids else None

                issues.append(
                    Issue(
                        id=f"ISSUE-{g_id}",
                        category="ambiguous_geometry",
                        severity="warning",
                        confidence="instructor_review_required",
                        classification="informational",
                        deduction=0.0,
                        applied_deduction=0.0,
                        code="AMB-CONCENTRIC-ARC",
                        reference_entity_id=ref_eid,
                        student_entity_id=stu_eid,
                        parent_object_id=group.get("parent_object_id"),
                        location=loc,
                        message=(
                            f"Concentric arc bend has multiple equally plausible student candidate subsets ({subsets_str}) "
                            f"matching reference radii {ref_str}. DraftLens could not choose a reliable pairing; "
                            "instructor review is required."
                        ),
                        technical_feedback=(
                            "DraftLens detected multiple candidate concentric arc pairings with identical geometric cost "
                            "and no distinguishing connected-wall context. Automated correspondence was withheld to prevent "
                            "arbitrary scoring. Instructor review is required."
                        ),
                        learning_topic="Geometric precision",
                        expected=f"Concentric arcs with radii {ref_str}",
                        actual=f"Competing candidate subsets {subsets_str}",
                        measurement={
                            "reference_entity_ids": list(ref_eids),
                            "student_entity_ids": list(stu_eids),
                            "candidate_student_entity_ids": list(stu_eids),
                            "reference_radii": list(ref_radii),
                            "competing_subsets": list(comp_subsets),
                            "type": group.get("type", "concentric_arc_ambiguity"),
                        },
                        derived_evidence=[
                            {
                                "reference_entity_ids": ref_eids,
                                "candidate_student_entity_ids": stu_eids,
                                "competing_subsets": comp_subsets,
                                "type": group.get("type", "concentric_arc_ambiguity"),
                            }
                        ],
                    )
                )

    global_displacement = student_normalization.get("global_displacement") or {}
    if global_displacement.get("detected"):
        ratio = float(global_displacement["displacement_to_tolerance_ratio"])
        if ratio <= 5:
            scheduled_deduction = 25.0
        elif ratio <= 20:
            scheduled_deduction = 40.0
        else:
            scheduled_deduction = 50.0
        issues.append(
            Issue(
                id="E-GLOBAL-DISPLACEMENT",
                category="global_drawing_displacement",
                code="GLOBAL_DRAWING_DISPLACEMENT",
                severity="major" if ratio <= 20 else "critical",
                confidence="verified",
                classification="primary",
                deduction=scheduled_deduction,
                location=(
                    (reference.bbox[0] + reference.bbox[2]) / 2.0,
                    (reference.bbox[1] + reference.bbox[3]) / 2.0,
                ),
                measurement=deepcopy(global_displacement),
                technical_feedback=(
                    "The complete drawing is displaced by one consistent vector "
                    "while strict placement is required."
                ),
                message="Move the complete drawing to the approved reference location.",
                expected=[0.0, 0.0],
                actual=[
                    global_displacement["displacement_x"],
                    global_displacement["displacement_y"],
                ],
            )
        )

    for issue in issues:
        if issue.category != "endpoint_gap" or issue.measurement is None:
            continue
        primary_issue = next(
            (
                candidate
                for candidate in issues
                if candidate.classification == "primary"
                and candidate.reference_entity_id == issue.reference_entity_id
                and candidate.student_entity_id == issue.student_entity_id
            ),
            None,
        )
        issue.measurement["linked_primary_issue_id"] = (
            primary_issue.id if primary_issue else None
        )

    def resolve_suppressed(raw: dict[str, Any]) -> dict[str, Any]:
        resolved = deepcopy(raw)
        primary_category = resolved.pop("primary_category", None)
        ref_id = resolved.get("reference_entity_id")
        ref_obj = ref_entity_to_obj.get(ref_id) if ref_id else None
        primary_issue = next(
            (
                issue
                for issue in issues
                if issue.category == primary_category
                and (
                    (
                        issue.reference_entity_id == ref_id
                        and issue.student_entity_id
                        == resolved.get("student_entity_id")
                    )
                    or (ref_obj and issue.parent_object_id == ref_obj)
                )
            ),
            None,
        )
        resolved["primary_issue_id"] = (
            primary_issue.id if primary_issue else None
        )
        return resolved

    suppressed_findings = [
        resolve_suppressed(finding) for finding in analysis.suppressed_findings
    ]
    for issue in issues:
        issue.suppressed_findings = [
            resolve_suppressed(finding) for finding in issue.suppressed_findings
        ]

    if use_canonical_reconciliation:
        if rubric.rubric_version in {"2.0", "2.1"} or rubric.completion_scoring_mode == "object_part_deduction":
            completion = round(100.0 * canonical_match.completion_fraction, 2)
        else:
            matched_required = len(reference.entities) - len(missing)
            completion = round(
                100.0 * matched_required / max(len(reference.entities), 1), 2
            )
        by_type = {}
        if canonical_match and canonical_match.component_matches:
            comp_kinds = sorted(
                {
                    cm.reference_component.kind
                    for cm in canonical_match.component_matches
                }
            )
            for ckind in comp_kinds:
                matches_k = [
                    cm
                    for cm in canonical_match.component_matches
                    if cm.reference_component.kind == ckind
                ]
                tot = sum(cm.weight for cm in matches_k)
                pres = sum(cm.weight * cm.presence for cm in matches_k)
                by_type[ckind] = round(100.0 * pres / max(tot, 1e-9), 1)
    else:
        matched_required = len(matched)
        completion = round(
            100 * matched_required / max(len(reference.entities), 1), 1
        )
        by_type = {}
        for kind in sorted({e.kind for e in reference.entities}):
            total = sum(e.kind == kind for e in reference.entities)
            count = sum(r.kind == kind for r, _, _ in matched)
            by_type[kind] = round(100 * count / max(total, 1), 1)

    scoring = score_issues(
        issues,
        rubric,
        completion,
        suppressed_findings,
        canonical_match=canonical_match,
    )
    for issue in issues:
        guidance = correction_guidance(
            issue,
            reference_by_id.get(issue.reference_entity_id),
            student_by_id.get(issue.student_entity_id),
        )
        issue.correction_guidance = guidance.to_dict() if guidance else None
        issue.recommended_commands = (
            guidance.flattened_commands() if guidance else []
        )
    score = scoring["score"]
    deduction = scoring["deduction"]
    breakdown = scoring["rubric_breakdown"]
    audit = scoring["audit_trail"]

    match_records_dict = {}
    for reference_entity, student_entity, confidence in matched:
        match_records_dict[(reference_entity.id, student_entity.id)] = {
            "reference_entity_id": reference_entity.id,
            "student_entity_id": student_entity.id,
            "confidence": round(confidence, 3),
            "match_quality": round(
                match_qualities.get(reference_entity.id, confidence), 3
            ),
        }

    if use_canonical_reconciliation and canonical_match and canonical_match.component_matches:
        used_ref = {r.id for r, _, _ in matched}
        used_stu = {s.id for _, s, _ in matched}
        for cm in canonical_match.component_matches:
            if cm.presence <= 0 or not cm.student_components:
                continue
            ref_ids = [
                rid for rid in (
                    cm.reference_component.source_entity_ids
                    or [cm.reference_component.source_entity_id]
                )
                if rid
            ]
            stu_ids = [
                eid
                for sc in cm.student_components
                for eid in (sc.source_entity_ids or [sc.source_entity_id])
                if eid
            ]
            # 1-to-many segmentation: 1 reference entity segmented into student components
            if len(ref_ids) == 1:
                ref_id = ref_ids[0]
                for sc_id in stu_ids:
                    if sc_id not in used_stu:
                        conf = 1.0 if cm.correctness >= 1.0 - 1e-4 else 0.8
                        match_records_dict[(ref_id, sc_id)] = {
                            "reference_entity_id": ref_id,
                            "student_entity_id": sc_id,
                            "confidence": conf,
                            "match_quality": conf,
                        }
                        used_stu.add(sc_id)
            # many-to-1 representation: multiple reference entities covered by 1 student component
            elif len(stu_ids) == 1:
                stu_id = stu_ids[0]
                for ref_id in ref_ids:
                    if ref_id not in used_ref:
                        conf = 1.0 if cm.correctness >= 1.0 - 1e-4 else 0.8
                        match_records_dict[(ref_id, stu_id)] = {
                            "reference_entity_id": ref_id,
                            "student_entity_id": stu_id,
                            "confidence": conf,
                            "match_quality": conf,
                        }
                        used_ref.add(ref_id)

    all_matches = list(match_records_dict.values())

    is_formative_assessment = getattr(rubric, "assessment_mode", "summative") == "formative"
    if is_formative_assessment:
        score = None
        deduction = None
        if "category_deductions" in scoring and isinstance(scoring["category_deductions"], dict):
            scoring["category_deductions"] = {k: None for k in scoring["category_deductions"]}
        if "summary" in scoring and isinstance(scoring["summary"], dict):
            scoring["summary"]["by_category"] = dict(scoring["category_deductions"])

        def _sanitize_dict_deductions(d: dict[str, Any]) -> None:
            for k in list(d.keys()):
                if (
                    k.endswith("_deduction")
                    or k in {
                        "requested",
                        "raw_deduction",
                        "deduction_after_rule_cap",
                        "deduction_after_category_cap",
                        "final_applied_contribution",
                        "applied",
                        "deduction",
                        "weight",
                        "score",
                    }
                ):
                    d[k] = None
                elif k == "object_budgets":
                    if isinstance(d[k], dict):
                        d[k] = {obj_id: None for obj_id in d[k]}
                    else:
                        d[k] = None
                elif k == "category_split":
                    if isinstance(d[k], dict):
                        d[k] = {cat_id: None for cat_id in d[k]}
                    else:
                        d[k] = None

        def _sanitize_formative_entry(entry: dict[str, Any]) -> None:
            _sanitize_dict_deductions(entry)
            if entry.get("deduction_status") != "suppressed":
                entry["deduction_status"] = "diagnostic"
            if "supporting_evidence" in entry and isinstance(entry["supporting_evidence"], list):
                for ev in entry["supporting_evidence"]:
                    if isinstance(ev, dict):
                        _sanitize_dict_deductions(ev)

        def _sanitize_formative_category(cat: dict[str, Any]) -> None:
            cat["weight"] = None
            cat["score"] = None
            cat["deduction"] = None
            for ev in cat.get("deduction_evidence", []):
                _sanitize_formative_entry(ev)

        if "score_breakdown" in scoring and isinstance(scoring["score_breakdown"], dict):
            sb = scoring["score_breakdown"]
            sb["final_score"] = None
            sb["unrounded_final_score"] = None
            sb["total_applied_deduction"] = None
            sb["missing_part_deduction"] = None
            for item in sb.get("category_subtotals", []):
                _sanitize_formative_category(item)
            for item in sb.get("issues", []):
                _sanitize_formative_entry(item)
            for item in sb.get("suppressed_findings", []):
                _sanitize_formative_entry(item)

        if "rubric_breakdown" in scoring and isinstance(scoring["rubric_breakdown"], list):
            for cat in scoring["rubric_breakdown"]:
                _sanitize_formative_category(cat)

        if "audit_trail" in scoring and isinstance(scoring["audit_trail"], list):
            for entry in scoring["audit_trail"]:
                _sanitize_formative_entry(entry)

        for iss in issues:
            iss.deduction = None
            iss.applied_deduction = None
            iss.raw_rule_deduction = None
            iss.final_applied_contribution = None
            iss.deduction_after_rule_cap = None
            iss.deduction_after_category_cap = None
            iss.deduction_status = "diagnostic"
            if iss.category_split and isinstance(iss.category_split, dict):
                iss.category_split = {k: None for k in iss.category_split}
            if iss.supporting_evidence and isinstance(iss.supporting_evidence, list):
                for ev in iss.supporting_evidence:
                    if isinstance(ev, dict):
                        _sanitize_dict_deductions(ev)

    return {
        "score": score,
        "system_score": score,
        "deduction": deduction,
        "issues": [issue.to_dict() for issue in issues],
        "summary": {
            "issue_count": len(issues),
            "by_category": scoring["category_deductions"],
        },
        "rubric_breakdown": breakdown,
        "completion": {
            "overall": completion,
            "by_entity_type": by_type,
            "by_region": {"all": completion},
            "by_category": {"completion": completion},
            "fraction": round(canonical_match.completion_fraction, 6),
        },
        "normalization": {
            "reference": reference_normalization,
            "student": student_normalization,
        },
        "match_count": len(all_matches),
        "matches": all_matches,
        "canonical_match": canonical_match.to_dict(),
        "assessment_objects": [
            obj.to_dict() for obj in canonical_match.reference_objects
        ],
        "object_translations": (
            dict(canonical_match.object_translations)
            if canonical_match
            else {}
        ),
        "completion_fraction": round(canonical_match.completion_fraction, 6),
        "accuracy_fraction": round(canonical_match.accuracy_fraction, 6),
        "audit_trail": audit,
        "observations": [
            observation.to_dict() for observation in analysis.observations
        ],
        "suppressed_findings": suppressed_findings,
        "topology": analysis.topology.to_dict() if analysis.topology else None,
        "score_breakdown": scoring["score_breakdown"],
        "tolerances": tolerance.model_dump(),
        "assessment_mode": getattr(rubric, "assessment_mode", "summative"),
        "assignment_type": getattr(rubric, "assignment_type", None),
        "rubric_application": {
            "approved": rubric.approved,
            "rubric_version": rubric.rubric_version,
            "assignment_type": getattr(rubric, "assignment_type", None),
            "assessment_mode": getattr(rubric, "assessment_mode", "summative"),
            "normalization_mode": rubric.normalization_mode,
            "rubric_source": getattr(rubric, "rubric_source", None),
            "completion_scoring_mode": rubric.completion_scoring_mode,
            "missing_part_deduction": rubric.missing_part_deduction,
            "construction_requirement": rubric.construction_requirement,
            "category_weights": {
                category.id: category.weight for category in rubric.categories
            },
        },
    }
