from __future__ import annotations

from typing import Any

from .compatibility import CompatibilityResult
from .rubric import Rubric


GEOMETRY_EVIDENCE_TARGET_COVERAGE = 0.75


def _category(comparison: dict[str, Any], category_id: str) -> dict[str, Any]:
    return next(
        category
        for category in comparison["score_breakdown"]["category_subtotals"]
        if category["id"] == category_id
    )


def _set_issue_contribution(
    comparison: dict[str, Any],
    entry: dict[str, Any],
    contribution: float,
    *,
    reason: str,
) -> None:
    value = round(max(0.0, contribution), 2)
    entry["deduction_after_category_cap"] = value
    entry["final_applied_contribution"] = value
    entry["applied"] = value
    entry["deduction_status"] = "partially_applied" if value else "capped"
    entry["cap_reason"] = reason
    issue_id = entry.get("issue_id")
    for issue in comparison.get("issues", []):
        if issue.get("id") == issue_id:
            issue["applied_deduction"] = value
            issue["deduction_after_category_cap"] = value
            issue["final_applied_contribution"] = value
            issue["deduction_status"] = entry["deduction_status"]
            issue["cap_reason"] = reason
            break


def _apply_partial_completion_credit(
    comparison: dict[str, Any],
    rubric: Rubric,
    compatibility: CompatibilityResult,
) -> float:
    if (
        rubric.completion_scoring_mode != "rule_based"
        or compatibility.compatibility_status not in {"compatible", "suspicious"}
        or compatibility.confident_match_count <= 0
        or compatibility.reference_match_coverage <= 0
    ):
        return 0.0
    completion = _category(comparison, "completion")
    if float(completion["score"]) > 0:
        return 0.0
    missing_entries = [
        entry
        for entry in comparison["audit_trail"]
        if entry.get("finding_category") == "missing_geometry"
        and entry.get("score_category") == "completion"
    ]
    reached_repeat_cap = any(
        entry.get("deduction_status") == "capped"
        and "rule_repeat_cap" in str(entry.get("cap_reason") or "")
        for entry in missing_entries
    )
    if not reached_repeat_cap:
        return 0.0

    weight = float(completion["weight"])
    credit = float(
        min(
            20,
            max(5, round(weight * compatibility.reference_match_coverage)),
        )
    )
    target_deduction = max(0.0, weight - credit)
    reduction = max(0.0, float(completion["deduction"]) - target_deduction)
    remaining = reduction
    for entry in reversed(missing_entries):
        current = float(entry.get("final_applied_contribution") or 0.0)
        if current <= 0 or remaining <= 0:
            continue
        removed = min(current, remaining)
        _set_issue_contribution(
            comparison,
            entry,
            current - removed,
            reason="partial_completion_credit",
        )
        remaining = round(remaining - removed, 2)

    completion["deduction"] = round(target_deduction, 2)
    completion["score"] = round(weight - target_deduction, 2)
    return credit


def apply_acceptance_scoring(
    comparison: dict[str, Any],
    rubric: Rubric,
    compatibility: CompatibilityResult,
) -> None:
    """Apply evidence sufficiency and demonstrated-work credit transparently."""

    if comparison.get("score") is None:
        return
    coverage = float(compatibility.reference_match_coverage)
    status_allows_evidence = compatibility.compatibility_status in {
        "compatible",
        "suspicious",
    }
    geometry = _category(comparison, "geometry")
    before = float(geometry["score"])
    factor = (
        min(1.0, coverage / GEOMETRY_EVIDENCE_TARGET_COVERAGE)
        if status_allows_evidence
        else 1.0
    )
    after = round(before * factor, 2)
    evidence_deduction = round(max(0.0, before - after), 2)
    if evidence_deduction:
        policy_entry = {
            "issue_id": None,
            "primary_issue_id": None,
            "category": "geometry",
            "finding_category": "geometry_evidence_limit",
            "score_category": "geometry",
            "classification": "policy",
            "rule_id": "GEOMETRY-EVIDENCE-LIMIT",
            "applied_rule": "GEOMETRY-EVIDENCE-LIMIT",
            "requested": evidence_deduction,
            "raw_deduction": evidence_deduction,
            "deduction_after_rule_cap": evidence_deduction,
            "deduction_after_category_cap": evidence_deduction,
            "final_applied_contribution": evidence_deduction,
            "applied": evidence_deduction,
            "deduction_status": "applied",
            "cap_reason": "insufficient_reference_match_coverage",
            "derived_observations": [],
            "supporting_evidence": [
                {
                    "property": "reference_match_coverage",
                    "expected": GEOMETRY_EVIDENCE_TARGET_COVERAGE,
                    "actual": coverage,
                }
            ],
            "suppressed_findings": [],
            "suppression_reason": None,
        }
        comparison["audit_trail"].append(policy_entry)
        geometry["deduction_evidence"].append(policy_entry)
        geometry["deduction"] = round(float(geometry["deduction"]) + evidence_deduction, 2)
        geometry["score"] = after

    partial_credit = _apply_partial_completion_credit(
        comparison, rubric, compatibility
    )
    subtotals = comparison["score_breakdown"]["category_subtotals"]
    total_deduction = round(sum(float(item["deduction"]) for item in subtotals), 2)
    final_score = max(0.0, round(100.0 - total_deduction, 1))
    comparison["score"] = final_score
    comparison["system_score"] = final_score
    comparison["deduction"] = total_deduction
    comparison["rubric_breakdown"] = subtotals
    comparison["summary"]["by_category"] = {
        item["id"]: item["deduction"] for item in subtotals
    }
    comparison["score_breakdown"].update(
        {
            "total_applied_deduction": total_deduction,
            "final_score": final_score,
            "geometry_evidence_factor": round(factor, 6),
            "geometry_evidence_coverage": round(coverage, 6),
            "geometry_points_before_evidence_limit": round(before, 2),
            "geometry_points_after_evidence_limit": round(after, 2),
            "evidence_limit_reason": (
                None
                if factor >= 1.0
                else "Reference match coverage is below the 75% evidence threshold."
            ),
            "partial_completion_credit": round(partial_credit, 2),
        }
    )
    comparison.update(
        {
            "geometry_evidence_factor": round(factor, 6),
            "geometry_evidence_coverage": round(coverage, 6),
            "geometry_points_before_evidence_limit": round(before, 2),
            "geometry_points_after_evidence_limit": round(after, 2),
            "evidence_limit_reason": comparison["score_breakdown"][
                "evidence_limit_reason"
            ],
            "partial_completion_credit": round(partial_credit, 2),
        }
    )
