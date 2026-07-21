from __future__ import annotations

from collections import defaultdict
from typing import Any


COMPACT_PRIMARY_THRESHOLD = 30
ZERO_CONTRIBUTION_REPRESENTATIVES = 3
SYSTEMATIC_CATEGORIES = {"global_drawing_displacement"}


def compact_finding_presentation(
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select a deterministic presentation subset while preserving raw findings."""

    primary = [issue for issue in issues if issue.get("finding_role") == "primary"]
    if len(primary) <= COMPACT_PRIMARY_THRESHOLD:
        return {
            "compacted": False,
            "total_raw_count": len(primary),
            "total_displayed_count": len(primary),
            "total_summarized_count": 0,
            "displayed_issue_ids": [issue["issue_id"] for issue in issues],
            "summary_groups": [],
        }

    displayed: set[str] = {
        issue["issue_id"]
        for issue in primary
        if float(issue.get("final_applied_contribution") or 0.0) > 0
        or issue.get("category") in SYSTEMATIC_CATEGORIES
    }
    critical_keys: set[tuple[str, str]] = set()
    zero_by_category: dict[str, int] = defaultdict(int)
    for issue in primary:
        issue_id = issue["issue_id"]
        if issue.get("severity") == "critical":
            key = (
                str(issue.get("category") or ""),
                str(issue.get("code") or issue.get("technical_feedback") or ""),
            )
            if key not in critical_keys:
                displayed.add(issue_id)
                critical_keys.add(key)
        if (
            issue_id not in displayed
            and float(issue.get("final_applied_contribution") or 0.0) <= 0
            and zero_by_category[str(issue.get("category") or "")] <
            ZERO_CONTRIBUTION_REPRESENTATIVES
        ):
            displayed.add(issue_id)
            zero_by_category[str(issue.get("category") or "")] += 1

    linked_primary_ids = set(displayed)
    for issue in issues:
        if issue.get("finding_role") == "primary":
            continue
        guidance = issue.get("correction_guidance") or {}
        measurement = issue.get("measurement") or {}
        linked = (
            guidance.get("related_primary_issue_id")
            or measurement.get("linked_primary_issue_id")
        )
        if issue.get("finding_role") in {"reference", "unsupported", "informational"}:
            displayed.add(issue["issue_id"])
        elif linked in linked_primary_ids:
            displayed.add(issue["issue_id"])

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for issue in primary:
        key = (
            str(issue.get("category") or "unknown"),
            str(issue.get("score_category") or "not_scored"),
            str(issue.get("deduction_status") or "not_scored"),
            str(issue.get("cap_reason") or "none"),
        )
        group = grouped.setdefault(
            key,
            {
                "issue_type": key[0],
                "score_category": key[1],
                "deduction_status": key[2],
                "cap_reason": key[3],
                "total_count": 0,
                "displayed_count": 0,
                "contributed_count": 0,
                "summarized_count": 0,
                "score_contribution": 0.0,
            },
        )
        contribution = float(issue.get("final_applied_contribution") or 0.0)
        group["total_count"] += 1
        group["displayed_count"] += issue["issue_id"] in displayed
        group["contributed_count"] += contribution > 0
        group["score_contribution"] += contribution

    detailed_groups = []
    for key in sorted(grouped):
        group = grouped[key]
        group["summarized_count"] = (
            group["total_count"] - group["displayed_count"]
        )
        group["score_contribution"] = round(group["score_contribution"], 2)
        detailed_groups.append(group)

    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for group in detailed_groups:
        key = (group["issue_type"], group["score_category"])
        aggregate = aggregates.setdefault(
            key,
            {
                "issue_type": key[0],
                "score_category": key[1],
                "deduction_status": "",
                "cap_reason": "",
                "total_count": 0,
                "displayed_count": 0,
                "contributed_count": 0,
                "summarized_count": 0,
                "score_contribution": 0.0,
                "deduction_groups": [],
            },
        )
        aggregate["total_count"] += group["total_count"]
        aggregate["displayed_count"] += group["displayed_count"]
        aggregate["contributed_count"] += group["contributed_count"]
        aggregate["summarized_count"] += group["summarized_count"]
        aggregate["score_contribution"] += group["score_contribution"]
        aggregate["deduction_groups"].append(group)

    summaries = []
    for key in sorted(aggregates):
        aggregate = aggregates[key]
        omitted_groups = [
            group
            for group in aggregate["deduction_groups"]
            if group["summarized_count"] > 0
        ]
        if not omitted_groups:
            continue
        aggregate["deduction_status"] = ", ".join(sorted({
            group["deduction_status"] for group in omitted_groups
        }))
        aggregate["cap_reason"] = ", ".join(sorted({
            group["cap_reason"] for group in omitted_groups
        }))
        aggregate["score_contribution"] = round(
            aggregate["score_contribution"], 2
        )
        summaries.append(aggregate)

    displayed_primary_count = sum(
        issue["issue_id"] in displayed for issue in primary
    )
    return {
        "compacted": True,
        "total_raw_count": len(primary),
        "total_displayed_count": displayed_primary_count,
        "total_summarized_count": len(primary) - displayed_primary_count,
        "displayed_issue_ids": [
            issue["issue_id"] for issue in issues if issue["issue_id"] in displayed
        ],
        "summary_groups": summaries,
    }
