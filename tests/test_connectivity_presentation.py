from app.compare import compare_drawings
from app.models import Drawing, Entity
from app.pdf_report import _LEGEND_ENTRIES, ReviewedDrawingFlowable
from app.reviewed_dxf import build_reviewed_drawing
from app.rubric import default_rubric
from app.svg_renderer import render_svg


def line(entity_id, start, end, *, source="reference", layer=None):
    points = [tuple(start), tuple(end)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer=layer or entity_id,
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2),
    )


def drawing(*entities, units="mm"):
    boxes = [entity.bbox for entity in entities]
    return Drawing(
        entities=list(entities),
        bbox=(
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
        units=units,
        units_code=4,
    )


def rubric(mode: str = "strict"):
    r = default_rubric().model_copy(update={"approved": True, "normalization_mode": mode})
    r.tolerances.position = 0.5
    return r


def test_endpoint_gap_produces_localized_markers_not_visible_bounding_rectangles():
    """Confirmed endpoint gap marks endpoints with circles and connector, hiding bounding box."""
    ref = drawing(
        line("R-1", (0, 0), (10, 0)),
        line("R-2", (10, 0), (10, 10)),
    )
    stu = drawing(
        line("S-1", (0, 0), (10, 0), source="student"),
        line("S-2", (10, 2), (10, 10), source="student"),
    )

    result = compare_drawings(ref, stu, rubric=rubric())
    gap_issues = [i for i in result["issues"] if i["category"] == "endpoint_gap"]
    assert len(gap_issues) == 1
    gap = gap_issues[0]

    # Verify measurement details
    meas = gap["measurement"]
    assert meas is not None
    assert meas["distance"] == 2.0
    assert len(meas["actual_points"]) == 2
    assert meas["expected_point"] == [10.0, 0.0]
    assert "Endpoint gap of 2.000 mm exceeds tolerance (0.500 mm)" in gap["technical_feedback"]
    assert "Connect endpoints at this junction as required by the reference." in gap["technical_feedback"]

    reviewed = build_reviewed_drawing(ref, stu, result)
    svg = render_svg(reviewed)

    # Localized markers: connector line and endpoint circles
    assert '<line class="connectivity-connector"' in svg
    assert '<circle class="connectivity-endpoint"' in svg

    # Bounding rectangle is marked technical-only (hidden from normal view)
    assert 'class="connectivity connectivity-region technical-only"' in svg
    # Normal view must not have naked visible connectivity bounding rectangles
    assert '<rect class="connectivity"' not in svg.replace('class="connectivity connectivity-region technical-only"', "")


def test_closed_connection_within_tolerance_is_not_flagged():
    """When student endpoints meet within tolerance, no gap is produced."""
    ref = drawing(
        line("R-1", (0, 0), (10, 0)),
        line("R-2", (10, 0), (10, 10)),
    )
    stu = drawing(
        line("S-1", (0, 0), (10, 0), source="student"),
        line("S-2", (10, 0.1), (10, 10), source="student"),  # 0.1 <= 0.5 tolerance
    )

    result = compare_drawings(ref, stu, rubric=rubric())
    gap_issues = [i for i in result["issues"] if i["category"] == "endpoint_gap"]
    assert len(gap_issues) == 0


def test_intentional_reference_opening_is_not_flagged_as_error():
    """Intentional openings in the reference are terminals and must not be flagged."""
    # Reference has a 5mm intentional opening between R-1 and R-2 (e.g. doorway or separate objects)
    ref = drawing(
        line("R-1", (0, 0), (10, 0)),
        line("R-2", (15, 0), (25, 0)),
    )
    # Student matches the intentional opening
    stu = drawing(
        line("S-1", (0, 0), (10, 0), source="student"),
        line("S-2", (15, 0), (25, 0), source="student"),
    )

    result = compare_drawings(ref, stu, rubric=rubric())
    gap_issues = [i for i in result["issues"] if i["category"] == "endpoint_gap"]
    assert len(gap_issues) == 0


def test_supporting_connectivity_finding_carries_no_additional_deduction():
    """Supporting connectivity findings carry applied_deduction == 0."""
    ref = drawing(
        line("R-1", (0, 0), (10, 0)),
        line("R-2", (10, 0), (10, 10)),
    )
    stu = drawing(
        line("S-1", (0, 0), (10, 0), source="student"),
        line("S-2", (10, 3), (10, 10), source="student"),
    )

    result = compare_drawings(ref, stu, rubric=rubric())
    supporting = [i for i in result["issues"] if i.get("classification") == "supporting_evidence"]
    assert len(supporting) >= 1
    for issue in supporting:
        assert issue["applied_deduction"] == 0.0
        assert issue["deduction_status"] in {"suppressed", "informational", "none"}


def test_legend_entries_and_explanation_contract():
    """Legend entry for connectivity uses Gaps & Connections and exact approved explanation."""
    conn_entry = next(entry for entry in _LEGEND_ENTRIES if entry[0] == "connectivity")
    role, label, explanation = conn_entry
    assert role == "connectivity"
    assert label == "Gaps & Connections"
    expected_exp = (
        "Highlights places where drawing elements do not connect as required by the reference, "
        "such as gaps between endpoints or broken junctions. Intentional openings are not errors. "
        "Supporting findings may carry no additional deduction."
    )
    assert explanation == expected_exp


def test_pdf_reviewed_drawing_renders_localized_connectivity():
    """PDF reviewed drawing flowable draws localized connector and endpoints rather than bounding box."""
    ref = drawing(
        line("R-1", (0, 0), (10, 0)),
        line("R-2", (10, 0), (10, 10)),
    )
    stu = drawing(
        line("S-1", (0, 0), (10, 0), source="student"),
        line("S-2", (10, 2), (10, 10), source="student"),
    )

    result = compare_drawings(ref, stu, rubric=rubric())
    reviewed = build_reviewed_drawing(ref, stu, result)

    class MockCanvas:
        def __init__(self):
            self.lines = []
            self.circles = []
            self.rects = []
            self.dashes = []

        def saveState(self):
            pass

        def restoreState(self):
            pass

        def setFillColor(self, _color):
            pass

        def setStrokeColor(self, _color):
            pass

        def setLineWidth(self, _w):
            pass

        def setDash(self, dash):
            self.dashes.append(list(dash))

        def roundRect(self, *_args, **_kwargs):
            pass

        def line(self, x1, y1, x2, y2):
            self.lines.append((x1, y1, x2, y2))

        def circle(self, x, y, r, **_kwargs):
            self.circles.append((x, y, r))

        def rect(self, x, y, w, h, **_kwargs):
            self.rects.append((x, y, w, h))

        def setFont(self, *_args):
            pass

        def drawString(self, *_args):
            pass

        def beginPath(self):
            pass

    mock_canv = MockCanvas()
    flowable = ReviewedDrawingFlowable(reviewed, 500, 300)
    flowable.canv = mock_canv
    flowable.draw()

    # The flowable must draw localized circles at the endpoints and dashed connector line
    assert len(mock_canv.circles) >= 2
    assert len(mock_canv.lines) >= 3  # student lines + gap connector
    # Bounding rectangle is NOT drawn on the drawing page
    assert len(mock_canv.rects) == 0
