import io
import math
import xml.etree.ElementTree as ET
import ezdxf
from fastapi.testclient import TestClient
import pytest
from reportlab.pdfgen import canvas

from app.dxf import parse_dxf_bytes
from app.main import app
from app.models import Drawing, Entity
from app.pdf_report import ReviewedDrawingFlowable
from app.reviewed_dxf import build_reviewed_drawing, sample_ellipse_arc, _entity_bounds
from app.svg_renderer import CoordinateTransform, render_svg


client = TestClient(app)


def _make_synthetic_dxf(build_fn) -> bytes:
    """Create synthetic DXF bytes in memory without saving to disk."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    build_fn(msp)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def _extract_paths_and_ellipses(svg: str):
    """Parse SVG and extract path d attributes and ellipse elements."""
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    ellipses = root.findall(".//svg:ellipse", ns)
    paths = root.findall(".//svg:path", ns)
    return root, ellipses, paths


def test_sample_ellipse_arc_distinguishes_full_and_partial():
    """Verify that sample_ellipse_arc returns None for complete ellipses and sampled points for partial."""
    center = (0.0, 0.0)
    major = (10.0, 0.0)
    ratio = 0.5

    # Missing parameters -> full ellipse
    assert sample_ellipse_arc(center, major, ratio, None, None) is None
    assert sample_ellipse_arc(center, major, ratio, 0.0, None) is None
    assert sample_ellipse_arc(center, major, ratio, None, 2 * math.pi) is None

    # Full turn 0 to 2*pi -> full ellipse
    assert sample_ellipse_arc(center, major, ratio, 0.0, 2 * math.pi) is None
    assert sample_ellipse_arc(center, major, ratio, 0.0, 6.283185307179586) is None
    assert sample_ellipse_arc(center, major, ratio, 1.0, 1.0 + 2 * math.pi) is None

    # Partial intervals -> list of points
    quarter = sample_ellipse_arc(center, major, ratio, 0.0, math.pi / 2)
    assert quarter is not None
    assert len(quarter) >= 33
    # Exact start point: (10, 0)
    assert math.isclose(quarter[0][0], 10.0, abs_tol=1e-6)
    assert math.isclose(quarter[0][1], 0.0, abs_tol=1e-6)
    # Exact end point: (0, 5)
    assert math.isclose(quarter[-1][0], 0.0, abs_tol=1e-6)
    assert math.isclose(quarter[-1][1], 5.0, abs_tol=1e-6)


def test_complete_ellipse_remains_complete():
    """A complete ellipse must continue to render as an SVG <ellipse> element."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(100, 100), major_axis=(40, 0), ratio=0.6, start_param=0.0, end_param=2 * math.pi
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 1, "Complete ellipse must render as an SVG <ellipse>"
    ellipse_el = ellipses[0]
    assert ellipse_el.attrib.get("data-entity-id") == "R-00001"
    assert "cx" in ellipse_el.attrib
    assert "cy" in ellipse_el.attrib
    assert "rx" in ellipse_el.attrib
    assert "ry" in ellipse_el.attrib
    assert "transform" in ellipse_el.attrib

    # Ensure no partial path was generated for this complete ellipse
    partial_paths = [p for p in paths if p.attrib.get("data-entity-id") == "R-00001"]
    assert len(partial_paths) == 0


def test_unrotated_partial_ellipse_renders_only_selected_interval():
    """An unrotated partial ellipse renders only the requested interval with exact endpoints."""
    # First quadrant arc: center (50, 50), major (20, 0), ratio 0.5, start 0, end pi/2
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(50, 50), major_axis=(20, 0), ratio=0.5, start_param=0.0, end_param=math.pi / 2
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 0, "Partial ellipse must NOT render as an <ellipse>"
    entity_paths = [p for p in paths if p.attrib.get("data-entity-id") == "R-00001"]
    assert len(entity_paths) == 1

    d = entity_paths[0].attrib["d"]
    assert d.startswith("M "), "Path must start with M command"
    assert "Z" not in d.upper(), "Partial ellipse path must be open (no Z command)"
    assert entity_paths[0].attrib.get("fill") == "none", "Partial path must have fill=none"

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_start = transform.point((70.0, 50.0))  # center + major = (50+20, 50)
    expected_end = transform.point((50.0, 60.0))    # center + minor = (50, 50 + 20*0.5)

    commands = d.split()
    start_x, start_y = float(commands[1]), float(commands[2])
    end_x, end_y = float(commands[-2]), float(commands[-1])

    assert math.isclose(start_x, expected_start[0], abs_tol=1e-3)
    assert math.isclose(start_y, expected_start[1], abs_tol=1e-3)
    assert math.isclose(end_x, expected_end[0], abs_tol=1e-3)
    assert math.isclose(end_y, expected_end[1], abs_tol=1e-3)


def test_rotated_partial_ellipse_preserves_orientation_and_endpoints():
    """A rotated partial ellipse preserves orientation and exact endpoints."""
    # 3-4-5 triangle major axis: vector (12, 16), length = 20, angle = 53.13 deg
    # ratio 0.5 -> minor axis length = 10, minor vector = (-16*0.5, 12*0.5) = (-8, 6)
    # start 0, end pi (semi-ellipse)
    center = (100.0, 100.0)
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=center, major_axis=(12, 16), ratio=0.5, start_param=0.0, end_param=math.pi
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 0
    entity_paths = [p for p in paths if p.attrib.get("data-entity-id") == "R-00001"]
    assert len(entity_paths) == 1

    d = entity_paths[0].attrib["d"]
    assert "Z" not in d.upper()

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_start = transform.point((112.0, 116.0))
    expected_end = transform.point((88.0, 84.0))

    commands = d.split()
    start_x, start_y = float(commands[1]), float(commands[2])
    end_x, end_y = float(commands[-2]), float(commands[-1])

    assert math.isclose(start_x, expected_start[0], abs_tol=1e-3)
    assert math.isclose(start_y, expected_start[1], abs_tol=1e-3)
    assert math.isclose(end_x, expected_end[0], abs_tol=1e-3)
    assert math.isclose(end_y, expected_end[1], abs_tol=1e-3)


def test_parameter_interval_crossing_2pi_renders_correct_wrapped_arc():
    """A parameter interval that crosses 2pi renders the correct wrapped counterclockwise arc."""
    # From 270 deg (1.5*pi) to 90 deg (0.5*pi), crossing 0/2pi
    # Center (0, 0), major (20, 0), ratio 0.5
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(0, 0), major_axis=(20, 0), ratio=0.5, start_param=1.5 * math.pi, end_param=0.5 * math.pi
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    entity_paths = [p for p in paths if p.attrib.get("data-entity-id") == "R-00001"]
    assert len(entity_paths) == 1

    d = entity_paths[0].attrib["d"]
    assert "Z" not in d.upper()

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_start = transform.point((0.0, -10.0))
    expected_end = transform.point((0.0, 10.0))
    expected_mid = transform.point((20.0, 0.0))

    commands = d.split()
    start_x, start_y = float(commands[1]), float(commands[2])
    end_x, end_y = float(commands[-2]), float(commands[-1])

    assert math.isclose(start_x, expected_start[0], abs_tol=1e-3)
    assert math.isclose(start_y, expected_start[1], abs_tol=1e-3)
    assert math.isclose(end_x, expected_end[0], abs_tol=1e-3)
    assert math.isclose(end_y, expected_end[1], abs_tol=1e-3)

    pts = []
    for i in range(1, len(commands), 3):
        pts.append((float(commands[i]), float(commands[i + 1])))

    min_dist = min(math.hypot(px - expected_mid[0], py - expected_mid[1]) for px, py in pts)
    assert min_dist < 1.0, f"Wrapped arc must pass through midpoint (20, 0), min dist was {min_dist}"


def test_generated_partial_path_is_open_and_has_no_endpoint_chord():
    """Verify that the generated SVG path is strictly open with no closing chord."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(10, 10), major_axis=(10, 0), ratio=0.5, start_param=0.2, end_param=3.0
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    entity_path = [p for p in paths if p.attrib.get("data-entity-id") == "R-00001"][0]
    d = entity_path.attrib["d"]

    assert "Z" not in d and "z" not in d
    assert entity_path.attrib.get("fill") == "none"

    commands = d.split()
    first_pt = (float(commands[1]), float(commands[2]))
    last_pt = (float(commands[-2]), float(commands[-1]))
    dist = math.hypot(first_pt[0] - last_pt[0], first_pt[1] - last_pt[1])
    assert dist > 1.0, "Path endpoints must not be closed together"


def test_start_and_end_parameters_survive_parsing_and_serialization():
    """Start and end parameters survive DXF parsing, Entity to_dict, and ReviewedEntity properties."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(15, 25), major_axis=(8, 6), ratio=0.75, start_param=0.45, end_param=4.8
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    assert len(drawing.entities) == 1
    entity = drawing.entities[0]

    assert math.isclose(entity.properties["start_param"], 0.45)
    assert math.isclose(entity.properties["end_param"], 4.8)

    data = entity.to_dict()
    assert math.isclose(data["properties"]["start_param"], 0.45)
    assert math.isclose(data["properties"]["end_param"], 4.8)

    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    rev_entity = reviewed.reference_entities[0]
    assert math.isclose(rev_entity.properties["start_param"], 0.45)
    assert math.isclose(rev_entity.properties["end_param"], 4.8)


def test_missing_optional_values_retain_backward_compatibility():
    """Missing start/end param in synthetic entities gracefully defaults to full ellipse."""
    ent = Entity(
        id="R-TEST",
        kind="ellipse",
        layer="0",
        points=[(10.0, 20.0)],
        properties={"major_axis": [10.0, 0.0], "ratio": 0.5},
    )
    ref = Drawing(entities=[ent], bbox=(0.0, 10.0, 20.0, 30.0))
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(ref, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 1
    el = ellipses[0]
    assert el.attrib.get("data-entity-id") == "R-TEST"
    assert "rx" in el.attrib and "ry" in el.attrib

    bounds = _entity_bounds(ent)
    assert bounds == (0.0, 10.0, 20.0, 30.0)


def test_circle_circular_arc_and_full_ellipse_rendering_remain_unchanged():
    """Ensure circle, arc, and full ellipse rendering remain unchanged."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: (
        msp.add_circle(center=(10, 10), radius=5),
        msp.add_arc(center=(30, 10), radius=5, start_angle=0, end_angle=180),
        msp.add_ellipse(center=(50, 10), major_axis=(8, 0), ratio=0.5, start_param=0.0, end_param=2 * math.pi),
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    circles = root.findall(".//svg:circle", ns)
    paths = root.findall(".//svg:path", ns)
    ellipses = root.findall(".//svg:ellipse", ns)

    assert len(circles) == 1, "Circle must still render as <circle>"
    assert len(ellipses) == 1, "Full ellipse must still render as <ellipse>"
    arc_paths = [p for p in paths if "A " in p.attrib.get("d", "")]
    assert len(arc_paths) == 1, "Circular arc must still render as <path d='M...A...'>"


def test_visible_bounds_use_partial_curve():
    """Visible bounds (_entity_bounds) for partial ellipse cover only the partial curve."""
    partial_ent = Entity(
        id="R-PARTIAL",
        kind="ellipse",
        layer="0",
        points=[(100.0, 100.0)],
        properties={"major_axis": [50.0, 0.0], "ratio": 0.5, "start_param": 0.0, "end_param": math.pi},
    )
    bounds = _entity_bounds(partial_ent)
    assert bounds is not None
    min_x, min_y, max_x, max_y = bounds
    assert math.isclose(min_x, 50.0, abs_tol=1e-3)
    assert math.isclose(max_x, 150.0, abs_tol=1e-3)
    assert math.isclose(min_y, 100.0, abs_tol=1e-3), f"Partial bounds min_y should be ~100, got {min_y}"
    assert math.isclose(max_y, 125.0, abs_tol=1e-3), f"Partial bounds max_y should be ~125, got {max_y}"


def test_cylinder_like_geometry_issue_5():
    """Verify Issue #5 scenario: a cylinder with top full ellipse and bottom partial ellipse."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: (
        msp.add_line((10, 20), (10, 80)),
        msp.add_line((70, 20), (70, 80)),
        msp.add_ellipse(center=(40, 80), major_axis=(30, 0), ratio=0.4),  # top complete ellipse
        msp.add_ellipse(center=(40, 20), major_axis=(30, 0), ratio=0.4, start_param=math.pi, end_param=2 * math.pi),  # bottom front arc
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    # Top ellipse is complete -> <ellipse>
    top_ellipses = [el for el in ellipses if el.attrib.get("data-entity-id") == "R-00003"]
    assert len(top_ellipses) == 1

    # Bottom ellipse is partial -> open <path>
    bottom_paths = [p for p in paths if p.attrib.get("data-entity-id") == "R-00004"]
    assert len(bottom_paths) == 1
    d = bottom_paths[0].attrib["d"]
    assert "Z" not in d.upper(), "Bottom partial ellipse must not close across the cylinder"
    assert bottom_paths[0].attrib.get("fill") == "none"


def test_pdf_report_renders_partial_ellipse_as_open_vector_path():
    """Verify that ReportLab ReviewedDrawingFlowable draws partial ellipses as open paths without errors."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: (
        msp.add_ellipse(center=(50, 50), major_axis=(30, 10), ratio=0.6, start_param=0.3, end_param=3.5),
        msp.add_ellipse(center=(150, 50), major_axis=(30, 0), ratio=0.5),  # full ellipse
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})

    flowable = ReviewedDrawingFlowable(reviewed, 500, 250)
    out = io.BytesIO()
    canv = canvas.Canvas(out)
    flowable.canv = canv
    flowable.draw()
    canv.save()

    pdf_content = out.getvalue()
    assert pdf_content.startswith(b"%PDF-"), "Must generate valid PDF"
    assert len(pdf_content) > 1000


def test_api_review_full_workflow_with_partial_ellipse():
    """End-to-end API test: upload synthetic drawings with partial ellipses and verify report & viewer SVG."""
    ref_dxf = _make_synthetic_dxf(lambda msp: (
        msp.add_line((0, 0), (100, 0)),
        msp.add_ellipse(center=(50, 50), major_axis=(30, 0), ratio=0.5, start_param=0.0, end_param=math.pi),
    ))
    stu_dxf = _make_synthetic_dxf(lambda msp: (
        msp.add_line((0, 0), (100, 0)),
        msp.add_ellipse(center=(50, 50), major_axis=(30, 0), ratio=0.5, start_param=0.0, end_param=math.pi),
    ))

    response = client.post(
        "/api/review",
        data={"allow_fallback": "true"},
        files={
            "reference": ("ref.dxf", ref_dxf, "application/dxf"),
            "student": ("stu.dxf", stu_dxf, "application/dxf"),
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["score"] == 100
    svg = data["svg"]
    assert svg.startswith("<svg")

    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    # Both reference and student partial ellipses should render as open paths
    partial_paths = [p for p in paths if p.attrib.get("data-entity-id") in {"R-00002", "S-00002"}]
    assert len(partial_paths) == 2
    for p in partial_paths:
        assert "Z" not in p.attrib["d"].upper()
        assert p.attrib.get("fill") == "none"

    report_res = client.get(f"/api/reviews/{data['review_id']}/report.pdf")
    assert report_res.status_code == 200
    assert report_res.content.startswith(b"%PDF-")
