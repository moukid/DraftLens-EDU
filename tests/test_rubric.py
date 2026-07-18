import pytest
from pydantic import ValidationError
from app.rubric import Rubric, RubricCategory, default_rubric

def test_default_rubric_totals_100_and_is_provisional():
    rubric = default_rubric()
    assert sum(category.weight for category in rubric.categories) == 100
    assert rubric.approved is False
    assert rubric.tolerances.radius == 1.0

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
