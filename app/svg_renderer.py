from __future__ import annotations

from html import escape
import math
from typing import Any

from .reviewed_dxf import ReviewedDrawing, ReviewedEntity, ReviewedIssue


SVG_STYLE = """svg{background:#fff}g{vector-effect:non-scaling-stroke}.reference{fill:none;stroke:#2f855a;stroke-width:1;opacity:.42}.student{fill:none;stroke:#24313a;stroke-width:1.35}.missing{fill:none;stroke:#ed8936;stroke-width:3;stroke-dasharray:9 6}.extra{fill:none;stroke:#3182ce;stroke-width:3}.inaccurate-expected{fill:none;stroke:#ed8936;stroke-width:2;stroke-dasharray:7 5}.inaccurate-actual{fill:none;stroke:#e53e3e;stroke-width:3}.connectivity{fill:none;stroke:#d53f8c;stroke-width:3}.warning{fill:#ecc94b;fill-opacity:.12;stroke:#b7791f;stroke-width:2;stroke-dasharray:4 4}.critical{fill:#e53e3e;fill-opacity:.12;stroke:#c53030;stroke-width:3}.entity-text{font:12px sans-serif;fill:currentColor;stroke:none}.empty{font:14px sans-serif;fill:#718096;stroke:none}"""


def _number(value: float) -> str:
    if not math.isfinite(float(value)):
        raise ValueError("SVG coordinates must be finite.")
    value = 0.0 if abs(float(value)) < 1e-14 else float(value)
    return format(value, ".12g")


def _attribute(value: Any) -> str:
    return escape(str(value), quote=True)


class CoordinateTransform:
    """Stable fit transform: uniform scale, fixed margin, and inverted CAD Y axis."""

    def __init__(self, extents: tuple[float, float, float, float], width: float, height: float, margin: float):
        if not all(math.isfinite(float(value)) for value in (*extents, width, height, margin)):
            raise ValueError("SVG dimensions and extents must be finite.")
        if width <= 0 or height <= 0 or margin < 0 or margin * 2 >= min(width, height):
            raise ValueError("SVG dimensions must leave a positive drawable area.")
        min_x, min_y, max_x, max_y = (float(value) for value in extents)
        if min_x > max_x or min_y > max_y:
            raise ValueError("Drawing extents are invalid.")
        span_x, span_y = max_x - min_x, max_y - min_y
        self.empty = span_x == 0 and span_y == 0
        if span_x == 0:
            min_x -= max(span_y * 0.5, 1.0)
            max_x += max(span_y * 0.5, 1.0)
            span_x = max_x - min_x
        if span_y == 0:
            min_y -= max(span_x * 0.5, 1.0)
            max_y += max(span_x * 0.5, 1.0)
            span_y = max_y - min_y
        available_width, available_height = width - 2 * margin, height - 2 * margin
        self.scale = min(available_width / span_x, available_height / span_y)
        self.min_x, self.max_y = min_x, max_y
        self.offset_x = margin + (available_width - span_x * self.scale) / 2
        self.offset_y = margin + (available_height - span_y * self.scale) / 2
        self.width, self.height, self.margin = width, height, margin

    def point(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            self.offset_x + (float(x) - self.min_x) * self.scale,
            self.offset_y + (self.max_y - float(y)) * self.scale,
        )

    def length(self, value: float) -> float:
        return abs(float(value)) * self.scale


def _points(points: tuple[tuple[float, float], ...], transform: CoordinateTransform) -> str:
    return " ".join(f"{_number(x)},{_number(y)}" for x, y in (transform.point(point) for point in points))


def _entity_svg(entity: ReviewedEntity, css_class: str, transform: CoordinateTransform, suffix: str) -> str:
    classes = css_class + (" entity-text" if entity.kind == "text" else "")
    attrs = (
        f'class="{_attribute(classes)}" '
        f'data-entity-id="{_attribute(entity.entity_id)}" '
        f'data-source="{_attribute(entity.source)}" '
        f'data-layer="{_attribute(entity.layer)}" '
        f'data-render-key="{_attribute(entity.entity_id + suffix)}" '
        'vector-effect="non-scaling-stroke"'
    )
    points = tuple(sorted(entity.points)) if entity.kind == "line" else entity.points
    if entity.kind == "line" and len(points) >= 2:
        a, b = transform.point(points[0]), transform.point(points[-1])
        return f'<line {attrs} x1="{_number(a[0])}" y1="{_number(a[1])}" x2="{_number(b[0])}" y2="{_number(b[1])}"/>'
    if entity.kind in {"polyline", "spline", "dimension"} and points:
        tag = "polygon" if entity.kind == "polyline" and entity.closed else "polyline"
        return f'<{tag} {attrs} points="{_points(points, transform)}" fill="none"/>'
    if entity.kind == "circle" and points and entity.radius is not None:
        center = transform.point(points[0])
        return f'<circle {attrs} cx="{_number(center[0])}" cy="{_number(center[1])}" r="{_number(transform.length(entity.radius))}"/>'
    if entity.kind == "arc" and points and entity.radius is not None and entity.start_angle is not None and entity.end_angle is not None:
        center_x, center_y = points[0]
        start = math.radians(entity.start_angle)
        end = math.radians(entity.end_angle)
        start_point = transform.point((center_x + entity.radius * math.cos(start), center_y + entity.radius * math.sin(start)))
        end_point = transform.point((center_x + entity.radius * math.cos(end), center_y + entity.radius * math.sin(end)))
        span = (entity.end_angle - entity.start_angle) % 360
        large_arc = 1 if span > 180 else 0
        radius = transform.length(entity.radius)
        return f'<path {attrs} d="M {_number(start_point[0])} {_number(start_point[1])} A {_number(radius)} {_number(radius)} 0 {large_arc} 0 {_number(end_point[0])} {_number(end_point[1])}"/>'
    if entity.kind == "ellipse" and points:
        major = entity.properties.get("major_axis", [0.0, 0.0])
        if len(major) >= 2:
            rx = math.hypot(float(major[0]), float(major[1]))
            ry = rx * abs(float(entity.properties.get("ratio", 1.0)))
            angle = -math.degrees(math.atan2(float(major[1]), float(major[0])))
            center = transform.point(points[0])
            return f'<ellipse {attrs} cx="{_number(center[0])}" cy="{_number(center[1])}" rx="{_number(transform.length(rx))}" ry="{_number(transform.length(ry))}" transform="rotate({_number(angle)} {_number(center[0])} {_number(center[1])})"/>'
    if entity.kind == "text" and points:
        point = transform.point(points[0])
        return f'<text {attrs} x="{_number(point[0])}" y="{_number(point[1])}">{escape(entity.text or "")}</text>'
    return ""


def _region_svg(issue: ReviewedIssue, transform: CoordinateTransform) -> str:
    if not issue.region:
        return ""
    min_x, min_y, max_x, max_y = issue.region
    top_left = transform.point((min_x, max_y))
    bottom_right = transform.point((max_x, min_y))
    width = max(abs(bottom_right[0] - top_left[0]), 8.0)
    height = max(abs(bottom_right[1] - top_left[1]), 8.0)
    x = top_left[0] - (width - abs(bottom_right[0] - top_left[0])) / 2
    y = top_left[1] - (height - abs(bottom_right[1] - top_left[1])) / 2
    return f'<rect class="{_attribute(issue.visual_role)}" data-issue-id="{_attribute(issue.issue_id)}" x="{_number(x)}" y="{_number(y)}" width="{_number(width)}" height="{_number(height)}" vector-effect="non-scaling-stroke"/>'


def _issue_svg(issue: ReviewedIssue, transform: CoordinateTransform) -> list[str]:
    output: list[str] = []
    issue_attr = f'data-issue-id="{_attribute(issue.issue_id)}"'
    if issue.visual_role == "missing" and issue.expected_geometry:
        output.append(f'<g {issue_attr} data-role="missing">{_entity_svg(issue.expected_geometry, "missing", transform, "-missing")}</g>')
    elif issue.visual_role == "extra" and issue.actual_geometry:
        output.append(f'<g {issue_attr} data-role="extra">{_entity_svg(issue.actual_geometry, "extra", transform, "-extra")}</g>')
    elif issue.visual_role == "inaccurate":
        parts = []
        if issue.expected_geometry:
            parts.append(_entity_svg(issue.expected_geometry, "inaccurate-expected", transform, "-expected"))
        if issue.actual_geometry:
            parts.append(_entity_svg(issue.actual_geometry, "inaccurate-actual", transform, "-actual"))
        output.append(f'<g {issue_attr} data-role="inaccurate">{"".join(parts)}</g>')
    elif issue.visual_role == "connectivity":
        region = _region_svg(issue, transform)
        if region:
            output.append(f'<g {issue_attr} data-role="connectivity">{region}</g>')
    else:
        region = _region_svg(issue, transform)
        if region:
            output.append(f'<g {issue_attr} data-role="{_attribute(issue.visual_role)}">{region}</g>')
        else:
            output.append(f'<g {issue_attr} data-role="{_attribute(issue.visual_role)}" class="{_attribute(issue.visual_role)}" data-geometry="unavailable"></g>')
    return output


def render_svg(reviewed: ReviewedDrawing, width: float = 1200, height: float = 800, margin: float = 32) -> str:
    """Serialize a reviewed snapshot as deterministic, escaped, standalone SVG."""

    transform = CoordinateTransform(reviewed.extents, float(width), float(height), float(margin))
    root = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_number(width)}" height="{_number(height)}" '
        f'viewBox="0 0 {_number(width)} {_number(height)}" role="img" aria-label="DraftLens reviewed drawing" '
        f'data-min-x="{_number(reviewed.extents[0])}" data-min-y="{_number(reviewed.extents[1])}" '
        f'data-max-x="{_number(reviewed.extents[2])}" data-max-y="{_number(reviewed.extents[3])}" '
        f'data-scale="{_number(transform.scale)}" data-margin="{_number(margin)}">'
    )
    parts = [root, f"<style>{SVG_STYLE}</style>", "<desc>Deterministic CAD review overlay. Y coordinates are inverted from CAD space.</desc>"]
    if transform.empty and not reviewed.reference_entities and not reviewed.student_entities:
        parts.append(f'<text class="empty" x="{_number(width / 2)}" y="{_number(height / 2)}" text-anchor="middle">No drawable geometry</text>')
    parts.append('<g data-layer="reference">')
    parts.extend(_entity_svg(entity, "reference", transform, "-reference") for entity in reviewed.reference_entities)
    parts.append('</g><g data-layer="student">')
    parts.extend(_entity_svg(entity, "student", transform, "-student") for entity in reviewed.student_entities)
    parts.append('</g><g data-layer="issues">')
    for issue in reviewed.issues:
        parts.extend(_issue_svg(issue, transform))
    parts.append("</g></svg>")
    return "".join(parts)
