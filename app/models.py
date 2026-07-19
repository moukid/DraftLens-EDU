from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EntityKind = Literal["line", "polyline", "circle", "arc", "ellipse", "spline", "text", "dimension"]
Severity = Literal["critical", "major", "moderate", "minor", "warning"]
Confidence = Literal["verified", "high", "moderate", "instructor_review_required"]
FindingClassification = Literal[
    "primary", "derived", "supporting_evidence", "suppressed", "informational"
]

@dataclass(slots=True)
class Entity:
    """Canonical representation of a supported DXF entity."""
    id: str
    kind: EntityKind
    layer: str
    points: list[tuple[float, float]] = field(default_factory=list)
    source_handle: str | None = None
    source: Literal["reference", "student"] = "reference"
    text: str | None = None
    radius: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    measurement: float | None = None
    closed: bool = False
    properties: dict[str, Any] = field(default_factory=dict)
    bbox: tuple[float, float, float, float] | None = None
    centroid: tuple[float, float] | None = None

    @property
    def entity_type(self) -> str:
        return {"polyline": "LWPOLYLINE"}.get(self.kind, self.kind.upper())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["internal_id"] = data.pop("id")
        data["entity_type"] = self.entity_type
        data["geometry"] = {"points": data["points"], "radius": data["radius"], "start_angle": data["start_angle"], "end_angle": data["end_angle"], "closed": data["closed"]}
        return data

@dataclass(slots=True)
class Drawing:
    entities: list[Entity]
    bbox: tuple[float, float, float, float]
    units: str = "unitless"
    units_code: int = 0
    unsupported_entities: list[dict[str, Any]] = field(default_factory=list)
    normalization: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"entities": [e.to_dict() for e in self.entities], "bbox": self.bbox, "units": self.units, "unsupported_entities": self.unsupported_entities, "normalization": self.normalization}

@dataclass(slots=True)
class Issue:
    id: str
    category: str
    severity: Severity
    message: str
    deduction: float
    applied_deduction: float = 0.0
    confidence: Confidence = "verified"
    classification: FindingClassification = "primary"
    code: str | None = None
    reference_entity_id: str | None = None
    student_entity_id: str | None = None
    location: tuple[float, float] | None = None
    measurement: dict[str, Any] | None = None
    rubric_rule_id: str | None = None
    technical_feedback: str = ""
    learning_topic: str = "Geometric precision"
    recommended_commands: list[str] = field(default_factory=list)
    expected: Any = None
    actual: Any = None
    derived_evidence: list[dict[str, Any]] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    suppressed_findings: list[dict[str, Any]] = field(default_factory=list)
    suppression_reason: str | None = None
    status: Literal["accepted", "rejected"] = "accepted"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_id"] = data["id"]
        return data
