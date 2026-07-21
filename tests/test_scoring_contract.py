from __future__ import annotations

from app.models import Issue
from app.rubric import BASELINE_RUBRIC_TEMPLATE, default_rubric, rubric_rule_map
from app.scoring import score_issues


def _issue(issue_id: str, category: str) -> Issue:
    return Issue(
        id=issue_id,
        category=category,
        severity="major",
        message=category,
        deduction=0,
    )


def test_baseline_template_has_fixed_source_and_central_category_semantics():
    rubric = default_rubric().model_copy(update={"approved": True})
    rules = rubric_rule_map(rubric)
    assert rubric.rubric_template_name == BASELINE_RUBRIC_TEMPLATE
    assert rubric.rubric_source == "baseline_template"
    assert rules["missing_geometry"][1].id == "completion"
    assert rules["incorrect_length"][1].id == "geometry"
    assert rules["extra_geometry"][1].id == "quality"
    assert rules["duplicate_geometry"][1].id == "quality"


def test_controlled_category_reallocation_preserves_scores_and_reconciles():
    cases = [
        ("missing_geometry", 95, "completion", 5),
        ("incorrect_length", 97, "geometry", 3),
        ("incorrect_angle", 97, "geometry", 3),
        ("incorrect_position", 97, "geometry", 3),
        ("incorrect_radius", 97, "geometry", 3),
        ("extra_geometry", 98, "quality", 2),
        ("duplicate_geometry", 99, "quality", 1),
    ]
    rubric = default_rubric().model_copy(update={"approved": True})
    for category, expected_score, expected_score_category, deduction in cases:
        issue = _issue("E-001", category)
        result = score_issues([issue], rubric, 90, [])
        assert result["score"] == expected_score
        assert issue.score_category == expected_score_category
        assert issue.final_applied_contribution == deduction
        assert issue.deduction_status == "applied"
        subtotal = next(
            item
            for item in result["score_breakdown"]["category_subtotals"]
            if item["id"] == expected_score_category
        )
        assert subtotal["deduction"] == deduction
        assert sum(
            evidence["final_applied_contribution"]
            for evidence in subtotal["deduction_evidence"]
        ) == deduction


def test_rule_and_category_caps_are_exposed_per_issue_and_reconcile():
    rubric = default_rubric().model_copy(update={"approved": True})
    issues = [_issue(f"E-{index:03d}", "extra_geometry") for index in range(1, 8)]
    result = score_issues(issues, rubric, 100, [])
    assert result["deduction"] == 10
    assert [issue.final_applied_contribution for issue in issues] == [2, 2, 2, 2, 2, 0, 0]
    assert issues[-1].deduction_status == "capped"
    assert issues[-1].cap_reason == "rule_repeat_cap"
    assert sum(issue.final_applied_contribution for issue in issues) == result["deduction"]
