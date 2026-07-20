from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from .dxf import entity_length
from .models import Entity, Issue


@dataclass(frozen=True, slots=True)
class CorrectionGuidance:
    primary_command: str | None = None
    alternative_commands: tuple[str, ...] = ()
    precision_aids: tuple[str, ...] = ()
    explanation: str = ""
    related_primary_issue_id: str | None = None

    def flattened_commands(self) -> list[str]:
        return _unique_commands(
            (self.primary_command,) + self.alternative_commands + self.precision_aids
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["alternative_commands"] = list(self.alternative_commands)
        data["precision_aids"] = list(self.precision_aids)
        return data


def _unique_commands(commands: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if not command:
            continue
        normalized = str(command).upper()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _center(entity: Entity) -> tuple[float, float]:
    return entity.centroid or (entity.points[0] if entity.points else (0.0, 0.0))


def _angle(entity: Entity) -> float | None:
    if len(entity.points) < 2:
        return None
    start, end = entity.points[0], entity.points[-1]
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180


def entity_evidence(entity: Entity) -> dict[str, Any]:
    """Return deterministic measurable evidence for an unmatched entity."""

    center = list(_center(entity))
    evidence: dict[str, Any] = {
        "entity_type": entity.entity_type,
        "layer": entity.layer,
        "bounds": list(entity.bbox) if entity.bbox else None,
    }
    if entity.kind == "line":
        evidence.update(
            {
                "length": entity_length(entity),
                "angle": _angle(entity),
                "centroid": center,
                "position": center,
            }
        )
    elif entity.kind == "circle":
        evidence.update(
            {
                "radius": entity.radius,
                "diameter": 2 * entity.radius if entity.radius is not None else None,
                "center": center,
            }
        )
    elif entity.kind == "arc":
        start_angle = entity.start_angle
        end_angle = entity.end_angle
        evidence.update(
            {
                "radius": entity.radius,
                "center": center,
                "start_angle": start_angle,
                "end_angle": end_angle,
                "sweep": (
                    (end_angle - start_angle) % 360
                    if start_angle is not None and end_angle is not None
                    else None
                ),
            }
        )
    elif entity.kind == "polyline":
        evidence.update(
            {
                "vertex_count": len(entity.points),
                "closed": entity.closed,
                "total_length": entity_length(entity),
            }
        )
    else:
        evidence["centroid"] = center
    return evidence


def duplicate_entity_evidence(
    entity: Entity, coincident: Entity, unit: str
) -> dict[str, Any]:
    evidence = entity_evidence(entity)
    evidence.update(
        {
            "property": "duplicate_overlap",
            "expected": "unique geometry",
            "actual": "duplicate geometry",
            "deviation": None,
            "tolerance": 0,
            "unit": unit,
            "overlap_percentage": 100.0,
            "coincident_entity_id": coincident.id,
            "duplicate_entity_id": entity.id,
        }
    )
    return evidence


def _missing_guidance(entity: Entity | None) -> CorrectionGuidance | None:
    if entity is None:
        return None
    commands = {
        "line": "LINE",
        "arc": "ARC",
        "circle": "CIRCLE",
        "polyline": "PLINE",
        "ellipse": "ELLIPSE",
        "spline": "SPLINE",
    }
    command = commands.get(entity.kind)
    if command is None:
        return None
    return CorrectionGuidance(
        command,
        ("COPY",),
        (),
        f"Create the missing {entity.entity_type} at the expected reference geometry.",
    )


def correction_guidance(
    issue: Issue,
    reference_entity: Entity | None,
    student_entity: Entity | None,
) -> CorrectionGuidance | None:
    """Select deterministic correction guidance from causal and entity evidence."""

    measurement = issue.measurement or {}
    related_primary_id = measurement.get("linked_primary_issue_id")
    if issue.category == "endpoint_gap" and related_primary_id:
        return CorrectionGuidance(
            explanation="Resolve the linked primary issue to restore this connection.",
            related_primary_issue_id=str(related_primary_id),
        )
    if issue.classification != "primary" or issue.suppression_reason:
        return None
    if issue.category == "endpoint_gap":
        return CorrectionGuidance(
            "EXTEND",
            ("FILLET", "STRETCH"),
            ("OSNAP",),
            "Join the appropriate straight entities; when using FILLET for a corner, set the radius to 0.",
        )

    entity = student_entity or reference_entity
    kind = entity.kind if entity else None
    if issue.category == "incorrect_position":
        return CorrectionGuidance(
            "MOVE",
            (),
            ("OSNAP",),
            "Move the intrinsically correct entity to the expected location without changing its shape.",
        )
    if issue.category == "incorrect_length" and kind == "line":
        return CorrectionGuidance(
            "LENGTHEN",
            ("STRETCH", "EXTEND"),
            ("OSNAP",),
            "Correct the displaced endpoint while preserving the line's intended direction.",
        )
    if issue.category == "incorrect_angle" and kind == "line":
        return CorrectionGuidance(
            "ROTATE",
            ("REFERENCE", "POLAR"),
            ("OSNAP",),
            "Rotate the line to the expected angle without translating the whole entity.",
        )
    if issue.category == "incorrect_radius" and kind == "circle":
        return CorrectionGuidance(
            "PROPERTIES",
            ("SCALE", "CIRCLE"),
            (),
            "Set the expected radius directly. If using SCALE, use the circle center as the base point.",
        )
    if issue.category in {"incorrect_radius", "incorrect_angle", "incorrect_shape"} and kind == "arc":
        return CorrectionGuidance(
            "PROPERTIES",
            ("SCALE", "ARC") if issue.category == "incorrect_radius" else ("ARC",),
            ("OSNAP",),
            "Correct the ARC radius or angular geometry directly; if using SCALE, use the arc center as the base point.",
        )
    if issue.category == "missing_geometry":
        return _missing_guidance(reference_entity)
    if issue.category == "extra_geometry":
        return CorrectionGuidance(
            "ERASE",
            ("SELECTSIMILAR",),
            (),
            "Remove the separate unmatched entity; OVERKILL is reserved for coincident duplicates.",
        )
    if issue.category == "duplicate_geometry":
        return CorrectionGuidance(
            "OVERKILL",
            ("ERASE",),
            (),
            "Remove the coincident duplicate while retaining one valid instance.",
        )
    if issue.category == "open_polyline" and kind == "polyline":
        return CorrectionGuidance(
            "PEDIT",
            ("JOIN", "CLOSE"),
            (),
            "Edit the polyline and close its boundary; do not apply this workflow to standalone LINE or ARC entities.",
        )
    if issue.category == "wrong_layer":
        return CorrectionGuidance(
            "CHPROP",
            ("MATCHPROP", "LAYER"),
            (),
            "Move the entity to the required layer without changing its geometry.",
        )
    if issue.category == "incorrect_shape" and kind == "polyline":
        return CorrectionGuidance(
            "PEDIT",
            ("JOIN",),
            ("OSNAP",),
            "Edit the polyline vertices to match the expected boundary.",
        )
    if issue.category == "incorrect_shape" and kind == "spline":
        return CorrectionGuidance(
            "SPLINEDIT",
            ("SPLINE",),
            ("OSNAP",),
            "Edit or reconstruct the spline using the expected fit geometry.",
        )
    return None
