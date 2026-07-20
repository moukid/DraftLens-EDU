from __future__ import annotations
from collections import Counter, defaultdict
from .dxf import entity_length
from .models import Drawing, Entity
from .topology import build_topology

def _finding(code: str, severity: str, message: str, entity: Entity | None = None) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "entity_id": entity.id if entity else None,
        "location": entity.centroid if entity else None,
    }

def _signature(entity: Entity) -> tuple:
    return (entity.kind, tuple(entity.points), round(entity.radius or 0, 6), entity.closed)

def validate_reference(drawing: Drawing) -> dict:
    """Return deterministic reference-quality findings before rubric approval."""
    findings: list[dict] = []
    if drawing.units_code == 0:
        findings.append(_finding("missing_units", "warning", "The reference DXF does not declare insertion units."))
    for unsupported in drawing.unsupported_entities:
        findings.append({
            "code": "unsupported_entity", "severity": "warning",
            "message": f"Unsupported {unsupported['entity_type']} entity requires instructor review.",
            "entity_id": None, "location": None, "source_handle": unsupported.get("handle"),
        })
    signatures: dict[tuple, list[Entity]] = defaultdict(list)
    for entity in drawing.entities:
        signatures[_signature(entity)].append(entity)
        if entity.kind == "line":
            length = entity_length(entity)
            if length is not None and length <= 1e-9:
                findings.append(_finding("zero_length", "critical", "A zero-length line makes the reference invalid.", entity))
        if entity.kind in {"circle", "arc"} and (entity.radius is None or entity.radius <= 0):
            findings.append(_finding("zero_radius", "critical", "A circle or arc has a non-positive radius.", entity))
        if entity.kind == "polyline" and not entity.closed:
            findings.append(_finding("open_polyline", "warning", "An open polyline may be an incomplete expected boundary.", entity))
    for group in signatures.values():
        for duplicate in group[1:]:
            findings.append(_finding("duplicate_geometry", "warning", "Duplicate reference geometry may cause unfair grading.", duplicate))
    topology = build_topology(drawing)
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
