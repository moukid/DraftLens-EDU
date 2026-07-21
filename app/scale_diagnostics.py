from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any

from .dxf import entity_length
from .models import Drawing, Entity


MIN_SCALE_SUPPORT = 3
MIN_SCALE_SUPPORT_RATIO = 0.8
SCALE_TOLERANCE = 0.03


@dataclass(frozen=True, slots=True)
class ScaleDiagnostic:
    detected_scale_mismatch: bool
    estimated_scale_factor: float | None
    scale_support_count: int
    scale_support_ratio: float
    scale_confidence: str
    likely_unit_or_scale_mismatch: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_scale_mismatch": self.detected_scale_mismatch,
            "estimated_scale_factor": self.estimated_scale_factor,
            "scale_support_count": self.scale_support_count,
            "scale_support_ratio": self.scale_support_ratio,
            "scale_confidence": self.scale_confidence,
            "likely_unit_or_scale_mismatch": self.likely_unit_or_scale_mismatch,
        }


def _drawing_scale(drawing: Drawing) -> float:
    width = float(drawing.bbox[2] - drawing.bbox[0])
    height = float(drawing.bbox[3] - drawing.bbox[1])
    return max(math.hypot(width, height), 1e-12)


def _center(entity: Entity) -> tuple[float, float]:
    if entity.centroid is not None:
        return float(entity.centroid[0]), float(entity.centroid[1])
    if entity.points:
        xs = [float(point[0]) for point in entity.points]
        ys = [float(point[1]) for point in entity.points]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return (0.0, 0.0)


def _normalized_signature(entity: Entity, drawing: Drawing) -> tuple[Any, ...]:
    scale = _drawing_scale(drawing)
    center_x = (drawing.bbox[0] + drawing.bbox[2]) / 2.0
    center_y = (drawing.bbox[1] + drawing.bbox[3]) / 2.0
    x, y = _center(entity)
    length = entity_length(entity)
    points = [(float(px), float(py)) for px, py in entity.points]
    relative = []
    if points:
        anchor_x, anchor_y = points[0]
        relative = [
            (round((px - anchor_x) / scale, 5), round((py - anchor_y) / scale, 5))
            for px, py in points
        ]
        if entity.kind == "line" and len(relative) == 2:
            vector = min(relative[1], (-relative[1][0], -relative[1][1]))
            relative = [(0.0, 0.0), vector]
    return (
        entity.kind,
        bool(entity.closed),
        len(points),
        round((x - center_x) / scale, 4),
        round((y - center_y) / scale, 4),
        round(float(length or 0.0) / scale, 5),
        round(float(entity.radius or 0.0) / scale, 5),
        round(float(entity.start_angle or 0.0), 3),
        round(float(entity.end_angle or 0.0), 3),
        tuple(relative),
    )


def diagnose_uniform_scale(reference: Drawing, student: Drawing) -> ScaleDiagnostic:
    """Diagnose, but never apply, a strongly supported global uniform scale."""

    if len(reference.entities) < MIN_SCALE_SUPPORT or len(student.entities) < MIN_SCALE_SUPPORT:
        return ScaleDiagnostic(False, None, 0, 0.0, "insufficient_evidence", False)
    reference_scale = _drawing_scale(reference)
    student_scale = _drawing_scale(student)
    if reference_scale <= 1e-12 or student_scale <= 1e-12:
        return ScaleDiagnostic(False, None, 0, 0.0, "insufficient_evidence", False)

    reference_signatures = Counter(
        _normalized_signature(entity, reference) for entity in reference.entities
    )
    student_signatures = Counter(
        _normalized_signature(entity, student) for entity in student.entities
    )
    support = sum(
        min(count, student_signatures.get(signature, 0))
        for signature, count in reference_signatures.items()
    )
    support_ratio = support / max(len(reference.entities), len(student.entities), 1)
    factor = student_scale / reference_scale
    mismatch = (
        support >= MIN_SCALE_SUPPORT
        and support_ratio >= MIN_SCALE_SUPPORT_RATIO
        and abs(math.log(factor)) > SCALE_TOLERANCE
    )
    if support_ratio >= 0.95:
        confidence = "verified"
    elif support_ratio >= MIN_SCALE_SUPPORT_RATIO:
        confidence = "high"
    elif support:
        confidence = "low"
    else:
        confidence = "none"
    return ScaleDiagnostic(
        mismatch,
        round(factor, 6),
        support,
        round(support_ratio, 6),
        confidence,
        mismatch,
    )
