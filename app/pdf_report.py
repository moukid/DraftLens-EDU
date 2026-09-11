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
from .reviewed_dxf import ReviewedDrawing, ReviewedEntity, ReviewedIssue
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
    "inaccurate-expected": ("#ed8936", 1.5, (5, 3)), "inaccurate-actual": ("#e53e3e", 2.1, None),
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

    def __init__(self, reviewed: ReviewedDrawing, width: float, height: float = 205):
        super().__init__()
        self.reviewed, self.width, self.height = reviewed, float(width), float(height)

    def wrap(self, available_width: float, _available_height: float) -> tuple[float, float]:
        return min(self.width, available_width), self.height

    def _point(self, transform: CoordinateTransform, point: tuple[float, float]) -> tuple[float, float]:
        x, screen_y = transform.point(point)
        return x, self.height - screen_y

    def _style(self, role: str) -> None:
        _set_role_style(self.canv, role)

    def _entity(self, entity: ReviewedEntity, role: str, transform: CoordinateTransform) -> None:
        self._style(role)
        points = tuple(sorted(entity.points)) if entity.kind == "line" else entity.points
        if entity.kind == "line" and len(points) >= 2:
            start, end = self._point(transform, points[0]), self._point(transform, points[-1])
            self.canv.line(start[0], start[1], end[0], end[1])
        elif entity.kind in {"polyline", "spline", "dimension"} and points:
            path = self.canv.beginPath(); path.moveTo(*self._point(transform, points[0]))
            for point in points[1:]: path.lineTo(*self._point(transform, point))
            if entity.kind == "polyline" and entity.closed: path.close()
            self.canv.drawPath(path, stroke=1, fill=0)
        elif entity.kind == "circle" and points and entity.radius is not None:
            center = self._point(transform, points[0]); self.canv.circle(*center, transform.length(entity.radius), stroke=1, fill=0)
        elif entity.kind == "arc" and points and entity.radius is not None and entity.start_angle is not None and entity.end_angle is not None:
            center = self._point(transform, points[0]); radius = transform.length(entity.radius)
            self.canv.arc(center[0]-radius, center[1]-radius, center[0]+radius, center[1]+radius, startAng=entity.start_angle, extent=(entity.end_angle-entity.start_angle)%360)
        elif entity.kind == "ellipse" and points:
            major = entity.properties.get("major_axis", [0.0, 0.0])
            if len(major) >= 2:
                rx = transform.length(math.hypot(float(major[0]), float(major[1]))); ry = rx * abs(float(entity.properties.get("ratio", 1.0)))
                center = self._point(transform, points[0]); angle = math.degrees(math.atan2(float(major[1]), float(major[0])))
                self.canv.saveState(); self.canv.translate(*center); self.canv.rotate(angle)
                self.canv.ellipse(-rx, -ry, rx, ry, stroke=1, fill=0); self.canv.restoreState()
        elif entity.kind == "text" and points:
            self.canv.setFont(FONT_NAME, 5.5); self.canv.drawString(*self._point(transform, points[0]), _display_text(entity.text or ""))

    def _region(self, issue: ReviewedIssue, transform: CoordinateTransform, role: str) -> None:
        if not issue.region: return
        min_x, min_y, max_x, max_y = issue.region
        first, second = self._point(transform, (min_x, min_y)), self._point(transform, (max_x, max_y))
        natural_width, natural_height = abs(second[0]-first[0]), abs(second[1]-first[1])
        width, height = max(natural_width, 6), max(natural_height, 6)
        x = min(first[0], second[0]) - (width-natural_width)/2; y = min(first[1], second[1]) - (height-natural_height)/2
        self._style(role); self.canv.rect(x, y, width, height, stroke=1, fill=0)
        self.canv.setFont(FONT_BOLD, 5.5); self.canv.drawString(x+1.5, y+height+1.5, _display_text(issue.issue_id))

    def draw(self) -> None:
        _register_fonts(); self.canv.saveState()
        self.canv.setFillColor(colors.white); self.canv.setStrokeColor(colors.HexColor("#cbd5d1")); self.canv.roundRect(0, 0, self.width, self.height, 5, stroke=1, fill=1)
        transform = CoordinateTransform(self.reviewed.extents, self.width, self.height, 12)
        for entity in self.reviewed.reference_entities: self._entity(entity, "reference", transform)
        for entity in self.reviewed.student_entities: self._entity(entity, "student", transform)
        for issue in self.reviewed.issues:
            if issue.visual_role == "missing" and issue.expected_geometry: self._entity(issue.expected_geometry, "missing", transform)
            elif issue.visual_role == "extra" and issue.actual_geometry: self._entity(issue.actual_geometry, "extra", transform)
            elif issue.visual_role == "inaccurate":
                if issue.expected_geometry: self._entity(issue.expected_geometry, "inaccurate-expected", transform)
                if issue.actual_geometry: self._entity(issue.actual_geometry, "inaccurate-actual", transform)
            elif issue.visual_role in {"connectivity", "warning", "critical"}: self._region(issue, transform, issue.visual_role)
        if transform.empty and not self.reviewed.reference_entities and not self.reviewed.student_entities:
            self.canv.setFillColor(colors.HexColor("#718096")); self.canv.setFont(FONT_NAME, 9); self.canv.drawCentredString(self.width/2, self.height/2, "No drawable geometry")
        self.canv.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts(); sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("DLTitle", parent=sample["Title"], fontName=FONT_BOLD, fontSize=21, leading=25, textColor=colors.HexColor("#125c3e"), spaceAfter=2),
        "subtitle": ParagraphStyle("DLSubtitle", parent=sample["Normal"], fontName=FONT_NAME, fontSize=10, leading=13, textColor=colors.HexColor("#51615a"), spaceAfter=8),
        "h1": ParagraphStyle("DLH1", parent=sample["Heading1"], fontName=FONT_BOLD, fontSize=13, leading=16, spaceBefore=8, spaceAfter=5),
        "h2": ParagraphStyle("DLH2", parent=sample["Heading2"], fontName=FONT_BOLD, fontSize=10, leading=13, textColor=colors.HexColor("#125c3e"), spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("DLBody", parent=sample["BodyText"], fontName=FONT_NAME, fontSize=7.5, leading=10, textColor=colors.HexColor("#24313a")),
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


def _metadata_table(snapshot: ReviewSnapshot, styles: dict[str, ParagraphStyle], width: float) -> Table:
    metadata = snapshot.student_metadata
    response = snapshot.review_response
    rubric_template = response.get("rubric_template_name") or "DraftLens Baseline Rubric"
    rubric_source = str(response.get("rubric_source") or "baseline_template").replace("_", " ")
    return _four_column_table([
        ("Student name", metadata.student_name or "Not provided", "Student ID", metadata.student_id or "Not provided"),
        ("Course / section", metadata.course_section or "Not provided", "Report timestamp", snapshot.report_timestamp),
        ("Student DXF", _basename(snapshot.student_filename), "Reference DXF", _basename(snapshot.reference_filename)),
        ("Assignment title", snapshot.assignment_title or "Assignment", "Rubric template", rubric_template),
        ("Assignment type", snapshot.assignment_type or "Not confirmed", "Report ID", snapshot.review_id[:12]),
        ("Detected structure", ", ".join(snapshot.detected_features) or "No repeated structural features detected", "Rubric source", rubric_source),
    ], styles, width)


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
) -> list[Flowable]:
    expected, actual, deviation = _measurement(issue); guidance = issue.get("correction_guidance") or {}
    title = str(issue.get("category") or "finding").replace("_"," ").title()
    rows = [("Severity",issue.get("severity"),"Finding role",issue.get("finding_role")),
            ("Expected entity",issue.get("expected_entity_id"),"Student entity",issue.get("source_entity_id")),
            ("Expected measurement",_number(expected),"Actual measurement",_number(actual)),
            ("Deviation",_number(deviation),"Rubric rule",issue.get("rubric_rule_id") or "None"),
            ("Score category",issue.get("score_category") or "Not scored","Raw deduction",_number(issue.get("raw_rule_deduction",0))),
            ("Applied deduction",_number(issue.get("final_applied_contribution",0)),"Caps",f"rule {_number(issue.get('deduction_after_rule_cap',0))} / category {_number(issue.get('deduction_after_category_cap',0))}; {issue.get('cap_reason') or issue.get('deduction_status')}")]
    output: list[Flowable] = [CondPageBreak(55), _p(f"{issue.get('issue_id','Issue')} - {title}", styles["h2"]), _four_column_table(rows, styles, width), Spacer(1,3), _p(issue.get("technical_feedback") or "Review this finding.", styles["body"])]
    if compact:
        output = [CondPageBreak(55), _p(f"{issue.get('issue_id','Issue')} - {title}", styles["h2"]),
                  _p(f"{issue.get('severity')} | Expected {issue.get('expected_entity_id') or '-'} / student {issue.get('source_entity_id') or '-'} | Applied {_number(issue.get('final_applied_contribution', 0))} | {issue.get('deduction_status') or 'not scored'}", styles["small"]),
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
            _p("Supporting issue", styles["small"]),
            _p("Category", styles["small"]),
            _p("Technical feedback", styles["small"]),
        ]]
        for sup in linked_supporting:
            sup_title = str(sup.get("category") or "topology").replace("_", " ").title()
            sup_rows.append([
                _p(sup.get("issue_id", "Issue"), styles["body"]),
                _p(sup_title, styles["body"]),
                _p(sup.get("technical_feedback") or "Supporting topology evidence", styles["body"]),
            ])
        sup_table = Table(sup_rows, colWidths=[width * .25, width * .25, width * .5],
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
) -> list[Flowable]:
    presentation = response.get("finding_presentation") or {}
    if not presentation.get("compacted"):
        return []
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
        "All primary findings, including capped findings, are retained below."
    )
    return [_p("Compact finding summary", styles["h1"]), _p(totals, styles["body"]), table, Spacer(1, 5)]



def generate_pdf(snapshot: ReviewSnapshot, *, include_appendix: bool = False) -> bytes:
    """Generate a deterministic authoritative report without invoking grading."""
    styles, output = _styles(), BytesIO()
    document = SimpleDocTemplate(output,pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,topMargin=15*mm,bottomMargin=16*mm,title="DraftLens EDU Drawing Assessment Report",author="DraftLens EDU",subject=f"Authoritative review {snapshot.review_id}")
    # SimpleDocTemplate's frame has 6pt padding on each side, inside the margins.
    width = A4[0]-document.leftMargin-document.rightMargin - 12; response = snapshot.review_response; counts = response.get("finding_counts") or {}; score = response.get("score",0)
    presentation = compact_finding_presentation(
        list(response.get("issues") or []), response.get("unsupported_entities")
    )
    unsupported_summary = presentation.get("unsupported_summary") or {}
    unsupported_count = counts.get("unsupported_entities", 0)

    # --- PAGE 1: Assessment Summary ---
    story: list[Flowable] = [_p("DraftLens EDU",styles["title"]),_p("Drawing Assessment Report",styles["subtitle"]),_metadata_table(snapshot,styles,width),Spacer(1,4)]
    if response.get("instructor_override") is True:
        status = str(response.get("compatibility_status") or "suspicious").replace("_", " ")
        story.extend([
            _p("Instructor compatibility override", styles["h1"]),
            _p(
                f"Compatibility was classified as {status}. The instructor explicitly selected Grade anyway; the numerical result below records that override.",
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
    score_table = Table([[_p(f"{_number(score)} / 100",styles["score"]),_p("Primary issues",styles["small"]),_p("Supporting",styles["small"]),_p("Reference notes",styles["small"]),_p("Unsupported",styles["small"])],
                         ["",_p(counts.get("primary_student_issues",0),styles["body"]),_p(counts.get("supporting_findings",0),styles["body"]),_p(counts.get("reference_validation_notes",0),styles["body"]),_p(unsupported_count,styles["body"])]],colWidths=[width*.36,width*.16,width*.16,width*.16,width*.16])
    score_table.setStyle(TableStyle([("SPAN",(0,0),(0,1)),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ALIGN",(0,0),(-1,-1),"CENTER"),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#e8f4ed")),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#cbd5d1")),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
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
    placement = "Placement policy: " + ("Translation-tolerant placement" if response.get("normalization_mode")=="translation" else "Strict placement") + f". Completion policy: {response.get('completion_scoring_mode','rule_based').replace('_',' ')}."
    story.extend([
        breakdown,
        _p("Placement and transform decision", styles["h1"]),
        _p(placement, styles["body"]),
        _p(_normalization_summary(snapshot), styles["small"]),
        PageBreak(),
    ])

    # --- PAGE 2: Dedicated Drawing Page ---
    story.extend([
        _p("Reviewed drawing", styles["h1"]),
        ReviewedDrawingFlowable(snapshot.reviewed_drawing, width, 480),
        Spacer(1, 4),
        *_overlay_legend(styles, width),
        PageBreak(),
    ])

    # --- PAGES 3+: Primary Feedback Pages ---
    story.extend([
        _p("Finding details", styles["title"]),
        _p("Primary actionable findings and correction guidance. Supporting evidence is linked under primary findings.", styles["subtitle"]),
    ])
    story.extend(_finding_summary_story(response, styles, width))

    all_issues = list(response.get("issues") or [])
    issue_by_id = {issue["issue_id"]: issue for issue in all_issues}

    displayed_ids = set(presentation["default_issue_ids"])
    issues = [issue for issue in all_issues if issue.get("issue_id") in displayed_ids]

    primary_issues = [issue for issue in issues if issue.get("finding_role") == "primary"]
    representative_ids = set(presentation["displayed_issue_ids"])
    summarized_primary = [issue for issue in primary_issues if issue["issue_id"] not in representative_ids]
    primary_issues = [issue for issue in primary_issues if issue["issue_id"] in representative_ids]
    linked_map = presentation.get("linked_supporting_by_primary") or {}

    story.append(_p("Primary issue details", styles["h1"]))
    if not primary_issues:
        story.append(_p("No student issues detected.", styles["body"]))
    else:
        for issue in primary_issues:
            linked_ids = linked_map.get(issue["issue_id"]) or []
            linked_supporting = [issue_by_id[lid] for lid in linked_ids if lid in issue_by_id]
            detail = _issue_story(issue, styles, width, linked_supporting=linked_supporting,
                                  compact=presentation["compacted"])
            if linked_supporting:
                # A multi-page evidence table must not push the heading to an empty page.
                story.extend(detail)
            else:
                story.append(KeepTogether(detail))

    if summarized_primary:
        story.append(_p("Additional actionable findings", styles["h1"]))
        story.append(_p("These findings still require review and correction. A zero applied deduction, including a cap, does not mean the issue is resolved. Full evidence is available by issue ID in the viewer or technical appendix.", styles["body"]))
        rows = [[_p(label, styles["small"]) for label in ("Issue ID", "Expected / student entity", "Correction", "Applied / status")]]
        for issue in summarized_primary:
            guidance = issue.get("correction_guidance") or {}
            rows.append([
                _p(issue["issue_id"], styles["small"]),
                _p(f"{issue.get('expected_entity_id') or '-'} / {issue.get('source_entity_id') or '-'}", styles["small"]),
                _p(f"{issue.get('severity', '')} {str(issue.get('category') or 'finding').replace('_', ' ')}: {guidance.get('primary_command') or 'See representative correction guidance'}", styles["small"]),
                _p(f"{_number(issue.get('final_applied_contribution', 0))} / {issue.get('deduction_status') or 'not scored'}", styles["small"]),
            ])
        additional = Table(rows, colWidths=[width * .12, width * .26, width * .44, width * .18], repeatRows=1, splitInRow=1)
        additional.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cbd5d1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f0")),
        ]))
        story.append(additional)

    # Essential supporting evidence stays visible even without the appendix.
    unlinked_supporting = [issue for issue in issues if issue.get("finding_role") == "supporting"]
    if unlinked_supporting:
        story.append(_p("Essential supporting findings", styles["h1"]))
        for issue in unlinked_supporting:
            story.append(KeepTogether(_issue_story(issue, styles, width)))

    # Reference notes
    ref_notes = [issue for issue in issues if issue.get("finding_role") == "reference"]
    if ref_notes:
        story.append(_p("Reference notes", styles["h1"]))
        for issue in ref_notes:
            story.append(KeepTogether(_issue_story(issue, styles, width)))

    # Actionable unsupported findings (score-affecting or critical)
    actionable_unsupported = [
        issue for issue in issues
        if issue.get("finding_role") == "unsupported" and essential_finding(issue)
    ]
    if actionable_unsupported:
        story.append(_p("Actionable unsupported findings", styles["h1"]))
        for issue in actionable_unsupported:
            story.append(KeepTogether(_issue_story(issue, styles, width)))

    informational = [issue for issue in issues if issue.get("finding_role") == "informational"]
    if informational:
        story.append(_p("Informational findings", styles["h1"]))
        for issue in informational:
            story.append(KeepTogether(_issue_story(issue, styles, width)))

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
                story.append(KeepTogether(_issue_story(issue, styles, width)))
        if all_supporting:
            story.append(_p("All supporting topology findings", styles["h1"]))
            for issue in all_supporting:
                story.append(KeepTogether(_issue_story(issue, styles, width)))

        unsupported_findings = [issue for issue in all_issues if issue.get("finding_role") == "unsupported"]
        if unsupported_findings:
            story.append(_p("Unsupported findings", styles["h1"]))
            for issue in unsupported_findings:
                story.append(KeepTogether(_issue_story(issue, styles, width)))

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
        pdf.saveState(); pdf.setStrokeColor(colors.HexColor("#d8e0dc")); pdf.line(document.leftMargin,11*mm,A4[0]-document.rightMargin,11*mm)
        pdf.setFillColor(colors.HexColor("#51615a")); pdf.setFont(FONT_NAME,7); pdf.drawString(document.leftMargin,7.5*mm,f"DraftLens EDU - Report {snapshot.review_id[:12]}"); pdf.drawRightString(A4[0]-document.rightMargin,7.5*mm,f"Page {doc.page}"); pdf.restoreState()
    document.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=_InvariantCanvas); return output.getvalue()
