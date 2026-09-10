from __future__ import annotations
import math
from collections import Counter, defaultdict
from .dxf import entity_length
from .models import Drawing, Entity
from .topology import build_topology

GEOMETRIC_TOLERANCE = 1e-6
NEAR_CLOSURE_RATIO = 0.01

from typing import Any

REFERENCE_FINDING_GUIDANCE: dict[str, dict[str, str]] = {
    "zero_length": {
        "explanation": "A line entity has identical start and end points (zero length), making geometric matching and dimensional assessment invalid.",
        "suggested_correction": "Inspect the identified entity in AutoCAD. Remove it only if it is unintended. OVERKILL may help locate duplicate or zero-length geometry, but review the result before saving.",
    },
    "zero_radius": {
        "explanation": "A circle or arc entity has a non-positive or zero radius, which represents degenerate geometry that cannot be evaluated.",
        "suggested_correction": "Inspect the entity in AutoCAD. Specify a valid positive radius in Properties, or remove the entity if it is not part of the required drawing.",
    },
    "missing_units": {
        "explanation": "The reference DXF does not declare insertion units ($INSUNITS is 0), which may lead to scaling ambiguity when comparing student submissions.",
        "suggested_correction": "Open the reference drawing in AutoCAD, run UNITS, and set the intended insertion scale (such as Millimeters or Inches) before saving.",
    },
    "unsupported_entity": {
        "explanation": "The reference contains entity types not supported by DraftLens 2D foundation grading, which will be omitted during assessment.",
        "suggested_correction": "Review the entity in AutoCAD. If the geometry is required for assessment, convert or explode it into supported 2D entities (lines, arcs, or polylines).",
    },
    "open_polyline": {
        "explanation": "Polyline endpoints are nearly coincident but the polyline is not marked closed; verify whether a closed boundary was intended.",
        "suggested_correction": "Inspect the vertex endpoints in AutoCAD. If the shape is intended to form a closed boundary, use PEDIT or set Closed to Yes in the Properties palette.",
    },
    "duplicate_geometry": {
        "explanation": "Multiple identical entities exist at the same position and layer in the reference drawing, which can cause ambiguous or unfair grading.",
        "suggested_correction": "Inspect the coincident geometry in AutoCAD. Remove redundant overlapping copies. OVERKILL can assist in detecting duplicates, but review changes before saving.",
    },
    "extreme_coordinates": {
        "explanation": "Reference extents or coordinates exceed 1,000,000 drawing units, which often indicates misplaced geometry or incorrect unit insertion.",
        "suggested_correction": "Use ZOOM Extents in AutoCAD to inspect for distant stray entities or residual construction geometry, and verify drawing origin and units.",
    },
    "inconsistent_layers": {
        "explanation": "All reference entities are placed on a single layer, which may prevent layer-based standards verification if required by the assignment.",
        "suggested_correction": "Verify whether the assignment rubric requires specific layer organization. Distribute entities to appropriate layers if layer standards are assessed.",
    },
}

def _safe_entity_attr(entity: Any, attr: str, default: Any = None) -> Any:
    if entity is None:
        return default
    if isinstance(entity, dict):
        return entity.get(attr, default)
    return getattr(entity, attr, default)

def _extract_entity_type(entity: Any) -> str | None:
    if entity is None:
        return None
    val = _safe_entity_attr(entity, "entity_type")
    if val:
        return str(val)
    kind = _safe_entity_attr(entity, "kind")
    if kind:
        return {"polyline": "LWPOLYLINE"}.get(kind, str(kind).upper())
    return None

def _extract_source_handle(entity: Any) -> str | None:
    if entity is None:
        return None
    val = _safe_entity_attr(entity, "source_handle")
    if val is not None:
        return str(val)
    handle = _safe_entity_attr(entity, "handle")
    if handle is not None:
        return str(handle)
    return None

def _extract_layer(entity: Any) -> str | None:
    if entity is None:
        return None
    val = _safe_entity_attr(entity, "layer")
    return str(val) if val is not None else None

def _extract_location(entity: Any) -> tuple[float, float] | list[float] | None:
    if entity is None:
        return None
    loc = _safe_entity_attr(entity, "centroid")
    if loc is None:
        loc = _safe_entity_attr(entity, "location")
    if loc is not None:
        try:
            return (float(loc[0]), float(loc[1]))
        except (IndexError, TypeError, ValueError):
            return None
    return None

def _extract_entity_id(entity: Any) -> str | None:
    if entity is None:
        return None
    val = _safe_entity_attr(entity, "id")
    if val is None:
        val = _safe_entity_attr(entity, "entity_id")
    return str(val) if val is not None else None

def _finding(
    code: str,
    severity: str,
    message: str,
    entity: Any = None,
    *,
    entity_type: str | None = None,
    source_handle: str | None = None,
    layer: str | None = None,
    location: tuple[float, float] | list[float] | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    resolved_entity_id = entity_id or _extract_entity_id(entity)
    resolved_entity_type = entity_type or _extract_entity_type(entity)
    resolved_handle = source_handle or _extract_source_handle(entity)
    resolved_layer = layer or _extract_layer(entity)
    resolved_location = location or _extract_location(entity)

    guidance = REFERENCE_FINDING_GUIDANCE.get(code, {})
    explanation = guidance.get("explanation") or message
    suggested_correction = guidance.get(
        "suggested_correction",
        "Inspect the reference drawing in AutoCAD to verify the geometry matches assignment requirements.",
    )

    blocks_reference = (severity == "critical")

    return {
        "code": code,
        "severity": severity,
        "message": message,
        "entity_id": resolved_entity_id,
        "location": resolved_location,
        "entity_type": resolved_entity_type,
        "source_handle": resolved_handle,
        "layer": resolved_layer,
        "blocks_reference": blocks_reference,
        "explanation": explanation,
        "suggested_correction": suggested_correction,
    }

def _signature(entity: Entity) -> tuple:
    return (entity.kind, tuple(entity.points), round(entity.radius or 0, 6), entity.closed)

def _is_near_closed_polyline(entity: Entity) -> bool:
    if entity.kind != "polyline" or entity.closed or len(entity.points) < 3:
        return False
    path_length = entity_length(entity) or 0.0
    if path_length <= GEOMETRIC_TOLERANCE:
        return False
    if entity.bbox is not None:
        width = entity.bbox[2] - entity.bbox[0]
        height = entity.bbox[3] - entity.bbox[1]
    else:
        xs = [point[0] for point in entity.points]
        ys = [point[1] for point in entity.points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
    diagonal = math.hypot(width, height)
    if diagonal <= GEOMETRIC_TOLERANCE:
        return False
    endpoint_distance = math.dist(entity.points[0], entity.points[-1])
    relative_limit = min(diagonal, path_length) * NEAR_CLOSURE_RATIO
    closure_limit = max(GEOMETRIC_TOLERANCE, relative_limit)
    return endpoint_distance <= closure_limit

def validate_reference(drawing: Drawing) -> dict:
    """Return deterministic reference-quality findings before rubric approval."""
    findings: list[dict] = []
    if drawing.units_code == 0:
        findings.append(_finding("missing_units", "warning", "The reference DXF does not declare insertion units."))
    for unsupported in drawing.unsupported_entities:
        findings.append(_finding(
            "unsupported_entity",
            "warning",
            f"Unsupported {unsupported.get('entity_type', 'entity')} entity requires instructor review.",
            entity=unsupported,
            entity_type=unsupported.get("entity_type"),
            source_handle=unsupported.get("handle"),
            layer=unsupported.get("layer"),
        ))
    signatures: dict[tuple, list[Entity]] = defaultdict(list)
    for entity in drawing.entities:
        signatures[_signature(entity)].append(entity)
        if entity.kind == "line":
            length = entity_length(entity)
            if length is not None and length <= 1e-9:
                findings.append(_finding("zero_length", "critical", "A zero-length line makes the reference invalid.", entity))
        if entity.kind in {"circle", "arc"} and (entity.radius is None or entity.radius <= 0):
            findings.append(_finding("zero_radius", "critical", "A circle or arc has a non-positive radius.", entity))
        if _is_near_closed_polyline(entity):
            findings.append(_finding(
                "open_polyline",
                "warning",
                "Polyline endpoints are nearly coincident but the polyline is not marked closed; verify the intended boundary.",
                entity,
            ))
    for group in signatures.values():
        for duplicate in group[1:]:
            findings.append(_finding("duplicate_geometry", "warning", "Duplicate reference geometry may cause unfair grading.", duplicate))
    topology = build_topology(drawing, tolerance=GEOMETRIC_TOLERANCE)
    width = drawing.bbox[2] - drawing.bbox[0]
    height = drawing.bbox[3] - drawing.bbox[1]
    if max(abs(v) for v in drawing.bbox) > 1_000_000 or max(width, height) > 1_000_000:
        findings.append(_finding("extreme_coordinates", "warning", "Reference extents are unusually large; verify units and residual geometry."))
    layers = Counter(entity.layer for entity in drawing.entities)
    if len(layers) == 1 and len(drawing.entities) >= 20:
        findings.append(_finding("inconsistent_layers", "warning", "All reference geometry is on one layer; verify the assignment layer policy."))
    critical = sum(item["severity"] == "critical" for item in findings)
    warnings = len(findings) - critical
    return {
        "valid": critical == 0,
        "can_continue": critical == 0,
        "requires_acknowledgement": warnings > 0,
        "summary": {"critical": critical, "warnings": warnings, "supported_entities": len(drawing.entities), "unsupported_entities": len(drawing.unsupported_entities)},
        "findings": findings,
        "topology": topology.to_dict(),
    }
