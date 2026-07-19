from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Issue
from .rubric import Rubric, rubric_rule_map


def _category_breakdown(
    rubric: Rubric,
    category_deductions: dict[str, float],
) -> list[dict[str, Any]]:
    breakdown = []
    for category in rubric.categories:
        deducted = round(category_deductions.get(category.id, 0.0), 2)
        breakdown.append(
            {
                "id": category.id,
                "name": category.name,
                "weight": category.weight,
                "deduction": deducted,
                "score": round(max(0.0, category.weight - deducted), 2),
            }
        )
    return breakdown


def _audit_entry(
    issue: Issue,
    *,
    applied_rule: str | None,
    raw_deduction: float,
    after_rule_cap: float,
    after_category_cap: float,
    suppression_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "issue_id": issue.id,
        "primary_issue_id": issue.id if issue.classification == "primary" else None,
        "category": issue.category,
        "classification": issue.classification,
        "rule_id": applied_rule,
        "applied_rule": applied_rule,
        "requested": raw_deduction,
        "raw_deduction": raw_deduction,
        "deduction_after_rule_cap": after_rule_cap,
        "deduction_after_category_cap": after_category_cap,
        "applied": after_category_cap,
        "derived_observations": issue.derived_evidence,
        "supporting_evidence": issue.supporting_evidence,
        "suppressed_findings": issue.suppressed_findings,
        "suppression_reason": suppression_reason,
    }


def score_issues(
    issues: list[Issue],
    rubric: Rubric,
    completion_percentage: float,
    suppressed_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply visible rubric deductions after causal consolidation."""

    rules = rubric_rule_map(rubric)
    category_deductions: dict[str, float] = defaultdict(float)
    rule_deductions: dict[str, float] = defaultdict(float)
    audit: list[dict[str, Any]] = []

    for issue in issues:
        pair = rules.get(issue.category)
        rule = pair[0] if pair else None
        category = pair[1] if pair else None
        raw = float(rule.deduction if rule else 0.0)
        issue.deduction = raw
        issue.rubric_rule_id = rule.id if rule else None

        suppression_reason = None
        if issue.classification != "primary":
            suppression_reason = f"{issue.classification} findings are not scored"
        elif issue.confidence not in {"verified", "high"} or issue.status == "rejected":
            suppression_reason = "requires instructor confirmation"
        elif (
            issue.category == "missing_geometry"
            and rubric.completion_scoring_mode == "proportional"
        ):
            suppression_reason = (
                "fixed missing deduction suppressed by proportional completion policy"
            )
        elif not rule or not category:
            suppression_reason = "no enabled rubric rule"

        issue.suppression_reason = suppression_reason
        if suppression_reason:
            issue.applied_deduction = 0.0
            audit.append(
                _audit_entry(
                    issue,
                    applied_rule=rule.id if rule else None,
                    raw_deduction=raw,
                    after_rule_cap=0.0,
                    after_category_cap=0.0,
                    suppression_reason=suppression_reason,
                )
            )
            continue

        rule_limit = rule.repeat_cap if rule.repeat_cap is not None else float("inf")
        remaining_rule = max(0.0, rule_limit - rule_deductions[rule.id])
        after_rule_cap = min(raw, remaining_rule)
        category_limit = (
            category.max_deduction
            if category.max_deduction is not None
            else category.weight
        )
        remaining_category = max(
            0.0, category_limit - category_deductions[category.id]
        )
        after_category_cap = min(after_rule_cap, remaining_category)
        rule_deductions[rule.id] += after_category_cap
        category_deductions[category.id] += after_category_cap
        issue.applied_deduction = round(after_category_cap, 2)
        audit.append(
            _audit_entry(
                issue,
                applied_rule=rule.id,
                raw_deduction=raw,
                after_rule_cap=round(after_rule_cap, 2),
                after_category_cap=round(after_category_cap, 2),
            )
        )

    completion_category = next(
        category for category in rubric.categories if category.id == "completion"
    )
    if rubric.completion_scoring_mode == "proportional":
        raw_completion = round(
            (100.0 - completion_percentage) / 100.0 * completion_category.weight,
            2,
        )
        completion_limit = (
            completion_category.max_deduction
            if completion_category.max_deduction is not None
            else completion_category.weight
        )
        completion_applied = min(raw_completion, completion_limit)
        category_deductions["completion"] = completion_applied
        audit.append(
            {
                "issue_id": None,
                "primary_issue_id": None,
                "category": "completion",
                "classification": "primary",
                "rule_id": "COMPLETION-PROPORTIONAL",
                "applied_rule": "COMPLETION-PROPORTIONAL",
                "requested": raw_completion,
                "raw_deduction": raw_completion,
                "deduction_after_rule_cap": raw_completion,
                "deduction_after_category_cap": completion_applied,
                "applied": completion_applied,
                "derived_observations": [],
                "supporting_evidence": [
                    {
                        "property": "completion_percentage",
                        "expected": 100.0,
                        "actual": completion_percentage,
                    }
                ],
                "suppressed_findings": [],
                "suppression_reason": None,
            }
        )
    else:
        category_deductions["completion"] = 0.0
        audit.append(
            {
                "issue_id": None,
                "primary_issue_id": None,
                "category": "completion",
                "classification": "informational",
                "rule_id": None,
                "applied_rule": None,
                "requested": 0.0,
                "raw_deduction": 0.0,
                "deduction_after_rule_cap": 0.0,
                "deduction_after_category_cap": 0.0,
                "applied": 0.0,
                "derived_observations": [],
                "supporting_evidence": [
                    {
                        "property": "completion_percentage",
                        "expected": 100.0,
                        "actual": completion_percentage,
                    }
                ],
                "suppressed_findings": [],
                "suppression_reason": (
                    "proportional completion deduction disabled by rule-based policy"
                ),
            }
        )

    for finding in suppressed_findings:
        audit.append(
            {
                "issue_id": None,
                "primary_issue_id": finding.get("primary_issue_id"),
                "category": finding["category"],
                "classification": "suppressed",
                "rule_id": None,
                "applied_rule": None,
                "requested": 0.0,
                "raw_deduction": 0.0,
                "deduction_after_rule_cap": 0.0,
                "deduction_after_category_cap": 0.0,
                "applied": 0.0,
                "derived_observations": [finding.get("observation")],
                "supporting_evidence": [],
                "suppressed_findings": [],
                "suppression_reason": finding["suppression_reason"],
            }
        )

    deduction = round(sum(category_deductions.values()), 2)
    score = max(0.0, round(100.0 - deduction, 1))
    breakdown = _category_breakdown(rubric, category_deductions)
    visible_applied = round(sum(float(entry["applied"]) for entry in audit), 2)
    if visible_applied != deduction:
        raise RuntimeError(
            "Visible applied deductions do not reconcile with the final deduction."
        )

    return {
        "score": score,
        "deduction": deduction,
        "category_deductions": dict(category_deductions),
        "rubric_breakdown": breakdown,
        "audit_trail": audit,
        "score_breakdown": {
            "completion_scoring_mode": rubric.completion_scoring_mode,
            "issues": [
                entry for entry in audit if entry.get("primary_issue_id") is not None
            ],
            "suppressed_findings": [
                entry for entry in audit if entry["classification"] == "suppressed"
            ],
            "category_subtotals": breakdown,
            "total_applied_deduction": deduction,
            "final_score": score,
        },
    }
