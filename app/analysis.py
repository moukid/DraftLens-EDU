from __future__ import annotations
import math
from collections import Counter
from .models import Drawing

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
    closed = sum(entity.kind == "polyline" and entity.closed for entity in drawing.entities)
    radial_count = entity_counts.get("CIRCLE", 0) + entity_counts.get("ARC", 0)
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
    likely = "technical_drawing" if entity_counts.get("DIMENSION", 0) else "geometric_reasoning"
    if radial_count >= 8 and len(drawing.entities) >= 30:
        likely = "islamic_geometric_pattern"
    suggested = ["missing_geometry", "extra_geometry", "incorrect_position", "duplicate_geometry"]
    if entity_counts.get("LINE", 0) or entity_counts.get("LWPOLYLINE", 0):
        suggested += ["incorrect_length", "incorrect_angle", "connectivity"]
    if radial_count:
        suggested += ["incorrect_radius"]
    if closed:
        suggested += ["polyline_closure"]
    return {
        "likely_assignment_type": likely,
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
