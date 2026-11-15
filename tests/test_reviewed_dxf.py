from tests.synthetic_data import fixture_root, samples_root
from copy import deepcopy
from pathlib import Path
import math
import xml.etree.ElementTree as ET

from app.compare import compare_drawings
from app.dxf import parse_dxf_path
from app.models import Drawing, Entity
from app.reviewed_dxf import build_reviewed_drawing
from app.svg_renderer import CoordinateTransform, render_svg
from app.validator import validate_reference

SAMPLES = samples_root()


def entity(entity_id, kind, points, *, source="reference", layer="0", radius=None, closed=False, text=None, properties=None):
    return Entity(
        id=entity_id,
        kind=kind,
        layer=layer,
        points=list(points),
        source=source,
        radius=radius,
        closed=closed,
        text=text,
        properties=properties or {},
    )


def drawing(entities, bbox, *, units="mm", unsupported=None):
    return Drawing(list(entities), bbox, units=units, units_code=4, unsupported_entities=unsupported or [])


def issue(issue_id, category, *, reference_id=None, student_id=None, severity="major", feedback="Correct the geometry.", deduction=3, confidence="verified"):
    return {
        "id": issue_id,
        "error_id": issue_id,
        "category": category,
        "severity": severity,
        "reference_entity_id": reference_id,
        "student_entity_id": student_id,
        "location": [2, 2],
        "technical_feedback": feedback,
        "rubric_rule_id": "RULE-TEST",
        "deduction": deduction,
        "confidence": confidence,
        "measurement": {"property": "test", "expected": 1, "actual": 2},
    }


def review_with_all_overlay_roles():
    reference = drawing([
        entity("R-M", "line", [(0, 0), (10, 0)]),
        entity("R-I", "circle", [(20, 5)], radius=5),
    ], (0, 0, 25, 10))
    student = drawing([
        entity("S-I", "circle", [(22, 5)], source="student", radius=4),
        entity("S-X", "line", [(30, 0), (35, 0)], source="student"),
    ], (18, 0, 35, 9))
    comparison = {
        "score": 82,
        "issues": [
            issue("E-003", "incorrect_radius", reference_id="R-I", student_id="S-I"),
            issue("E-001", "missing_geometry", reference_id="R-M"),
            issue("E-002", "extra_geometry", student_id="S-X"),
        ],
    }
    return build_reviewed_drawing(reference, student, comparison)


def test_svg_is_valid_deterministic_and_repeated_execution_is_identical():
    reviewed = review_with_all_overlay_roles()
    first = render_svg(reviewed)
    second = render_svg(reviewed)
    assert first == second
    root = ET.fromstring(first)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 1200 800"


def test_review_model_preserves_missing_extra_and_inaccurate_provenance():
    reviewed = review_with_all_overlay_roles()
    assert [item.issue_id for item in reviewed.issues] == ["E-001", "E-002", "E-003"]
    by_id = {item.issue_id: item for item in reviewed.issues}
    assert by_id["E-001"].visual_role == "missing"
    assert by_id["E-001"].expected_geometry.entity_id == "R-M"
    assert by_id["E-001"].actual_geometry is None
    assert by_id["E-002"].visual_role == "extra"
    assert by_id["E-002"].source_entity_id == "S-X"
    assert by_id["E-002"].actual_geometry.entity_id == "S-X"
    assert by_id["E-003"].visual_role == "inaccurate"
    assert by_id["E-003"].expected_geometry.entity_id == "R-I"
    assert by_id["E-003"].actual_geometry.entity_id == "S-I"
    assert by_id["E-003"].rubric_rule_id == "RULE-TEST"
    assert by_id["E-003"].deduction == 3
    assert by_id["E-003"].confidence == "verified"



def test_connectivity_issue_uses_local_region_and_selectable_svg_id():
    reference = drawing(
        [entity("R-L", "line", [(10, 0), (10, 10)])], (10, 0, 10, 10)
    )
    student = drawing(
        [entity("S-L", "line", [(10, 5), (10, 10)], source="student")],
        (10, 5, 10, 10),
    )
    raw_issue = issue(
        "T-GAP-STABLE",
        "endpoint_gap",
        reference_id="R-L",
        student_id="S-L",
        deduction=0,
    )
    raw_issue["location"] = [10, 0]
    raw_issue["measurement"] = {
        "property": "endpoint_gap", "expected": 0, "actual": 5,
        "region": [10, 0, 10, 5],
    }
    reviewed = build_reviewed_drawing(reference, student, {"issues": [raw_issue]})
    topology_issue = reviewed.issues[0]
    svg = render_svg(reviewed)

    assert topology_issue.visual_role == "connectivity"
    assert topology_issue.region == (10, 0, 10, 5)
    assert 'data-issue-id="T-GAP-STABLE"' in svg
    assert 'data-role="connectivity"' in svg


def test_review_model_distinguishes_raw_applied_and_suppressed_deductions():
    reference = drawing([entity("R-M", "line", [(0, 0), (10, 0)])], (0, 0, 10, 0))
    raw_issue = issue("E-001", "missing_geometry", reference_id="R-M", deduction=5)
    raw_issue["applied_deduction"] = 0
    raw_issue["suppression_reason"] = "fixed missing deduction suppressed by proportional completion policy"
    raw_issue["classification"] = "primary"
    reviewed = build_reviewed_drawing(reference, drawing([], (0, 0, 0, 0)), {"score": 98.7, "issues": [raw_issue]})
    finding = reviewed.issues[0]
    assert finding.raw_deduction == 5
    assert finding.applied_deduction == finding.deduction == 0
    assert finding.deduction_status == "suppressed"
    assert finding.suppression_reason == raw_issue["suppression_reason"]
    assert finding.classification == "primary"

def test_review_model_preserves_structured_and_flat_correction_guidance():
    reference = drawing([entity("R-M", "line", [(0, 0), (10, 0)])], (0, 0, 10, 0))
    raw_issue = issue("E-GUIDE", "missing_geometry", reference_id="R-M", deduction=5)
    raw_issue["correction_guidance"] = {
        "primary_command": "LINE",
        "alternative_commands": ["COPY"],
        "precision_aids": ["OSNAP"],
        "explanation": "Create the missing line.",
        "related_primary_issue_id": None,
    }
    raw_issue["recommended_commands"] = ["LINE", "COPY", "OSNAP"]

    reviewed = build_reviewed_drawing(
        reference,
        drawing([], (0, 0, 0, 0)),
        {"score": 95, "issues": [raw_issue]},
    )
    serialized = reviewed.issues[0].to_dict()

    assert serialized["correction_guidance"] == raw_issue["correction_guidance"]
    assert serialized["recommended_commands"] == raw_issue["recommended_commands"]


def test_svg_contains_expected_visual_conventions_and_dual_overlay():
    svg = render_svg(review_with_all_overlay_roles())
    assert 'data-role="missing"' in svg and 'class="missing"' in svg
    assert 'data-role="extra"' in svg and 'class="extra"' in svg
    assert 'data-role="inaccurate"' in svg
    assert 'class="inaccurate-expected"' in svg
    assert 'class="inaccurate-actual"' in svg


def test_line_circle_polyline_ellipse_and_sampled_spline_render():
    reference = drawing([
        entity("R-L", "line", [(10, 0), (0, 0)]),
        entity("R-C", "circle", [(5, 5)], radius=2),
        entity("R-P", "polyline", [(0, 0), (5, 0), (5, 5)], closed=True),
        entity("R-E", "ellipse", [(15, 5)], properties={"major_axis": [4, 0], "ratio": 0.5}),
        entity("R-S", "spline", [(0, 10), (5, 12), (10, 10)], properties={"sampled": True}),
    ], (0, 0, 19, 12))
    reviewed = build_reviewed_drawing(reference, drawing([], (0, 0, 0, 0)), {"score": 100, "issues": []})
    svg = render_svg(reviewed)
    assert '<line ' in svg
    assert '<circle ' in svg
    assert '<polygon ' in svg
    assert '<ellipse ' in svg
    assert 'data-entity-id="R-S"' in svg and '<polyline ' in svg
    ET.fromstring(svg)


def test_empty_drawings_have_stable_finite_fallback_view():
    empty = drawing([], (0, 0, 0, 0))
    reviewed = build_reviewed_drawing(empty, empty, {"issues": [], "score": 100})
    svg = render_svg(reviewed)
    assert "No drawable geometry" in svg
    assert 'data-scale="368"' in svg
    assert "nan" not in svg.lower() and "inf" not in svg.lower()
    ET.fromstring(svg)


def test_reversed_line_endpoints_produce_identical_svg():
    forward = drawing([entity("R-L", "line", [(-5, 2), (5, 2)])], (-5, 2, 5, 2))
    reversed_line = drawing([entity("R-L", "line", [(5, 2), (-5, 2)])], (-5, 2, 5, 2))
    student = drawing([], (0, 0, 0, 0))
    comparison = {"issues": [], "score": 100}
    assert render_svg(build_reviewed_drawing(forward, student, comparison)) == render_svg(build_reviewed_drawing(reversed_line, student, comparison))


def test_negative_coordinates_and_y_axis_inversion_are_stable():
    transform = CoordinateTransform((-10, -20, 10, 20), 200, 160, 20)
    upper = transform.point((0, 20))
    lower = transform.point((0, -20))
    assert upper[1] < lower[1]
    assert math.isclose(transform.scale, 3)
    reviewed = build_reviewed_drawing(
        drawing([entity("R-N", "line", [(-10, -20), (10, 20)])], (-10, -20, 10, 20)),
        drawing([], (0, 0, 0, 0)),
        {"issues": [], "score": 100},
    )
    assert 'data-min-x="-10"' in render_svg(reviewed)


def test_extreme_coordinates_fit_without_overflow_or_nonfinite_output():
    extreme = 1e150
    reference = drawing([entity("R-X", "line", [(-extreme, -extreme), (extreme, extreme)])], (-extreme, -extreme, extreme, extreme))
    svg = render_svg(build_reviewed_drawing(reference, drawing([], (0, 0, 0, 0)), {"issues": []}))
    lower = svg.lower()
    assert "nan" not in lower and "inf" not in lower
    ET.fromstring(svg)


def test_unsupported_entities_and_validation_findings_keep_provenance_and_stable_ids():
    reference = drawing(
        [entity("R-1", "line", [(0, 0), (10, 0)])],
        (0, 0, 10, 0),
        unsupported=[{"source": "spoofed", "entity_type": "HATCH", "handle": "A"}],
    )
    student = drawing([], (0, 0, 0, 0), unsupported=[{"entity_type": "INSERT", "handle": "B"}])
    validation = {"findings": [
        {"code": "zero_length", "severity": "critical", "message": "Critical reference issue.", "entity_id": "R-1", "location": [0, 0]},
        {"code": "missing_units", "severity": "warning", "message": "Units need review.", "entity_id": None, "location": None},
    ]}
    first = build_reviewed_drawing(reference, student, {"issues": []}, validation)
    second = build_reviewed_drawing(reference, student, {"issues": []}, validation)
    assert [item.issue_id for item in first.issues] == [item.issue_id for item in second.issues] == ["V-001", "V-002"]
    assert {item.visual_role for item in first.issues} == {"critical", "reference"}
    assert first.reference_unsupported == [{"entity_type": "HATCH", "handle": "A", "source": "reference"}]
    assert first.student_unsupported == [{"entity_type": "INSERT", "handle": "B", "source": "student"}]


def test_xml_text_and_attribute_content_is_escaped_safely():
    malicious = entity('R"&<', "text", [(0, 0)], layer='layer"&<', text='<script>&"')
    reference = drawing([malicious], (0, 0, 0, 0))
    comparison = {"issues": [issue('E"&<', "missing_geometry", reference_id='R"&<', feedback='<unsafe>&"')]}
    svg = render_svg(build_reviewed_drawing(reference, drawing([], (0, 0, 0, 0)), comparison))
    assert "<script>" not in svg
    assert "&lt;script&gt;&amp;&quot;" in svg
    assert 'data-entity-id="R&quot;&amp;&lt;"' in svg
    assert 'data-layer="layer&quot;&amp;&lt;"' in svg
    assert 'data-issue-id="E&quot;&amp;&lt;"' in svg
    ET.fromstring(svg)


def test_build_and_render_do_not_mutate_drawings_comparison_or_validation():
    reference = parse_dxf_path(SAMPLES / "reference.dxf", source="reference")
    student = parse_dxf_path(SAMPLES / "student_missing_wall.dxf", source="student")
    comparison = compare_drawings(reference, student)
    validation = validate_reference(reference)
    before_reference = deepcopy(reference.to_dict())
    before_student = deepcopy(student.to_dict())
    before_comparison = deepcopy(comparison)
    before_validation = deepcopy(validation)
    reviewed = build_reviewed_drawing(reference, student, comparison, validation)
    render_svg(reviewed)
    assert reference.to_dict() == before_reference
    assert student.to_dict() == before_student
    assert comparison == before_comparison
    assert validation == before_validation


def test_existing_fixture_grades_are_unchanged_by_review_serialization():
    reference = parse_dxf_path(SAMPLES / "reference.dxf")
    good = parse_dxf_path(SAMPLES / "student_good.dxf", source="student")
    incomplete = parse_dxf_path(SAMPLES / "student_missing_wall.dxf", source="student")
    good_result = compare_drawings(reference, good)
    incomplete_result = compare_drawings(reference, incomplete)
    scores = (good_result["score"], incomplete_result["score"])
    render_svg(build_reviewed_drawing(reference, good, good_result))
    render_svg(build_reviewed_drawing(reference, incomplete, incomplete_result))
    assert (good_result["score"], incomplete_result["score"]) == scores
    assert scores[0] == 100
    assert scores[1] < 100


def test_canonical_endpoint_gap_with_nonzero_object_translation_stays_in_student_frame():
    from app.rubric import default_rubric

    # Anchor object at (0, 0)-(10, 0)-(10, 10)-(0, 10) + translated object shifted by (-200, +300)
    # with a real 5-unit corner endpoint gap on the translated object.
    dx, dy = -200.0, 300.0
    reference = drawing(
        [
            entity("R-A1", "line", [(0, 0), (10, 0)]),
            entity("R-A2", "line", [(10, 0), (10, 10)]),
            entity("R-A3", "line", [(10, 10), (0, 10)]),
            entity("R-A4", "line", [(0, 10), (0, 0)]),
            entity("R-B1", "line", [(100, 100), (150, 100)]),
            entity("R-B2", "line", [(150, 100), (150, 150)]),
            entity("R-B3", "line", [(150, 150), (100, 150)]),
            entity("R-B4", "line", [(100, 150), (100, 100)]),
        ],
        (0, 0, 150, 150),
    )
    student = drawing(
        [
            entity("S-A1", "line", [(0, 0), (10, 0)], source="student"),
            entity("S-A2", "line", [(10, 0), (10, 10)], source="student"),
            entity("S-A3", "line", [(10, 10), (0, 10)], source="student"),
            entity("S-A4", "line", [(0, 10), (0, 0)], source="student"),
            # Translated by (-200, +300), with a 5-unit gap at corner (150+dx, 100+dy) = (-50, 400):
            # S-B1 ends at (-55, 400) instead of (-50, 400).
            entity("S-B1", "line", [(100 + dx, 100 + dy), (145 + dx, 100 + dy)], source="student"),
            entity("S-B2", "line", [(150 + dx, 100 + dy), (150 + dx, 150 + dy)], source="student"),
            entity("S-B3", "line", [(150 + dx, 150 + dy), (100 + dx, 150 + dy)], source="student"),
            entity("S-B4", "line", [(100 + dx, 150 + dy), (100 + dx, 100 + dy)], source="student"),
        ],
        (-100, 0, 10, 450),
    )
    rubric = default_rubric().model_copy(
        update={
            "approved": True,
            "assessment_mode": "formative",
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
        }
    )
    comparison = compare_drawings(reference, student, rubric=rubric)
    assert comparison["normalization"]["student"]["translation"] == [0.0, 0.0]
    gap_issues = [
        item for item in comparison["issues"]
        if item.get("category") == "endpoint_gap" and str(item.get("id", "")).startswith("ERR-")
    ]
    assert gap_issues, "Expected canonical ERR-*-ENDPOINT_GAP finding"
    gap_issue = gap_issues[0]
    meas = gap_issue["measurement"]
    assert meas["coordinate_frame"] == "student"
    actual_pts = meas["actual_points"]
    assert len(actual_pts) == 2
    expected_pair = {(145 + dx, 100 + dy), (150 + dx, 100 + dy)}
    actual_pair = {(round(p[0], 4), round(p[1], 4)) for p in actual_pts}
    assert actual_pair == expected_pair

    reviewed = build_reviewed_drawing(reference, student, comparison)
    rev_gap = next(i for i in reviewed.issues if i.issue_id == gap_issue["id"])
    assert rev_gap.region is not None
    # Region must stay around (-55..-50, 400), NOT shifted again by (-200, +300) to (-255, 700).
    assert -65.0 <= rev_gap.region[0] <= -50.0
    assert 390.0 <= rev_gap.region[1] <= 405.0

    svg = render_svg(reviewed)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    marker_group = root.find(f'.//svg:g[@class="connectivity-marker"][@data-issue-id="{gap_issue["id"]}"]', ns)
    assert marker_group is not None
    circles = marker_group.findall("svg:circle", ns)
    assert len(circles) == 2

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_svg_pts = {
        (round(transform.point(p)[0], 2), round(transform.point(p)[1], 2))
        for p in actual_pts
    }
    rendered_svg_pts = {
        (round(float(c.attrib["cx"]), 2), round(float(c.attrib["cy"]), 2))
        for c in circles
    }
    assert rendered_svg_pts == expected_svg_pts


def test_canonical_endpoint_gap_with_nonzero_accepted_global_translation_stays_in_student_frame():
    from app.rubric import default_rubric

    dx, dy = 150.0, -250.0
    reference = drawing(
        [
            entity(
                "R-B",
                "polyline",
                [(100, 100), (150, 100), (150, 150), (100, 150)],
                closed=True,
            ),
        ],
        (100, 100, 150, 150),
    )
    student = drawing(
        [
            entity("S-B1", "line", [(100 + dx, 100 + dy), (145 + dx, 100 + dy)], source="student"),
            entity("S-B2", "line", [(150 + dx, 100 + dy), (150 + dx, 150 + dy)], source="student"),
            entity("S-B3", "line", [(150 + dx, 150 + dy), (100 + dx, 150 + dy)], source="student"),
            entity("S-B4", "line", [(100 + dx, 150 + dy), (100 + dx, 100 + dy)], source="student"),
        ],
        (100 + dx, 100 + dy, 150 + dx, 150 + dy),
    )
    rubric = default_rubric().model_copy(
        update={
            "approved": True,
            "assessment_mode": "formative",
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
        }
    )
    comparison = compare_drawings(reference, student, rubric=rubric)
    sel_trans = comparison["normalization"]["student"]["translation"]
    assert sel_trans != [0.0, 0.0]

    gap_issues = [
        item for item in comparison["issues"]
        if item.get("category") == "endpoint_gap" and str(item.get("id", "")).startswith("ERR-")
    ]
    assert gap_issues, "Expected canonical ERR-*-ENDPOINT_GAP finding"
    gap_issue = gap_issues[0]
    meas = gap_issue["measurement"]
    assert meas["coordinate_frame"] == "student"
    actual_pts = meas["actual_points"]
    assert len(actual_pts) == 2
    expected_pair = {(145 + dx, 100 + dy), (150 + dx, 100 + dy)}
    actual_pair = {(round(p[0], 4), round(p[1], 4)) for p in actual_pts}
    assert actual_pair == expected_pair

    reviewed = build_reviewed_drawing(reference, student, comparison)
    rev_gap = next(i for i in reviewed.issues if i.issue_id == gap_issue["id"])
    assert rev_gap.region is not None
    assert 290.0 <= rev_gap.region[0] <= 300.0
    assert -155.0 <= rev_gap.region[1] <= -145.0

    svg = render_svg(reviewed)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    marker_group = root.find(f'.//svg:g[@class="connectivity-marker"][@data-issue-id="{gap_issue["id"]}"]', ns)
    assert marker_group is not None
    circles = marker_group.findall("svg:circle", ns)
    assert len(circles) == 2

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_svg_pts = {
        (round(transform.point(p)[0], 2), round(transform.point(p)[1], 2))
        for p in actual_pts
    }
    rendered_svg_pts = {
        (round(float(c.attrib["cx"]), 2), round(float(c.attrib["cy"]), 2))
        for c in circles
    }
    assert rendered_svg_pts == expected_svg_pts


def test_topology_t_gap_connectivity_regression_control():
    reference = drawing([entity("R-1", "line", [(0, 0), (10, 0)]), entity("R-2", "line", [(10, 0), (10, 10)])], (0, 0, 10, 10))
    student = drawing([entity("S-1", "line", [(0, 0), (10, 0)], source="student"), entity("S-2", "line", [(12, 0), (12, 10)], source="student")], (0, 0, 12, 10))
    t_gap = {
        "id": "T-GAP-001",
        "error_id": "T-GAP-001",
        "category": "endpoint_gap",
        "severity": "major",
        "reference_entity_id": "R-2",
        "student_entity_id": "S-2",
        "location": [12, 0],
        "technical_feedback": "Restore junction.",
        "rubric_rule_id": "RULE-TEST",
        "deduction": 2,
        "confidence": "verified",
        "measurement": {
            "property": "endpoint_gap",
            "expected": 0.0,
            "actual": 2.0,
            "actual_points": [[10.0, 0.0], [12.0, 0.0]],
        },
    }
    reviewed = build_reviewed_drawing(reference, student, {"issues": [t_gap], "score": 98})
    rev_issue = reviewed.issues[0]
    assert rev_issue.visual_role == "connectivity"
    assert rev_issue.region == (6.0, -4.0, 16.0, 4.0)
    svg = render_svg(reviewed)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    marker_group = root.find('.//svg:g[@class="connectivity-marker"][@data-issue-id="T-GAP-001"]', ns)
    assert marker_group is not None
    circles = marker_group.findall("svg:circle", ns)
    assert len(circles) == 2

    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    expected_svg_pts = {
        (round(transform.point(p)[0], 2), round(transform.point(p)[1], 2))
        for p in ((10.0, 0.0), (12.0, 0.0))
    }
    rendered_svg_pts = {
        (round(float(c.attrib["cx"]), 2), round(float(c.attrib["cy"]), 2))
        for c in circles
    }
    assert rendered_svg_pts == expected_svg_pts


def _incorrect_position_comparison(
    *,
    normalization_mode: str,
    component_id: str | None,
    issue_id: str,
):
    return {
        "score": 95,
        "rubric_application": {"normalization_mode": normalization_mode},
        "normalization": {"student": {"mode": normalization_mode, "translation": [0.0, 0.0]}},
        "object_translations": {"OBJ-001": [500.0, 1000.0]},
        "assessment_objects": [
            {
                "object_id": "OBJ-001",
                "bbox": [0.0, 0.0, 10.0, 10.0],
                "translation": [500.0, 1000.0],
            }
        ],
        "issues": [
            {
                "id": issue_id,
                "error_id": issue_id,
                "code": "INCORRECT_POSITION",
                "category": "incorrect_position",
                "severity": "major",
                "parent_object_id": "OBJ-001",
                "component_id": component_id,
                "reference_entity_id": "R-1",
                "student_entity_id": "S-1",
                "location": [507.0, 1000.0],
                "technical_feedback": "Align component position.",
                "rubric_rule_id": "RULE-TEST",
                "deduction": 5,
                "confidence": "verified",
                "measurement": {"property": "position", "expected": [5.0, 0.0], "actual": [507.0, 1000.0]},
            }
        ],
    }


def test_component_incorrect_position_under_object_translation_stays_in_student_frame():
    reference = drawing([entity("R-1", "line", [(0.0, 0.0), (10.0, 0.0)])], (0.0, 0.0, 10.0, 0.0))
    student = drawing([entity("S-1", "line", [(502.0, 1000.0), (512.0, 1000.0)], source="student")], (502.0, 1000.0, 512.0, 1000.0))
    comparison = _incorrect_position_comparison(
        normalization_mode="translation",
        component_id="R-1",
        issue_id="ERR-R-1-INCORRECT_POSITION",
    )
    reviewed = build_reviewed_drawing(reference, student, comparison)
    rev_issue = reviewed.issues[0]

    assert rev_issue.expected_geometry.points == ((500.0, 1000.0), (510.0, 1000.0))
    assert rev_issue.actual_geometry.points == ((502.0, 1000.0), (512.0, 1000.0))
    assert rev_issue.region == (500.0, 1000.0, 512.0, 1000.0)
    assert reviewed.student_extents[0] >= 500.0 and reviewed.student_extents[1] >= 1000.0

    svg = render_svg(reviewed)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    expected_line = root.find('.//svg:g[@data-issue-id="ERR-R-1-INCORRECT_POSITION"]/svg:line[@class="inaccurate-expected"]', ns)
    assert expected_line is not None
    transform = CoordinateTransform(reviewed.extents, 1200, 800, 32)
    p1 = transform.point((500.0, 1000.0))
    p2 = transform.point((510.0, 1000.0))
    assert math.isclose(float(expected_line.attrib["x1"]), p1[0], abs_tol=1e-2)
    assert math.isclose(float(expected_line.attrib["y1"]), p1[1], abs_tol=1e-2)
    assert math.isclose(float(expected_line.attrib["x2"]), p2[0], abs_tol=1e-2)
    assert math.isclose(float(expected_line.attrib["y2"]), p2[1], abs_tol=1e-2)


def test_incorrect_position_strict_mode_keeps_raw_reference_frame():
    reference = drawing([entity("R-1", "line", [(0.0, 0.0), (10.0, 0.0)])], (0.0, 0.0, 10.0, 0.0))
    student = drawing([entity("S-1", "line", [(502.0, 1000.0), (512.0, 1000.0)], source="student")], (502.0, 1000.0, 512.0, 1000.0))
    comparison = _incorrect_position_comparison(
        normalization_mode="strict",
        component_id="R-1",
        issue_id="ERR-R-1-INCORRECT_POSITION",
    )
    reviewed = build_reviewed_drawing(reference, student, comparison)
    assert reviewed.issues[0].expected_geometry.points == ((0.0, 0.0), (10.0, 0.0))


def test_object_level_incorrect_position_keeps_raw_reference_frame():
    reference = drawing([entity("R-1", "line", [(0.0, 0.0), (10.0, 0.0)])], (0.0, 0.0, 10.0, 0.0))
    student = drawing([entity("S-1", "line", [(502.0, 1000.0), (512.0, 1000.0)], source="student")], (502.0, 1000.0, 512.0, 1000.0))
    comparison = _incorrect_position_comparison(
        normalization_mode="translation",
        component_id=None,
        issue_id="ISSUE-OBJ-001-POS",
    )
    reviewed = build_reviewed_drawing(reference, student, comparison)
    assert reviewed.issues[0].expected_geometry.points == ((0.0, 0.0), (10.0, 0.0))


def test_detached_object_position_marks_svg_group_with_placement_context():
    reference = drawing([entity("R-1", "line", [(0.0, 0.0), (10.0, 0.0)])], (0.0, 0.0, 10.0, 0.0))
    student = drawing([entity("S-1", "line", [(502.0, 1000.0), (512.0, 1000.0)], source="student")], (502.0, 1000.0, 512.0, 1000.0))
    comparison = _incorrect_position_comparison(
        normalization_mode="translation",
        component_id=None,
        issue_id="ISSUE-OBJ-001-POS",
    )
    reviewed = build_reviewed_drawing(reference, student, comparison)
    svg = render_svg(reviewed)
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    group = root.find('.//svg:g[@data-issue-id="ISSUE-OBJ-001-POS"]', ns)
    assert group is not None
    assert group.attrib.get("data-placement-context") == "detached"
    assert group.find('./svg:line[@class="inaccurate-expected"]', ns) is not None
    assert group.find('./svg:line[@class="inaccurate-actual"]', ns) is not None


def test_closed_polyline_component_issue_includes_full_reference_outline():
    reference = drawing(
        [entity("R-1", "polyline", [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)], closed=True)],
        (0.0, 0.0, 20.0, 10.0),
    )
    student = drawing(
        [entity("S-1", "line", [(100.0, 200.0), (115.0, 200.0)], source="student")],
        (100.0, 200.0, 115.0, 200.0),
    )
    comparison = {
        "normalization_mode": "translation",
        "object_translations": {"OBJ-001": [100.0, 200.0]},
        "assessment_objects": [
            {
                "object_id": "OBJ-001",
                "source_entity_ids": ["R-1"],
                "components": [
                    {"id": "R-1-S00", "kind": "segment", "source_entity_id": "R-1", "layer": "0", "start": [0.0, 0.0], "end": [20.0, 0.0]},
                    {"id": "R-1-S01", "kind": "segment", "source_entity_id": "R-1", "layer": "0", "start": [20.0, 0.0], "end": [20.0, 10.0]},
                    {"id": "R-1-S02", "kind": "segment", "source_entity_id": "R-1", "layer": "0", "start": [20.0, 10.0], "end": [0.0, 10.0]},
                    {"id": "R-1-S03", "kind": "segment", "source_entity_id": "R-1", "layer": "0", "start": [0.0, 10.0], "end": [0.0, 0.0]},
                ],
            }
        ],
        "issues": [
            {
                "id": "ERR-R-1-S00-INCORRECT_LENGTH",
                "error_id": "ERR-R-1-S00-INCORRECT_LENGTH",
                "category": "incorrect_length",
                "severity": "major",
                "reference_entity_id": "R-1",
                "student_entity_id": "S-1",
                "parent_object_id": "OBJ-001",
                "component_id": "R-1-S00",
                "location": [10.0, 0.0],
                "technical_feedback": "Length mismatch.",
                "rubric_rule_id": "RULE-LEN",
                "deduction": 3,
                "confidence": "verified",
            }
        ],
    }
    reviewed = build_reviewed_drawing(reference, student, comparison)
    assert len(reviewed.issues) == 1
    expected_geoms = reviewed.issues[0].expected_geometries
    assert any(g.kind == "polyline" and g.closed and len(g.points) == 4 for g in expected_geoms)
    poly = next(g for g in expected_geoms if g.kind == "polyline")
    assert poly.points == ((100.0, 200.0), (120.0, 200.0), (120.0, 210.0), (100.0, 210.0))


def test_incorrect_length_includes_adjacent_missing_chamfer_expected_context():
    reference = drawing(
        [
            entity("R-1", "line", [(0.0, 0.0), (80.0, 0.0)]),
            entity("R-2", "line", [(80.0, 0.0), (100.0, 20.0)]),
        ],
        (0.0, 0.0, 100.0, 20.0),
    )
    student = drawing(
        [entity("S-1", "line", [(50.0, 50.0), (150.0, 50.0)], source="student")],
        (50.0, 50.0, 150.0, 50.0),
    )
    comparison = {
        "normalization_mode": "translation",
        "object_translations": {"OBJ-001": [50.0, 50.0]},
        "assessment_objects": [
            {
                "object_id": "OBJ-001",
                "source_entity_ids": ["R-1", "R-2"],
                "components": [
                    {"id": "R-1-S00", "kind": "segment", "source_entity_id": "R-1", "layer": "0", "start": [0.0, 0.0], "end": [80.0, 0.0]},
                    {"id": "R-2-S00", "kind": "segment", "source_entity_id": "R-2", "layer": "0", "start": [80.0, 0.0], "end": [100.0, 20.0]},
                ],
            }
        ],
        "issues": [
            {
                "id": "ERR-R-1-S00-INCORRECT_LENGTH",
                "error_id": "ERR-R-1-S00-INCORRECT_LENGTH",
                "category": "incorrect_length",
                "severity": "major",
                "reference_entity_id": "R-1",
                "student_entity_id": "S-1",
                "parent_object_id": "OBJ-001",
                "component_id": "R-1-S00",
                "location": [40.0, 0.0],
                "technical_feedback": "Length mismatch.",
                "rubric_rule_id": "RULE-LEN",
                "deduction": 3,
                "confidence": "verified",
            },
            {
                "id": "ISSUE-R-2-S00",
                "error_id": "ISSUE-R-2-S00",
                "category": "missing_geometry",
                "severity": "major",
                "reference_entity_id": "R-2",
                "student_entity_id": None,
                "parent_object_id": "OBJ-001",
                "component_id": "R-2-S00",
                "location": [90.0, 10.0],
                "technical_feedback": "Missing chamfer.",
                "rubric_rule_id": "RULE-MISS",
                "deduction": 1,
                "confidence": "verified",
            },
        ],
    }
    reviewed = build_reviewed_drawing(reference, student, comparison)
    assert len([i for i in reviewed.issues if i.category == "missing_geometry"]) == 1
    len_issue = next(i for i in reviewed.issues if i.category == "incorrect_length")
    assert len(len_issue.expected_geometries) == 2
    assert len_issue.expected_geometries[1].points == ((130.0, 50.0), (150.0, 70.0))
