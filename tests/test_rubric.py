import pytest
from pydantic import ValidationError
from app.rubric import Rubric, RubricCategory, default_rubric, suggest_assignment_title

def test_default_rubric_totals_100_and_is_provisional():
    rubric = default_rubric()
    assert sum(category.weight for category in rubric.categories) == 100
    assert rubric.approved is False
    assert rubric.assignment_type is None
    assert rubric.tolerances.radius == 1.0
    assert rubric.completion_scoring_mode == "rule_based"

def test_rubric_accepts_only_instructor_assignment_type_options():
    payload = default_rubric().model_dump()
    payload["assignment_type"] = "Complex Geometric Pattern"
    assert Rubric.model_validate(payload).assignment_type == "Complex Geometric Pattern"

    payload["assignment_type"] = "Islamic Geometric Pattern"
    with pytest.raises(ValidationError):
        Rubric.model_validate(payload)

    payload["assignment_type"] = "Gothic pattern"
    with pytest.raises(ValidationError):
        Rubric.model_validate(payload)

def test_assignment_title_suggestion_removes_safe_technical_filename_parts():
    assert suggest_assignment_title(
        "00_REFERENCE_Interior_Plan_Supported_Geometry.dxf"
    ) == "Interior Plan"
    assert suggest_assignment_title(
        "00_REFERENCE_Complex_Pattern_Supported_Geometry.dxf"
    ) == "Complex Pattern"

def test_rubric_rejects_weights_that_do_not_total_100():
    with pytest.raises(ValidationError, match="weights must total 100"):
        Rubric(categories=[
            RubricCategory(id="geometry", name="Geometry", weight=80),
            RubricCategory(id="completion", name="Completion", weight=10),
        ])



def test_unapproved_rubric_cannot_grade_directly():
    from pathlib import Path
    from app.compare import compare_drawings
    from app.dxf import parse_dxf_path
    samples = Path(__file__).parents[1] / "samples"
    with pytest.raises(ValueError, match="approved rubric"):
        compare_drawings(parse_dxf_path(samples/"reference.dxf"), parse_dxf_path(samples/"student_good.dxf", source="student"), rubric=default_rubric())


def test_deductions_respect_rule_and_category_caps():
    from pathlib import Path
    from app.compare import compare_drawings
    from app.dxf import parse_dxf_path
    samples = Path(__file__).parents[1] / "samples"
    rubric = default_rubric().model_copy(update={"approved": True})
    missing_rule = next(rule for category in rubric.categories for rule in category.rules if rule.check == "missing_geometry")
    missing_rule.deduction = 100
    missing_rule.repeat_cap = 4
    result = compare_drawings(parse_dxf_path(samples/"reference.dxf"), parse_dxf_path(samples/"student_missing_wall.dxf", source="student"), rubric=rubric)
    applied = [entry["applied"] for entry in result["audit_trail"] if entry.get("rule_id") == missing_rule.id]
    assert applied and sum(applied) <= 4
    assert 0 <= result["score"] <= 100
    assert all(category["deduction"] <= category["weight"] for category in result["rubric_breakdown"])

def test_proportional_completion_suppresses_fixed_missing_rule():
    from pathlib import Path
    from app.compare import compare_drawings
    from app.dxf import parse_dxf_path

    samples = Path(__file__).parents[1] / "samples"
    rubric = default_rubric().model_copy(
        update={"approved": True, "completion_scoring_mode": "proportional"}
    )
    result = compare_drawings(
        parse_dxf_path(samples / "reference.dxf"),
        parse_dxf_path(
            samples / "student_missing_wall.dxf", source="student"
        ),
        rubric=rubric,
    )
    missing = next(
        entry
        for entry in result["audit_trail"]
        if entry["category"] == "missing_geometry"
    )
    completion = next(
        entry
        for entry in result["audit_trail"]
        if entry.get("rule_id") == "COMPLETION-PROPORTIONAL"
    )

    assert missing["raw_deduction"] == 5
    assert missing["applied"] == 0
    assert "proportional completion policy" in missing["suppression_reason"]
    missing_issue = next(issue for issue in result["issues"] if issue["category"] == "missing_geometry")
    assert missing_issue["deduction"] == 5
    assert missing_issue["applied_deduction"] == 0
    assert missing_issue["suppression_reason"] == missing["suppression_reason"]
    assert completion["applied"] > 0
    assert sum(entry["applied"] for entry in result["audit_trail"]) == result[
        "deduction"
    ]


def test_completion_scoring_mode_rejects_implicit_hybrid_policy():
    payload = default_rubric().model_dump()
    payload["completion_scoring_mode"] = "hybrid"
    with pytest.raises(ValidationError):
        Rubric.model_validate(payload)
