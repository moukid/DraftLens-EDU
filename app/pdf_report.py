from __future__ import annotations

from html import escape
from importlib.resources import files
from io import BytesIO
import math
from pathlib import PurePath
import re
import unicodedata
from urllib.parse import quote
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import CondPageBreak, Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .review_snapshot import ReviewSnapshot
from .finding_presentation import compact_finding_presentation, essential_finding
from .reviewed_dxf import ReviewedDrawing, ReviewedEntity, ReviewedIssue, sample_ellipse_arc
from .svg_renderer import CoordinateTransform

FONT_NAME = "DraftLensVera"
FONT_BOLD = "DraftLensVeraBold"
_INVALID_FILENAME = re.compile(r"[<>:\"/\\|?*\x00-\x1f\x7f]+")
_SAFE_ASCII = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_FONT_CHARACTERS: set[int] | None = None


def _register_fonts() -> None:
    global _FONT_CHARACTERS
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        font_root = files("reportlab").joinpath("fonts")
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_root.joinpath("Vera.ttf"))))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(font_root.joinpath("VeraBd.ttf"))))
    if _FONT_CHARACTERS is None:
        _FONT_CHARACTERS = set(pdfmetrics.getFont(FONT_NAME).face.charToGlyph)


def _display_text(value: Any) -> str:
    """Use bundled fonts and losslessly spell unsupported Unicode code points."""
    _register_fonts()
    text = str(value) if value is not None else "Not provided"
    output: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character in "\n\t" or codepoint in (_FONT_CHARACTERS or set()):
            output.append(character)
        else:
            output.append(f" U+{codepoint:04X} ")
    return "".join(output)


def _paragraph_text(value: Any) -> str:
    return escape(_display_text(value), quote=True).replace("\n", "<br/>")


def _basename(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "drawing.dxf")).replace("\\", "/")
    return PurePath(normalized).name or "drawing.dxf"


def _safe_stem(value: str, *, ascii_only: bool, maximum: int = 80) -> str:
    stem = unicodedata.normalize("NFC", PurePath(_basename(value)).stem)
    stem = _INVALID_FILENAME.sub("_", stem).strip(" ._")
    if ascii_only:
        stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
        stem = _SAFE_ASCII.sub("_", stem).strip(" ._")
    stem = stem or "Drawing"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return stem[:maximum].rstrip(" ._") or "Drawing"


def report_filenames(snapshot: ReviewSnapshot) -> tuple[str, str]:
    assignment_ascii = _safe_stem(snapshot.reference_filename, ascii_only=True, maximum=60)
    assignment_unicode = _safe_stem(snapshot.reference_filename, ascii_only=False, maximum=60)
    if snapshot.student_metadata.student_id:
        safe_identifier = snapshot.student_metadata.student_id.replace("/", "_").replace("\\", "_")
        identifier_ascii = _safe_stem(safe_identifier, ascii_only=True, maximum=40)
        identifier_unicode = _safe_stem(safe_identifier, ascii_only=False, maximum=40)
        ascii_stem = f"{identifier_ascii}_{assignment_ascii}"
        unicode_stem = f"{identifier_unicode}_{assignment_unicode}"
    else:
        ascii_stem = _safe_stem(snapshot.student_filename, ascii_only=True, maximum=100)
        unicode_stem = _safe_stem(snapshot.student_filename, ascii_only=False, maximum=100)
    return f"{ascii_stem[:120]}_DraftLens_Report.pdf", f"{unicode_stem[:120]}_DraftLens_Report.pdf"


def content_disposition(snapshot: ReviewSnapshot) -> str:
    ascii_name, unicode_name = report_filenames(snapshot)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(unicode_name, safe="")}'


class _InvariantCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any):
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


_ROLE_STYLE = {
    "reference": ("#2f855a", .65, None), "student": ("#24313a", .9, None),
    "missing": ("#ed8936", 2.1, (6, 4)), "extra": ("#3182ce", 2.1, None),
    "inaccurate-expected": ("#fc8181", 1.5, (5, 3)), "inaccurate-actual": ("#e53e3e", 2.1, None),
    "connectivity": ("#d53f8c", 2, None), "warning": ("#b7791f", 1.5, (3, 3)), "critical": ("#c53030", 2.2, None),
}

_LEGEND_ENTRIES = (
    ("reference", "Reference", "Approved instructor geometry"),
    ("student", "Student", "Submitted student geometry"),
    ("missing", "Missing", "Required reference geometry absent from the submission"),
    ("extra", "Extra", "Unmatched geometry found only in the submission"),
    ("inaccurate", "Inaccurate", "Matched geometry outside the approved tolerance"),
    ("connectivity", "Connectivity", "Junction, closure, or topology evidence"),
    ("warning", "Warning", "Non-critical advisory or validation note"),
    ("critical", "Critical", "Severe validation or assessment condition"),
)


def _segments_cross(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    """Exact interior segment intersection matching Codex's vector audit."""
    ux = p2[0] - p1[0]
    uy = p2[1] - p1[1]
    vx = p4[0] - p3[0]
    vy = p4[1] - p3[1]
    wx = p3[0] - p1[0]
    wy = p3[1] - p1[1]
    den = ux * vy - uy * vx
    if abs(den) < 1e-8:
        return False
    t = (wx * vy - wy * vx) / den
    s = (wx * uy - wy * ux) / den
    return 1e-6 < t < 1.0 - 1e-6 and 1e-6 < s < 1.0 - 1e-6


def _is_detached_placement_issue(issue: ReviewedIssue) -> bool:
    """Return True when an object-level placement issue carries raw detached reference geometry."""
    if issue.visual_role != "inaccurate" or issue.category != "incorrect_position" or issue.component_id:
        return False
    act_geoms = issue.actual_geometries or ((issue.actual_geometry,) if issue.actual_geometry else ())
    return bool(act_geoms)


def _set_role_style(pdf: canvas.Canvas, role: str) -> None:
    color, width, dash = _ROLE_STYLE[role]
    pdf.setStrokeColor(colors.HexColor(color))
    pdf.setFillColor(colors.HexColor(color))
    pdf.setLineWidth(width)
    pdf.setDash(dash or [])


class LegendSampleFlowable(Flowable):
    """Compact vector sample using the reviewed drawing's exact role style."""

    def __init__(self, role: str, width: float = 24, height: float = 18):
        super().__init__()
        self.role, self.width, self.height = role, float(width), float(height)

    def wrap(self, _available_width: float, _available_height: float) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        self.canv.saveState()
        if self.role == "inaccurate":
            _set_role_style(self.canv, "inaccurate-expected")
            self.canv.line(1, self.height * .68, self.width - 1, self.height * .68)
            _set_role_style(self.canv, "inaccurate-actual")
            self.canv.line(1, self.height * .32, self.width - 1, self.height * .32)
        elif self.role in {"connectivity", "warning", "critical"}:
            _set_role_style(self.canv, self.role)
            self.canv.rect(2, 3, self.width - 4, self.height - 6, stroke=1, fill=0)
        else:
            _set_role_style(self.canv, self.role)
            self.canv.line(1, self.height / 2, self.width - 1, self.height / 2)
        self.canv.restoreState()


class ReviewedDrawingFlowable(Flowable):
    """ReportLab-vector rendering of the exact immutable reviewed drawing."""

    def __init__(
        self,
        reviewed: ReviewedDrawing,
        width: float,
        height: float | None = None,
        *,
        allowed_badge_labels: set[str] | None = None,
        representative_issue_ids: set[str] | None = None,
        role_filter: str | None = None,
        extents: tuple[float, float, float, float] | None = None,
        allowed_issue_ids: set[str] | None = None,
    ):
        super().__init__()
        self.reviewed = reviewed
        self.width = float(width)
        self.allowed_badge_labels = allowed_badge_labels
        self.representative_issue_ids = representative_issue_ids
        self.role_filter = role_filter
        self.extents = extents
        self.allowed_issue_ids = allowed_issue_ids
        if height is not None:
            self.height = float(height)
        else:
            ext = reviewed.extents
            span_x = (ext[2] - ext[0]) if len(ext) >= 4 else 0.0
            span_y = (ext[3] - ext[1]) if len(ext) >= 4 else 0.0
            if span_x > 1e-6:
                aspect = span_y / span_x
                proportional_h = (self.width - 24) * aspect + 36
                self.height = float(round(max(150.0, min(proportional_h, 280.0)), 1))
            else:
                self.height = 200.0

    def wrap(self, available_width: float, _available_height: float) -> tuple[float, float]:
        return min(self.width, available_width), self.height

    def _point(self, transform: CoordinateTransform, point: tuple[float, float]) -> tuple[float, float]:
        x, screen_y = transform.point(point)
        return x, self.height - screen_y

    def _style(self, role: str) -> None:
        _set_role_style(self.canv, role)

    def _apply_short_missing_style(self, canvas_length: float) -> None:
        if 0.0 < canvas_length < 24.0:
            dash_on = max(2.2, min(4.2, canvas_length / 4.2))
            dash_off = max(1.2, dash_on * 0.45)
            self.canv.setLineWidth(2.4)
            self.canv.setDash((dash_on, dash_off))

    def _entity(self, entity: ReviewedEntity, role: str, transform: CoordinateTransform) -> None:
        self._style(role)
        points = tuple(sorted(entity.points)) if entity.kind == "line" else entity.points
        if entity.kind == "line" and len(points) >= 2:
            start, end = self._point(transform, points[0]), self._point(transform, points[-1])
            if role == "missing":
                self._apply_short_missing_style(math.hypot(end[0] - start[0], end[1] - start[1]))
            self.canv.line(start[0], start[1], end[0], end[1])
        elif entity.kind in {"polyline", "spline", "dimension"} and points:
            pts_screen = [self._point(transform, pt) for pt in points]
            if role == "missing":
                seg_total = sum(
                    math.hypot(pts_screen[i + 1][0] - pts_screen[i][0], pts_screen[i + 1][1] - pts_screen[i][1])
                    for i in range(len(pts_screen) - 1)
                )
                if entity.kind == "polyline" and entity.closed and len(pts_screen) >= 3:
                    seg_total += math.hypot(pts_screen[0][0] - pts_screen[-1][0], pts_screen[0][1] - pts_screen[-1][1])
                self._apply_short_missing_style(seg_total)
            path = self.canv.beginPath(); path.moveTo(*pts_screen[0])
            for point in pts_screen[1:]: path.lineTo(*point)
            if entity.kind == "polyline" and entity.closed: path.close()
            self.canv.drawPath(path, stroke=1, fill=0)
        elif entity.kind == "circle" and points and entity.radius is not None:
            center = self._point(transform, points[0]); r_len = transform.length(entity.radius)
            if role == "missing":
                self._apply_short_missing_style(2.0 * math.pi * r_len)
            self.canv.circle(*center, r_len, stroke=1, fill=0)
        elif entity.kind == "arc" and points and entity.radius is not None and entity.start_angle is not None and entity.end_angle is not None:
            center = self._point(transform, points[0]); radius = transform.length(entity.radius)
            extent = (entity.end_angle - entity.start_angle) % 360
            if role == "missing":
                arc_span = extent if extent > 0 else 360.0
                self._apply_short_missing_style(2.0 * math.pi * radius * (arc_span / 360.0))
            self.canv.arc(center[0]-radius, center[1]-radius, center[0]+radius, center[1]+radius, startAng=entity.start_angle, extent=extent)
        elif entity.kind == "ellipse" and points:
            major = entity.properties.get("major_axis", [0.0, 0.0])
            if len(major) >= 2:
                sampled = sample_ellipse_arc(
                    points[0],
                    major,
                    float(entity.properties.get("ratio", 1.0)),
                    entity.properties.get("start_param"),
                    entity.properties.get("end_param"),
                    extrusion=entity.properties.get("extrusion"),
                )
                if sampled is not None and sampled:
                    path = self.canv.beginPath()
                    path.moveTo(*self._point(transform, sampled[0]))
                    for p in sampled[1:]:
                        path.lineTo(*self._point(transform, p))
                    self.canv.drawPath(path, stroke=1, fill=0)
                else:
                    from app.reviewed_dxf import project_ellipse_2d
                    proj = project_ellipse_2d(major, float(entity.properties.get("ratio", 1.0)), entity.properties.get("extrusion"))
                    if proj:
                        rx, ry, angle_rad = proj
                        rx = transform.length(rx); ry = transform.length(ry)
                        angle = math.degrees(angle_rad)
                    else:
                        rx = transform.length(math.hypot(float(major[0]), float(major[1]))); ry = rx * abs(float(entity.properties.get("ratio", 1.0)))
                        angle = math.degrees(math.atan2(float(major[1]), float(major[0])))
                    center = self._point(transform, points[0])
                    self.canv.saveState(); self.canv.translate(*center); self.canv.rotate(angle)
                    if rx < 1e-5 and ry < 1e-5: pass
                    elif rx < 1e-5: self.canv.line(0, -ry, 0, ry)
                    elif ry < 1e-5: self.canv.line(-rx, 0, rx, 0)
                    else: self.canv.ellipse(-rx, -ry, rx, ry, stroke=1, fill=0)
                    self.canv.restoreState()
        elif entity.kind == "text" and points:
            self.canv.setFont(FONT_NAME, 5.5); self.canv.drawString(*self._point(transform, points[0]), _display_text(entity.text or ""))

    def _region(self, issue: ReviewedIssue, transform: CoordinateTransform, role: str) -> None:
        if role == "connectivity":
            meas = issue.measurement if isinstance(issue.measurement, dict) else {}
            actual_points = meas.get("actual_points") or []
            if len(actual_points) >= 2:
                p1 = self._point(transform, actual_points[0])
                p2 = self._point(transform, actual_points[1])
                self._style(role)
                self.canv.circle(p1[0], p1[1], 3, stroke=1, fill=0)
                self.canv.circle(p2[0], p2[1], 3, stroke=1, fill=0)
                self.canv.saveState()
                self.canv.setDash(2, 2)
                self.canv.line(p1[0], p1[1], p2[0], p2[1])
                self.canv.restoreState()
                return
            elif len(actual_points) == 1:
                p = self._point(transform, actual_points[0])
                self._style(role)
                self.canv.circle(p[0], p[1], 3, stroke=1, fill=0)
                return
            elif getattr(issue, "location", None):
                p = self._point(transform, getattr(issue, "location"))
                self._style(role)
                self.canv.circle(p[0], p[1], 3, stroke=1, fill=0)
                return
            elif issue.region:
                rx = (issue.region[0] + issue.region[2]) / 2.0
                ry = (issue.region[1] + issue.region[3]) / 2.0
                p = self._point(transform, (rx, ry))
                self._style(role)
                self.canv.circle(p[0], p[1], 3, stroke=1, fill=0)
                return
            return
        if not issue.region: return
        min_x, min_y, max_x, max_y = issue.region
        first, second = self._point(transform, (min_x, min_y)), self._point(transform, (max_x, max_y))
        natural_width, natural_height = abs(second[0]-first[0]), abs(second[1]-first[1])
        width, height = max(natural_width, 6), max(natural_height, 6)
        x = min(first[0], second[0]) - (width-natural_width)/2; y = min(first[1], second[1]) - (height-natural_height)/2
        self._style(role); self.canv.rect(x, y, width, height, stroke=1, fill=0)

    def _draw_all_badges(self, transform: CoordinateTransform) -> None:
        target_issues = [
            iss for iss in self.reviewed.issues
            if iss.visual_role in {"missing", "extra", "inaccurate", "connectivity", "warning", "critical"}
            and (self.role_filter is None or self.role_filter == "object_detail" or iss.visual_role == self.role_filter)
            and (self.allowed_issue_ids is None or iss.issue_id in self.allowed_issue_ids)
            and not (self.role_filter == "warning" and iss.category.startswith("reference_"))
        ]
        if not target_issues:
            return

        if self.allowed_badge_labels is not None:
            target_issues = [
                iss for iss in target_issues
                if iss.badge_label in self.allowed_badge_labels
            ]

        if not target_issues:
            return

        issue_data: list[dict[str, Any]] = []
        for issue in target_issues:
            feature_pts: list[tuple[float, float]] = []
            if _is_detached_placement_issue(issue):
                geoms = list(issue.actual_geometries or ([issue.actual_geometry] if issue.actual_geometry else []))
            else:
                geoms = list(issue.expected_geometries or ([issue.expected_geometry] if issue.expected_geometry else []))
                geoms += list(issue.actual_geometries or ([issue.actual_geometry] if issue.actual_geometry else []))
            if not geoms:
                if issue.expected_entity_id:
                    ref_match = next((e for e in self.reviewed.reference_entities if e.entity_id == issue.expected_entity_id), None)
                    if ref_match:
                        geoms.append(ref_match)
                if issue.source_entity_id:
                    stu_match = next((e for e in self.reviewed.student_entities if e.entity_id == issue.source_entity_id), None)
                    if stu_match:
                        geoms.append(stu_match)

            def _sample_segment(pt_a: tuple[float, float], pt_b: tuple[float, float]) -> None:
                p1 = self._point(transform, pt_a)
                p2 = self._point(transform, pt_b)
                seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                steps = max(2, min(16, int(seg_len / 6.0)))
                for s in range(steps + 1):
                    frac = s / steps
                    feature_pts.append((p1[0] + (p2[0] - p1[0]) * frac, p1[1] + (p2[1] - p1[1]) * frac))

            for g in geoms:
                if g.kind in ("line", "polyline") and len(g.points) >= 2:
                    for idx in range(len(g.points) - 1):
                        _sample_segment(g.points[idx], g.points[idx + 1])
                    if g.kind == "polyline" and g.closed and len(g.points) >= 3:
                        _sample_segment(g.points[-1], g.points[0])
                elif g.kind in ("arc", "circle"):
                    if g.points:
                        cp = self._point(transform, g.points[0])
                        r_canvas = abs(transform.scale * (g.radius or 0.0)) if hasattr(transform, "scale") else (g.radius or 0.0)
                        if r_canvas > 0:
                            if g.kind == "arc" and g.start_angle is not None and g.end_angle is not None:
                                span = (g.end_angle - g.start_angle) % 360.0
                                for frac in (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0):
                                    rad = math.radians(g.start_angle + frac * span)
                                    feature_pts.append((cp[0] + r_canvas * math.cos(rad), cp[1] + r_canvas * math.sin(rad)))
                            else:
                                for ang_deg in range(0, 360, 45):
                                    rad = math.radians(ang_deg)
                                    feature_pts.append((cp[0] + r_canvas * math.cos(rad), cp[1] + r_canvas * math.sin(rad)))
                        else:
                            # degenerate zero-radius point
                            feature_pts.append(cp)
                elif g.kind == "ellipse" and g.points:
                    major = g.properties.get("major_axis", [0.0, 0.0])
                    if len(major) >= 2:
                        sampled = sample_ellipse_arc(
                            g.points[0],
                            major,
                            float(g.properties.get("ratio", 1.0)),
                            g.properties.get("start_param"),
                            g.properties.get("end_param"),
                            extrusion=g.properties.get("extrusion"),
                        )
                        if sampled is not None and sampled:
                            for p in sampled:
                                feature_pts.append(self._point(transform, p))
                        else:
                            from app.reviewed_dxf import project_ellipse_2d
                            proj = project_ellipse_2d(major, float(g.properties.get("ratio", 1.0)), g.properties.get("extrusion"))
                            if proj:
                                rx, ry, angle_rad = proj
                            else:
                                rx = math.hypot(float(major[0]), float(major[1]))
                                ry = rx * abs(float(g.properties.get("ratio", 1.0)))
                                angle_rad = math.atan2(float(major[1]), float(major[0]))
                            cx_e, cy_e = float(g.points[0][0]), float(g.points[0][1])
                            if rx > 1e-6 or ry > 1e-6:
                                cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
                                for ang_deg in range(0, 360, 45):
                                    t = math.radians(ang_deg)
                                    px = cx_e + rx * math.cos(t) * cos_a - ry * math.sin(t) * sin_a
                                    py = cy_e + rx * math.cos(t) * sin_a + ry * math.sin(t) * cos_a
                                    feature_pts.append(self._point(transform, (px, py)))
                            else:
                                feature_pts.append(self._point(transform, g.points[0]))
                else:
                    for p in g.points:
                        feature_pts.append(self._point(transform, p))

            if not feature_pts and issue.visual_role == "connectivity":
                meas = issue.measurement if isinstance(issue.measurement, dict) else {}
                for pt in meas.get("actual_points") or ():
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        feature_pts.append(self._point(transform, (float(pt[0]), float(pt[1]))))

            has_exact_feature = bool(feature_pts)
            if has_exact_feature:
                xs = [p[0] for p in feature_pts]
                ys = [p[1] for p in feature_pts]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                top_y = max(ys)
                bot_y = min(ys)
            else:
                # Never fabricate feature_pts from a region centroid or unverified location.
                # Use region/location coordinates solely to choose the nearest exterior gutter slot
                # for an unanchored badge pill, and report the limitation explicitly in the notice strip.
                loc = getattr(issue, "location", None)
                if loc and isinstance(loc, (list, tuple)) and len(loc) >= 2:
                    cx, cy = self._point(transform, (float(loc[0]), float(loc[1])))
                    top_y = bot_y = cy
                elif issue.region:
                    min_x, min_y, max_x, max_y = issue.region
                    p1 = self._point(transform, (min_x, min_y))
                    p2 = self._point(transform, (max_x, max_y))
                    cx = (p1[0] + p2[0]) / 2.0
                    cy = (p1[1] + p2[1]) / 2.0
                    top_y = max(p1[1], p2[1])
                    bot_y = min(p1[1], p2[1])
                else:
                    continue
            label = issue.badge_label or issue.issue_id
            text_w = pdfmetrics.stringWidth(label, FONT_BOLD, 6.5)
            bw = max(16.0, text_w + 5.5)
            bh = 11.5
            role = issue.visual_role
            color_hex, _, _ = _ROLE_STYLE.get(role, ("#3182ce", 1, None))
            applied = float(getattr(issue, "final_applied_contribution", 0.0) or 0.0)
            is_rep = bool(
                self.representative_issue_ids and issue.issue_id in self.representative_issue_ids
            )
            issue_data.append({
                "issue": issue,
                "label": label,
                "text_w": text_w,
                "cx": cx,
                "cy": cy,
                "top_y": top_y,
                "bot_y": bot_y,
                "bw": bw,
                "bh": bh,
                "role": role,
                "color_hex": color_hex,
                "applied": applied,
                "is_rep": is_rep,
                "feature_pts": feature_pts,
                "has_exact_feature": has_exact_feature,
            })

        if not issue_data:
            return

        # Collect canvas-space geometry segments so anchors and side selection avoid cutting across walls.
        drawn_segs: list[tuple[float, float, float, float, float, float, float, float]] = []
        geom_xs: list[float] = []
        geom_ys: list[float] = []

        def _add_seg(pa: tuple[float, float], pb: tuple[float, float]) -> None:
            x1, y1 = pa
            x2, y2 = pb
            if math.hypot(x2 - x1, y2 - y1) < 1e-4:
                return
            drawn_segs.append((x1, y1, x2, y2, min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)))
            geom_xs.extend((x1, x2))
            geom_ys.extend((y1, y2))

        def _collect_entity_segs(ent: ReviewedEntity) -> None:
            pts = ent.points or ()
            if ent.kind == "line" and len(pts) >= 2:
                _add_seg(self._point(transform, pts[0]), self._point(transform, pts[-1]))
            elif ent.kind in {"polyline", "spline", "dimension"} and len(pts) >= 2:
                spts = [self._point(transform, p) for p in pts]
                for k in range(len(spts) - 1):
                    _add_seg(spts[k], spts[k + 1])
                if ent.kind == "polyline" and ent.closed and len(spts) >= 3:
                    _add_seg(spts[-1], spts[0])
            elif ent.kind in {"circle", "arc"} and pts and ent.radius is not None:
                cp = self._point(transform, pts[0])
                r_c = transform.length(ent.radius)
                geom_xs.extend((cp[0] - r_c, cp[0] + r_c))
                geom_ys.extend((cp[1] - r_c, cp[1] + r_c))
            elif pts:
                for p in pts:
                    sp = self._point(transform, p)
                    geom_xs.append(sp[0])
                    geom_ys.append(sp[1])

        for stu_ent in self.reviewed.student_entities:
            _collect_entity_segs(stu_ent)
        for iss in target_issues:
            for g in (iss.actual_geometries or ()):
                _collect_entity_segs(g)
            if not _is_detached_placement_issue(iss):
                for g in (iss.expected_geometries or ()):
                    _collect_entity_segs(g)

        def _count_geom_cross(pa: tuple[float, float], pb: tuple[float, float]) -> int:
            min_x = min(pa[0], pb[0])
            max_x = max(pa[0], pb[0])
            min_y = min(pa[1], pb[1])
            max_y = max(pa[1], pb[1])
            cnt = 0
            for x1, y1, x2, y2, sminx, smaxx, sminy, smaxy in drawn_segs:
                if smaxx < min_x or sminx > max_x or smaxy < min_y or sminy > max_y:
                    continue
                if _segments_cross(pa, pb, (x1, y1), (x2, y2)):
                    cnt += 1
            return cnt

        if geom_xs and geom_ys:
            gmin_x, gmax_x = min(geom_xs), max(geom_xs)
            gmin_y, gmax_y = min(geom_ys), max(geom_ys)
        else:
            gm = transform.margin
            gmin_x, gmin_y, gmax_x, gmax_y = gm, gm, self.width - gm, self.height - gm

        # Prioritize representative, paid, and object-placement issues, then 1st finding per distinct entity
        issue_data.sort(key=lambda d: (
            0 if d["is_rep"] else 1,
            0 if d["applied"] > 0.0 else 1,
            0 if not getattr(d["issue"], "component_id", None) else 1,
            -d["applied"],
            d["cx"],
        ))
        seen_ent_counts: dict[str, int] = {}
        for d in issue_data:
            iss = d["issue"]
            ent_key = iss.source_entity_id or iss.expected_entity_id or iss.issue_id
            rank = seen_ent_counts.get(ent_key, 0)
            seen_ent_counts[ent_key] = rank + 1
            d["dup_rank"] = rank
        issue_data.sort(key=lambda d: (
            0 if d["is_rep"] else 1,
            0 if d["applied"] > 0.0 else 1,
            0 if not getattr(d["issue"], "component_id", None) else 1,
            d["dup_rank"],
            -d["applied"],
            d["cx"],
        ))

        geom_margin = transform.margin
        geom_box = (geom_margin, geom_margin, self.width - 2.0 * geom_margin, self.height - 2.0 * geom_margin)

        def _collides_with_geom(b: tuple[float, float, float, float]) -> bool:
            bx, by, bw, bh = b
            gx, gy, gw, gh = geom_box
            return not (bx + bw <= gx or gx + gw <= bx or by + bh <= gy or gy + gh <= by)

        def _collides(b1: tuple[float, float, float, float], b2: tuple[float, float, float, float], pad: float = 2.0) -> bool:
            x1, y1, w1, h1 = b1
            x2, y2, w2, h2 = b2
            return not (x1 + w1 + pad <= x2 or x2 + w2 + pad <= x1 or y1 + h1 + pad <= y2 or y2 + h2 + pad <= y1)

        placed_boxes: list[tuple[float, float, float, float]] = []
        placements: list[tuple[dict[str, Any], tuple[float, float, float, float], tuple[float, float] | None]] = []

        top_gutter_1 = self.height - 15.5
        top_gutter_2 = self.height - 29.0
        bot_gutter_1 = 11.0
        bot_gutter_2 = 24.5

        unplaced_issues: list[dict[str, Any]] = []
        unanchored_issues: list[dict[str, Any]] = []

        # Separate into top and bottom half-planes
        top_list = [d for d in issue_data if d["cy"] >= self.height / 2]
        bot_list = [d for d in issue_data if d["cy"] < self.height / 2]

        def _sort_key(d: dict[str, Any]) -> float:
            if d.get("feature_pts"):
                return sum(p[0] for p in d["feature_pts"]) / len(d["feature_pts"])
            return float(d["cx"])

        avail_w = self.width - 8.0
        max_bw = max((d["bw"] for d in issue_data), default=18.0)
        has_side_space = (gmin_x - 4.0 >= max_bw + 44.0) and ((self.width - 4.0) - gmax_x >= max_bw + 44.0)
        needs_multi_row = (
            sum(d["bw"] + 1.5 for d in top_list) > avail_w
            or sum(d["bw"] + 1.5 for d in bot_list) > avail_w
        )
        use_4side = bool(
            self.role_filter != "object_detail"
            and has_side_space
            and needs_multi_row
            and len(issue_data) > 20
        )

        # Connector helper used during both placement and optimization
        def _get_conn(box: tuple[float, float, float, float], anchor: tuple[float, float]) -> tuple[float, float]:
            bx, by, bw, bh = box
            ax, ay = anchor
            if by >= ay:
                return (max(bx + 2.0, min(bx + bw - 2.0, ax)), by)
            elif by + bh <= ay:
                return (max(bx + 2.0, min(bx + bw - 2.0, ax)), by + bh)
            elif bx >= ax:
                return (bx, max(by + 2.0, min(by + bh - 2.0, ay)))
            elif bx + bw <= ax:
                return (bx + bw, max(by + 2.0, min(by + bh - 2.0, ay)))
            else:
                return (bx + bw / 2.0, by if by > ay else (by + bh))

        def _all_crossings(curr_placements: list[Any]) -> list[tuple[int, int]]:
            pts: list[tuple[int, float, float, float, float, float, float, float, float]] = []
            for idx, item in enumerate(curr_placements):
                anc = item[2]
                if anc is None:
                    continue
                ax, ay = anc
                cx, cy = _get_conn(item[1], anc)
                pts.append((
                    idx,
                    ax, ay, cx, cy,
                    ax if ax < cx else cx,
                    ax if ax > cx else cx,
                    ay if ay < cy else cy,
                    ay if ay > cy else cy,
                ))
            res: list[tuple[int, int]] = []
            m = len(pts)
            for a in range(m):
                i, ax, ay, bx, by, ax0, ax1, ay0, ay1 = pts[a]
                for b in range(a + 1, m):
                    j, cx, cy, dx, dy, cx0, cx1, cy0, cy1 = pts[b]
                    if ax1 < cx0 - 1e-6 or cx1 < ax0 - 1e-6 or ay1 < cy0 - 1e-6 or cy1 < ay0 - 1e-6:
                        continue
                    if _segments_cross((ax, ay), (bx, by), (cx, cy), (dx, dy)):
                        res.append((i, j))
            return res

        def _count_crossings(curr_placements: list[Any]) -> int:
            pts: list[tuple[float, float, float, float, float, float, float, float]] = []
            for item in curr_placements:
                anc = item[2]
                if anc is None:
                    continue
                ax, ay = anc
                cx, cy = _get_conn(item[1], anc)
                pts.append((
                    ax, ay, cx, cy,
                    ax if ax < cx else cx,
                    ax if ax > cx else cx,
                    ay if ay < cy else cy,
                    ay if ay > cy else cy,
                ))
            cnt = 0
            m = len(pts)
            for a in range(m):
                ax, ay, bx, by, ax0, ax1, ay0, ay1 = pts[a]
                for b in range(a + 1, m):
                    cx, cy, dx, dy, cx0, cx1, cy0, cy1 = pts[b]
                    if ax1 < cx0 - 1e-6 or cx1 < ax0 - 1e-6 or ay1 < cy0 - 1e-6 or cy1 < ay0 - 1e-6:
                        continue
                    if _segments_cross((ax, ay), (bx, by), (cx, cy), (dx, dy)):
                        cnt += 1
            return cnt

        def _total_leader_len(curr_placements: list[Any]) -> float:
            total = 0.0
            for _d, box, anchor in curr_placements:
                if anchor is not None:
                    conn = _get_conn(box, anchor)
                    total += math.hypot(conn[0] - anchor[0], conn[1] - anchor[1])
            return total

        if use_4side:
            # Disjoint single-layer 4-side perimeter layout:
            # Left column (x <= left_rail_x), Right column (x >= right_rail_x),
            # Top row (top_gutter_2 inside [horiz_min_x, horiz_max_x]),
            # Bottom row (bot_gutter_2 inside [horiz_min_x, horiz_max_x]).
            side_min_y = 38.0
            side_max_y = self.height - 38.0
            left_rail_x = max(max_bw + 8.0, min(gmin_x - 30.0, 96.0))
            right_rail_x = min(self.width - max_bw - 8.0, max(gmax_x + 30.0, self.width - 96.0))
            # Top/bottom rows sit at y=211.0 and y=24.5, clear of side columns [38.0, 202.0]
            horiz_min_x = max(8.0, left_rail_x - 10.0)
            horiz_max_x = min(self.width - 8.0, right_rail_x + 10.0)
            horiz_avail_w = max(40.0, horiz_max_x - horiz_min_x)
            top_row_y = top_gutter_2
            bot_row_y = bot_gutter_2
            side_cap = max(1, int((side_max_y - side_min_y + 2.0) // (11.5 + 2.0)))

            anchored_candidates = [d for d in issue_data if d.get("feature_pts")]
            unanchored_candidates = [d for d in issue_data if not d.get("feature_pts")]
            unanchored_issues.extend(unanchored_candidates)

            side_slots: dict[str, list[dict[str, Any]]] = {"top": [], "bottom": [], "left": [], "right": []}
            side_widths = {"top": 0.0, "bottom": 0.0}

            def _side_fits(side: str, d: dict[str, Any]) -> bool:
                if side in ("top", "bottom"):
                    cur_w = side_widths[side]
                    needed = d["bw"] + (1.5 if side_slots[side] else 0.0)
                    return cur_w + needed <= horiz_avail_w + 1e-6
                return len(side_slots[side]) < side_cap

            def _add_to_side(side: str, d: dict[str, Any]) -> None:
                if side in ("top", "bottom"):
                    side_widths[side] += d["bw"] + (1.5 if side_slots[side] else 0.0)
                side_slots[side].append(d)

            def _best_anchor_for_side(d: dict[str, Any], side: str, target_pos: tuple[float, float] | None = None) -> tuple[int, float, tuple[float, float]]:
                pts = d["feature_pts"]
                best_key: tuple[int, float] | None = None
                best_pt = pts[0]
                for pt in pts:
                    if target_pos is not None:
                        rp = target_pos
                    elif side == "top":
                        rp = (max(horiz_min_x + 10.0, min(horiz_max_x - 10.0, pt[0])), top_row_y)
                    elif side == "bottom":
                        rp = (max(horiz_min_x + 10.0, min(horiz_max_x - 10.0, pt[0])), bot_row_y + 11.5)
                    elif side == "left":
                        rp = (left_rail_x, max(side_min_y + 6.0, min(side_max_y - 6.0, pt[1])))
                    else:
                        rp = (right_rail_x, max(side_min_y + 6.0, min(side_max_y - 6.0, pt[1])))
                    gc = _count_geom_cross(rp, pt)
                    dist = math.hypot(pt[0] - rp[0], pt[1] - rp[1])
                    key = (gc, dist)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_pt = pt
                assert best_key is not None
                return best_key[0], best_key[1], best_pt

            for d in anchored_candidates:
                ranked_sides = []
                for side in ("top", "bottom", "left", "right"):
                    gc, dist, _pt = _best_anchor_for_side(d, side)
                    ranked_sides.append((gc, dist, side))
                ranked_sides.sort()
                placed_ok = False
                for _gc, _dist, side in ranked_sides:
                    if _side_fits(side, d):
                        _add_to_side(side, d)
                        placed_ok = True
                        break
                if not placed_ok:
                    unplaced_issues.append(d)

            # Rebalance side assignments among accepted badges via cost-reducing exchanges
            # so later-priority items are never stranded on an opposite side of the canvas.
            side_cost = {
                (id(d), s): _best_anchor_for_side(d, s)[:2]
                for s in ("top", "bottom", "left", "right")
                for d in side_slots[s]
            }
            for s_dst in ("top", "bottom", "left", "right"):
                for s_src in ("top", "bottom", "left", "right"):
                    if s_dst == s_src:
                        continue
                    for d in side_slots[s_src]:
                        side_cost[(id(d), s_dst)] = _best_anchor_for_side(d, s_dst)[:2]
            sides_all = ("top", "bottom", "left", "right")
            for _ in range(len(anchored_candidates) * 2):
                best_swap: tuple[str, int, str, int] | None = None
                best_gain: tuple[int, float] = (0, 0.5)
                for idx_s1 in range(4):
                    s1 = sides_all[idx_s1]
                    for idx_s2 in range(idx_s1 + 1, 4):
                        s2 = sides_all[idx_s2]
                        for p1, d1 in enumerate(side_slots[s1]):
                            gc1_cur, dist1_cur = side_cost[(id(d1), s1)]
                            gc1_new, dist1_new = side_cost[(id(d1), s2)]
                            for p2, d2 in enumerate(side_slots[s2]):
                                if s1 in ("top", "bottom") and side_widths[s1] - d1["bw"] + d2["bw"] > horiz_avail_w + 1e-6:
                                    continue
                                if s2 in ("top", "bottom") and side_widths[s2] - d2["bw"] + d1["bw"] > horiz_avail_w + 1e-6:
                                    continue
                                gc2_cur, dist2_cur = side_cost[(id(d2), s2)]
                                gc2_new, dist2_new = side_cost[(id(d2), s1)]
                                gain_gc = (gc1_cur + gc2_cur) - (gc1_new + gc2_new)
                                gain_dist = (dist1_cur + dist2_cur) - (dist1_new + dist2_new)
                                if gain_gc > best_gain[0] or (gain_gc == best_gain[0] and gain_dist > best_gain[1]):
                                    best_gain = (gain_gc, gain_dist)
                                    best_swap = (s1, p1, s2, p2)
                if best_swap is None:
                    break
                s1, p1, s2, p2 = best_swap
                d1 = side_slots[s1][p1]
                d2 = side_slots[s2][p2]
                side_slots[s1][p1] = d2
                side_slots[s2][p2] = d1
                if s1 in ("top", "bottom"):
                    side_widths[s1] += d2["bw"] - d1["bw"]
                if s2 in ("top", "bottom"):
                    side_widths[s2] += d1["bw"] - d2["bw"]

            def _pack_horiz_side(items_with_anc: list[tuple[dict[str, Any], tuple[float, float]]], row_y: float) -> list[tuple[dict[str, Any], tuple[float, float, float, float], tuple[float, float]]]:
                if not items_with_anc:
                    return []
                M = len(items_with_anc)
                total_bw = sum(d["bw"] for d, _ in items_with_anc)
                gap = 2.0 if M <= 1 else min(3.0, max(1.0, (horiz_avail_w - total_bw) / (M - 1)))
                ideal_x = [
                    max(horiz_min_x, min(horiz_max_x - d["bw"], anc[0] - d["bw"] / 2.0))
                    for d, anc in items_with_anc
                ]
                bx = [0.0] * M
                cur_x = horiz_min_x
                for m in range(M):
                    bx[m] = max(cur_x, ideal_x[m])
                    cur_x = bx[m] + items_with_anc[m][0]["bw"] + gap
                if bx[-1] + items_with_anc[-1][0]["bw"] > horiz_max_x:
                    cur_r = horiz_max_x
                    for m in range(M - 1, -1, -1):
                        bw = items_with_anc[m][0]["bw"]
                        bx[m] = min(bx[m], cur_r - bw)
                        cur_r = bx[m] - gap
                    if bx[0] < horiz_min_x:
                        bx[0] = horiz_min_x
                        for m in range(1, M):
                            bx[m] = max(bx[m], bx[m - 1] + items_with_anc[m - 1][0]["bw"] + gap)
                return [(items_with_anc[m][0], (bx[m], row_y, items_with_anc[m][0]["bw"], items_with_anc[m][0]["bh"]), items_with_anc[m][1]) for m in range(M)]

            def _pack_vert_side(items_with_anc: list[tuple[dict[str, Any], tuple[float, float]]], is_left: bool) -> list[tuple[dict[str, Any], tuple[float, float, float, float], tuple[float, float]]]:
                if not items_with_anc:
                    return []
                M = len(items_with_anc)
                bh = 11.5
                total_bh = M * bh
                avail_v = side_max_y - side_min_y
                gap = 2.0 if M <= 1 else min(4.0, max(1.5, (avail_v - total_bh) / (M - 1)))
                ideal_y = [
                    max(side_min_y, min(side_max_y - bh, anc[1] - bh / 2.0))
                    for _d, anc in items_with_anc
                ]
                by = [0.0] * M
                cur_y = side_min_y
                for m in range(M):
                    by[m] = max(cur_y, ideal_y[m])
                    cur_y = by[m] + bh + gap
                if by[-1] + bh > side_max_y:
                    cur_top = side_max_y
                    for m in range(M - 1, -1, -1):
                        by[m] = min(by[m], cur_top - bh)
                        cur_top = by[m] - gap
                    if by[0] < side_min_y:
                        by[0] = side_min_y
                        for m in range(1, M):
                            by[m] = max(by[m], by[m - 1] + bh + gap)
                res = []
                for m in range(M):
                    d, anc = items_with_anc[m]
                    bx_val = (left_rail_x - d["bw"]) if is_left else right_rail_x
                    res.append((d, (bx_val, by[m], d["bw"], d["bh"]), anc))
                return res

            def _side_of_box(box: tuple[float, float, float, float]) -> str:
                bx, by, bw, _bh = box
                if by >= top_row_y - 2.0:
                    return "top"
                if by <= bot_row_y + 2.0:
                    return "bottom"
                if bx + bw <= left_rail_x + 1.0:
                    return "left"
                return "right"

            def _rebuild_all_4sides(by_side: dict[str, list[tuple[dict[str, Any], tuple[float, float]]]]) -> list[Any]:
                out: list[Any] = []
                out.extend(_pack_horiz_side(by_side["top"], top_row_y))
                out.extend(_pack_horiz_side(by_side["bottom"], bot_row_y))
                out.extend(_pack_vert_side(by_side["left"], True))
                out.extend(_pack_vert_side(by_side["right"], False))
                return out

            def _split_placements_by_side(curr: list[Any]) -> dict[str, list[tuple[dict[str, Any], tuple[float, float]]]]:
                res: dict[str, list[tuple[dict[str, Any], tuple[float, float]]]] = {"top": [], "bottom": [], "left": [], "right": []}
                for d, box, anc in curr:
                    res[_side_of_box(box)].append((d, anc))
                return res

            def _sort_side_list(side: str, items: list[tuple[dict[str, Any], tuple[float, float]]]) -> list[tuple[dict[str, Any], tuple[float, float]]]:
                if side in ("top", "bottom"):
                    return sorted(items, key=lambda it: (it[1][0], it[1][1], it[0]["label"]))
                return sorted(items, key=lambda it: (it[1][1], it[1][0], it[0]["label"]))

            def _side_has_room(side: str, items: list[tuple[dict[str, Any], tuple[float, float]]], extra_d: dict[str, Any]) -> bool:
                if side in ("top", "bottom"):
                    tot_w = sum(it[0]["bw"] for it in items) + extra_d["bw"] + max(0, len(items)) * 1.5
                    return tot_w <= horiz_avail_w + 1e-6
                return len(items) + 1 <= side_cap

            # Initial ordering and best unobstructed anchor selection per side
            init_by_side: dict[str, list[tuple[dict[str, Any], tuple[float, float]]]] = {"top": [], "bottom": [], "left": [], "right": []}
            for side in ("top", "bottom", "left", "right"):
                init_by_side[side] = _sort_side_list(
                    side,
                    [(d, _best_anchor_for_side(d, side)[2]) for d in side_slots[side]],
                )
            placements = _rebuild_all_4sides(init_by_side)

            # Re-optimize each badge's anchor against its actual placed connector, then re-sort sides cleanly
            for idx in range(len(placements)):
                d, box, anc = placements[idx]
                side = _side_of_box(box)
                conn = _get_conn(box, anc)
                _gc, _dist, best_pt = _best_anchor_for_side(d, side, target_pos=conn)
                placements[idx] = (d, box, best_pt)
            by_s_ref = _split_placements_by_side(placements)
            for side in ("top", "bottom", "left", "right"):
                by_s_ref[side] = _sort_side_list(side, by_s_ref[side])
            placements = _rebuild_all_4sides(by_s_ref)

            # 2-opt descent across anchor shifts, same-side slides, adjacent-side transfers, and swaps
            for _ in range(120):
                cross_pairs = _all_crossings(placements)
                if not cross_pairs:
                    break
                curr_c = len(cross_pairs)
                curr_l = _total_leader_len(placements)
                best_trial: list[Any] | None = None
                best_delta_c = 0
                best_delta_l = 0.0

                def _consider_trial(trial: list[Any]) -> None:
                    nonlocal best_trial, best_delta_c, best_delta_l
                    new_c = _count_crossings(trial)
                    delta_c = curr_c - new_c
                    if delta_c < best_delta_c:
                        return
                    new_l = _total_leader_len(trial)
                    delta_l = curr_l - new_l
                    if delta_c > best_delta_c or (delta_c == best_delta_c and delta_l > best_delta_l):
                        best_delta_c = delta_c
                        best_delta_l = delta_l
                        best_trial = trial

                crossing_indices = sorted({idx for pair in cross_pairs for idx in pair})

                # 1) Try alternate feature_pts for crossing badges
                for idx in crossing_indices:
                    d, box, _old_anc = placements[idx]
                    pts = d.get("feature_pts") or []
                    if len(pts) <= 1:
                        continue
                    other_ancs = [placements[k][2] for k in range(len(placements)) if k != idx and placements[k][2] is not None]
                    for pt in pts:
                        if other_ancs and min(math.hypot(pt[0] - oa[0], pt[1] - oa[1]) for oa in other_ancs) < 2.5:
                            continue
                        trial = list(placements)
                        trial[idx] = (d, box, pt)
                        _consider_trial(trial)

                base_by_s = _split_placements_by_side(placements)
                pos_map: dict[int, tuple[str, int]] = {}
                side_cursors: dict[str, int] = {"top": 0, "bottom": 0, "left": 0, "right": 0}
                for idx_p, (_dp, box_p, _ap) in enumerate(placements):
                    sd = _side_of_box(box_p)
                    pos_map[idx_p] = (sd, side_cursors[sd])
                    side_cursors[sd] += 1

                # 2) Same-side slot slides & adjacent-side transfers for crossing badges
                for idx in crossing_indices:
                    d_i = placements[idx][0]
                    side_i, pos_i = pos_map[idx]
                    for target_k in range(len(base_by_s[side_i])):
                        if target_k == pos_i:
                            continue
                        by_s = {s: list(v) for s, v in base_by_s.items()}
                        item = by_s[side_i].pop(pos_i)
                        by_s[side_i].insert(target_k, item)
                        _consider_trial(_rebuild_all_4sides(by_s))
                    adj_sides = ("left", "right") if side_i in ("top", "bottom") else ("top", "bottom")
                    for side_j in adj_sides:
                        if not _side_has_room(side_j, base_by_s[side_j], d_i):
                            continue
                        by_s = {s: list(v) for s, v in base_by_s.items()}
                        by_s[side_i].pop(pos_i)
                        by_s[side_j].append((d_i, _best_anchor_for_side(d_i, side_j)[2]))
                        by_s[side_j] = _sort_side_list(side_j, by_s[side_j])
                        _consider_trial(_rebuild_all_4sides(by_s))

                # 3) Pairwise swaps across crossing badges and all adjacent-side partners (sorted + direct)
                side_anc_cache = {
                    (id(item[0]), s): _best_anchor_for_side(item[0], s)[2]
                    for item in placements
                    for s in ("top", "bottom", "left", "right")
                }
                side_widths_cur = {
                    s: sum(it[0]["bw"] for it in base_by_s[s]) + max(0, len(base_by_s[s]) - 1) * 1.5
                    for s in ("top", "bottom")
                }
                cand_pairs = [(i, k) for i in crossing_indices for k in range(len(placements)) if i != k]
                seen_swaps: set[tuple[int, int]] = set()
                for raw_i, raw_j in cand_pairs:
                    i, j = (raw_i, raw_j) if raw_i < raw_j else (raw_j, raw_i)
                    if (i, j) in seen_swaps:
                        continue
                    seen_swaps.add((i, j))
                    d_i = placements[i][0]
                    d_j = placements[j][0]
                    side_i, pos_i = pos_map[i]
                    side_j, pos_j = pos_map[j]
                    if side_i == side_j:
                        by_s = {s: list(v) for s, v in base_by_s.items()}
                        by_s[side_i][pos_i], by_s[side_i][pos_j] = by_s[side_i][pos_j], by_s[side_i][pos_i]
                        _consider_trial(_rebuild_all_4sides(by_s))
                    else:
                        if side_i in ("top", "bottom") and side_widths_cur[side_i] - d_i["bw"] + d_j["bw"] > horiz_avail_w + 1e-6:
                            continue
                        if side_j in ("top", "bottom") and side_widths_cur[side_j] - d_j["bw"] + d_i["bw"] > horiz_avail_w + 1e-6:
                            continue
                        by_s = {s: list(v) for s, v in base_by_s.items()}
                        by_s[side_i][pos_i] = (d_j, side_anc_cache[(id(d_j), side_i)])
                        by_s[side_j][pos_j] = (d_i, side_anc_cache[(id(d_i), side_j)])
                        _consider_trial(_rebuild_all_4sides(by_s))
                        sorted_i = _sort_side_list(side_i, by_s[side_i])
                        sorted_j = _sort_side_list(side_j, by_s[side_j])
                        if sorted_i != by_s[side_i] or sorted_j != by_s[side_j]:
                            by_s_sorted = {s: list(v) for s, v in by_s.items()}
                            by_s_sorted[side_i] = sorted_i
                            by_s_sorted[side_j] = sorted_j
                            _consider_trial(_rebuild_all_4sides(by_s_sorted))

                if best_trial is not None and (best_delta_c > 0 or (best_delta_c == 0 and best_delta_l > 0.1)):
                    placements[:] = best_trial
                else:
                    break
        else:
            top_list.sort(key=_sort_key)
            bot_list.sort(key=_sort_key)

            def _partition_to_rows(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
                if not items:
                    return [], []
                if sum(d["bw"] + 2.0 for d in items) <= avail_w:
                    return list(items), []
                # Alternate into outer (1) and inner (2) gutters
                row1 = [items[i] for i in range(0, len(items), 2)]
                row2 = [items[i] for i in range(1, len(items), 2)]
                return row1, row2

            top_row1, top_row2 = _partition_to_rows(top_list)
            bot_row1, bot_row2 = _partition_to_rows(bot_list)

            def _layout_horizontal_row(row_list: list[dict[str, Any]], gutter_y: float, is_top: bool) -> None:
                if not row_list:
                    return
                # Truncate any items that exceed gutter line capacity
                fit_count = 0
                accum_w = 0.0
                for d in row_list:
                    needed = d["bw"] + 1.0
                    if accum_w + needed <= avail_w + 1.0:
                        accum_w += needed
                        fit_count += 1
                    else:
                        break

                fit_items = row_list[:fit_count]
                for d in row_list[fit_count:]:
                    unplaced_issues.append(d)

                if not fit_items:
                    return

                M = len(fit_items)
                total_bw = sum(d["bw"] for d in fit_items)
                gap = 2.0 if M <= 1 else min(2.0, max(1.0, (avail_w - total_bw) / (M - 1)))
                ideal_x = [
                    max(4.0, min(self.width - fit_items[m]["bw"] - 4.0, _sort_key(fit_items[m]) - fit_items[m]["bw"] / 2.0))
                    for m in range(M)
                ]
                bx = [0.0] * M
                cur_x = 4.0
                for m in range(M):
                    bx[m] = max(cur_x, ideal_x[m])
                    cur_x = bx[m] + fit_items[m]["bw"] + gap

                if bx[-1] + fit_items[-1]["bw"] > self.width - 4.0:
                    cur_right = self.width - 4.0
                    for m in range(M - 1, -1, -1):
                        bw = fit_items[m]["bw"]
                        bx[m] = min(bx[m], cur_right - bw)
                        cur_right = bx[m] - gap
                    if bx[0] < 4.0:
                        bx[0] = 4.0
                        for m in range(1, M):
                            bx[m] = max(bx[m], bx[m - 1] + fit_items[m - 1]["bw"] + gap)

                for m in range(M):
                    d = fit_items[m]
                    bw, bh = d["bw"], d["bh"]
                    cand_box = (bx[m], gutter_y, bw, bh)
                    feature_pts = d.get("feature_pts")
                    if feature_pts:
                        conn_pt = (bx[m] + bw / 2.0, gutter_y if is_top else gutter_y + bh)
                        anchor = min(feature_pts, key=lambda pt: math.hypot(pt[0] - conn_pt[0], pt[1] - conn_pt[1]))
                    else:
                        anchor = None
                        unanchored_issues.append(d)
                    placements.append((d, cand_box, anchor))
                    placed_boxes.append(cand_box)

            _layout_horizontal_row(top_row1, top_gutter_1, is_top=True)
            _layout_horizontal_row(top_row2, top_gutter_2, is_top=True)
            _layout_horizontal_row(bot_row1, bot_gutter_1, is_top=False)
            _layout_horizontal_row(bot_row2, bot_gutter_2, is_top=False)

            gutter_rows = (
                ("top_1", top_gutter_1),
                ("top_2", top_gutter_2),
                ("bot_1", bot_gutter_1),
                ("bot_2", bot_gutter_2),
            )
            gutter_y_by_key = dict(gutter_rows)

            def _row_key(by: float) -> str:
                return min(gutter_rows, key=lambda item: abs(by - item[1]))[0]

            def _row_fits(curr_placements: list[Any], gkey: str) -> bool:
                widths = [p[1][2] for p in curr_placements if _row_key(p[1][1]) == gkey]
                if not widths:
                    return True
                return sum(widths) + max(0, len(widths) - 1) * 1.0 <= avail_w + 1e-6

            def _untangle_gutters(curr_placements: list[Any], *, use_box_order: bool = False, reanchor: bool = True) -> None:
                groups: dict[str, list[tuple[int, Any]]] = {k: [] for k, _ in gutter_rows}

                for idx, p in enumerate(curr_placements):
                    groups[_row_key(p[1][1])].append((idx, p))

                for gkey, row_y in gutter_rows:
                    items = groups[gkey]
                    if not items:
                        continue
                    if use_box_order:
                        items_sorted = sorted(
                            items,
                            key=lambda it: (
                                it[1][1][0] + it[1][1][2] / 2.0,
                                it[1][2][0] if it[1][2] is not None else it[1][0]["cx"],
                                it[0],
                            ),
                        )
                    else:
                        items_sorted = sorted(
                            items,
                            key=lambda it: (
                                it[1][2][0] if it[1][2] is not None else it[1][0]["cx"],
                                it[1][0]["cx"],
                                it[0],
                            ),
                        )
                    M = len(items_sorted)
                    total_bw = sum(it[1][1][2] for it in items_sorted)
                    gap = 2.0 if M <= 1 else min(2.0, max(1.0, (avail_w - total_bw) / (M - 1)))
                    ideal_x = [
                        max(
                            4.0,
                            min(
                                self.width - it[1][1][2] - 4.0,
                                (it[1][2][0] if it[1][2] is not None else it[1][0]["cx"]) - it[1][1][2] / 2.0,
                            ),
                        )
                        for it in items_sorted
                    ]
                    bx = [0.0] * M
                    cur_x = 4.0
                    for m in range(M):
                        bx[m] = max(cur_x, ideal_x[m])
                        cur_x = bx[m] + items_sorted[m][1][1][2] + gap

                    if bx[-1] + items_sorted[-1][1][1][2] > self.width - 4.0:
                        cur_right = self.width - 4.0
                        for m in range(M - 1, -1, -1):
                            bw = items_sorted[m][1][1][2]
                            bx[m] = min(bx[m], cur_right - bw)
                            cur_right = bx[m] - gap
                        if bx[0] < 4.0:
                            bx[0] = 4.0
                            for m in range(1, M):
                                bx[m] = max(bx[m], bx[m - 1] + items_sorted[m - 1][1][1][2] + gap)

                    for m in range(M):
                        orig_idx, p = items_sorted[m]
                        d, old_box, old_anchor = p
                        bw, bh = old_box[2], old_box[3]
                        new_box = (bx[m], row_y, bw, bh)
                        feature_pts = d.get("feature_pts")
                        if reanchor and feature_pts and old_anchor is not None:
                            conn_pt = _get_conn(new_box, old_anchor)
                            new_anchor = min(feature_pts, key=lambda pt: math.hypot(pt[0] - conn_pt[0], pt[1] - conn_pt[1]))
                        else:
                            new_anchor = old_anchor
                        curr_placements[orig_idx] = (d, new_box, new_anchor)

            # Initial topological layout sweep along each gutter to ensure monotonic order and no collisions
            _untangle_gutters(placements, use_box_order=False)

            # Uncross leader lines using 2-opt descent until ZERO crossings remain (capped at 50 passes)
            max_passes = 50
            for _ in range(max_passes):
                cross_pairs = _all_crossings(placements)
                if not cross_pairs:
                    break

                curr_c = len(cross_pairs)
                curr_l = _total_leader_len(placements)
                best_trial: list[Any] | None = None
                best_delta_c = 0
                best_delta_l = 0.0

                def _try_candidate_pairs(pairs: list[tuple[int, int]]) -> None:
                    nonlocal best_trial, best_delta_c, best_delta_l
                    seen_pairs: set[tuple[int, int]] = set()
                    for raw_i, raw_j in pairs:
                        i, j = (raw_i, raw_j) if raw_i < raw_j else (raw_j, raw_i)
                        if i == j or (i, j) in seen_pairs:
                            continue
                        seen_pairs.add((i, j))
                        p_i, p_j = placements[i], placements[j]
                        d_i, box_i, anchor_i = p_i
                        d_j, box_j, anchor_j = p_j

                        if (box_i[1] >= self.height / 2) != (box_j[1] >= self.height / 2):
                            continue

                        row_i = _row_key(box_i[1])
                        row_j = _row_key(box_j[1])
                        cxi = box_i[0] + box_i[2] / 2.0
                        cxj = box_j[0] + box_j[2] / 2.0
                        y_i = gutter_y_by_key[row_i]
                        y_j = gutter_y_by_key[row_j]

                        move_specs = [
                            (
                                (max(4.0, min(self.width - box_i[2] - 4.0, cxj - box_i[2] / 2.0)), y_j, box_i[2], box_i[3]),
                                (max(4.0, min(self.width - box_j[2] - 4.0, cxi - box_j[2] / 2.0)), y_i, box_j[2], box_j[3]),
                                True,
                            )
                        ]
                        if row_i != row_j:
                            move_specs.append(
                                (
                                    (box_i[0], y_j, box_i[2], box_i[3]),
                                    (box_j[0], y_i, box_j[2], box_j[3]),
                                    False,
                                )
                            )

                        for new_box_i, new_box_j, use_box_order in move_specs:
                            for reanchor_flag in (True, False):
                                trial = list(placements)
                                trial[i] = (d_i, new_box_i, anchor_i)
                                trial[j] = (d_j, new_box_j, anchor_j)
                                if row_i != row_j and (not _row_fits(trial, row_i) or not _row_fits(trial, row_j)):
                                    continue
                                _untangle_gutters(trial, use_box_order=use_box_order, reanchor=reanchor_flag)
                                new_c = len(_all_crossings(trial))
                                delta_c = curr_c - new_c
                                if delta_c < best_delta_c:
                                    continue
                                new_l = _total_leader_len(trial)
                                delta_l = curr_l - new_l
                                if delta_c > best_delta_c or (delta_c == best_delta_c and delta_l > best_delta_l):
                                    best_delta_c = delta_c
                                    best_delta_l = delta_l
                                    best_trial = trial

                _try_candidate_pairs(list(cross_pairs))
                if best_trial is None or not (best_delta_c > 0 or (best_delta_c == 0 and best_delta_l > 0.1)):
                    crossing_indices = sorted({idx for pair in cross_pairs for idx in pair})
                    expanded_pairs = [
                        (i, k)
                        for i in crossing_indices
                        for k in range(len(placements))
                        if i != k and (placements[i][1][1] >= self.height / 2) == (placements[k][1][1] >= self.height / 2)
                    ]
                    _try_candidate_pairs(expanded_pairs)

                if best_trial is not None and (best_delta_c > 0 or (best_delta_c == 0 and best_delta_l > 0.1)):
                    placements[:] = best_trial
                else:
                    break

            _untangle_gutters(placements, use_box_order=True, reanchor=False)

        # Separate coincident anchors across adjacent badges and prefer lower-geometry-crossing anchors
        # whenever a valid feature point preserves the crossing count.
        used_anchors: list[tuple[float, float]] = []
        for idx in range(len(placements)):
            d, box, anchor = placements[idx]
            if anchor is None:
                continue
            pts = d.get("feature_pts") or []
            if len(pts) > 1 and (
                any(math.hypot(anchor[0] - ua[0], anchor[1] - ua[1]) < 4.0 for ua in used_anchors)
                or (use_4side and _count_geom_cross(_get_conn(box, anchor), anchor) > 0)
            ):
                conn = _get_conn(box, anchor)
                cur_cross = len(_all_crossings(placements))
                best_cand = anchor
                best_score: tuple[int, int, int, float] | None = None
                for pt in pts:
                    min_sep = min((math.hypot(pt[0] - ua[0], pt[1] - ua[1]) for ua in used_anchors), default=999.0)
                    if min_sep < 2.5:
                        continue
                    placements[idx] = (d, box, pt)
                    trial_cross = len(_all_crossings(placements))
                    if trial_cross > cur_cross:
                        continue
                    gc = _count_geom_cross(_get_conn(box, pt), pt) if use_4side else 0
                    dist_conn = math.hypot(pt[0] - conn[0], pt[1] - conn[1])
                    score = (0 if min_sep >= 4.5 else 1, trial_cross, gc, dist_conn)
                    if best_score is None or score < best_score:
                        best_score = score
                        best_cand = pt
                placements[idx] = (d, box, best_cand)
                anchor = best_cand
            used_anchors.append(anchor)

        for d, box, anchor in placements:
            bx, by, bw, bh = box
            badge_color = colors.HexColor(d["color_hex"])

            if anchor is not None:
                ax, ay = anchor
                ax = max(4.0, min(self.width - 4.0, ax))
                ay = max(4.0, min(self.height - 4.0, ay))

                if by >= ay:
                    conn_x = max(bx + 2.0, min(bx + bw - 2.0, ax))
                    conn_y = by
                elif by + bh <= ay:
                    conn_x = max(bx + 2.0, min(bx + bw - 2.0, ax))
                    conn_y = by + bh
                elif bx >= ax:
                    conn_x = bx
                    conn_y = max(by + 2.0, min(by + bh - 2.0, ay))
                elif bx + bw <= ax:
                    conn_x = bx + bw
                    conn_y = max(by + 2.0, min(by + bh - 2.0, ay))
                else:
                    conn_x = bx + bw / 2.0
                    conn_y = by if by > ay else (by + bh)

                dist = math.hypot(conn_x - ax, conn_y - ay)
                if dist > 2.0:
                    self.canv.saveState()
                    self.canv.setStrokeColor(badge_color)
                    self.canv.setFillColor(badge_color)
                    self.canv.setLineWidth(0.65)
                    self.canv.setDash([])
                    self.canv.circle(ax, ay, 1.2, stroke=0, fill=1)
                    self.canv.line(ax, ay, conn_x, conn_y)
                    self.canv.restoreState()

            self.canv.saveState()
            self.canv.setStrokeColor(badge_color)
            self.canv.setFillColor(colors.HexColor("#ffffff"))
            self.canv.setLineWidth(0.7)
            self.canv.setDash([])
            self.canv.roundRect(bx, by, bw, bh, 2.5, stroke=1, fill=1)
            self.canv.setFillColor(badge_color)
            self.canv.setFont(FONT_BOLD, 6.5)
            text_x = bx + (bw - d["text_w"]) / 2.0
            text_y = by + 2.5
            self.canv.drawString(text_x, text_y, _display_text(d["label"]))
            self.canv.restoreState()

        if unplaced_issues or unanchored_issues:
            # Explicit visible notice for omitted badges or unanchored region-only findings
            notice_w = self.width - 16.0
            max_text_w = notice_w - 12.0
            cand_candidates = []
            if unplaced_issues:
                n_unplaced = len(unplaced_issues)
                unplaced_labels = [str(d["label"]) for d in unplaced_issues]
                for k in (5, 4, 3, 2, 1):
                    sample_str = ", ".join(unplaced_labels[:k])
                    cand_candidates.append(f"Notice: {n_unplaced} findings ({sample_str}...) listed in findings table below")
                cand_candidates.append(f"Notice: {n_unplaced} findings omitted from canvas; see findings table below")
                cand_candidates.append(f"Notice: {n_unplaced} findings; see findings table below")
            else:
                n_unanchored = len(unanchored_issues)
                unanchored_labels = [str(d["label"]) for d in unanchored_issues]
                noun = "finding" if n_unanchored == 1 else "findings"
                for k in (5, 4, 3, 2, 1):
                    if n_unanchored >= k:
                        sample_str = ", ".join(unanchored_labels[:k]) + ("..." if n_unanchored > k else "")
                        cand_candidates.append(
                            f"Notice: {n_unanchored} {noun} ({sample_str}) unanchored (no resolvable feature); see findings table below"
                        )
                        cand_candidates.append(
                            f"Notice: {n_unanchored} {noun} ({sample_str}) no resolvable feature; see findings table below"
                        )
                cand_candidates.append(f"Notice: {n_unanchored} {noun} unanchored (no feature); see findings table below")
                cand_candidates.append(f"Notice: {n_unanchored} unanchored {noun}; see findings table below")

            chosen_text = cand_candidates[-1]
            chosen_fs = 5.5
            for cand in cand_candidates:
                w = pdfmetrics.stringWidth(cand, FONT_NAME, 5.5)
                if w <= max_text_w:
                    chosen_text = cand
                    break
            else:
                while chosen_fs > 5.0 and pdfmetrics.stringWidth(chosen_text, FONT_NAME, chosen_fs) > max_text_w:
                    chosen_fs -= 0.5

            actual_text_w = pdfmetrics.stringWidth(chosen_text, FONT_NAME, chosen_fs)
            actual_box_w = min(notice_w, actual_text_w + 12.0)
            notice_x = (self.width - actual_box_w) / 2.0
            notice_y = 1.0
            notice_h = 9.0

            self.canv.saveState()
            self.canv.setFillColor(colors.HexColor("#fffbeb"))
            self.canv.setStrokeColor(colors.HexColor("#f59e0b"))
            self.canv.setLineWidth(0.7)
            self.canv.roundRect(notice_x, notice_y, actual_box_w, notice_h, 2.0, stroke=1, fill=1)
            self.canv.setFillColor(colors.HexColor("#92400e"))
            self.canv.setFont(FONT_NAME, chosen_fs)
            text_x = notice_x + (actual_box_w - actual_text_w) / 2.0
            text_y = notice_y + 2.0
            self.canv.drawString(text_x, text_y, _display_text(chosen_text))
            self.canv.restoreState()

    def draw(self) -> None:
        _register_fonts()
        self.canv.saveState()
        self.canv.setFillColor(colors.white)
        self.canv.setStrokeColor(colors.HexColor("#cbd5d1"))
        self.canv.roundRect(0, 0, self.width, self.height, 5, stroke=1, fill=1)

        clip_path = self.canv.beginPath() if hasattr(self.canv, "beginPath") else None
        if clip_path is not None and hasattr(clip_path, "rect") and hasattr(self.canv, "clipPath"):
            clip_path.rect(0, 0, self.width, self.height)
            self.canv.clipPath(clip_path, stroke=0, fill=0)

        use_extents = self.extents or (getattr(self.reviewed, "student_extents", None) if self.role_filter else None) or self.reviewed.extents
        has_badges = bool(any(
            iss.visual_role in {"missing", "extra", "inaccurate", "connectivity", "warning", "critical"}
            for iss in self.reviewed.issues
            if (self.allowed_issue_ids is None or iss.issue_id in self.allowed_issue_ids)
        ))
        drawing_margin = 36.0 if has_badges else 12.0
        transform = CoordinateTransform(use_extents, self.width, self.height, drawing_margin)

        self.canv.saveState()
        geom_margin = drawing_margin
        geom_clip = self.canv.beginPath() if hasattr(self.canv, "beginPath") else None
        if geom_clip is not None and hasattr(geom_clip, "rect") and hasattr(self.canv, "clipPath"):
            geom_clip.rect(geom_margin, geom_margin, self.width - 2.0 * geom_margin, self.height - 2.0 * geom_margin)
            self.canv.clipPath(geom_clip, stroke=0, fill=0)

        if not self.role_filter:
            for entity in self.reviewed.reference_entities:
                self._entity(entity, "reference", transform)
        for entity in self.reviewed.student_entities:
            self._entity(entity, "student", transform)

        active_issues: list[ReviewedIssue] = []
        for issue in self.reviewed.issues:
            if self.allowed_issue_ids is not None and issue.issue_id not in self.allowed_issue_ids:
                continue
            role = issue.visual_role
            if self.role_filter and self.role_filter != "object_detail" and role != self.role_filter:
                continue
            if self.role_filter == "warning" and issue.category.startswith("reference_"):
                continue
            active_issues.append(issue)

        active_count = len(active_issues)

        # Draw entity overlays in layered priority order:
        # 1) inaccurate-expected (omitting detached raw-coordinate placement copies),
        # 2) inaccurate-actual, 3) extra, 4) missing (on top so short chamfers stay visible),
        # 5) region/marker roles (connectivity, warning, critical).
        for issue in active_issues:
            if issue.visual_role == "inaccurate" and not _is_detached_placement_issue(issue):
                exp_geoms = issue.expected_geometries or ((issue.expected_geometry,) if issue.expected_geometry else ())
                for geom in exp_geoms:
                    self._entity(geom, "inaccurate-expected", transform)
        for issue in active_issues:
            if issue.visual_role == "inaccurate":
                act_geoms = issue.actual_geometries or ((issue.actual_geometry,) if issue.actual_geometry else ())
                for geom in act_geoms:
                    self._entity(geom, "inaccurate-actual", transform)
        for issue in active_issues:
            if issue.visual_role == "extra":
                geoms = issue.actual_geometries or ((issue.actual_geometry,) if issue.actual_geometry else ())
                for geom in geoms:
                    self._entity(geom, "extra", transform)
        for issue in active_issues:
            if issue.visual_role == "missing":
                geoms = issue.expected_geometries or ((issue.expected_geometry,) if issue.expected_geometry else ())
                for geom in geoms:
                    self._entity(geom, "missing", transform)
        for issue in active_issues:
            if issue.visual_role in {"connectivity", "warning", "critical"}:
                self._region(issue, transform, issue.visual_role)

        self.canv.restoreState()

        self._draw_all_badges(transform)

        if self.role_filter and active_count == 0:
            self.canv.setFillColor(colors.HexColor("#718096"))
            self.canv.setFont(FONT_NAME, 9)
            empty_y = (
                (self.height - 20.0)
                if (has_badges and (self.reviewed.student_entities or self.reviewed.reference_entities))
                else (self.height / 2)
            )
            self.canv.drawCentredString(self.width / 2, empty_y, f"No {self.role_filter} findings.")
        elif transform.empty and not self.reviewed.reference_entities and not self.reviewed.student_entities:
            self.canv.setFillColor(colors.HexColor("#718096"))
            self.canv.setFont(FONT_NAME, 9)
            self.canv.drawCentredString(self.width / 2, self.height / 2, "No drawable geometry")

        self.canv.restoreState()


class SideBySideDrawingFlowable(Flowable):
    """Side-by-side vector rendering of student drawing (left) and reference drawing (right)."""

    def __init__(self, reviewed: ReviewedDrawing, width: float, height: float = 220.0):
        super().__init__()
        self.reviewed = reviewed
        self.width = float(width)
        self.height = float(height)

    def wrap(self, available_width: float, _available_height: float) -> tuple[float, float]:
        return min(self.width, available_width), self.height

    def _point(self, transform: CoordinateTransform, point: tuple[float, float], offset_x: float = 0.0) -> tuple[float, float]:
        x, screen_y = transform.point(point)
        return x + offset_x, transform.height - screen_y

    def _draw_entity(self, entity: ReviewedEntity, role: str, transform: CoordinateTransform, offset_x: float = 0.0) -> None:
        _set_role_style(self.canv, role)
        points = tuple(sorted(entity.points)) if entity.kind == "line" else entity.points
        if entity.kind == "line" and len(points) >= 2:
            start = self._point(transform, points[0], offset_x)
            end = self._point(transform, points[-1], offset_x)
            self.canv.line(start[0], start[1], end[0], end[1])
        elif entity.kind in {"polyline", "spline", "dimension"} and points:
            path = self.canv.beginPath()
            path.moveTo(*self._point(transform, points[0], offset_x))
            for point in points[1:]:
                path.lineTo(*self._point(transform, point, offset_x))
            if entity.kind == "polyline" and entity.closed:
                path.close()
            self.canv.drawPath(path, stroke=1, fill=0)
        elif entity.kind == "circle" and points and entity.radius is not None:
            center = self._point(transform, points[0], offset_x)
            self.canv.circle(*center, transform.length(entity.radius), stroke=1, fill=0)
        elif entity.kind == "arc" and points and entity.radius is not None and entity.start_angle is not None and entity.end_angle is not None:
            center = self._point(transform, points[0], offset_x)
            radius = transform.length(entity.radius)
            self.canv.arc(center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius,
                          startAng=entity.start_angle, extent=(entity.end_angle - entity.start_angle) % 360)
        elif entity.kind == "text" and points:
            self.canv.setFont(FONT_NAME, 5.5)
            self.canv.drawString(*self._point(transform, points[0], offset_x), _display_text(entity.text or ""))

    def draw(self) -> None:
        _register_fonts()
        self.canv.saveState()
        gap = 10.0
        panel_w = (self.width - gap) / 2.0
        margin = 10.0
        header_h = 16.0
        draw_h = self.height - header_h

        # Left panel: Student submission
        self.canv.setFillColor(colors.white)
        self.canv.setStrokeColor(colors.HexColor("#cbd5d1"))
        self.canv.roundRect(0, 0, panel_w, self.height, 4, stroke=1, fill=1)
        self.canv.setFillColor(colors.HexColor("#125c3e"))
        self.canv.setFont(FONT_BOLD, 7.5)
        self.canv.drawString(8, self.height - 12, "Student submission (original arrangement)")

        stu_ext = getattr(self.reviewed, "student_extents", None) or self.reviewed.extents
        stu_transform = CoordinateTransform(stu_ext, panel_w, draw_h, margin)
        for entity in self.reviewed.student_entities:
            self._draw_entity(entity, "student", stu_transform, offset_x=0.0)

        # Right panel: Reference drawing
        offset_r = panel_w + gap
        self.canv.setFillColor(colors.white)
        self.canv.setStrokeColor(colors.HexColor("#cbd5d1"))
        self.canv.roundRect(offset_r, 0, panel_w, self.height, 4, stroke=1, fill=1)
        self.canv.setFillColor(colors.HexColor("#125c3e"))
        self.canv.setFont(FONT_BOLD, 7.5)
        self.canv.drawString(offset_r + 8, self.height - 12, "Reference drawing (original arrangement)")

        ref_ext = getattr(self.reviewed, "reference_extents", None) or self.reviewed.extents
        ref_transform = CoordinateTransform(ref_ext, panel_w, draw_h, margin)
        for entity in self.reviewed.reference_entities:
            self._draw_entity(entity, "reference", ref_transform, offset_x=offset_r)

        self.canv.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts(); sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("DLTitle", parent=sample["Title"], fontName=FONT_BOLD, fontSize=21, leading=25, textColor=colors.HexColor("#125c3e"), spaceAfter=2, keepWithNext=True),
        "subtitle": ParagraphStyle("DLSubtitle", parent=sample["Normal"], fontName=FONT_NAME, fontSize=10, leading=13, textColor=colors.HexColor("#51615a"), spaceAfter=8),
        "h1": ParagraphStyle("DLH1", parent=sample["Heading1"], fontName=FONT_BOLD, fontSize=13, leading=16, spaceBefore=8, spaceAfter=5, keepWithNext=True),
        "h2": ParagraphStyle("DLH2", parent=sample["Heading2"], fontName=FONT_BOLD, fontSize=10, leading=13, textColor=colors.HexColor("#125c3e"), spaceBefore=6, spaceAfter=3, keepWithNext=True),
        "body": ParagraphStyle("DLBody", parent=sample["BodyText"], fontName=FONT_NAME, fontSize=7.5, leading=10, textColor=colors.HexColor("#24313a")),
        "badge": ParagraphStyle("DLBadge", parent=sample["BodyText"], fontName=FONT_BOLD, fontSize=7.5, leading=10, textColor=colors.HexColor("#24313a")),
        "small": ParagraphStyle("DLSmall", parent=sample["BodyText"], fontName=FONT_NAME, fontSize=6.7, leading=8.5, textColor=colors.HexColor("#51615a")),
        "legend": ParagraphStyle("DLLegend", parent=sample["BodyText"], fontName=FONT_NAME, fontSize=5.6, leading=6.7, textColor=colors.HexColor("#51615a")),
        "score": ParagraphStyle("DLScore", parent=sample["Title"], fontName=FONT_BOLD, fontSize=27, leading=30, alignment=TA_CENTER, textColor=colors.HexColor("#125c3e")),
        "score_earned": ParagraphStyle("DLScoreEarned", parent=sample["BodyText"], fontName=FONT_BOLD, fontSize=13, leading=15, alignment=TA_CENTER, textColor=colors.HexColor("#125c3e")),
        "callout": ParagraphStyle("DLCallout", parent=sample["BodyText"], fontName=FONT_NAME, fontSize=7.3, leading=9.5, textColor=colors.HexColor("#163f30")),
    }


def _p(value: Any, style: ParagraphStyle) -> Paragraph: return Paragraph(_paragraph_text(value), style)
def _number(value: Any) -> str:
    if value is None: return "Not available"
    if isinstance(value, float): return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _four_column_table(rows: list[tuple[Any, Any, Any, Any]], styles: dict[str, ParagraphStyle], width: float) -> Table:
    cells = [[_p(a, styles["small"]), _p(b, styles["body"]), _p(c, styles["small"]), _p(d, styles["body"])] for a,b,c,d in rows]
    table = Table(cells, colWidths=[width*.14, width*.36, width*.14, width*.36], splitByRow=1)
    table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f4f7f5")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#d8e0dc")),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    return table


def _overlay_legend(styles: dict[str, ParagraphStyle], width: float) -> list[Flowable]:
    column_width = width / 4
    cells: list[Table] = []
    for role, label, explanation in _LEGEND_ENTRIES:
        description = Paragraph(
            f'<font name="{FONT_BOLD}" size="6.3">{_paragraph_text(label)}</font><br/>{_paragraph_text(explanation)}',
            styles["legend"],
        )
        cell = Table(
            [[LegendSampleFlowable(role), description]],
            colWidths=[28, column_width - 34],
        )
        cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        cells.append(cell)
    legend = Table(
        [cells[:4], cells[4:]],
        colWidths=[column_width] * 4,
        splitByRow=0,
    )
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7f5")),
        ("BOX", (0, 0), (-1, -1), .35, colors.HexColor("#cbd5d1")),
        ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#d8e0dc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [
        _p("Drawing overlay legend", styles["h2"]),
        legend,
        Spacer(1, 2),
        _p("Drawing issue IDs correspond to the detailed findings on the following pages.", styles["small"]),
        Spacer(1, 4),
    ]


def _category_legend(role: str, styles: dict[str, ParagraphStyle], width: float) -> list[Flowable]:
    entries_map = {
        "missing": [
            ("missing", "Missing geometry", "Required reference geometry absent from the submission"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "extra": [
            ("extra", "Extra geometry", "Unmatched geometry found only in the submission"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "inaccurate": [
            ("inaccurate-actual", "Inaccurate actual", "Matched student geometry deviating from approved tolerance"),
            ("inaccurate-expected", "Inaccurate expected", "Required reference counterpart for the same issue"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "connectivity": [
            ("connectivity", "Connectivity", "Endpoint gap or improper junction between student elements"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "warning": [
            ("warning", "Warning / Quality", "Duplicate geometry, zero-length lines, or quality issues"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "critical": [
            ("critical", "Critical", "Severe validation or assessment condition"),
            ("student", "Student base", "Submitted student geometry"),
        ],
        "object_detail": [
            ("inaccurate-actual", "Inaccurate actual", "Matched student geometry deviating from tolerance"),
            ("inaccurate-expected", "Inaccurate expected", "Required reference counterpart"),
            ("missing", "Missing geometry", "Required reference geometry absent from submission"),
            ("student", "Student base", "Submitted student geometry"),
        ],
    }
    entries = entries_map.get(role, [])
    if not entries:
        return []
    col_w = width / len(entries)
    cells = []
    for r, label, exp in entries:
        desc = Paragraph(f'<font name="{FONT_BOLD}" size="6.3">{_paragraph_text(label)}</font><br/>{_paragraph_text(exp)}', styles["legend"])
        cell = Table([[LegendSampleFlowable(r), desc]], colWidths=[28, col_w - 34])
        cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        cells.append(cell)
    legend = Table([cells], colWidths=[col_w] * len(entries), splitByRow=0)
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7f5")),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5d1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e0dc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return [legend]


def _issue_mapping_table(
    snapshot: ReviewSnapshot,
    styles: dict[str, ParagraphStyle],
    width: float,
    role_filter: str | None = None,
    *,
    is_formative: bool = False,
    custom_issues: list[ReviewedIssue] | None = None,
) -> list[Flowable]:
    if custom_issues is not None:
        visual_issues = list(custom_issues)
    else:
        issues = list(snapshot.reviewed_drawing.issues)
        visual_issues = [
            iss for iss in issues
            if iss.visual_role in {"missing", "extra", "inaccurate", "connectivity", "warning", "critical"}
            and (role_filter is None or iss.visual_role == role_filter)
            and not (role_filter == "warning" and iss.category.startswith("reference_"))
        ]
    if not visual_issues:
        heading_title = "Issue-to-drawing mapping" if not role_filter else f"Issue-to-drawing mapping ({role_filter.title()})"
        return [
            _p(heading_title, styles["h2"]),
            _p(f"No {role_filter if role_filter else 'visual'} findings identified on this view.", styles["body"]),
            Spacer(1, 4),
        ]

    presentation = snapshot.review_response.get("finding_presentation") or {}
    is_compacted = bool(presentation.get("compacted"))
    max_rows = 15 if custom_issues is not None else (6 if role_filter else (10 if is_compacted else 25))
    total_count = len(visual_issues)
    summarized_count = 0
    if total_count > max_rows:
        summarized_count = total_count - max_rows
        visual_issues = visual_issues[:max_rows]

    last_header = "Evaluation status" if is_formative else "Applied deduction"
    rows = [[
        _p("Badge", styles["small"]),
        _p("Issue ID", styles["small"]),
        _p("Drawing role", styles["small"]),
        _p("Affected geometry / description", styles["small"]),
        _p(last_header, styles["small"]),
    ]]

    for iss in visual_issues:
        role_label = iss.visual_role.replace("-", " ").title()

        if iss.parent_object_id and iss.category == "missing_geometry":
            meas = iss.measurement if isinstance(iss.measurement, dict) else {}
            parts_cnt = meas.get("missing_part_count") or (len(iss.expected_geometries) if iss.expected_geometries else 1)
            total_cnt = meas.get("total_part_count", parts_cnt)
            is_whole_obj = ((iss.raw_deduction or 0.0) >= 9.0 and not iss.component_id) or (
                not iss.component_id and parts_cnt == total_cnt and total_cnt > 1
            )
            if is_whole_obj:
                desc = f"Missing object {iss.parent_object_id} ({parts_cnt}/{total_cnt} parts absent)"
            else:
                cid = iss.component_id or meas.get("component_id") or ""
                desc = f"Missing part {cid} of object {iss.parent_object_id}" if cid else f"Missing part of object {iss.parent_object_id}"
        elif iss.expected_entity_id or iss.source_entity_id:
            exp_str = f"Expected: {iss.expected_entity_id}" if iss.expected_entity_id else ""
            src_str = f"Student: {iss.source_entity_id}" if iss.source_entity_id else ""
            ents = " / ".join(filter(None, [exp_str, src_str]))
            desc = f"{str(iss.category).replace('_', ' ').title()}{f' ({ents})' if ents else ''}"
        else:
            desc = str(iss.technical_feedback or iss.category).replace("_", " ")

        if is_formative:
            score_str = "Diagnostic (Not graded)"
        else:
            applied = iss.final_applied_contribution
            split = iss.category_split
            if split and any(v > 0 for v in split.values()) and len([v for v in split.values() if v > 0]) > 1:
                ordered_keys = [k for k in ("geometry", "completion") if split.get(k, 0) > 0]
                ordered_keys += [k for k in split if k not in ("geometry", "completion") and split[k] > 0]
                split_str = ", ".join(f"{k.title()}: -{_number(split[k])}" for k in ordered_keys)
                score_str = f"-{_number(applied)} ({split_str})"
            elif applied > 0:
                cat_name = str(iss.score_category or "Applied").title()
                score_str = f"-{_number(applied)} ({cat_name})"
            else:
                score_str = f"0.00 ({iss.deduction_status or 'not scored'})"

        badge_text = _display_text(iss.badge_label) if iss.badge_label else "-"
        badge_style = styles["badge"] if iss.badge_label else styles["body"]
        rows.append([
            _p(badge_text, badge_style),
            _p(iss.issue_id, styles["body"]),
            _p(role_label, styles["body"]),
            _p(desc, styles["body"]),
            _p(score_str, styles["body"]),
        ])

    if summarized_count > 0:
        rows.append([
            _p("...", styles["body"]),
            _p("...", styles["body"]),
            _p("Summary", styles["body"]),
            _p(f"{summarized_count} additional findings summarized below", styles["body"]),
            _p("See details", styles["body"]),
        ])

    table = Table(rows, colWidths=[width * .10, width * .18, width * .16, width * .34, width * .22], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cbd5d1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    heading_title = "Issue-to-drawing mapping" if not role_filter else f"Issue-to-drawing mapping ({role_filter.title()})"
    return [
        _p(heading_title, styles["h2"]),
        table,
        Spacer(1, 4),
    ]


def _metadata_table(snapshot: ReviewSnapshot, styles: dict[str, ParagraphStyle], width: float) -> Table:
    metadata = snapshot.student_metadata
    response = snapshot.review_response
    rubric_template = response.get("rubric_template_name") or "DraftLens Baseline Rubric"
    rubric_source = str(response.get("rubric_source") or "baseline_template").replace("_", " ")
    assign_code = getattr(metadata, "assignment_code", None)
    assign_label = getattr(metadata, "assignment_type_label", None)
    assign_code_display = (
        f"{assign_code} ({assign_label})"
        if assign_code and assign_label
        else (assign_code or "Not provided")
    )
    rows = [
        ("Student name", metadata.student_name or "Not provided", "Student ID", metadata.student_id or "Not provided"),
        ("Course / section", metadata.course_section or "Not provided", "Report timestamp", snapshot.report_timestamp),
        ("Student DXF", _basename(snapshot.student_filename), "Reference DXF", _basename(snapshot.reference_filename)),
        ("Assignment title", snapshot.assignment_title or "Assignment", "Rubric template", rubric_template),
        ("Assignment type", snapshot.assignment_type or "Not confirmed", "Report ID", snapshot.review_id[:12]),
        ("Detected structure", ", ".join(snapshot.detected_features) or "No repeated structural features detected", "Rubric source", rubric_source),
    ]
    group_val = getattr(metadata, "group_code", None)
    if assign_code or group_val:
        rows.append(("Group", group_val or "Not provided", "Submission code", assign_code_display))
    return _four_column_table(rows, styles, width)


def _measurement(issue: dict[str, Any]) -> tuple[Any, Any, Any]:
    value = issue.get("measurement") or {}
    if not isinstance(value, dict): return None, None, None
    expected, actual = value.get("expected"), value.get("actual")
    deviation = value.get("deviation", value.get("difference", value.get("delta")))
    if deviation is None and isinstance(expected,(int,float)) and isinstance(actual,(int,float)): deviation = round(float(actual)-float(expected),6)
    return expected, actual, deviation


def _normalization_summary(snapshot: ReviewSnapshot) -> str:
    response, decision = snapshot.review_response, snapshot.normalization_decision
    if response.get("normalization_mode", "strict") == "strict":
        displacement = decision.get("global_displacement")
        if not displacement or not displacement.get("detected"):
            return "Strict placement. No transform is permitted or applied."
        return (
            "Strict placement. No transform was applied. Robust global displacement "
            f"evidence: displacement X={_number(displacement.get('displacement_x'))}, "
            f"Y={_number(displacement.get('displacement_y'))}; "
            f"magnitude {_number(displacement.get('magnitude'))}; support "
            f"{displacement.get('support_count', 0)}/{displacement.get('evidence_count', 0)} "
            f"({float(displacement.get('support_ratio') or 0) * 100:.1f}%); "
            f"position tolerance {_number(displacement.get('position_tolerance'))}; "
            f"displacement-to-tolerance ratio {_number(displacement.get('displacement_to_tolerance_ratio'))}."
        )
    selected, candidate = decision.get("selected_translation") or [0,0], decision.get("candidate_translation") or [0,0]
    status = "accepted" if decision.get("transform_applied") else "not accepted"
    return (f"Translation-tolerant placement; transform {status}. Selected translation X={_number(selected[0])}, Y={_number(selected[1])}; "
            f"candidate X={_number(candidate[0])}, Y={_number(candidate[1])}; support {decision.get('support_count',0)}/{decision.get('evidence_count',0)} "
            f"({float(decision.get('support_ratio') or 0)*100:.1f}%); confidence {decision.get('confidence','none')}; error reduction {_number(decision.get('total_error_reduction'))}. "
            f"Reason: {decision.get('rejection_reason') or 'accepted consensus transform'}.")


def _issue_story(
    issue: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    width: float,
    linked_supporting: list[dict[str, Any]] | None = None,
    compact: bool = False,
    *,
    is_formative: bool = False,
) -> list[Flowable]:
    if not is_formative and issue.get("deduction_status") == "diagnostic":
        is_formative = True
    expected, actual, deviation = _measurement(issue); guidance = issue.get("correction_guidance") or {}
    title = str(issue.get("category") or "finding").replace("_"," ").title()
    applied_num = issue.get("final_applied_contribution", 0)
    cat_split = issue.get("category_split")
    if not is_formative and cat_split and any(v > 0 for v in cat_split.values()) and len([v for v in cat_split.values() if v > 0]) > 1:
        ordered_keys = [k for k in ("geometry", "completion") if cat_split.get(k, 0) > 0]
        ordered_keys += [k for k in cat_split if k not in ("geometry", "completion") and cat_split[k] > 0]
        split_parts = [f"{k.title()}: -{_number(cat_split[k])}" for k in ordered_keys]
        applied_label = f"{_number(applied_num)} ({', '.join(split_parts)})"
    else:
        applied_label = _number(applied_num)
    if is_formative:
        rows = [
            ("Severity", issue.get("severity"), "Finding role", issue.get("finding_role")),
            ("Expected entity", issue.get("expected_entity_id"), "Student entity", issue.get("source_entity_id")),
            ("Expected measurement", _number(expected), "Actual measurement", _number(actual)),
            ("Deviation", _number(deviation), "Diagnostic status", "Actionable feedback (not graded)"),
        ]
    else:
        rows = [
            ("Severity",issue.get("severity"),"Finding role",issue.get("finding_role")),
            ("Expected entity",issue.get("expected_entity_id"),"Student entity",issue.get("source_entity_id")),
            ("Expected measurement",_number(expected),"Actual measurement",_number(actual)),
            ("Deviation",_number(deviation),"Rubric rule",issue.get("rubric_rule_id") or "None"),
            ("Score category",issue.get("score_category") or "Not scored","Raw deduction",_number(issue.get("raw_rule_deduction",0))),
            ("Applied deduction",applied_label,"Caps",f"rule {_number(issue.get('deduction_after_rule_cap',0))} / category {_number(issue.get('deduction_after_category_cap',0))}; {issue.get('cap_reason') or issue.get('deduction_status')}"),
        ]
    badge_part = f" [Badge {_display_text(issue.get('badge_label'))}]" if issue.get("badge_label") else ""
    heading_text = f"{issue.get('issue_id','Issue')}{badge_part} - {title}"
    output: list[Flowable] = [CondPageBreak(55), _p(heading_text, styles["h2"]), _four_column_table(rows, styles, width), Spacer(1,3), _p(issue.get("technical_feedback") or "Review this finding.", styles["body"])]
    if compact:
        if is_formative:
            compact_meta = f"{issue.get('severity')} | Expected {issue.get('expected_entity_id') or '-'} / student {issue.get('source_entity_id') or '-'} | Diagnostic feedback (not graded)"
        else:
            compact_meta = f"{issue.get('severity')} | Expected {issue.get('expected_entity_id') or '-'} / student {issue.get('source_entity_id') or '-'} | Applied {applied_label} | {issue.get('deduction_status') or 'not scored'}"
        output = [CondPageBreak(55), _p(heading_text, styles["h2"]),
                  _p(compact_meta, styles["small"]),
                  _p(issue.get("technical_feedback") or "Review this finding.", styles["body"])]
    if issue.get("suppression_reason"): output.append(_p(f"Suppression reason: {issue['suppression_reason']}", styles["small"]))
    related_primary = guidance.get("related_primary_issue_id") or (issue.get("measurement") or {}).get("linked_primary_issue_id")
    if related_primary and issue.get("finding_role") == "supporting":
        output.append(_p(f"Supporting evidence for primary issue: {related_primary}", styles["small"]))
    primary_command = guidance.get("primary_command") if issue.get("finding_role") == "primary" else None
    if primary_command and compact:
        output.append(_p(f"Correction: {primary_command}. {guidance.get('explanation') or ''}", styles["small"]))
    if primary_command and not compact:
        alternatives = ", ".join(guidance.get("alternative_commands") or []) or "None"
        precision_aids = ", ".join(guidance.get("precision_aids") or []) or "None"
        correction = Table(
            [
                [_p("Primary command", styles["small"]), _p(primary_command, styles["score_earned"])],
                [_p("Alternatives", styles["small"]), _p(alternatives, styles["callout"])],
                [_p("Precision aids", styles["small"]), _p(precision_aids, styles["callout"])],
                [_p("Explanation", styles["small"]), _p(guidance.get("explanation") or "Not provided", styles["callout"])],
            ],
            colWidths=[width * .2, width * .8],
            splitByRow=1, splitInRow=1,
        )
        correction.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff8f3")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#2d7254")),
            ("INNERGRID", (0, 0), (-1, -1), .3, colors.HexColor("#b8d6c7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        output.extend([Spacer(1, 3), _p("How to correct", styles["h2"]), correction])
    if linked_supporting:
        sup_rows = [[
            _p("Badge", styles["small"]),
            _p("Supporting issue", styles["small"]),
            _p("Category", styles["small"]),
            _p("Technical feedback", styles["small"]),
        ]]
        for sup in linked_supporting:
            sup_title = str(sup.get("category") or "topology").replace("_", " ").title()
            b_label = sup.get("badge_label")
            badge_p = _p(f"[Badge {b_label}]", styles["badge"]) if b_label else _p("-", styles["body"])
            sup_rows.append([
                badge_p,
                _p(sup.get("issue_id", "Issue"), styles["body"]),
                _p(sup_title, styles["body"]),
                _p(sup.get("technical_feedback") or "Supporting topology evidence", styles["body"]),
            ])
        sup_table = Table(sup_rows, colWidths=[width * .16, width * .22, width * .22, width * .40],
                          repeatRows=1, splitByRow=1, splitInRow=1)
        sup_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf4f9")),
            ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#d53f8c")),
            ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#e8b4cb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        output.extend([
            Spacer(1, 3),
            _p("Supporting topology findings (linked evidence)", styles["h2"]),
            sup_table,
        ])
    output.append(Spacer(1,5)); return output


def _finding_summary_story(
    response: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    width: float,
    *,
    is_formative: bool = False,
) -> list[Flowable]:
    presentation = response.get("finding_presentation") or {}
    if not presentation.get("compacted"):
        return []
    if is_formative:
        rows = [[
            _p("Issue type", styles["small"]),
            _p("Counts", styles["small"]),
            _p("Diagnostic status", styles["small"]),
        ]]
        for group in presentation.get("summary_groups") or []:
            counts = (
                f"{group.get('total_count', 0)} total; "
                f"{group.get('displayed_count', 0)} representatives; "
                f"{group.get('summarized_count', 0)} summarized"
            )
            rows.append([
                _p(str(group.get("issue_type") or "unknown").replace("_", " ").title(), styles["body"]),
                _p(counts, styles["body"]),
                _p("Actionable feedback (not graded)", styles["body"]),
            ])
        table = Table(rows, colWidths=[width * .30, width * .44, width * .26], repeatRows=1)
    else:
        rows = [[
            _p("Issue type", styles["small"]),
            _p("Counts", styles["small"]),
            _p("Score contribution", styles["small"]),
            _p("Cap reason", styles["small"]),
        ]]
        for group in presentation.get("summary_groups") or []:
            counts = (
                f"{group.get('total_count', 0)} total; "
                f"{group.get('contributed_count', 0)} contributed; "
                f"{group.get('summarized_count', 0)} summarized"
            )
            rows.append([
                _p(str(group.get("issue_type") or "unknown").replace("_", " ").title(), styles["body"]),
                _p(counts, styles["body"]),
                _p(_number(group.get("score_contribution", 0)), styles["body"]),
                _p(str(group.get("cap_reason") or group.get("deduction_status") or "none").replace("_", " "), styles["body"]),
            ])
        table = Table(rows, colWidths=[width * .24, width * .4, width * .16, width * .2], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d6bd7d")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff3cf")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    totals = (
        f"{presentation.get('total_raw_count', 0)} primary findings; "
        f"{presentation.get('total_displayed_count', 0)} representatives; "
        f"{presentation.get('total_summarized_count', 0)} additional summarized findings. "
        + (
            "All primary findings are retained below for diagnostic review."
            if is_formative
            else "All primary findings, including capped findings, are retained below."
        )
    )
    return [_p("Compact finding summary", styles["h1"]), _p(totals, styles["body"]), table, Spacer(1, 5)]



def generate_pdf(snapshot: ReviewSnapshot, *, include_appendix: bool = False) -> bytes:
    """Generate a deterministic authoritative report without invoking grading."""
    styles, output = _styles(), BytesIO()
    response = snapshot.review_response
    is_overridden = bool(response.get("instructor_override"))
    doc_subject = f"Instructor-override review {snapshot.review_id}" if is_overridden else f"Authoritative review {snapshot.review_id}"
    document = SimpleDocTemplate(output,pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,topMargin=15*mm,bottomMargin=16*mm,title="DraftLens EDU Drawing Assessment Report",author="DraftLens EDU",subject=doc_subject)
    # SimpleDocTemplate's frame has 6pt padding on each side, inside the margins.
    width = A4[0]-document.leftMargin-document.rightMargin - 12; counts = response.get("finding_counts") or {}; score = response.get("score",0)
    presentation = compact_finding_presentation(
        list(response.get("issues") or []), response.get("unsupported_entities")
    )
    unsupported_summary = presentation.get("unsupported_summary") or {}
    unsupported_count = counts.get("unsupported_entities", 0)

    is_formative = str(response.get("assessment_mode") or snapshot.approved_rubric.get("assessment_mode") or "summative").lower() == "formative"
    title_text = "DraftLens EDU — Formative Assessment" if is_formative else "DraftLens EDU"
    subtitle_text = "Diagnostic Drawing Assessment (Feedback Only — Not Graded)" if is_formative else "Drawing Assessment Report"

    # --- PAGE 1: Assessment Summary ---
    story: list[Flowable] = [_p(title_text, styles["title"]), _p(subtitle_text, styles["subtitle"]), _metadata_table(snapshot, styles, width), Spacer(1, 4)]
    if is_overridden:
        status = str(response.get("compatibility_status") or "suspicious").replace("_", " ")
        story.extend([
            _p("Instructor compatibility override (Non-authoritative result)", styles["h1"]),
            _p(
                f"Compatibility was classified as {status}. The instructor explicitly selected Grade anyway. "
                "Because automated compatibility safeguards were bypassed, this report records the provisional override result rather than an authoritative certification.",
                styles["body"],
            ),
        ])
        if response.get("compatibility_message"):
            story.append(
                _p(f"Compatibility warning: {response['compatibility_message']}", styles["body"])
            )
    story.append(
        _p(f"Rubric source: {response.get('rubric_template_name', 'DraftLens Baseline Rubric')} ({str(response.get('rubric_source', 'baseline_template')).replace('_', ' ')}).", styles["small"])
    )
    if is_formative:
        score_cell = Table(
            [
                [_p("Diagnostic Feedback", styles["score_earned"])],
                [_p("Not Graded", styles["small"])],
            ],
            colWidths=[width * 0.34],
        )
        score_cell.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
    else:
        score_cell = _p(f"{_number(score)} / 100", styles["score"])
    score_table = Table([[score_cell, _p("Primary issues", styles["small"]), _p("Supporting", styles["small"]), _p("Reference notes", styles["small"]), _p("Unsupported", styles["small"])],
                         ["", _p(counts.get("primary_student_issues", 0), styles["body"]), _p(counts.get("supporting_findings", 0), styles["body"]), _p(counts.get("reference_validation_notes", 0), styles["body"]), _p(unsupported_count, styles["body"])]], colWidths=[width * .36, width * .16, width * .16, width * .16, width * .16])
    score_table.setStyle(TableStyle([("SPAN", (0, 0), (0, 1)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f4ed")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#cbd5d1")), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([score_table, Spacer(1, 3)])

    if unsupported_summary.get("has_unsupported") or unsupported_count > 0:
        notice_msg = unsupported_summary.get("notice") or (
            f"Notice: {unsupported_count} unsupported entity record(s) detected. "
            "Unsupported DXF content was not automatically assessed."
        )
        notice_cell = Table([[_p(notice_msg, styles["callout"])]], colWidths=[width])
        notice_cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff9e6")),
            ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#d69e2e")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([notice_cell, Spacer(1, 3)])

    if is_formative:
        story.append(_p("Formative evaluation categories", styles["h1"]))
        breakdown_rows = [[
            _p("Evaluation category", styles["small"]),
            _p("Category scope", styles["small"]),
            _p("Diagnostic status", styles["small"]),
        ]]
        for category in snapshot.score_breakdown.get("category_subtotals", []):
            breakdown_rows.append([
                _p(category.get("name", category.get("id", "Category")), styles["body"]),
                _p(category.get("definition") or humanize(category.get("id", "")), styles["body"]),
                _p("Diagnostic feedback provided", styles["body"]),
            ])
        breakdown = Table(breakdown_rows, colWidths=[width * .35, width * .45, width * .20], repeatRows=1)
        breakdown.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d8e0dc")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    else:
        story.append(_p("Score breakdown", styles["h1"]))
        breakdown_rows = [[
            _p("Category", styles["small"]),
            _p("Earned / available", styles["small"]),
            _p("Applied deduction", styles["small"]),
        ]]
        for category in snapshot.score_breakdown.get("category_subtotals", []):
            breakdown_rows.append([
                _p(category.get("name", category.get("id", "Category")), styles["body"]),
                _p(f"{_number(category.get('score'))} / {_number(category.get('weight'))}", styles["score_earned"]),
                _p(_number(category.get("deduction")), styles["body"]),
            ])
        breakdown_rows.append([
            _p("Total", styles["body"]),
            _p(f"{_number(score)} / 100", styles["score_earned"]),
            _p(_number(snapshot.score_breakdown.get("total_applied_deduction", 0)), styles["body"]),
        ])
        breakdown = Table(breakdown_rows, colWidths=[width * .48, width * .3, width * .22], repeatRows=1)
        breakdown.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,colors.HexColor("#d8e0dc")),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#edf3f0")),("ALIGN",(1,1),(-1,-1),"RIGHT"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    completion_mode = response.get("completion_scoring_mode", "rule_based")
    if completion_mode == "object_part_deduction":
        p_val = response.get("missing_part_deduction")
        c_req = response.get("construction_requirement", "geometry_only").replace("_", " ")
        if is_formative or p_val is None:
            completion_str = f"Object & part structure ({c_req})"
        else:
            completion_str = f"Object & part budget (p = {float(p_val):g}, {c_req})"
    elif completion_mode == "proportional":
        completion_str = "Proportional completion"
    else:
        completion_str = "Rule-based structure" if is_formative else "Rule-based deductions"
    placement = "Placement policy: " + ("Translation-tolerant placement" if response.get("normalization_mode")=="translation" else "Strict placement") + f". Completion policy: {completion_str}."
    story.extend([
        breakdown,
        _p("Placement and transform decision", styles["h1"]),
        _p(placement, styles["body"]),
        _p(_normalization_summary(snapshot), styles["small"]),
        PageBreak(),
    ])

    all_issues = list(response.get("issues") or [])
    issue_by_id = {issue["issue_id"]: issue for issue in all_issues}

    displayed_ids = set(presentation["default_issue_ids"])
    issues = [issue for issue in all_issues if issue.get("issue_id") in displayed_ids]

    primary_issues = [issue for issue in issues if issue.get("finding_role") == "primary"]
    representative_ids = set(presentation["displayed_issue_ids"])
    summarized_primary = [issue for issue in primary_issues if issue["issue_id"] not in representative_ids]
    rep_primary = [issue for issue in primary_issues if issue["issue_id"] in representative_ids]
    linked_map = presentation.get("linked_supporting_by_primary") or {}

    # Determine all badge labels that have an unambiguous printed lookup in this report
    visual_issues = [
        iss for iss in snapshot.reviewed_drawing.issues
        if iss.visual_role in {"missing", "extra", "inaccurate", "connectivity", "warning", "critical"}
    ]
    max_map_rows = 10 if bool(presentation.get("compacted")) else 25
    mapped_badges = {iss.badge_label for iss in visual_issues[:max_map_rows] if iss.badge_label}

    # Include badges from each role-specific drawing view (Drawings 1-6 each display up to 6 issues)
    for r in ("missing", "extra", "inaccurate", "connectivity", "warning", "critical"):
        for iss in [i for i in visual_issues if i.visual_role == r][:6]:
            if iss.badge_label:
                mapped_badges.add(iss.badge_label)

    # Include badges from object detail sheets
    for iss in snapshot.reviewed_drawing.issues:
        if iss.parent_object_id and iss.visual_role in {"missing", "inaccurate"} and iss.badge_label:
            mapped_badges.add(iss.badge_label)

    headings_badges = set()
    for iss in rep_primary:
        if iss.get("badge_label"): headings_badges.add(iss["badge_label"])
    for iss in summarized_primary:
        if iss.get("badge_label"): headings_badges.add(iss["badge_label"])
    for iss in rep_primary:
        for lid in linked_map.get(iss["issue_id"], []):
            sup = issue_by_id.get(lid)
            if sup and sup.get("badge_label"):
                headings_badges.add(sup["badge_label"])
    for iss in issues:
        if iss.get("finding_role") == "supporting" and iss.get("badge_label"):
            headings_badges.add(iss["badge_label"])
        elif iss.get("finding_role") == "reference" and iss.get("badge_label"):
            headings_badges.add(iss["badge_label"])
        elif iss.get("finding_role") == "unsupported" and essential_finding(iss) and iss.get("badge_label"):
            headings_badges.add(iss["badge_label"])
        elif iss.get("finding_role") == "informational" and iss.get("badge_label"):
            headings_badges.add(iss["badge_label"])

    if include_appendix:
        for iss in all_issues:
            if iss.get("badge_label"):
                headings_badges.add(iss["badge_label"])

    allowed_badge_labels = mapped_badges | headings_badges

    # --- DRAWING PAGES 0 TO 6 (7 Consecutive Drawing Pages) ---
    rep_drawing_height = 240.0
    stu_extents = getattr(snapshot.reviewed_drawing, "student_extents", None) or snapshot.reviewed_drawing.extents

    # Drawing 0: Student and reference, side by side
    story.extend([
        _p("Drawing 0 — Reviewed drawing (Student and reference)", styles["h1"]),
        _p("Student drawing (left) and Reference drawing (right) shown side-by-side in raw comparison basis without defect overlays.", styles["subtitle"]),
        SideBySideDrawingFlowable(snapshot.reviewed_drawing, width, height=210.0),
        Spacer(1, 4),
        *_overlay_legend(styles, width),
    ])
    unit_notice = response.get("unit_notice")
    if unit_notice:
        story.append(_p(unit_notice, styles["small"]))
    story.append(PageBreak())

    # Drawing 1: Missing
    story.extend([
        _p("Drawing 1 — Student + Missing entities overlay", styles["h1"]),
        _p("Orange dashed lines indicate expected reference geometry absent from the student submission.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="missing",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("missing", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="missing", is_formative=is_formative),
        PageBreak(),
    ])

    # Drawing 2: Extra
    story.extend([
        _p("Drawing 2 — Student + Extra entities overlay", styles["h1"]),
        _p("Solid blue lines indicate extra student geometry not required by the reference drawing.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="extra",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("extra", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="extra", is_formative=is_formative),
        PageBreak(),
    ])

    # Drawing 3: Inaccurate
    story.extend([
        _p("Drawing 3 — Student + Inaccurate overlay", styles["h1"]),
        _p("Solid red indicates actual student geometry; dashed red indicates the expected reference counterpart.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="inaccurate",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("inaccurate", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="inaccurate", is_formative=is_formative),
        PageBreak(),
    ])

    # Drawing 4: Connectivity
    story.extend([
        _p("Drawing 4 — Student + Connectivity overlay", styles["h1"]),
        _p("Magenta markers indicate endpoint gaps, improper closures, or junction errors in student geometry.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="connectivity",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("connectivity", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="connectivity", is_formative=is_formative),
        PageBreak(),
    ])

    # Drawing 5: Warning
    story.extend([
        _p("Drawing 5 — Student + Warning overlay", styles["h1"]),
        _p("Amber markers indicate student-file quality findings such as duplicate overlapping geometry or zero-length lines.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="warning",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("warning", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="warning", is_formative=is_formative),
        PageBreak(),
    ])

    # Drawing 6: Critical
    story.extend([
        _p("Drawing 6 — Student + Critical overlay", styles["h1"]),
        _p("Bold red markers indicate critical assessment blockers or severe drawing errors.", styles["subtitle"]),
        ReviewedDrawingFlowable(
            snapshot.reviewed_drawing,
            width,
            height=rep_drawing_height,
            role_filter="critical",
            extents=stu_extents,
            allowed_badge_labels=allowed_badge_labels,
            representative_issue_ids=representative_ids,
        ),
        Spacer(1, 4),
        *_category_legend("critical", styles, width),
        Spacer(1, 2),
        *_issue_mapping_table(snapshot, styles, width, role_filter="critical", is_formative=is_formative),
        PageBreak(),
    ])

    # --- OBJECT DETAIL SECTION: INDEX AND PER-OBJECT PAGES ---
    assessment_objects = response.get("assessment_objects") or []
    object_translations = response.get("object_translations") or {}
    rubric_obj = response.get("rubric") or {}
    rubric_version_str = str(response.get("rubric_version") or rubric_obj.get("rubric_version") or "1.0")
    assignment_type_str = str(response.get("assignment_type") or rubric_obj.get("assignment_type") or "")
    show_object_detail = bool(assessment_objects) and (
        completion_mode == "object_part_deduction"
        or rubric_version_str in {"2.0", "2.1"}
        or assignment_type_str == "Geometry only"
        or bool(response.get("confirmed_objects"))
    )

    if show_object_detail:
        obj_issues_map: dict[str, list[ReviewedIssue]] = {}
        for iss in snapshot.reviewed_drawing.issues:
            if iss.parent_object_id and iss.visual_role in {"missing", "inaccurate"}:
                obj_issues_map.setdefault(iss.parent_object_id, []).append(iss)

        max_callouts_per_sheet = 12

        def _issue_local_bounds(iss: ReviewedIssue) -> tuple[float, float, float, float] | None:
            bxs: list[float] = []
            bys: list[float] = []
            if _is_detached_placement_issue(iss):
                geoms = iss.actual_geometries or ((iss.actual_geometry,) if iss.actual_geometry else ())
            else:
                if iss.region and len(iss.region) == 4:
                    bxs.extend([float(iss.region[0]), float(iss.region[2])])
                    bys.extend([float(iss.region[1]), float(iss.region[3])])
                geoms = (iss.expected_geometries or ()) + (iss.actual_geometries or ())
            for g in geoms:
                if g.bbox and len(g.bbox) == 4:
                    bxs.extend([float(g.bbox[0]), float(g.bbox[2])])
                    bys.extend([float(g.bbox[1]), float(g.bbox[3])])
            if bxs and bys:
                return (min(bxs), min(bys), max(bxs), max(bys))
            return None

        def _issue_sort_xy(iss: ReviewedIssue) -> tuple[float, float, str]:
            lb = _issue_local_bounds(iss)
            if lb is not None:
                return ((lb[0] + lb[2]) / 2.0, (lb[1] + lb[3]) / 2.0, iss.issue_id)
            return (0.0, 0.0, iss.issue_id)

        def _cluster_object_batches(issues: list[ReviewedIssue]) -> list[list[ReviewedIssue]]:
            if len(issues) <= max_callouts_per_sheet:
                return [list(issues)] if issues else []
            component_items = [iss for iss in issues if not _is_detached_placement_issue(iss)]
            detached_items = [iss for iss in issues if _is_detached_placement_issue(iss)]
            remaining = list(component_items)
            batches_out: list[list[ReviewedIssue]] = []
            bounds_cache = {iss.issue_id: _issue_local_bounds(iss) for iss in issues}
            while remaining:
                seed = min(
                    remaining,
                    key=lambda it: (
                        (bounds_cache[it.issue_id][0] + bounds_cache[it.issue_id][2]) / 2.0
                        if bounds_cache[it.issue_id] else 0.0,
                        (bounds_cache[it.issue_id][1] + bounds_cache[it.issue_id][3]) / 2.0
                        if bounds_cache[it.issue_id] else 0.0,
                        it.issue_id,
                    ),
                )
                remaining.remove(seed)
                batch = [seed]
                cur_box = bounds_cache[seed.issue_id]
                while remaining and len(batch) < max_callouts_per_sheet:
                    if cur_box is None:
                        nxt = remaining.pop(0)
                        batch.append(nxt)
                        cur_box = bounds_cache[nxt.issue_id]
                        continue
                    cur_cx = (cur_box[0] + cur_box[2]) / 2.0
                    cur_cy = (cur_box[1] + cur_box[3]) / 2.0
                    cur_span = (cur_box[2] - cur_box[0]) + (cur_box[3] - cur_box[1])

                    def _pick_key(cand: ReviewedIssue) -> tuple[float, float, str]:
                        cb = bounds_cache[cand.issue_id]
                        if cb is None:
                            return (0.0, 0.0, cand.issue_id)
                        nmin_x = min(cur_box[0], cb[0])
                        nmin_y = min(cur_box[1], cb[1])
                        nmax_x = max(cur_box[2], cb[2])
                        nmax_y = max(cur_box[3], cb[3])
                        new_span = (nmax_x - nmin_x) + (nmax_y - nmin_y)
                        ccx = (cb[0] + cb[2]) / 2.0
                        ccy = (cb[1] + cb[3]) / 2.0
                        return (max(0.0, new_span - cur_span), math.hypot(ccx - cur_cx, ccy - cur_cy), cand.issue_id)

                    nxt = min(remaining, key=_pick_key)
                    remaining.remove(nxt)
                    batch.append(nxt)
                    nb = bounds_cache[nxt.issue_id]
                    if nb is not None:
                        cur_box = (
                            min(cur_box[0], nb[0]),
                            min(cur_box[1], nb[1]),
                            max(cur_box[2], nb[2]),
                            max(cur_box[3], nb[3]),
                        )
                batches_out.append(batch)
            for det in detached_items:
                det_b = bounds_cache.get(det.issue_id)
                merged = False
                if batches_out and len(batches_out[-1]) < max_callouts_per_sheet:
                    last_boxes = [bounds_cache.get(it.issue_id) for it in batches_out[-1] if bounds_cache.get(it.issue_id) is not None]
                    if last_boxes and det_b is not None:
                        lx0 = min(b[0] for b in last_boxes); ly0 = min(b[1] for b in last_boxes)
                        lx1 = max(b[2] for b in last_boxes); ly1 = max(b[3] for b in last_boxes)
                        lspan_x = lx1 - lx0; lspan_y = ly1 - ly0
                        dspan_x = det_b[2] - det_b[0]; dspan_y = det_b[3] - det_b[1]
                        if (dspan_x <= 1e-6 or lspan_x >= 0.70 * dspan_x) and (dspan_y <= 1e-6 or lspan_y >= 0.70 * dspan_y):
                            batches_out[-1].append(det)
                            merged = True
                    elif det_b is None:
                        batches_out[-1].append(det)
                        merged = True
                if not merged:
                    batches_out.append([det])
            return batches_out

        # 1. Object Assessment Detail Index Page
        index_rows = [[
            _p("Object ID", styles["small"]),
            _p("Components", styles["small"]),
            _p("Missing", styles["small"]),
            _p("Inaccurate", styles["small"]),
            _p("Placement offset", styles["small"]),
            _p("Status", styles["small"]),
            _p("Detail sheet", styles["small"]),
        ]]
        sheet_counter = 0
        detail_sheet_batches: dict[str, list[tuple[str, list[ReviewedIssue]]]] = {}
        for obj in sorted(assessment_objects, key=lambda o: str(o.get("object_id", ""))):
            oid = str(obj.get("object_id", ""))
            issues_for_obj = sorted(obj_issues_map.get(oid, []), key=_issue_sort_xy)
            n_miss = sum(1 for iss in issues_for_obj if iss.visual_role == "missing")
            n_inacc = sum(1 for iss in issues_for_obj if iss.visual_role == "inaccurate")
            comp_cnt = obj.get("component_count") or len(obj.get("components") or []) or obj.get("part_count", 1)

            t = object_translations.get(oid)
            if t and (abs(t[0]) > 1e-4 or abs(t[1]) > 1e-4):
                offset_str = f"dx={t[0]:+.1f}, dy={t[1]:+.1f}"
            else:
                offset_str = "Aligned (0, 0)"

            if n_miss > 0 or n_inacc > 0:
                sheet_counter += 1
                batches = _cluster_object_batches(issues_for_obj)
                if len(batches) == 1:
                    sheet_label = f"Sheet D-{sheet_counter}"
                    detail_sheet_batches[oid] = [(sheet_label, batches[0])]
                else:
                    named_batches = []
                    for b_idx, batch in enumerate(batches):
                        suffix = chr(ord("a") + b_idx)
                        named_batches.append((f"Sheet D-{sheet_counter}{suffix}", batch))
                    detail_sheet_batches[oid] = named_batches
                    first_suffix = "a"
                    last_suffix = chr(ord("a") + len(batches) - 1)
                    sheet_label = f"Sheets D-{sheet_counter}{first_suffix}–D-{sheet_counter}{last_suffix}"
                status_str = "Action required"
            else:
                sheet_label = "None (Compliant)"
                status_str = "Clean / Compliant"

            index_rows.append([
                _p(oid, styles["badge"]),
                _p(str(comp_cnt), styles["body"]),
                _p(f"{n_miss} absent" if n_miss > 0 else "0 (Clean)", styles["body"]),
                _p(f"{n_inacc} deviations" if n_inacc > 0 else "0 (Clean)", styles["body"]),
                _p(offset_str, styles["small"]),
                _p(status_str, styles["body"]),
                _p(sheet_label, styles["body"]),
            ])

        index_table = Table(index_rows, colWidths=[width * .13, width * .11, width * .12, width * .14, width * .19, width * .14, width * .17], repeatRows=1)
        index_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cbd5d1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))

        story.extend([
            _p("Object Assessment Detail Index", styles["title"]),
            _p("Assessment object index, component breakdowns, recognized placement offsets, and local detail view references.", styles["subtitle"]),
            Spacer(1, 4),
            index_table,
            Spacer(1, 8),
            _p("Objects with recorded Missing or Inaccurate findings are detailed on the individual sheets following this index.", styles["small"]),
            PageBreak(),
        ])

        # 2. Per-Object Zoomed Detail Pages (with automatic continuation sheets for dense objects)
        for obj in sorted(assessment_objects, key=lambda o: str(o.get("object_id", ""))):
            oid = str(obj.get("object_id", ""))
            batches = detail_sheet_batches.get(oid, [])
            if not batches:
                continue

            raw_bounds = obj.get("bounds") or obj.get("bbox")
            t = object_translations.get(oid) or (0.0, 0.0)
            dx, dy = float(t[0]), float(t[1])

            total_batches = len(batches)
            for b_idx, (sheet_name, batch_issues) in enumerate(batches, 1):
                n_miss = sum(1 for iss in batch_issues if iss.visual_role == "missing")
                n_inacc = sum(1 for iss in batch_issues if iss.visual_role == "inaccurate")

                xs: list[float] = []
                ys: list[float] = []
                if total_batches == 1 and raw_bounds and len(raw_bounds) == 4:
                    xs.extend([raw_bounds[0] + dx, raw_bounds[2] + dx])
                    ys.extend([raw_bounds[1] + dy, raw_bounds[3] + dy])

                for iss in batch_issues:
                    if _is_detached_placement_issue(iss):
                        crop_geoms = iss.actual_geometries or ((iss.actual_geometry,) if iss.actual_geometry else ())
                    else:
                        if iss.region and len(iss.region) == 4:
                            xs.extend([iss.region[0], iss.region[2]])
                            ys.extend([iss.region[1], iss.region[3]])
                        crop_geoms = (iss.expected_geometries or ()) + (iss.actual_geometries or ())
                    for g in crop_geoms:
                        if g.bbox and len(g.bbox) == 4:
                            xs.extend([g.bbox[0], g.bbox[2]])
                            ys.extend([g.bbox[1], g.bbox[3]])

                if not (xs and ys) and raw_bounds and len(raw_bounds) == 4:
                    xs.extend([raw_bounds[0] + dx, raw_bounds[2] + dx])
                    ys.extend([raw_bounds[1] + dy, raw_bounds[3] + dy])

                if xs and ys:
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    span_x = max(max_x - min_x, 12.0)
                    span_y = max(max_y - min_y, 12.0)
                    pad_x = max(span_x * 0.18, 12.0)
                    pad_y = max(span_y * 0.18, 12.0)
                    zoom_extents = (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)
                else:
                    zoom_extents = stu_extents

                batch_issue_ids = {iss.issue_id for iss in batch_issues}
                part_note = f" — Part {b_idx} of {total_batches}" if total_batches > 1 else ""

                story.extend([
                    _p(f"{sheet_name} - Object Detail ({oid}{part_note})", styles["h1"]),
                    _p(
                        f"Zoomed local view for {oid}{part_note} showing student geometry underlay with aligned expected overlays and defect callouts "
                        f"({n_miss} missing, {n_inacc} inaccurate on this sheet).",
                        styles["subtitle"],
                    ),
                    ReviewedDrawingFlowable(
                        snapshot.reviewed_drawing,
                        width,
                        height=205.0,
                        role_filter="object_detail",
                        extents=zoom_extents,
                        allowed_badge_labels=allowed_badge_labels,
                        allowed_issue_ids=batch_issue_ids,
                        representative_issue_ids=representative_ids,
                    ),
                    Spacer(1, 4),
                    *_category_legend("object_detail", styles, width),
                    Spacer(1, 2),
                    *_issue_mapping_table(snapshot, styles, width, is_formative=is_formative, custom_issues=batch_issues),
                    PageBreak(),
                ])

    # --- PAGES 3+: Primary Feedback Pages ---
    story.extend([
        _p("Finding details", styles["title"]),
        _p("Primary actionable findings and correction guidance. Supporting evidence is linked under primary findings.", styles["subtitle"]),
    ])
    story.extend(_finding_summary_story(response, styles, width, is_formative=is_formative))

    story.append(_p("Primary issue details", styles["h1"]))
    if not rep_primary:
        story.append(_p("No student issues detected.", styles["body"]))
    else:
        for issue in rep_primary:
            linked_ids = linked_map.get(issue["issue_id"]) or []
            linked_supporting = [issue_by_id[lid] for lid in linked_ids if lid in issue_by_id]
            detail = _issue_story(issue, styles, width, linked_supporting=linked_supporting,
                                  compact=presentation["compacted"], is_formative=is_formative)
            if linked_supporting:
                # A multi-page evidence table must not push the heading to an empty page.
                story.extend(detail)
            else:
                story.append(KeepTogether(detail))

    if summarized_primary:
        story.append(_p("Additional actionable findings", styles["h1"]))
        if is_formative:
            story.append(_p("These findings require review and correction. Full diagnostic evidence is available by issue ID in the viewer or technical appendix.", styles["body"]))
            rows = [[_p(label, styles["small"]) for label in ("Badge", "Issue ID", "Expected / student entity", "Correction", "Diagnostic status")]]
        else:
            story.append(_p("These findings still require review and correction. A zero applied deduction, including a cap, does not mean the issue is resolved. Full evidence is available by issue ID in the viewer or technical appendix.", styles["body"]))
            rows = [[_p(label, styles["small"]) for label in ("Badge", "Issue ID", "Expected / student entity", "Correction", "Applied / status")]]
        for issue in summarized_primary:
            guidance = issue.get("correction_guidance") or {}
            b_label = issue.get("badge_label")
            badge_p = _p(f"[Badge {b_label}]", styles["badge"]) if b_label else _p("-", styles["body"])
            if is_formative:
                status_col = _p("Actionable feedback (not graded)", styles["small"])
            else:
                applied_num = issue.get('final_applied_contribution', 0)
                split = issue.get("category_split")
                if split and any(v > 0 for v in split.values()) and len([v for v in split.values() if v > 0]) > 1:
                    ordered_keys = [k for k in ("geometry", "completion") if split.get(k, 0) > 0]
                    ordered_keys += [k for k in split if k not in ("geometry", "completion") and split[k] > 0]
                    applied_str = f"{_number(applied_num)} ({', '.join(f'{k.title()}: -{_number(split[k])}' for k in ordered_keys)})"
                else:
                    applied_str = _number(applied_num)
                status_col = _p(f"{applied_str} / {issue.get('deduction_status') or 'not scored'}", styles["small"])
            rows.append([
                badge_p,
                _p(issue["issue_id"], styles["small"]),
                _p(f"{issue.get('expected_entity_id') or '-'} / {issue.get('source_entity_id') or '-'}", styles["small"]),
                _p(f"{issue.get('severity', '')} {str(issue.get('category') or 'finding').replace('_', ' ')}: {guidance.get('primary_command') or 'See representative correction guidance'}", styles["small"]),
                status_col,
            ])
        additional = Table(rows, colWidths=[width * .16, width * .16, width * .20, width * .32, width * .16], repeatRows=1, splitInRow=1)
        additional.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cbd5d1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")),
        ]))
        story.append(additional)

    # Essential supporting evidence stays visible even without the appendix.
    unlinked_supporting = [issue for issue in issues if issue.get("finding_role") == "supporting"]
    if unlinked_supporting:
        first_detail = _issue_story(unlinked_supporting[0], styles, width, is_formative=is_formative)
        story.append(KeepTogether([_p("Essential supporting findings", styles["h1"])] + first_detail))
        for issue in unlinked_supporting[1:]:
            story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

    # Reference notes
    ref_notes = [issue for issue in issues if issue.get("finding_role") == "reference"]
    if ref_notes:
        first_detail = _issue_story(ref_notes[0], styles, width, is_formative=is_formative)
        story.append(KeepTogether([_p("Reference notes", styles["h1"])] + first_detail))
        for issue in ref_notes[1:]:
            story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

    # Actionable unsupported findings (score-affecting or critical)
    actionable_unsupported = [
        issue for issue in issues
        if issue.get("finding_role") == "unsupported" and essential_finding(issue)
    ]
    if actionable_unsupported:
        first_detail = _issue_story(actionable_unsupported[0], styles, width, is_formative=is_formative)
        story.append(KeepTogether([_p("Actionable unsupported findings", styles["h1"])] + first_detail))
        for issue in actionable_unsupported[1:]:
            story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

    informational = [issue for issue in issues if issue.get("finding_role") == "informational"]
    if informational:
        first_detail = _issue_story(informational[0], styles, width, is_formative=is_formative)
        story.append(KeepTogether([_p("Informational findings", styles["h1"])] + first_detail))
        for issue in informational[1:]:
            story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

    # --- OPTIONAL TECHNICAL APPENDIX ---
    if include_appendix:
        story.append(PageBreak())
        story.append(_p("Technical Appendix", styles["title"]))
        story.append(_p("Comprehensive diagnostic evidence, all supporting topology findings, and complete unsupported entity records.", styles["subtitle"]))

        all_supporting = [issue for issue in all_issues if issue.get("finding_role") == "supporting"]
        if presentation["compacted"]:
            story.append(_p("Full evidence for all primary findings", styles["h1"]))
            for issue in all_issues:
                if issue.get("finding_role") != "primary":
                    continue
                story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))
        if all_supporting:
            story.append(_p("All supporting topology findings", styles["h1"]))
            for issue in all_supporting:
                story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

        unsupported_findings = [issue for issue in all_issues if issue.get("finding_role") == "unsupported"]
        if unsupported_findings:
            story.append(_p("Unsupported findings", styles["h1"]))
            for issue in unsupported_findings:
                story.append(KeepTogether(_issue_story(issue, styles, width, is_formative=is_formative)))

        unsupported = response.get("unsupported_entities") or {}
        records = list(unsupported.get("reference") or []) + list(unsupported.get("student") or [])
        if records:
            story.append(_p("Unsupported entity records", styles["h1"]))
            groups = unsupported_summary.get("groups") or []
            if groups:
                summary_rows = [[
                    _p("Source", styles["small"]),
                    _p("Entity type", styles["small"]),
                    _p("Count", styles["small"]),
                    _p("Layers", styles["small"]),
                    _p("Sample handles", styles["small"]),
                ]]
                for grp in groups:
                    summary_rows.append([
                        _p(grp["source"].title(), styles["body"]),
                        _p(grp["entity_type"], styles["body"]),
                        _p(str(grp["count"]), styles["body"]),
                        _p(", ".join(grp.get("layers", [])) or "None", styles["body"]),
                        _p(", ".join(grp.get("sample_handles", [])) or "None", styles["body"]),
                    ])
                grp_table = Table(summary_rows, colWidths=[width * .15, width * .2, width * .1, width * .25, width * .3], repeatRows=1, splitInRow=1)
                grp_table.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cbd5d1")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.extend([grp_table, Spacer(1, 4)])

            for record in records:
                story.append(_p(
                    f"{record.get('source', 'drawing').title()}: {record.get('entity_type', 'unknown')} - "
                    f"handle {record.get('handle', 'not available')} - layer {record.get('layer', 'not available')}",
                    styles["body"],
                ))

    def footer(pdf: canvas.Canvas, doc: SimpleDocTemplate) -> None:
        pdf.saveState()
        pdf.setStrokeColor(colors.HexColor("#d8e0dc"))
        pdf.line(document.leftMargin, 11.5 * mm, A4[0] - document.rightMargin, 11.5 * mm)
        pdf.setFillColor(colors.HexColor("#51615a"))
        pdf.setFont(FONT_NAME, 6.5)
        pdf.drawString(document.leftMargin, 8.0 * mm, "DraftLens - part of M2 Intelligent Education System")
        pdf.drawRightString(A4[0] - document.rightMargin, 8.0 * mm, f"DraftLens EDU - Report {snapshot.review_id[:12]}")
        pdf.drawString(document.leftMargin, 4.5 * mm, "Founders: MOUKiD BADiE & Mervat El-Sawaf")
        pdf.drawRightString(A4[0] - document.rightMargin, 4.5 * mm, f"Page {doc.page}")
        pdf.restoreState()
    document.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=_InvariantCanvas); return output.getvalue()
