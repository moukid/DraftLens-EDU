from collections import Counter
from pathlib import Path

import pytest

from app.compare import compare_drawings
from app.dxf import parse_dxf_bytes
from app.review_service import build_review_response, run_grading_pipeline
from app.rubric import default_rubric


FIXTURES = Path(__file__).parent / "fixtures" / "simple_audit"
REFERENCE = "00_reference_000-Simple.dxf"
EXACT = "01_exact_copy_should_score_100.dxf"
MISSING = "02_missing_line_73B.dxf"
SHORT = "03_wrong_length_73C_80_units.dxf"
MOVED_LINE = "04_moved_line_73B_plus20Y.dxf"
ROTATED_LINE = "05_wrong_angle_73D_40deg.dxf"
MOVED_CIRCLE = "06_moved_circle_722_plus20X.dxf"
RADIUS = "07_wrong_circle_radius_40.dxf"
EXTRA = "08_extra_line_handle_740.dxf"
DUPLICATE = "09_duplicate_line_73B_handle_741.dxf"
DISCONNECTED = "10_disconnected_square_corner_5_units.dxf"


@pytest.fixture(scope="module")
def audit_outputs():
    reference = (FIXTURES / REFERENCE).read_bytes()
    outputs = {}
    for filename in (
        EXACT,
        MISSING,
        SHORT,
        MOVED_LINE,
        ROTATED_LINE,
        MOVED_CIRCLE,
        RADIUS,
        EXTRA,
        DUPLICATE,
        DISCONNECTED,
    ):
        outputs[filename] = run_grading_pipeline(
            reference,
            (FIXTURES / filename).read_bytes(),
            rubric_id=None,
            allow_fallback=True,
            position_tolerance=2,
            length_tolerance=1,
            angle_tolerance=3,
            dimension_tolerance=1,
            radius_tolerance=1,
            rubrics={},
            reference_rubrics={},
            rubric_references={},
        )
    return outputs


def comparison(audit_outputs, filename):
    return audit_outputs[filename].comparison


def issues(audit_outputs, filename, category=None):
    result = comparison(audit_outputs, filename)["issues"]
    return [item for item in result if category is None or item["category"] == category]


def breakdown(audit_outputs, filename, category_id):
    return next(
        category
        for category in comparison(audit_outputs, filename)["rubric_breakdown"]
        if category["id"] == category_id
    )


def strict_comparison(filename):
    rubric = default_rubric("Strict controlled audit").model_copy(
        update={"approved": True, "normalization_mode": "strict"}
    )
    reference = parse_dxf_bytes(
        (FIXTURES / REFERENCE).read_bytes(), source="reference", normalize=False
    )
    student = parse_dxf_bytes(
        (FIXTURES / filename).read_bytes(), source="student", normalize=False
    )
    return compare_drawings(reference, student, rubric=rubric)


def test_exact_copy_scores_100(audit_outputs):
    assert comparison(audit_outputs, EXACT)["score"] == 100


def test_exact_copy_has_zero_student_geometry_issues(audit_outputs):
    assert issues(audit_outputs, EXACT) == []


def test_reviewed_exact_copy_preserves_reference_note_provenance(audit_outputs):
    review = build_review_response(audit_outputs[EXACT])
    assert [item["provenance"] for item in review["issues"]] == [
        "reference_validation"
    ]


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_exact_copy_review_contract_separates_student_issue_count(audit_outputs):
    review = build_review_response(audit_outputs[EXACT])
    assert review["student_issue_count"] == 0
    assert review["reference_note_count"] == 1


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_intentional_standalone_reference_lines_are_not_connectivity_warnings(
    audit_outputs,
):
    codes = {item["code"] for item in audit_outputs[EXACT].validation["findings"]}
    assert "disconnected_boundary" not in codes


def test_missing_line_has_one_missing_causal_issue(audit_outputs):
    assert len(issues(audit_outputs, MISSING, "missing_geometry")) == 1
    assert len(issues(audit_outputs, MISSING)) == 1


def test_missing_line_issue_location_matches_expected_geometry(audit_outputs):
    output = audit_outputs[MISSING]
    issue = issues(audit_outputs, MISSING, "missing_geometry")[0]
    expected = next(
        entity
        for entity in output.reference.entities
        if entity.id == issue["reference_entity_id"]
    )
    assert issue["location"] == pytest.approx(expected.centroid)
    assert all(
        entity.points != expected.points or entity.kind != expected.kind
        for entity in output.student.entities
    )


def test_missing_line_does_not_reduce_completion_in_addition_to_rule(audit_outputs):
    assert breakdown(audit_outputs, MISSING, "completion")["deduction"] == 0


def test_missing_line_current_five_point_rule_produces_score_95(audit_outputs):
    result = comparison(audit_outputs, MISSING)
    assert result["deduction"] == 5
    assert result["score"] == 95


def test_shortened_line_records_expected_and_actual_length(audit_outputs):
    length_issue = issues(audit_outputs, SHORT, "incorrect_length")
    assert len(length_issue) == 1
    assert length_issue[0]["measurement"]["expected"] == pytest.approx(100)
    assert length_issue[0]["measurement"]["actual"] == pytest.approx(80)


def test_shortened_line_preserves_angle(audit_outputs):
    assert issues(audit_outputs, SHORT, "incorrect_angle") == []


def test_shortened_line_has_only_one_primary_length_issue(audit_outputs):
    assert [item["category"] for item in issues(audit_outputs, SHORT)] == [
        "incorrect_length"
    ]


def test_shortened_line_centroid_shift_is_derived_evidence(audit_outputs):
    length_issue = issues(audit_outputs, SHORT, "incorrect_length")[0]
    derived = length_issue.get("derived_evidence", [])
    centroid = next(item for item in derived if item["property"] == "centroid_shift")
    assert centroid["actual"] == pytest.approx(10)


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_shortened_line_recommends_endpoint_correction_commands(audit_outputs):
    length_issue = issues(audit_outputs, SHORT, "incorrect_length")[0]
    assert {"LENGTHEN", "STRETCH", "EXTEND", "OSNAP"} <= set(
        length_issue["recommended_commands"]
    )
    assert "MOVE" not in {
        command
        for item in issues(audit_outputs, SHORT)
        for command in item["recommended_commands"]
    }


def test_rigidly_moved_line_has_one_position_issue(audit_outputs):
    assert [item["category"] for item in issues(audit_outputs, MOVED_LINE)] == [
        "incorrect_position"
    ]


def test_rigidly_moved_line_records_20_unit_displacement(audit_outputs):
    position = issues(audit_outputs, MOVED_LINE, "incorrect_position")[0]
    assert position["measurement"]["actual"] == pytest.approx(20)


def test_rigidly_moved_line_preserves_length_and_angle(audit_outputs):
    categories = {item["category"] for item in issues(audit_outputs, MOVED_LINE)}
    assert "incorrect_length" not in categories
    assert "incorrect_angle" not in categories


def test_rigidly_moved_line_recommends_move(audit_outputs):
    position = issues(audit_outputs, MOVED_LINE, "incorrect_position")[0]
    assert "MOVE" in position["recommended_commands"]


def test_rotated_line_records_expected_and_actual_angle(audit_outputs):
    angle_issue = issues(audit_outputs, ROTATED_LINE, "incorrect_angle")
    assert len(angle_issue) == 1
    assert angle_issue[0]["measurement"]["expected"] == pytest.approx(30)
    assert angle_issue[0]["measurement"]["actual"] == pytest.approx(40)


def test_rotated_line_has_only_one_primary_angle_issue(audit_outputs):
    assert [item["category"] for item in issues(audit_outputs, ROTATED_LINE)] == [
        "incorrect_angle"
    ]


def test_rotated_line_centroid_shift_is_derived_evidence(audit_outputs):
    angle_issue = issues(audit_outputs, ROTATED_LINE, "incorrect_angle")[0]
    derived = angle_issue.get("derived_evidence", [])
    centroid = next(item for item in derived if item["property"] == "centroid_shift")
    assert centroid["actual"] == pytest.approx(8.715574, abs=1e-6)


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_rotated_line_recommends_rotation_not_move(audit_outputs):
    angle_issue = issues(audit_outputs, ROTATED_LINE, "incorrect_angle")[0]
    assert {"ROTATE", "REFERENCE", "OSNAP", "POLAR"} <= set(
        angle_issue["recommended_commands"]
    )
    assert "MOVE" not in {
        command
        for item in issues(audit_outputs, ROTATED_LINE)
        for command in item["recommended_commands"]
    }


def test_moved_circle_has_one_circle_position_issue(audit_outputs):
    output = audit_outputs[MOVED_CIRCLE]
    circle_ids = {entity.id for entity in output.reference.entities if entity.kind == "circle"}
    circle_position = [
        item
        for item in issues(audit_outputs, MOVED_CIRCLE, "incorrect_position")
        if item["reference_entity_id"] in circle_ids
    ]
    assert len(circle_position) == 1
    assert circle_position[0]["measurement"]["actual"] == pytest.approx(20)


def test_moved_circle_leaves_all_other_entities_correct(audit_outputs):
    result = comparison(audit_outputs, MOVED_CIRCLE)
    assert result["match_count"] == 19
    assert len(result["issues"]) == 1
    assert result["score"] == 97


def test_moved_circle_does_not_change_drawing_normalization(audit_outputs):
    normalization = comparison(audit_outputs, MOVED_CIRCLE)["normalization"]
    assert normalization["student"]["translation"] == normalization["reference"][
        "translation"
    ]


def test_strict_mode_applies_no_translation_to_moved_circle():
    result = strict_comparison(MOVED_CIRCLE)
    assert result["normalization"]["reference"]["translation"] == [0, 0]
    assert result["normalization"]["student"]["translation"] == [0, 0]


def test_strict_mode_localizes_moved_circle_position_error():
    result = strict_comparison(MOVED_CIRCLE)
    assert [item["category"] for item in result["issues"]] == [
        "incorrect_position"
    ]
    assert result["issues"][0]["measurement"]["actual"] == pytest.approx(20)


def test_radius_change_records_expected_and_actual_radius(audit_outputs):
    radius_issues = issues(audit_outputs, RADIUS, "incorrect_radius")
    assert len(radius_issues) == 1
    assert radius_issues[0]["measurement"]["expected"] == pytest.approx(50)
    assert radius_issues[0]["measurement"]["actual"] == pytest.approx(40)


def test_radius_change_keeps_circle_center_and_other_entities_in_place(audit_outputs):
    result = comparison(audit_outputs, RADIUS)
    assert issues(audit_outputs, RADIUS, "incorrect_position") == []
    assert result["match_count"] == 19


def test_radius_change_does_not_change_drawing_normalization(audit_outputs):
    normalization = comparison(audit_outputs, RADIUS)["normalization"]
    assert normalization["student"]["translation"] == normalization["reference"][
        "translation"
    ]


def test_radius_change_is_one_causal_radius_deduction(audit_outputs):
    result = comparison(audit_outputs, RADIUS)
    assert [item["category"] for item in result["issues"]] == [
        "incorrect_radius"
    ]
    assert result["deduction"] == 3
    assert result["score"] == 97


def test_radius_change_preserves_size_changes_as_supporting_evidence(
    audit_outputs,
):
    radius_issue = issues(audit_outputs, RADIUS, "incorrect_radius")[0]
    evidence = {
        item["property"]: item for item in radius_issue["supporting_evidence"]
    }
    assert evidence["diameter"]["expected"] == pytest.approx(100)
    assert evidence["diameter"]["actual"] == pytest.approx(80)
    assert "circumference" in evidence
    assert "bounding_box" in evidence


def test_strict_mode_prevents_radius_extent_shift():
    result = strict_comparison(RADIUS)
    assert result["normalization"]["reference"]["translation"] == [0, 0]
    assert result["normalization"]["student"]["translation"] == [0, 0]
    assert [
        item for item in result["issues"] if item["category"] == "incorrect_position"
    ] == []


def test_strict_mode_consolidates_circle_size_measurements():
    result = strict_comparison(RADIUS)
    assert [item["category"] for item in result["issues"]] == [
        "incorrect_radius"
    ]


def test_extra_line_has_one_extra_geometry_issue(audit_outputs):
    assert [item["category"] for item in issues(audit_outputs, EXTRA)] == [
        "extra_geometry"
    ]


def test_extra_line_preserves_all_required_matches(audit_outputs):
    result = comparison(audit_outputs, EXTRA)
    assert result["match_count"] == 19
    assert result["completion"]["overall"] == 100


def test_extra_line_does_not_change_normalization(audit_outputs):
    normalization = comparison(audit_outputs, EXTRA)["normalization"]
    assert normalization["student"]["translation"] == normalization["reference"][
        "translation"
    ]


def test_extra_line_uses_current_two_point_rule(audit_outputs):
    result = comparison(audit_outputs, EXTRA)
    assert result["deduction"] == 2
    assert result["score"] == 98


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_extra_line_feedback_includes_geometry_evidence(audit_outputs):
    measurement = issues(audit_outputs, EXTRA, "extra_geometry")[0]["measurement"]
    assert {"entity_type", "length", "angle", "layer", "position"} <= measurement.keys()


def test_duplicate_geometry_specific_issue_is_detected_once(audit_outputs):
    assert len(issues(audit_outputs, DUPLICATE, "duplicate_geometry")) == 1


def test_duplicate_keeps_required_geometry_complete(audit_outputs):
    result = comparison(audit_outputs, DUPLICATE)
    assert result["match_count"] == 19
    assert result["completion"]["overall"] == 100
    assert breakdown(audit_outputs, DUPLICATE, "completion")["deduction"] == 0


def test_duplicate_specific_rule_is_one_point_file_quality_policy(audit_outputs):
    duplicate_issue = issues(audit_outputs, DUPLICATE, "duplicate_geometry")[0]
    assert duplicate_issue["rubric_rule_id"] == "RULE-DUPLICATE-01"
    assert duplicate_issue["deduction"] == 1
    assert breakdown(audit_outputs, DUPLICATE, "quality")["deduction"] == 1


def test_duplicate_is_one_consolidated_file_quality_deduction(audit_outputs):
    result = comparison(audit_outputs, DUPLICATE)
    assert [item["category"] for item in result["issues"]] == [
        "duplicate_geometry"
    ]
    assert breakdown(audit_outputs, DUPLICATE, "geometry")["deduction"] == 0
    assert result["deduction"] == 1
    assert result["score"] == 99


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_duplicate_recommends_overkill_and_erase(audit_outputs):
    commands = set(
        issues(audit_outputs, DUPLICATE, "duplicate_geometry")[0][
            "recommended_commands"
        ]
    )
    assert {"OVERKILL", "ERASE"} <= commands


def test_duplicate_issue_includes_coincident_geometry_evidence(audit_outputs):
    evidence = issues(audit_outputs, DUPLICATE, "duplicate_geometry")[0][
        "measurement"
    ]
    assert {
        "entity_type",
        "length",
        "angle",
        "layer",
        "overlap_percentage",
        "coincident_entity_id",
    } <= evidence.keys()


def test_disconnected_corner_records_expected_and_actual_line_length(audit_outputs):
    length_issue = issues(audit_outputs, DISCONNECTED, "incorrect_length")
    assert len(length_issue) == 1
    assert length_issue[0]["measurement"]["expected"] == pytest.approx(100)
    assert length_issue[0]["measurement"]["actual"] == pytest.approx(95)


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_disconnected_corner_records_five_unit_endpoint_gap(audit_outputs):
    topology = [
        item
        for item in issues(audit_outputs, DISCONNECTED)
        if item["category"] in {"endpoint_gap", "disconnected_geometry", "connectivity"}
    ]
    gap = next(
        item
        for item in topology
        if item.get("measurement", {}).get("property") == "endpoint_gap"
    )
    assert gap["measurement"]["actual"] == pytest.approx(5)


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_disconnected_corner_reports_broken_connectivity(audit_outputs):
    categories = {item["category"] for item in issues(audit_outputs, DISCONNECTED)}
    assert categories & {"endpoint_gap", "disconnected_geometry", "connectivity"}


def test_disconnected_corner_centroid_shift_is_derived_evidence(audit_outputs):
    length_issue = issues(audit_outputs, DISCONNECTED, "incorrect_length")[0]
    derived = length_issue.get("derived_evidence", [])
    centroid = next(item for item in derived if item["property"] == "centroid_shift")
    assert centroid["actual"] == pytest.approx(2.5)


def test_disconnected_corner_has_no_independent_position_deduction(audit_outputs):
    assert issues(audit_outputs, DISCONNECTED, "incorrect_position") == []


def test_disconnected_corner_has_one_scored_causal_deduction(audit_outputs):
    applied = [
        item
        for item in comparison(audit_outputs, DISCONNECTED)["audit_trail"]
        if isinstance(item.get("applied"), (int, float)) and item["applied"] > 0
    ]
    assert len(applied) == 1


@pytest.mark.xfail(
    strict=True,
    reason="Known controlled-audit defect pending Stage 3A repair",
)
def test_disconnected_corner_recommends_endpoint_commands_not_move(audit_outputs):
    commands = {
        command
        for item in issues(audit_outputs, DISCONNECTED)
        for command in item["recommended_commands"]
    }
    assert {"STRETCH", "EXTEND", "LENGTHEN", "OSNAP"} <= commands
    assert "MOVE" not in commands


def test_category_deductions_remain_within_current_caps(audit_outputs):
    for output in audit_outputs.values():
        for category in output.comparison["rubric_breakdown"]:
            assert category["deduction"] <= category["weight"]

def test_all_controlled_deductions_are_visible_and_reconcile(audit_outputs):
    required_fields = {
        "primary_issue_id",
        "category",
        "applied_rule",
        "raw_deduction",
        "deduction_after_rule_cap",
        "deduction_after_category_cap",
        "derived_observations",
        "applied",
    }
    for output in audit_outputs.values():
        result = output.comparison
        visible = round(
            sum(float(entry["applied"]) for entry in result["audit_trail"]),
            2,
        )
        category_total = round(
            sum(category["deduction"] for category in result["rubric_breakdown"]),
            2,
        )
        assert visible == result["deduction"] == category_total
        assert result["score_breakdown"]["total_applied_deduction"] == visible
        assert result["score_breakdown"]["final_score"] == result["score"]
        for entry in result["audit_trail"]:
            if entry.get("primary_issue_id"):
                assert required_fields <= entry.keys()
