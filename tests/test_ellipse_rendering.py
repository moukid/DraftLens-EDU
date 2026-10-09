import io
import math
import xml.etree.ElementTree as ET
import ezdxf
from fastapi.testclient import TestClient
import pypdf
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


def _extract_pdf_paths(pdf_bytes: bytes):
    """Extract stroked/filled paths from a PDF's content stream using pypdf."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    page = reader.pages[0]
    cs = pypdf.generic.ContentStream(page.get_contents(), reader)
    paths = []
    curr = None
    for operands, operator in cs.operations:
        op = operator.decode("ascii") if isinstance(operator, bytes) else str(operator)
        if op == "m":
            curr = {
                "start": (float(operands[0]), float(operands[1])),
                "points": [(float(operands[0]), float(operands[1]))],
                "closed": False,
                "op": None,
            }
        elif op == "l" and curr is not None:
            curr["points"].append((float(operands[0]), float(operands[1])))
        elif op == "h" and curr is not None:
            curr["closed"] = True
        elif op in {"S", "s", "f", "F", "b", "B", "B*"} and curr is not None:
            curr["op"] = op
            if op in {"s", "b", "B", "B*"}:
                curr["closed"] = True
            paths.append(curr)
            curr = None
    return paths


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


def test_tiny_wrapped_arc_renders_as_open_path():
    """Verify that a tiny arc wrapping across the 0/2pi boundary renders as an open path, not a full ellipse."""
    center = (0.0, 0.0)
    major = (20.0, 0.0)
    ratio = 0.5
    sp = 2 * math.pi - 1e-6
    ep = 1e-6

    sampled = sample_ellipse_arc(center, major, ratio, sp, ep)
    assert sampled is not None, "Tiny wrapped arc must return sampled points, not None"
    assert len(sampled) >= 2
    # Verify start point is at sp and end point is at ep
    expected_start_x = center[0] + major[0] * math.cos(sp)
    expected_start_y = center[1] + major[0] * ratio * math.sin(sp)
    expected_end_x = center[0] + major[0] * math.cos(ep)
    expected_end_y = center[1] + major[0] * ratio * math.sin(ep)
    assert math.isclose(sampled[0][0], expected_start_x, abs_tol=1e-5)
    assert math.isclose(sampled[0][1], expected_start_y, abs_tol=1e-5)
    assert math.isclose(sampled[-1][0], expected_end_x, abs_tol=1e-5)
    assert math.isclose(sampled[-1][1], expected_end_y, abs_tol=1e-5)

    # In SVG, must render as <path> not <ellipse>
    ent = Entity(
        id="R-TINY",
        kind="ellipse",
        layer="0",
        points=[center],
        properties={"major_axis": major, "ratio": ratio, "start_param": sp, "end_param": ep},
    )
    ref = Drawing(entities=[ent], bbox=(-25, -15, 25, 15))
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(ref, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)
    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 0, "Tiny wrapped arc must not render as <ellipse>"
    assert len(paths) == 1, "Tiny wrapped arc must render as open <path>"
    assert "Z" not in paths[0].attrib["d"].upper()
    assert paths[0].attrib.get("fill") == "none"


def test_equal_endpoints_render_as_degenerate_point_arc():
    """Equal start and end parameters must be treated as a degenerate single-point arc, not a full ellipse."""
    center = (10.0, 20.0)
    major = (15.0, 0.0)
    ratio = 0.4

    # 0.0 to 0.0
    pts_zero = sample_ellipse_arc(center, major, ratio, 0.0, 0.0)
    assert pts_zero is not None, "0.0 to 0.0 must not be classified as a full ellipse"
    assert len(pts_zero) == 2
    assert pts_zero[0] == pts_zero[1]
    assert math.isclose(pts_zero[0][0], center[0] + major[0], abs_tol=1e-6)
    assert math.isclose(pts_zero[0][1], center[1], abs_tol=1e-6)

    # 1.5 to 1.5
    pts_arb = sample_ellipse_arc(center, major, ratio, 1.5, 1.5)
    assert pts_arb is not None
    assert len(pts_arb) == 2
    assert pts_arb[0] == pts_arb[1]

    # Distinct parameters (even with small delta 5e-8) must NOT collapse
    pts_distinct = sample_ellipse_arc(center, major, ratio, 1.0, 1.0 + 5e-8)
    assert pts_distinct is not None
    assert len(pts_distinct) >= 33
    assert pts_distinct[0] != pts_distinct[-1], "Distinct parameters must produce distinct endpoints"
    dist = math.hypot(pts_distinct[-1][0] - pts_distinct[0][0], pts_distinct[-1][1] - pts_distinct[0][1])
    assert dist > 0.0, "Endpoint distance must be positive for nonzero sweep"


def test_reversed_normal_inverts_minor_axis_and_sweep():
    """Reversed normal (extrusion (0, 0, -1)) inverts the minor axis vector so arcs curve to the correct side."""
    center = (0.0, 0.0)
    major = (20.0, 0.0)
    ratio = 0.5
    sp = 0.0
    ep = math.pi / 2

    # Standard positive normal (0, 0, 1)
    pts_pos = sample_ellipse_arc(center, major, ratio, sp, ep, extrusion=(0, 0, 1))
    assert pts_pos is not None
    # End point at pi/2 should be at (0, +10)
    assert math.isclose(pts_pos[-1][0], 0.0, abs_tol=1e-5)
    assert math.isclose(pts_pos[-1][1], 10.0, abs_tol=1e-5)

    # Reversed negative normal (0, 0, -1)
    pts_neg = sample_ellipse_arc(center, major, ratio, sp, ep, extrusion=(0, 0, -1))
    assert pts_neg is not None
    # End point at pi/2 should be at (0, -10)
    assert math.isclose(pts_neg[-1][0], 0.0, abs_tol=1e-5)
    assert math.isclose(pts_neg[-1][1], -10.0, abs_tol=1e-5)

    # Verify bounds calculation reflects the reversed normal
    ent_pos = Entity(
        id="R-POS",
        kind="ellipse",
        layer="0",
        points=[center],
        properties={"major_axis": major, "ratio": ratio, "start_param": sp, "end_param": ep, "extrusion": (0, 0, 1)},
    )
    ent_neg = Entity(
        id="R-NEG",
        kind="ellipse",
        layer="0",
        points=[center],
        properties={"major_axis": major, "ratio": ratio, "start_param": sp, "end_param": ep, "extrusion": (0, 0, -1)},
    )
    bounds_pos = _entity_bounds(ent_pos)
    bounds_neg = _entity_bounds(ent_neg)
    assert bounds_pos is not None and bounds_neg is not None
    # Positive normal: y ranges from 0 to 10
    assert bounds_pos[1] >= -1e-5 and bounds_pos[3] >= 9.9
    # Negative normal: y ranges from -10 to 0
    assert bounds_neg[1] <= -9.9 and bounds_neg[3] <= 1e-5


def test_rotated_major_axis_with_negative_normal():
    """Rotated major axis correctly reflects minor axis direction when normal is reversed."""
    center = (0.0, 0.0)
    major = (0.0, 20.0)
    ratio = 0.5
    sp = 0.0
    ep = math.pi / 2

    pts_pos = sample_ellipse_arc(center, major, ratio, sp, ep, extrusion=(0, 0, 1))
    pts_neg = sample_ellipse_arc(center, major, ratio, sp, ep, extrusion=(0, 0, -1))
    assert pts_pos is not None and pts_neg is not None

    # For positive normal, end point is at W = (-10, 0)
    assert math.isclose(pts_pos[-1][0], -10.0, abs_tol=1e-5)
    assert math.isclose(pts_pos[-1][1], 0.0, abs_tol=1e-5)

    # For negative normal, end point is at W = (10, 0)
    assert math.isclose(pts_neg[-1][0], 10.0, abs_tol=1e-5)
    assert math.isclose(pts_neg[-1][1], 0.0, abs_tol=1e-5)


def test_extrusion_survives_dxf_parsing_and_serialization():
    """Extrusion vector survives DXF parsing, Entity to_dict, and ReviewedEntity deserialization."""
    dxf_bytes = _make_synthetic_dxf(lambda msp: msp.add_ellipse(
        center=(10, 20),
        major_axis=(15, 0),
        ratio=0.5,
        start_param=0.0,
        end_param=math.pi,
        dxfattribs={"extrusion": (0.0, 0.0, -1.0)},
    ))
    drawing = parse_dxf_bytes(dxf_bytes, source="reference")
    assert len(drawing.entities) == 1
    ent = drawing.entities[0]
    assert ent.properties.get("extrusion") == (0.0, 0.0, -1.0)

    # Entity to_dict preserves extrusion
    d = ent.to_dict()
    assert d["properties"]["extrusion"] == (0.0, 0.0, -1.0)

    # ReviewedEntity deserializes extrusion correctly
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(drawing, empty, {"score": 100, "issues": []})
    rev_ent = reviewed.reference_entities[0]
    assert rev_ent.properties.get("extrusion") == [0.0, 0.0, -1.0]

    # SVG rendering uses the negative normal to produce correct open path
    svg = render_svg(reviewed)
    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 0
    assert len(paths) == 1
    assert "Z" not in paths[0].attrib["d"].upper()


def test_short_nonzero_arcs_preserve_geometry_across_scales():
    """Verify that short nonzero arcs are never collapsed into points across various scales and sweeps."""
    # 1. Exact four-unit reproduction from QA report
    center = (0.0, 0.0)
    major_1e8 = (100000000.0, 0.0)
    ratio = 0.5
    sp = 2 * math.pi - 4e-8
    ep = 4e-8

    pts = sample_ellipse_arc(center, major_1e8, ratio, sp, ep)
    assert pts is not None, "Four-unit short arc must return sampled points, not None"
    assert len(pts) >= 33

    # Analytical expected coordinates:
    # At t = 2*pi - 4e-8: x = 1e8 * cos(-4e-8) ~ 1e8, y = 5e7 * sin(-4e-8) ~ -2.0
    # At t = 4e-8: x = 1e8 * cos(4e-8) ~ 1e8, y = 5e7 * sin(4e-8) ~ +2.0
    exp_start = (1e8 * math.cos(sp), 5e7 * math.sin(sp))
    exp_end = (1e8 * math.cos(ep), 5e7 * math.sin(ep))
    assert math.isclose(pts[0][0], exp_start[0], rel_tol=1e-7)
    assert math.isclose(pts[0][1], exp_start[1], abs_tol=1e-5)
    assert math.isclose(pts[-1][0], exp_end[0], rel_tol=1e-7)
    assert math.isclose(pts[-1][1], exp_end[1], abs_tol=1e-5)
    endpoint_dist = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    assert math.isclose(endpoint_dist, 4.0, abs_tol=1e-5), f"Endpoint distance must be ~4.0, got {endpoint_dist}"

    # Verify bounds cover the surviving 4-unit geometry
    ent_1e8 = Entity(
        id="R-1E8",
        kind="ellipse",
        layer="0",
        points=[center],
        properties={"major_axis": major_1e8, "ratio": ratio, "start_param": sp, "end_param": ep},
    )
    bounds = _entity_bounds(ent_1e8)
    assert bounds is not None
    assert math.isclose(bounds[1], -2.0, abs_tol=1e-5)
    assert math.isclose(bounds[3], 2.0, abs_tol=1e-5)

    # In SVG: open path with distinct endpoints, fill=none, no Z
    ref_dwg = Drawing(entities=[ent_1e8], bbox=(1e8 - 10, -5, 1e8 + 10, 5))
    empty = Drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(ref_dwg, empty, {"score": 100, "issues": []})
    svg = render_svg(reviewed)
    root, ellipses, paths = _extract_paths_and_ellipses(svg)
    assert len(ellipses) == 0, "Short arc must not be rendered as a full ellipse"
    assert len(paths) == 1
    assert "Z" not in paths[0].attrib["d"].upper()
    assert paths[0].attrib.get("fill") == "none"

    # 2. Small nonwrapped interval with distinct parameters
    pts_nonwrap = sample_ellipse_arc((0.0, 0.0), (50.0, 0.0), 0.5, 0.5, 0.5 + 1e-7)
    assert pts_nonwrap is not None
    assert len(pts_nonwrap) >= 33
    assert pts_nonwrap[0] != pts_nonwrap[-1]

    # 3. Small wrapped intervals on both sides of previous 1e-7 cutoff
    pts_below = sample_ellipse_arc((0.0, 0.0), (20.0, 0.0), 0.5, 2 * math.pi - 4e-8, 4e-8)
    pts_above = sample_ellipse_arc((0.0, 0.0), (20.0, 0.0), 0.5, 2 * math.pi - 1e-7, 1e-7)
    assert pts_below is not None and pts_above is not None
    assert pts_below[0] != pts_below[-1]
    assert pts_above[0] != pts_above[-1]

    # 4. Scale invariance: different major-axis magnitudes
    for scale in [10.0, 1000.0, 100000000.0]:
        pts_scale = sample_ellipse_arc((0.0, 0.0), (scale, 0.0), 0.5, 2 * math.pi - 4e-8, 4e-8)
        assert pts_scale is not None
        d = math.hypot(pts_scale[-1][0] - pts_scale[0][0], pts_scale[-1][1] - pts_scale[0][1])
        expected_d = 2 * (scale * 0.5) * math.sin(4e-8)
        assert math.isclose(d, expected_d, rel_tol=1e-5), f"Distance {d} failed scale check for scale {scale}"

    # 5. Full vs near-full interval distinction
    assert sample_ellipse_arc((0.0, 0.0), (10.0, 0.0), 0.5, 0.0, 2 * math.pi) is None
    assert sample_ellipse_arc((0.0, 0.0), (10.0, 0.0), 0.5, 1.0, 1.0 + 2 * math.pi) is None
    near_full_1 = sample_ellipse_arc((0.0, 0.0), (10.0, 0.0), 0.5, 0.0, 2 * math.pi - 1e-6)
    near_full_2 = sample_ellipse_arc((0.0, 0.0), (10.0, 0.0), 0.5, 0.0, 2 * math.pi - 1e-8)
    assert near_full_1 is not None, "Near-full arc (gap 1e-6) must remain open"
    assert near_full_2 is not None, "Near-full arc (gap 1e-8) must remain open"
    assert near_full_1[0] != near_full_1[-1]
    assert near_full_2[0] != near_full_2[-1]


def test_pdf_report_handles_negative_extrusion_and_tiny_arcs():
    """ReportLab flowable renders reversed-normal and tiny-wrapped ellipses without error and with exact geometry."""
    # Smoke check with synthetic DXF
    dxf_bytes = _make_synthetic_dxf(lambda msp: (
        msp.add_ellipse(center=(50, 50), major_axis=(20, 0), ratio=0.5, start_param=0.0, end_param=math.pi / 2, dxfattribs={"extrusion": (0, 0, -1)}),
        msp.add_ellipse(center=(150, 50), major_axis=(20, 0), ratio=0.5, start_param=2 * math.pi - 1e-6, end_param=1e-6),
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
    assert pdf_content.startswith(b"%PDF-")
    assert len(pdf_content) > 1000

    # Detailed PDF content-stream path operator and coordinate verification:
    # A. Original wrapped arc: major=(20,0), ratio=0.5, start=2*pi-1e-6, end=1e-6
    # B. Four-unit short arc: major=(1e8,0), ratio=0.5, start=2*pi-4e-8, end=4e-8
    # C. Reversed-normal quarter ellipse: center=(0,0), major=(20,0), ratio=0.5, extrusion=(0,0,-1), start=0, end=pi/2
    # D. Rotated major axis with negative-Z normal: center=(0,0), major=(0,20), ratio=0.5, extrusion=(0,0,-1), start=0, end=pi/2
    test_cases = [
        ("Case A (wrapped arc)", (0.0, 0.0), (20.0, 0.0), 0.5, 2 * math.pi - 1e-6, 1e-6, (0.0, 0.0, 1.0), (-25.0, -15.0, 25.0, 15.0)),
        ("Case B (four-unit short arc)", (0.0, 0.0), (100000000.0, 0.0), 0.5, 2 * math.pi - 4e-8, 4e-8, (0.0, 0.0, 1.0), (100000000.0 - 10.0, -5.0, 100000000.0 + 10.0, 5.0)),
        ("Case C (reversed-normal quarter ellipse)", (0.0, 0.0), (20.0, 0.0), 0.5, 0.0, math.pi / 2, (0.0, 0.0, -1.0), (-25.0, -25.0, 25.0, 25.0)),
        ("Case D (rotated reversed-normal ellipse)", (0.0, 0.0), (0.0, 20.0), 0.5, 0.0, math.pi / 2, (0.0, 0.0, -1.0), (-25.0, -25.0, 25.0, 25.0)),
    ]

    for label, center, major, ratio, sp, ep, ext, bbox in test_cases:
        ent = Entity(
            id="R-TEST",
            kind="ellipse",
            layer="0",
            points=[center],
            properties={"major_axis": major, "ratio": ratio, "start_param": sp, "end_param": ep, "extrusion": ext},
        )
        dwg = Drawing(entities=[ent], bbox=bbox)
        rev = build_reviewed_drawing(dwg, Drawing([], (0, 0, 0, 0)), {"score": 100, "issues": []})
        flow = ReviewedDrawingFlowable(rev, 500, 250)
        transform = CoordinateTransform(rev.extents, 500, 250, 12)
        pdf_out = io.BytesIO()
        c = canvas.Canvas(pdf_out)
        flow.canv = c
        flow.draw()
        c.save()

        pdf_paths = [p for p in _extract_pdf_paths(pdf_out.getvalue()) if p["op"] == "S"]
        assert len(pdf_paths) == 1, f"{label}: expected exactly 1 stroked path in PDF"
        p = pdf_paths[0]
        assert not p["closed"], f"{label}: PDF path must be open (no closepath operator)"
        assert len(p["points"]) >= 33, f"{label}: expected >= 33 sampled points in PDF path"

        # Calculate independent analytical world endpoints
        nz = ext[2] if ext else 1.0
        sign = -1.0 if nz < 0 else 1.0
        w = (sign * (-major[1] * ratio), sign * (major[0] * ratio))
        world_start = (center[0] + major[0] * math.cos(sp) + w[0] * math.sin(sp), center[1] + major[1] * math.cos(sp) + w[1] * math.sin(sp))
        world_end = (center[0] + major[0] * math.cos(ep) + w[0] * math.sin(ep), center[1] + major[1] * math.cos(ep) + w[1] * math.sin(ep))
        exp_start_pdf = flow._point(transform, world_start)
        exp_end_pdf = flow._point(transform, world_end)

        assert math.isclose(p["start"][0], exp_start_pdf[0], abs_tol=1e-3), f"{label}: start X mismatch"
        assert math.isclose(p["start"][1], exp_start_pdf[1], abs_tol=1e-3), f"{label}: start Y mismatch"
        assert math.isclose(p["points"][-1][0], exp_end_pdf[0], abs_tol=1e-3), f"{label}: end X mismatch"
        assert math.isclose(p["points"][-1][1], exp_end_pdf[1], abs_tol=1e-3), f"{label}: end Y mismatch"
        pdf_dist = math.hypot(p["points"][-1][0] - p["start"][0], p["points"][-1][1] - p["start"][1])
        assert pdf_dist > 0.0, f"{label}: PDF endpoints must be distinct"

        # Check midpoint to verify correct side/quadrant
        span = (ep - sp) % (2 * math.pi)
        if span < 0:
            span += 2 * math.pi
        mid_t = sp + span * 0.5
        world_mid = (center[0] + major[0] * math.cos(mid_t) + w[0] * math.sin(mid_t), center[1] + major[1] * math.cos(mid_t) + w[1] * math.sin(mid_t))
        exp_mid_pdf = flow._point(transform, world_mid)
        act_mid_pdf = p["points"][len(p["points"]) // 2]
        assert math.isclose(act_mid_pdf[0], exp_mid_pdf[0], abs_tol=1e-2), f"{label}: midpoint X mismatch"
        assert math.isclose(act_mid_pdf[1], exp_mid_pdf[1], abs_tol=1e-2), f"{label}: midpoint Y mismatch"

        # Corresponding SVG checks
        svg = render_svg(rev)
        root, svg_ellipses, svg_paths = _extract_paths_and_ellipses(svg)
        assert len(svg_ellipses) == 0, f"{label}: SVG must not render as full ellipse"
        assert len(svg_paths) == 1, f"{label}: SVG must render exactly 1 path"
        d = svg_paths[0].attrib["d"]
        assert "Z" not in d.upper(), f"{label}: SVG path must be open (no Z command)"
        assert svg_paths[0].attrib.get("fill") == "none", f"{label}: SVG path must have fill=none"


def test_full_turn_boundary_and_near_full_contract():
    """Verify exact representable boundary behavior using math.nextafter, confirming near-full arcs remain open."""
    tau = math.tau

    # A. Canonical full turn: start=0, end=math.tau -> full ellipse
    assert sample_ellipse_arc((0, 0), (10, 0), 0.5, 0.0, tau) is None

    # B. Shifted full turns: several starts, including 0.1, 1.0, 1.4, 10.0; end=start+tau -> full ellipse
    for sp in [0.1, 1.0, 1.4, 10.0]:
        assert sample_ellipse_arc((0, 0), (10, 0), 0.5, sp, sp + tau) is None, f"Shifted full turn failed for sp={sp}"

    # C. Immediately below the full-turn boundary: end=math.nextafter(start+tau, -math.inf) -> partial
    for sp in [0.0, 0.1, 1.0, 1.4, 10.0]:
        ep = math.nextafter(sp + tau, -math.inf)
        pts = sample_ellipse_arc((0, 0), (10, 0), 0.5, sp, ep)
        assert pts is not None, f"Immediately below boundary must be partial for sp={sp}"
        assert len(pts) >= 33, f"Immediately below boundary must have >= 33 points for sp={sp}"
        assert pts[0] != pts[-1], f"Immediately below boundary must never collapse to point for sp={sp}"

    # D. Supported immediately-above-boundary behavior: end=math.nextafter(start+tau, math.inf) -> full turn
    for sp in [0.0, 0.1, 1.0, 1.4]:
        ep = math.nextafter(sp + tau, math.inf)
        assert sample_ellipse_arc((0, 0), (10, 0), 0.5, sp, ep) is None, f"Above boundary must be full turn for sp={sp}"

    # E. Confirmed failing reproduction case: start=0, end=tau - 5e-11 -> partial
    pts_repro = sample_ellipse_arc((0, 0), (20, 0), 0.5, 0.0, tau - 5e-11)
    assert pts_repro is not None, "tau - 5e-11 must remain an open partial arc"
    assert len(pts_repro) >= 33
    assert pts_repro[0] != pts_repro[-1], "Endpoints must be distinct mathematically"
    assert math.isclose(pts_repro[0][0], 20.0, abs_tol=1e-6)
    assert math.isclose(pts_repro[0][1], 0.0, abs_tol=1e-6)
    assert math.isclose(pts_repro[-1][0], 20.0, abs_tol=1e-6)
    # y = 10 * sin(-5e-11) ~ -5e-10 != 0
    assert pts_repro[-1][1] < 0.0, "End y-coordinate must be on negative side immediately before 2*pi"

    # Verify real renderers for confirmed reproduction case (start=0, end=tau - 5e-11)
    ent_e = Entity(
        id="R-REPRO",
        kind="ellipse",
        layer="0",
        points=[(0, 0)],
        properties={"major_axis": (20, 0), "ratio": 0.5, "start_param": 0.0, "end_param": tau - 5e-11},
    )
    dwg_e = Drawing(entities=[ent_e], bbox=(-25, -15, 25, 15))
    rev_e = build_reviewed_drawing(dwg_e, Drawing([], (0, 0, 0, 0)), {"score": 100, "issues": []})

    # SVG renderer: must render open <path>, never <ellipse>
    svg_e = render_svg(rev_e)
    root_e = ET.fromstring(svg_e)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    assert len(root_e.findall(".//svg:ellipse", ns)) == 0, "Reproduction must not render as <ellipse>"
    paths_e = root_e.findall(".//svg:path", ns)
    assert len(paths_e) == 1, "Reproduction must render exactly 1 SVG path"
    assert "Z" not in paths_e[0].attrib["d"].upper(), "Reproduction SVG path must be open (no Z command)"
    assert paths_e[0].attrib.get("fill") == "none", "Reproduction SVG path must have fill=none"

    # PDF renderer: must execute partial path branch, never full ellipse branch
    flow_e = ReviewedDrawingFlowable(rev_e, 500, 250)
    out_e = io.BytesIO()
    canv_e = canvas.Canvas(out_e)
    flow_e.canv = canv_e
    flow_e.draw()
    canv_e.save()

    reader_e = pypdf.PdfReader(io.BytesIO(out_e.getvalue()))
    cs_e = pypdf.generic.ContentStream(reader_e.pages[0].get_contents(), reader_e)
    stroked_e = []
    curr = None
    for operands, operator in cs_e.operations:
        op = operator.decode("ascii") if isinstance(operator, bytes) else str(operator)
        if op == "m":
            curr = {"start": (float(operands[0]), float(operands[1])), "points": [(float(operands[0]), float(operands[1]))], "closed": False, "op": None}
        elif op == "l" and curr is not None:
            curr["points"].append((float(operands[0]), float(operands[1])))
        elif op == "h" and curr is not None:
            curr["closed"] = True
        elif op in {"S", "s", "f", "F", "b", "B", "B*"} and curr is not None:
            curr["op"] = op
            if op in {"s", "b", "B", "B*"}:
                curr["closed"] = True
            stroked_e.append(curr)
            curr = None
    pdf_paths_e = [p for p in stroked_e if p["op"] == "S"]
    assert len(pdf_paths_e) == 1, "Reproduction must render exactly 1 stroked vector path in PDF"
    assert not pdf_paths_e[0]["closed"], "Reproduction PDF path must be open"
    assert len(pdf_paths_e[0]["points"]) >= 33

    # F. Distinct rendered endpoints where scale/gap is representable in output
    ent_gap = Entity(
        id="R-GAP",
        kind="ellipse",
        layer="0",
        points=[(0, 0)],
        properties={"major_axis": (20, 0), "ratio": 0.5, "start_param": 0.0, "end_param": tau - 0.2},
    )
    dwg_gap = Drawing(entities=[ent_gap], bbox=(-25, -15, 25, 15))
    rev_gap = build_reviewed_drawing(dwg_gap, Drawing([], (0, 0, 0, 0)), {"score": 100, "issues": []})
    flow_gap = ReviewedDrawingFlowable(rev_gap, 500, 250)
    out_gap = io.BytesIO()
    canv_gap = canvas.Canvas(out_gap)
    flow_gap.canv = canv_gap
    flow_gap.draw()
    canv_gap.save()

    paths_gap = [p for p in _extract_pdf_paths(out_gap.getvalue()) if p["op"] == "S"]
    assert len(paths_gap) == 1
    pdf_gap_dist = math.hypot(paths_gap[0]["points"][-1][0] - paths_gap[0]["start"][0], paths_gap[0]["points"][-1][1] - paths_gap[0]["start"][1])
    assert pdf_gap_dist > 5.0, f"PDF rendered endpoints must be distinctly separated for gap=0.2 rad, got {pdf_gap_dist}"

    svg_gap = render_svg(rev_gap)
    root_gap = ET.fromstring(svg_gap)
    svg_gap_paths = root_gap.findall(".//svg:path", ns)
    assert len(svg_gap_paths) == 1
    d_gap = svg_gap_paths[0].attrib["d"]
    coords = [float(x) for x in d_gap.replace("M ", "").replace(" L ", " ").split()]
    svg_gap_dist = math.hypot(coords[-2] - coords[0], coords[-1] - coords[1])
    assert svg_gap_dist > 5.0, f"SVG rendered endpoints must be distinctly separated for gap=0.2 rad, got {svg_gap_dist}"
