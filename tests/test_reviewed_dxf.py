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

SAMPLES = Path(__file__).parents[1] / "samples"


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
    assert {item.visual_role for item in first.issues} == {"critical", "warning"}
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
