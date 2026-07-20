from __future__ import annotations
import math
from collections import Counter
from .models import Drawing

NEUTRAL_CONSTRUCTION_TYPE = "Geometric Construction Exercise"
NEUTRAL_MIXED_TYPE = "Mixed Geometric Composition"


def analyze_assignment(drawing: Drawing) -> dict:
    """Summarize deterministic drawing features for rubric suggestion."""
    entity_counts = Counter(entity.entity_type for entity in drawing.entities)
    layers = Counter(entity.layer for entity in drawing.entities)
    width = drawing.bbox[2] - drawing.bbox[0]
    height = drawing.bbox[3] - drawing.bbox[1]
    area = max(width * height, 1.0)
    radii = [round(entity.radius, 4) for entity in drawing.entities if entity.radius is not None]
    repeated_radii = [value for value, count in Counter(radii).items() if count >= 2]
    line_angles = []
    for entity in drawing.entities:
        if entity.kind == "line" and len(entity.points) == 2:
            a, b = entity.points
            line_angles.append(round(math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 180, 1))
    repeated_angles = [value for value, count in Counter(line_angles).items() if count >= 3]
    closed_polylines = sum(
        entity.kind == "polyline" and entity.closed for entity in drawing.entities
    )
    closed = closed_polylines + sum(
        entity.kind in {"circle", "ellipse"} for entity in drawing.entities
    )
    radial_count = entity_counts.get("CIRCLE", 0) + entity_counts.get("ARC", 0)
    geometry_kinds = {
        entity.kind
        for entity in drawing.entities
        if entity.kind in {"line", "polyline", "circle", "arc", "ellipse", "spline"}
    }
    features = []
    if radial_count >= 4 or repeated_radii:
        features.append("radial structure")
    if repeated_angles:
        features.append("repeated angles")
    if closed:
        features.append("closed boundaries")
    if entity_counts.get("DIMENSION", 0):
        features.append("dimensions")
    if entity_counts.get("TEXT", 0):
        features.append("annotation")
    if len(drawing.entities) >= 40 and repeated_angles:
        features.append("possible repeated or symmetric structure")
    orthogonal_angles = bool(line_angles) and all(
        min(abs(angle), abs(angle - 90.0), abs(angle - 180.0)) <= 0.1
        for angle in line_angles
    )
    if len(line_angles) >= 4 and orthogonal_angles:
        features.append("orthogonal plan-like structure")
    if len(geometry_kinds) >= 2:
        features.append("mixed geometric primitives")
    suggested_assignment_type = (
        NEUTRAL_MIXED_TYPE if len(geometry_kinds) >= 2 else NEUTRAL_CONSTRUCTION_TYPE
    )
    suggested = ["missing_geometry", "extra_geometry", "incorrect_position", "duplicate_geometry"]
    if entity_counts.get("LINE", 0) or entity_counts.get("LWPOLYLINE", 0):
        suggested += ["incorrect_length", "incorrect_angle", "connectivity"]
    if radial_count:
        suggested += ["incorrect_radius"]
    if closed_polylines:
        suggested += ["polyline_closure"]
    return {
        "suggested_assignment_type": suggested_assignment_type,
        "assignment_type": None,
        "likely_assignment_type": suggested_assignment_type,
        "entity_counts": dict(sorted(entity_counts.items())),
        "layer_distribution": dict(sorted(layers.items())),
        "drawing_extents": {"min_x": drawing.bbox[0], "min_y": drawing.bbox[1], "max_x": drawing.bbox[2], "max_y": drawing.bbox[3], "width": width, "height": height},
        "geometric_density": round(len(drawing.entities) / area, 6),
        "closed_boundaries": closed,
        "repeated_radii": repeated_radii,
        "repeated_angles": repeated_angles,
        "detected_features": features,
        "suggested_checks": list(dict.fromkeys(suggested)),
    }
