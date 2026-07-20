from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from shapely.geometry import LineString

from .dxf import entity_length
from .models import Drawing, Entity
from .rubric import ToleranceProfile
from .topology import TopologyComparison, compare_topology


FindingClassification = Literal[
    "primary", "derived", "supporting_evidence", "suppressed", "informational"
]


@dataclass(slots=True)
class Observation:
    id: str
    property: str
    expected: Any
    actual: Any
    deviation: Any
    tolerance: float | None
    unit: str
    reference_entity_id: str | None
    student_entity_id: str | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "classification": "supporting_evidence",
            "property": self.property,
            "expected": self.expected,
            "actual": self.actual,
            "deviation": self.deviation,
            "tolerance": self.tolerance,
            "unit": self.unit,
            "reference_entity_id": self.reference_entity_id,
            "student_entity_id": self.student_entity_id,
            **self.details,
        }


@dataclass(slots=True)
class CausalFinding:
    category: str
    reference_entity: Entity | None = None
    student_entity: Entity | None = None
    measurement: dict[str, Any] | None = None
    expected: Any = None
    actual: Any = None
    confidence: str = "verified"
    classification: FindingClassification = "primary"
    derived_evidence: list[dict[str, Any]] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    suppressed_findings: list[dict[str, Any]] = field(default_factory=list)
    issue_id: str | None = None
    location: tuple[float, float] | None = None


@dataclass(slots=True)
class CausalAnalysis:
    findings: list[CausalFinding] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    suppressed_findings: list[dict[str, Any]] = field(default_factory=list)
    topology: TopologyComparison | None = None

    def observe(
        self,
        property_name: str,
        expected: Any,
        actual: Any,
        tolerance: float | None,
        unit: str,
        reference_entity: Entity | None,
        student_entity: Entity | None,
        *,
        deviation: Any = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if deviation is None and isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            deviation = actual - expected
        observation = Observation(
            id=f"O-{len(self.observations) + 1:03d}",
            property=property_name,
            expected=expected,
            actual=actual,
            deviation=deviation,
            tolerance=tolerance,
            unit=unit,
            reference_entity_id=reference_entity.id if reference_entity else None,
            student_entity_id=student_entity.id if student_entity else None,
            details=details or {},
        )
        self.observations.append(observation)
        return observation.to_dict()


def _center(entity: Entity) -> tuple[float, float]:
    return entity.centroid or (entity.points[0] if entity.points else (0.0, 0.0))


def _angle(entity: Entity) -> float | None:
    if len(entity.points) < 2:
        return None
    start, end = entity.points[0], entity.points[-1]
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180


def _angle_delta(first: float, second: float) -> float:
    delta = abs(first - second) % 180
    return min(delta, 180 - delta)


def _measurement(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in observation.items()
        if key
        in {
            "property",
            "expected",
            "actual",
            "deviation",
            "tolerance",
            "unit",
        }
    }


def _confidence(value: float) -> str:
    if value >= 0.85:
        return "verified"
    if value >= 0.55:
        return "high"
    return "moderate"


def _endpoint_evidence(
    analysis: CausalAnalysis,
    reference: Entity,
    student: Entity,
    tolerance: ToleranceProfile,
    unit: str,
) -> tuple[list[float], dict[str, Any]]:
    reference_points = [reference.points[0], reference.points[-1]]
    direct = [student.points[0], student.points[-1]]
    reversed_points = list(reversed(direct))
    student_points = min(
        (direct, reversed_points),
        key=lambda points: (
            sum(math.dist(ref, stu) for ref, stu in zip(reference_points, points)),
            tuple(points),
        ),
    )
    vectors = [
        (student_point[0] - reference_point[0], student_point[1] - reference_point[1])
        for reference_point, student_point in zip(reference_points, student_points)
    ]
    distances = [math.hypot(*vector) for vector in vectors]
    evidence = analysis.observe(
        "endpoint_displacement",
        [0.0, 0.0],
        distances,
        tolerance.position,
        unit,
        reference,
        student,
        deviation=distances,
        details={"vectors": [list(vector) for vector in vectors]},
    )
    return distances, evidence


def _suppressed_position(
    reference: Entity,
    student: Entity,
    primary_category: str,
    centroid_evidence: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "category": "incorrect_position",
        "classification": "suppressed",
        "reference_entity_id": reference.id,
        "student_entity_id": student.id,
        "primary_category": primary_category,
        "suppression_reason": reason,
        "observation": centroid_evidence,
    }


def _analyze_line(
    analysis: CausalAnalysis,
    reference: Entity,
    student: Entity,
    tolerance: ToleranceProfile,
    unit: str,
    confidence: str,
    centroid_evidence: dict[str, Any],
    length_evidence: dict[str, Any],
    angle_evidence: dict[str, Any],
) -> None:
    endpoint_distances, endpoint_evidence = _endpoint_evidence(
        analysis, reference, student, tolerance, unit
    )
    position_changed = centroid_evidence["actual"] > tolerance.position
    length_changed = abs(length_evidence["deviation"]) > tolerance.length
    angle_changed = abs(angle_evidence["deviation"]) > tolerance.angle
    intrinsic_changed = length_changed or angle_changed
    pivot_aligned = min(endpoint_distances) <= tolerance.position
    position_primary = position_changed and (not intrinsic_changed or not pivot_aligned)

    if position_primary:
        analysis.findings.append(
            CausalFinding(
                "incorrect_position",
                reference,
                student,
                _measurement(centroid_evidence),
                0.0,
                centroid_evidence["actual"],
                confidence,
                supporting_evidence=[endpoint_evidence],
            )
        )

    derived = [centroid_evidence] if position_changed and not position_primary else []
    if length_changed:
        analysis.findings.append(
            CausalFinding(
                "incorrect_length",
                reference,
                student,
                _measurement(length_evidence),
                length_evidence["expected"],
                length_evidence["actual"],
                confidence,
                derived_evidence=list(derived),
                supporting_evidence=[endpoint_evidence],
            )
        )
    if angle_changed:
        analysis.findings.append(
            CausalFinding(
                "incorrect_angle",
                reference,
                student,
                _measurement(angle_evidence),
                angle_evidence["expected"],
                angle_evidence["actual"],
                confidence,
                derived_evidence=list(derived),
                supporting_evidence=[endpoint_evidence],
            )
        )

    if position_changed and not position_primary:
        primary_category = "incorrect_length" if length_changed else "incorrect_angle"
        suppressed = _suppressed_position(
            reference,
            student,
            primary_category,
            centroid_evidence,
            "centroid displacement is a consequence of an aligned-pivot intrinsic edit",
        )
        analysis.suppressed_findings.append(suppressed)
        primary = next(
            finding
            for finding in reversed(analysis.findings)
            if finding.reference_entity is reference
            and finding.student_entity is student
            and finding.category == primary_category
        )
        primary.suppressed_findings.append(suppressed)


def _analyze_circle(
    analysis: CausalAnalysis,
    reference: Entity,
    student: Entity,
    tolerance: ToleranceProfile,
    unit: str,
    confidence: str,
    centroid_evidence: dict[str, Any],
    radius_evidence: dict[str, Any],
) -> None:
    if centroid_evidence["actual"] > tolerance.position:
        analysis.findings.append(
            CausalFinding(
                "incorrect_position",
                reference,
                student,
                _measurement(centroid_evidence),
                0.0,
                centroid_evidence["actual"],
                confidence,
            )
        )
    if abs(radius_evidence["deviation"]) <= tolerance.radius:
        return

    expected_radius = float(reference.radius)
    actual_radius = float(student.radius)
    circumference = analysis.observe(
        "circumference",
        2 * math.pi * expected_radius,
        2 * math.pi * actual_radius,
        2 * math.pi * tolerance.radius,
        unit,
        reference,
        student,
    )
    diameter = analysis.observe(
        "diameter",
        2 * expected_radius,
        2 * actual_radius,
        2 * tolerance.radius,
        unit,
        reference,
        student,
    )
    bounds = analysis.observe(
        "bounding_box",
        list(reference.bbox) if reference.bbox else None,
        list(student.bbox) if student.bbox else None,
        tolerance.radius,
        unit,
        reference,
        student,
        deviation=None,
    )
    analysis.findings.append(
        CausalFinding(
            "incorrect_radius",
            reference,
            student,
            _measurement(radius_evidence),
            expected_radius,
            actual_radius,
            confidence,
            supporting_evidence=[circumference, diameter, bounds],
        )
    )


def _coincident(
    first: Entity,
    second: Entity,
    tolerance: ToleranceProfile,
) -> bool:
    if first.kind != second.kind:
        return False
    if math.dist(_center(first), _center(second)) > tolerance.position:
        return False
    first_length, second_length = entity_length(first), entity_length(second)
    if first_length is not None and second_length is not None:
        if abs(first_length - second_length) > tolerance.length:
            return False
    if first.radius is not None and second.radius is not None:
        if abs(first.radius - second.radius) > tolerance.radius:
            return False
    if first.kind == "line" and len(first.points) == len(second.points) == 2:
        direct = max(math.dist(a, b) for a, b in zip(first.points, second.points))
        reverse = max(
            math.dist(a, b) for a, b in zip(first.points, reversed(second.points))
        )
        return min(direct, reverse) <= tolerance.position
    return first.closed == second.closed


def _duplicate_measurement(
    entity: Entity,
    coincident: Entity,
    unit: str,
) -> dict[str, Any]:
    return {
        "property": "duplicate_overlap",
        "expected": "unique geometry",
        "actual": "duplicate geometry",
        "deviation": None,
        "tolerance": 0,
        "unit": unit,
        "entity_type": entity.entity_type,
        "length": entity_length(entity),
        "angle": _angle(entity),
        "layer": entity.layer,
        "overlap_percentage": 100.0,
        "coincident_entity_id": coincident.id,
    }


def analyze_comparison(
    reference: Drawing,
    student: Drawing,
    matched: list[tuple[Entity, Entity, float]],
    missing: list[Entity],
    extra: list[Entity],
    tolerance: ToleranceProfile,
) -> CausalAnalysis:
    analysis = CausalAnalysis()
    unit = reference.units

    for entity in missing:
        analysis.observe(
            "unmatched_status",
            "matched",
            "missing",
            None,
            unit,
            entity,
            None,
        )
        analysis.findings.append(CausalFinding("missing_geometry", entity))

    matched_students = [student_entity for _, student_entity, _ in matched]
    prior_extras: list[Entity] = []
    for entity in sorted(extra, key=lambda item: item.id):
        coincident = next(
            (
                candidate
                for candidate in sorted(
                    matched_students + prior_extras, key=lambda item: item.id
                )
                if _coincident(entity, candidate, tolerance)
            ),
            None,
        )
        if coincident is None:
            analysis.observe(
                "unmatched_status",
                "matched",
                "extra",
                None,
                unit,
                None,
                entity,
            )
            analysis.findings.append(CausalFinding("extra_geometry", student_entity=entity))
        else:
            measurement = _duplicate_measurement(entity, coincident, unit)
            duplicate_evidence = analysis.observe(
                "duplicate_overlap",
                "unique geometry",
                "duplicate geometry",
                0,
                unit,
                None,
                entity,
                details={
                    key: value
                    for key, value in measurement.items()
                    if key
                    not in {
                        "property",
                        "expected",
                        "actual",
                        "deviation",
                        "tolerance",
                        "unit",
                    }
                },
            )
            suppressed = {
                "category": "extra_geometry",
                "classification": "suppressed",
                "reference_entity_id": None,
                "student_entity_id": entity.id,
                "primary_category": "duplicate_geometry",
                "suppression_reason": "coincident unmatched geometry is classified as a duplicate",
                "observation": duplicate_evidence,
            }
            analysis.suppressed_findings.append(suppressed)
            analysis.findings.append(
                CausalFinding(
                    "duplicate_geometry",
                    student_entity=entity,
                    measurement=measurement,
                    supporting_evidence=[duplicate_evidence],
                    suppressed_findings=[suppressed],
                )
            )
        prior_extras.append(entity)

    for reference_entity, student_entity, confidence_value in matched:
        confidence = _confidence(confidence_value)
        reference_center = _center(reference_entity)
        student_center = _center(student_entity)
        centroid_distance = math.dist(reference_center, student_center)
        centroid = analysis.observe(
            "centroid_shift",
            0.0,
            centroid_distance,
            tolerance.position,
            unit,
            reference_entity,
            student_entity,
            details={
                "vector": [
                    student_center[0] - reference_center[0],
                    student_center[1] - reference_center[1],
                ]
            },
        )
        reference_length = entity_length(reference_entity)
        student_length = entity_length(student_entity)
        length = (
            analysis.observe(
                "length",
                reference_length,
                student_length,
                tolerance.length,
                unit,
                reference_entity,
                student_entity,
            )
            if reference_length is not None and student_length is not None
            else None
        )
        reference_angle = _angle(reference_entity)
        student_angle = _angle(student_entity)
        angle = (
            analysis.observe(
                "angle",
                reference_angle,
                student_angle,
                tolerance.angle,
                "degrees",
                reference_entity,
                student_entity,
                deviation=_angle_delta(reference_angle, student_angle),
            )
            if reference_angle is not None and student_angle is not None
            else None
        )
        radius = (
            analysis.observe(
                "radius",
                reference_entity.radius,
                student_entity.radius,
                tolerance.radius,
                unit,
                reference_entity,
                student_entity,
            )
            if reference_entity.radius is not None and student_entity.radius is not None
            else None
        )

        if (
            reference_entity.kind == "line"
            and student_entity.kind == "line"
            and length is not None
            and angle is not None
        ):
            _analyze_line(
                analysis,
                reference_entity,
                student_entity,
                tolerance,
                unit,
                confidence,
                centroid,
                length,
                angle,
            )
            continue
        if (
            reference_entity.kind == "circle"
            and student_entity.kind == "circle"
            and radius is not None
        ):
            _analyze_circle(
                analysis,
                reference_entity,
                student_entity,
                tolerance,
                unit,
                confidence,
                centroid,
                radius,
            )
            continue

        if centroid_distance > tolerance.position:
            analysis.findings.append(
                CausalFinding(
                    "incorrect_position",
                    reference_entity,
                    student_entity,
                    _measurement(centroid),
                    0.0,
                    centroid_distance,
                    confidence,
                )
            )
        if length is not None and abs(length["deviation"]) > tolerance.length:
            analysis.findings.append(
                CausalFinding(
                    "incorrect_length",
                    reference_entity,
                    student_entity,
                    _measurement(length),
                    length["expected"],
                    length["actual"],
                    confidence,
                )
            )
        if angle is not None and abs(angle["deviation"]) > tolerance.angle:
            analysis.findings.append(
                CausalFinding(
                    "incorrect_angle",
                    reference_entity,
                    student_entity,
                    _measurement(angle),
                    angle["expected"],
                    angle["actual"],
                    confidence,
                )
            )
        if radius is not None and abs(radius["deviation"]) > tolerance.radius:
            analysis.findings.append(
                CausalFinding(
                    "incorrect_radius",
                    reference_entity,
                    student_entity,
                    _measurement(radius),
                    radius["expected"],
                    radius["actual"],
                    confidence,
                )
            )
        if (
            reference_entity.kind == "dimension"
            and reference_entity.measurement is not None
            and student_entity.measurement is not None
        ):
            dimension = analysis.observe(
                "dimension_measurement",
                reference_entity.measurement,
                student_entity.measurement,
                tolerance.dimension,
                unit,
                reference_entity,
                student_entity,
            )
            if abs(dimension["deviation"]) > tolerance.dimension:
                analysis.findings.append(
                    CausalFinding(
                        "incorrect_length",
                        reference_entity,
                        student_entity,
                        _measurement(dimension),
                        dimension["expected"],
                        dimension["actual"],
                        confidence,
                    )
                )
        if reference_entity.kind == "arc" and student_entity.kind == "arc":
            reference_span = (
                (reference_entity.end_angle or 0) - (reference_entity.start_angle or 0)
            ) % 360
            student_span = (
                (student_entity.end_angle or 0) - (student_entity.start_angle or 0)
            ) % 360
            span = analysis.observe(
                "arc_span",
                reference_span,
                student_span,
                tolerance.angle,
                "degrees",
                reference_entity,
                student_entity,
            )
            if abs(span["deviation"]) > tolerance.angle:
                analysis.findings.append(
                    CausalFinding(
                        "incorrect_angle",
                        reference_entity,
                        student_entity,
                        _measurement(span),
                        reference_span,
                        student_span,
                        confidence,
                    )
                )
        if reference_entity.kind == "polyline":
            if reference_entity.closed and not student_entity.closed:
                closed = analysis.observe(
                    "closed",
                    True,
                    False,
                    0,
                    unit,
                    reference_entity,
                    student_entity,
                )
                analysis.findings.append(
                    CausalFinding(
                        "open_polyline",
                        reference_entity,
                        student_entity,
                        _measurement(closed),
                        True,
                        False,
                        confidence,
                    )
                )
            if len(reference_entity.points) != len(student_entity.points):
                vertices = analysis.observe(
                    "vertex_count",
                    len(reference_entity.points),
                    len(student_entity.points),
                    0,
                    "count",
                    reference_entity,
                    student_entity,
                )
                analysis.findings.append(
                    CausalFinding(
                        "incorrect_shape",
                        reference_entity,
                        student_entity,
                        _measurement(vertices),
                        vertices["expected"],
                        vertices["actual"],
                        confidence,
                    )
                )
        if (
            reference_entity.kind == "spline"
            and len(reference_entity.points) > 1
            and len(student_entity.points) > 1
        ):
            hausdorff_distance = LineString(
                reference_entity.points
            ).hausdorff_distance(LineString(student_entity.points))
            hausdorff = analysis.observe(
                "sampled_hausdorff",
                0.0,
                hausdorff_distance,
                tolerance.position,
                unit,
                reference_entity,
                student_entity,
            )
            if hausdorff_distance > tolerance.position:
                analysis.findings.append(
                    CausalFinding(
                        "incorrect_shape",
                        reference_entity,
                        student_entity,
                        _measurement(hausdorff),
                        0.0,
                        hausdorff_distance,
                        "moderate",
                    )
                )

    analysis.topology = compare_topology(
        reference,
        student,
        matched,
        tolerance.position,
    )
    reference_by_id = {entity.id: entity for entity in reference.entities}
    student_by_id = {entity.id: entity for entity in student.entities}
    for gap in analysis.topology.endpoint_gaps:
        reference_entity = reference_by_id[gap.primary_reference_entity_id]
        student_entity = student_by_id[gap.primary_student_entity_id]
        evidence = analysis.observe(
            "endpoint_gap",
            0.0,
            gap.distance,
            tolerance.position,
            unit,
            reference_entity,
            student_entity,
            details={
                "topology_issue_id": gap.issue_id,
                "junction_id": gap.junction_id,
                "reference_connection_id": gap.reference_connection_id,
                "expected_point": list(gap.expected_point),
                "actual_points": [list(point) for point in gap.actual_points],
                "region": list(gap.region),
                "affected_reference_entity_ids": list(gap.reference_entity_ids),
                "affected_student_entity_ids": list(gap.student_entity_ids),
            },
        )
        primary = next(
            (
                finding
                for finding in analysis.findings
                if finding.classification == "primary"
                and finding.reference_entity is reference_entity
                and finding.student_entity is student_entity
            ),
            None,
        )
        if primary is not None:
            primary.supporting_evidence.append(evidence)
        measurement = _measurement(evidence)
        measurement["region"] = list(gap.region)
        measurement["linked_primary_category"] = (
            primary.category if primary is not None else None
        )
        analysis.findings.append(
            CausalFinding(
                "endpoint_gap",
                reference_entity,
                student_entity,
                measurement,
                0.0,
                gap.distance,
                "verified",
                "supporting_evidence",
                issue_id=gap.issue_id,
                location=gap.expected_point,
            )
        )

    for unsupported in student.unsupported_entities:
        analysis.findings.append(
            CausalFinding(
                "unsupported_entity",
                expected="supported entity",
                actual=unsupported.get("entity_type"),
                confidence="instructor_review_required",
                classification="informational",
            )
        )

    return analysis
