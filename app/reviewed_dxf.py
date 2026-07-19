from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from typing import Any

from .models import Drawing, Entity


@dataclass(frozen=True, slots=True)
class ReviewedEntity:
    """Immutable rendering snapshot with source provenance."""

    entity_id: str
    source: str
    kind: str
    layer: str
    points: tuple[tuple[float, float], ...]
    radius: float | None
    start_angle: float | None
    end_angle: float | None
    closed: bool
    text: str | None
    bbox: tuple[float, float, float, float] | None
    properties_json: str

    @property
    def properties(self) -> dict[str, Any]:
        return json.loads(self.properties_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["properties"] = json.loads(data.pop("properties_json"))
        return data


@dataclass(frozen=True, slots=True)
class ReviewedIssue:
    """Visual issue record grounded in comparison or validation evidence."""

    issue_id: str
    category: str
    severity: str
    visual_role: str
    source_entity_id: str | None
    expected_entity_id: str | None
    actual_geometry: ReviewedEntity | None
    expected_geometry: ReviewedEntity | None
    region: tuple[float, float, float, float] | None
    technical_feedback: str
    rubric_rule_id: str | None
    deduction: float
    raw_deduction: float
    applied_deduction: float
    deduction_status: str
    suppression_reason: str | None
    confidence: str
    classification: str
    provenance: str
    measurement_json: str

    @property
    def measurement(self) -> Any:
        return json.loads(self.measurement_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actual_geometry"] = self.actual_geometry.to_dict() if self.actual_geometry else None
        data["expected_geometry"] = self.expected_geometry.to_dict() if self.expected_geometry else None
        data["measurement"] = json.loads(data.pop("measurement_json"))
        return data


@dataclass(frozen=True, slots=True)
class ReviewedDrawing:
    """Complete, assignment-agnostic input for deterministic renderers."""

    reference_entities: tuple[ReviewedEntity, ...]
    student_entities: tuple[ReviewedEntity, ...]
    issues: tuple[ReviewedIssue, ...]
    reference_unsupported_json: tuple[str, ...]
    student_unsupported_json: tuple[str, ...]
    extents: tuple[float, float, float, float]
    units: str
    score: float | None

    @property
    def reference_unsupported(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.reference_unsupported_json]

    @property
    def student_unsupported(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.student_unsupported_json]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_entities": [entity.to_dict() for entity in self.reference_entities],
            "student_entities": [entity.to_dict() for entity in self.student_entities],
            "issues": [issue.to_dict() for issue in self.issues],
            "reference_unsupported": self.reference_unsupported,
            "student_unsupported": self.student_unsupported,
            "extents": self.extents,
            "units": self.units,
            "score": self.score,
        }


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _entity_bounds(entity: Entity) -> tuple[float, float, float, float] | None:
    points = [(float(x), float(y)) for x, y in entity.points if _finite(x) and _finite(y)]
    if entity.kind in {"circle", "arc"} and points and _finite(entity.radius):
        x, y = points[0]
        radius = abs(float(entity.radius))
        return (x - radius, y - radius, x + radius, y + radius)
    if entity.kind == "ellipse" and points:
        major = entity.properties.get("major_axis", (0.0, 0.0))
        if len(major) >= 2 and _finite(major[0]) and _finite(major[1]):
            rx = math.hypot(float(major[0]), float(major[1]))
            ry = rx * abs(float(entity.properties.get("ratio", 1.0)))
            radius = max(rx, ry)
            x, y = points[0]
            return (x - radius, y - radius, x + radius, y + radius)
    if points:
        xs, ys = zip(*points)
        return (min(xs), min(ys), max(xs), max(ys))
    if entity.bbox and all(_finite(value) for value in entity.bbox):
        return tuple(float(value) for value in entity.bbox)
    return None


def _snapshot(entity: Entity, source: str) -> ReviewedEntity:
    points = tuple((float(x), float(y)) for x, y in entity.points if _finite(x) and _finite(y))
    return ReviewedEntity(
        entity_id=str(entity.id),
        source=source,
        kind=str(entity.kind),
        layer=str(entity.layer),
        points=points,
        radius=float(entity.radius) if _finite(entity.radius) else None,
        start_angle=float(entity.start_angle) if _finite(entity.start_angle) else None,
        end_angle=float(entity.end_angle) if _finite(entity.end_angle) else None,
        closed=bool(entity.closed),
        text=None if entity.text is None else str(entity.text),
        bbox=_entity_bounds(entity),
        properties_json=json.dumps(deepcopy(entity.properties), sort_keys=True, separators=(",", ":"), default=str),
    )


def _union_regions(*regions: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    valid = [region for region in regions if region and all(_finite(value) for value in region)]
    if not valid:
        return None
    return (
        min(region[0] for region in valid),
        min(region[1] for region in valid),
        max(region[2] for region in valid),
        max(region[3] for region in valid),
    )


def _role(category: str, severity: str) -> str:
    if severity == "critical":
        return "critical"
    if category == "missing_geometry":
        return "missing"
    if category == "extra_geometry":
        return "extra"
    if category.startswith("incorrect_") or category in {"open_polyline", "wrong_layer", "wrong_entity_type"}:
        return "inaccurate"
    if category in {"endpoint_gap", "disconnected_geometry", "unwanted_intersection", "overlapping_geometry"}:
        return "connectivity"
    return "warning"


def _deduction_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _deduction_contract(raw_issue: dict[str, Any]) -> tuple[float, float, str, str | None]:
    raw = _deduction_number(raw_issue.get("deduction"))
    applied_value = raw_issue.get("applied_deduction")
    applied = raw if applied_value is None else _deduction_number(applied_value)
    suppression_reason = raw_issue.get("suppression_reason")
    if suppression_reason:
        status = "suppressed"
    elif applied < raw:
        status = "capped"
    elif applied > 0:
        status = "applied"
    else:
        status = "none"
    return raw, applied, status, str(suppression_reason) if suppression_reason else None


def _location_region(location: Any) -> tuple[float, float, float, float] | None:
    if isinstance(location, (list, tuple)) and len(location) >= 2 and _finite(location[0]) and _finite(location[1]):
        x, y = float(location[0]), float(location[1])
        return (x, y, x, y)
    return None


def _validation_key(finding: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(finding.get("severity", "")),
        str(finding.get("code", "")),
        str(finding.get("entity_id", "")),
        json.dumps(finding.get("location"), sort_keys=True, default=str),
        str(finding.get("message", "")),
    )


def build_reviewed_drawing(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
    validation: dict[str, Any] | None = None,
) -> ReviewedDrawing:
    """Build a detached review snapshot without mutating any input object."""

    reference_entities = tuple(sorted((_snapshot(entity, "reference") for entity in reference.entities), key=lambda item: item.entity_id))
    student_entities = tuple(sorted((_snapshot(entity, "student") for entity in student.entities), key=lambda item: item.entity_id))
    reference_by_id = {entity.entity_id: entity for entity in reference_entities}
    student_by_id = {entity.entity_id: entity for entity in student_entities}
    reviewed_issues: list[ReviewedIssue] = []

    for index, raw in enumerate(comparison.get("issues", []), 1):
        raw_issue = deepcopy(raw)
        issue_id = str(raw_issue.get("error_id") or raw_issue.get("id") or f"E-{index:03d}")
        category = str(raw_issue.get("category") or "warning")
        severity = str(raw_issue.get("severity") or "warning")
        source_id = raw_issue.get("student_entity_id")
        expected_id = raw_issue.get("reference_entity_id")
        actual = student_by_id.get(str(source_id)) if source_id is not None else None
        expected = reference_by_id.get(str(expected_id)) if expected_id is not None else None
        region = _union_regions(expected.bbox if expected else None, actual.bbox if actual else None, _location_region(raw_issue.get("location")))
        raw_deduction, applied_deduction, deduction_status, suppression_reason = _deduction_contract(raw_issue)
        reviewed_issues.append(ReviewedIssue(
            issue_id=issue_id,
            category=category,
            severity=severity,
            visual_role=_role(category, severity),
            source_entity_id=str(source_id) if source_id is not None else None,
            expected_entity_id=str(expected_id) if expected_id is not None else None,
            actual_geometry=actual,
            expected_geometry=expected,
            region=region,
            technical_feedback=str(raw_issue.get("technical_feedback") or raw_issue.get("message") or "Review this finding."),
            rubric_rule_id=str(raw_issue["rubric_rule_id"]) if raw_issue.get("rubric_rule_id") is not None else None,
            deduction=applied_deduction,
            raw_deduction=raw_deduction,
            applied_deduction=applied_deduction,
            deduction_status=deduction_status,
            suppression_reason=suppression_reason,
            confidence=str(raw_issue.get("confidence") or "instructor_review_required"),
            classification=str(raw_issue.get("classification") or "primary"),
            provenance="comparison",
            measurement_json=json.dumps(deepcopy(raw_issue.get("measurement")), sort_keys=True, separators=(",", ":"), default=str),
        ))

    findings = sorted(deepcopy((validation or {}).get("findings", [])), key=_validation_key)
    for index, finding in enumerate(findings, 1):
        entity_id = finding.get("entity_id")
        expected = reference_by_id.get(str(entity_id)) if entity_id is not None else None
        severity = str(finding.get("severity") or "warning")
        category = "reference_critical" if severity == "critical" else "reference_warning"
        reviewed_issues.append(ReviewedIssue(
            issue_id=f"V-{index:03d}",
            category=category,
            severity=severity,
            visual_role=_role(category, severity),
            source_entity_id=None,
            expected_entity_id=str(entity_id) if entity_id is not None else None,
            actual_geometry=None,
            expected_geometry=expected,
            region=_union_regions(expected.bbox if expected else None, _location_region(finding.get("location"))),
            technical_feedback=str(finding.get("message") or "Review the reference drawing."),
            rubric_rule_id=None,
            deduction=0.0,
            raw_deduction=0.0,
            applied_deduction=0.0,
            deduction_status="none",
            suppression_reason=None,
            confidence="verified",
            classification="informational",
            provenance="reference_validation",
            measurement_json="null",
        ))

    all_regions = [entity.bbox for entity in reference_entities + student_entities if entity.bbox]
    all_regions.extend(issue.region for issue in reviewed_issues if issue.region)
    extents = _union_regions(*all_regions) or (0.0, 0.0, 0.0, 0.0)
    reference_unsupported = tuple(
        json.dumps({**deepcopy(item), "source": "reference"}, sort_keys=True, separators=(",", ":"), default=str)
        for item in sorted(reference.unsupported_entities, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    )
    student_unsupported = tuple(
        json.dumps({**deepcopy(item), "source": "student"}, sort_keys=True, separators=(",", ":"), default=str)
        for item in sorted(student.unsupported_entities, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    )
    score = comparison.get("score")
    return ReviewedDrawing(
        reference_entities=reference_entities,
        student_entities=student_entities,
        issues=tuple(sorted(reviewed_issues, key=lambda issue: issue.issue_id)),
        reference_unsupported_json=reference_unsupported,
        student_unsupported_json=student_unsupported,
        extents=extents,
        units=str(reference.units),
        score=float(score) if _finite(score) else None,
    )
