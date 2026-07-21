from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Issue
from .rubric import CATEGORY_DEFINITIONS, Rubric, rubric_rule_map


def _category_breakdown(
    rubric: Rubric,
    category_deductions: dict[str, float],
    audit: list[dict[str, Any]],
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
                "definition": CATEGORY_DEFINITIONS.get(category.id, ""),
                "deduction_evidence": [
                    entry
                    for entry in audit
                    if entry.get("score_category") == category.id
                    and entry.get("issue_id") is not None
                ],
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
    cap_reason: str | None = None,
    deduction_status: str = "applied",
) -> dict[str, Any]:
    issue.raw_rule_deduction = round(raw_deduction, 2)
    issue.deduction_after_rule_cap = round(after_rule_cap, 2)
    issue.deduction_after_category_cap = round(after_category_cap, 2)
    issue.final_applied_contribution = round(after_category_cap, 2)
    issue.deduction_status = deduction_status
    issue.cap_reason = cap_reason
    return {
        "issue_id": issue.id,
        "primary_issue_id": issue.id if issue.classification == "primary" else None,
        "category": issue.category,
        "finding_category": issue.category,
        "score_category": issue.score_category,
        "classification": issue.classification,
        "rule_id": applied_rule,
        "applied_rule": applied_rule,
        "requested": raw_deduction,
        "raw_deduction": raw_deduction,
        "deduction_after_rule_cap": after_rule_cap,
        "deduction_after_category_cap": after_category_cap,
        "final_applied_contribution": after_category_cap,
        "applied": after_category_cap,
        "deduction_status": deduction_status,
        "cap_reason": cap_reason,
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
        raw = float(
            issue.deduction
            if issue.category == "global_drawing_displacement" and rule
            else rule.deduction if rule else 0.0
        )
        issue.deduction = raw
        issue.rubric_rule_id = rule.id if rule else None
        issue.score_category = category.id if category else None

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
            if not rule or issue.classification == "informational":
                deduction_status = "informational"
            elif issue.classification != "primary":
                deduction_status = "not_scored"
            else:
                deduction_status = "suppressed"
            audit.append(
                _audit_entry(
                    issue,
                    applied_rule=rule.id if rule else None,
                    raw_deduction=raw,
                    after_rule_cap=0.0,
                    after_category_cap=0.0,
                    suppression_reason=suppression_reason,
                    deduction_status=deduction_status,
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
        cap_reasons = []
        if after_rule_cap < raw:
            cap_reasons.append("rule_repeat_cap")
        if after_category_cap < after_rule_cap:
            cap_reasons.append("category_cap")
        cap_reason = ",".join(cap_reasons) or None
        if after_category_cap == 0 and raw > 0:
            deduction_status = "capped"
        elif after_category_cap < raw:
            deduction_status = "partially_applied"
        elif after_category_cap > 0:
            deduction_status = "applied"
        else:
            deduction_status = "informational"
        audit.append(
            _audit_entry(
                issue,
                applied_rule=rule.id,
                raw_deduction=raw,
                after_rule_cap=round(after_rule_cap, 2),
                after_category_cap=round(after_category_cap, 2),
                cap_reason=cap_reason,
                deduction_status=deduction_status,
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
        remaining_completion = max(0.0, completion_limit - category_deductions["completion"])
        completion_applied = min(raw_completion, remaining_completion)
        category_deductions["completion"] += completion_applied
        audit.append(
            {
                "issue_id": None,
                "primary_issue_id": None,
                "category": "completion",
                "finding_category": "proportional_completion",
                "score_category": "completion",
                "classification": "primary",
                "rule_id": "COMPLETION-PROPORTIONAL",
                "applied_rule": "COMPLETION-PROPORTIONAL",
                "requested": raw_completion,
                "raw_deduction": raw_completion,
                "deduction_after_rule_cap": raw_completion,
                "deduction_after_category_cap": completion_applied,
                "final_applied_contribution": completion_applied,
                "applied": completion_applied,
                "deduction_status": (
                    "applied" if completion_applied else "informational"
                ),
                "cap_reason": (
                    "category_cap" if completion_applied < raw_completion else None
                ),
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
        category_deductions.setdefault("completion", 0.0)
        audit.append(
            {
                "issue_id": None,
                "primary_issue_id": None,
                "category": "completion",
                "finding_category": "completion_percentage",
                "score_category": "completion",
                "classification": "informational",
                "rule_id": None,
                "applied_rule": None,
                "requested": 0.0,
                "raw_deduction": 0.0,
                "deduction_after_rule_cap": 0.0,
                "deduction_after_category_cap": 0.0,
                "final_applied_contribution": 0.0,
                "applied": 0.0,
                "deduction_status": "informational",
                "cap_reason": None,
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
                "finding_category": finding["category"],
                "score_category": None,
                "classification": "suppressed",
                "rule_id": None,
                "applied_rule": None,
                "requested": 0.0,
                "raw_deduction": 0.0,
                "deduction_after_rule_cap": 0.0,
                "deduction_after_category_cap": 0.0,
                "final_applied_contribution": 0.0,
                "applied": 0.0,
                "deduction_status": "suppressed",
                "cap_reason": None,
                "derived_observations": [finding.get("observation")],
                "supporting_evidence": [],
                "suppressed_findings": [],
                "suppression_reason": finding["suppression_reason"],
            }
        )

    deduction = round(sum(category_deductions.values()), 2)
    score = max(0.0, round(100.0 - deduction, 1))
    breakdown = _category_breakdown(rubric, category_deductions, audit)
    visible_applied = round(
        sum(float(entry["final_applied_contribution"]) for entry in audit), 2
    )
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
