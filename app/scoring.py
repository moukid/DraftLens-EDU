from __future__ import annotations

from collections import defaultdict
from math import fsum
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
                    if (
                        entry.get("score_category") == category.id
                        or category.id in (entry.get("score_categories") or [])
                    )
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
    score_categories: list[str] | None = None,
    category_split: dict[str, float] | None = None,
) -> dict[str, Any]:
    issue.raw_rule_deduction = round(raw_deduction, 2)
    issue.deduction_after_rule_cap = round(after_rule_cap, 2)
    issue.deduction_after_category_cap = round(after_category_cap, 2)
    issue.final_applied_contribution = round(after_category_cap, 2)
    issue.deduction_status = deduction_status
    issue.cap_reason = cap_reason
    entry = {
        "issue_id": issue.id,
        "primary_issue_id": issue.id if issue.classification == "primary" else None,
        "parent_object_id": issue.parent_object_id,
        "component_id": issue.component_id,
        "category": issue.category,
        "code": issue.code,
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
    if score_categories is not None:
        issue.score_categories = score_categories
        entry["score_categories"] = score_categories
    if category_split is not None:
        issue.category_split = category_split
        entry["category_split"] = category_split
    return entry


def _score_object_part_deduction(
    issues: list[Issue],
    rubric: Rubric,
    completion_percentage: float,
    suppressed_findings: list[dict[str, Any]],
    canonical_match: Any,
) -> dict[str, Any]:
    rules = rubric_rule_map(rubric)
    geometry_category = next(
        (c for c in rubric.categories if c.id == "geometry"), None
    )
    completion_category = next(
        c for c in rubric.categories if c.id == "completion"
    )
    w_geom = float(geometry_category.weight) if geometry_category else 0.0
    w_comp = float(completion_category.weight)
    w_content = w_geom + w_comp

    ref_objects = (
        getattr(canonical_match, "reference_objects", [])
        if canonical_match is not None
        else []
    )
    obj_budgets: dict[str, float] = {
        obj.object_id: float(obj.weight) * w_content for obj in ref_objects
    }
    obj_remaining: dict[str, float] = dict(obj_budgets)

    category_deductions: dict[str, float] = defaultdict(float)
    rule_deductions: dict[str, float] = defaultdict(float)
    audit: list[dict[str, Any]] = []

    # First pass: score missing_object and missing_part issues against object budgets
    missing_applied_total = 0.0
    missing_issue_ids: set[str] = set()

    for issue in issues:
        if issue.category not in {"missing_geometry", "missing_object", "missing_part"}:
            continue
        if (
            issue.classification != "primary"
            or issue.confidence not in {"verified", "high"}
            or issue.status == "rejected"
        ):
            continue
        missing_issue_ids.add(issue.id)
        oid = issue.parent_object_id
        if issue.code == "MISSING_OBJECT" and oid and oid in obj_budgets:
            raw = obj_budgets[oid]
            applied_rule = "OBJECT-BUDGET-MISSING"
        else:
            raw = float(rubric.missing_part_deduction)
            applied_rule = "PART-BUDGET-MISSING"

        issue.deduction = round(raw, 2)
        issue.rubric_rule_id = applied_rule
        issue.score_category = "completion"
        issue.suppression_reason = None

        avail_content = max(0.0, w_content - missing_applied_total)
        avail_obj = (
            obj_remaining.get(oid, avail_content)
            if oid and oid in obj_remaining
            else avail_content
        )
        applied = min(raw, avail_obj, avail_content)
        if oid and oid in obj_remaining:
            obj_remaining[oid] = max(0.0, obj_remaining[oid] - applied)
        missing_applied_total += applied

        issue.applied_deduction = round(applied, 2)
        cap_reasons = []
        if applied < raw - 1e-6:
            if oid and avail_obj < raw - 1e-6:
                cap_reasons.append("object_budget_cap")
            else:
                cap_reasons.append("category_cap")
        cap_reason = ",".join(cap_reasons) or None
        if applied == 0 and raw > 0:
            deduction_status = "capped"
        elif applied < raw - 1e-6:
            deduction_status = "partially_applied"
        elif applied > 0:
            deduction_status = "applied"
        else:
            deduction_status = "informational"

        comp_share = (
            round(applied * (w_comp / w_content), 4) if w_content > 0 else applied
        )
        geom_share = round(applied - comp_share, 4)

        cat_split = {
            "geometry": geom_share,
            "completion": comp_share,
        }
        score_cats = (
            ["geometry", "completion"] if (w_geom > 0 and geom_share > 0)
            else ["completion"]
        )
        is_formative = getattr(rubric, "assessment_mode", None) == "formative"
        if not is_formative and geom_share > 0 and comp_share > 0:
            issue.score_category = f"Geometry ({geom_share:g}) + Completion ({comp_share:g})"
            issue.technical_feedback = (
                f"{issue.technical_feedback} "
                f"Combined deduction {applied:g} marks: Geometry -{geom_share:g}, Completion -{comp_share:g}."
            )
        elif is_formative:
            issue.score_category = "not_scored"
        elif geom_share > 0:
            issue.score_category = "geometry"
        else:
            issue.score_category = "completion"

        audit.append(
            _audit_entry(
                issue,
                applied_rule=applied_rule,
                raw_deduction=raw,
                after_rule_cap=raw,
                after_category_cap=applied,
                cap_reason=cap_reason,
                deduction_status=deduction_status,
                score_categories=score_cats,
                category_split=cat_split,
            )
        )

    # Split total missing deduction across completion and geometry in exact W_comp : W_geom ratio
    if w_content > 0 and missing_applied_total > 0:
        comp_missing_ded = round(missing_applied_total * (w_comp / w_content), 2)
        geom_missing_ded = round(missing_applied_total - comp_missing_ded, 2)
    else:
        comp_missing_ded = round(min(w_comp, missing_applied_total), 2)
        geom_missing_ded = 0.0

    category_deductions["completion"] = comp_missing_ded
    category_deductions["geometry"] = geom_missing_ded

    # Second pass: score all other issues (geometry defects, quality issues, suppressed/derived)
    for issue in issues:
        if issue.id in missing_issue_ids:
            continue
        pair = rules.get(issue.category)
        if pair is None and issue.category == "endpoint_gap":
            fallback_pair = rules.get("open_polyline") or rules.get("incorrect_position")
            if fallback_pair is not None:
                pair = (fallback_pair[0], geometry_category or fallback_pair[1])
        rule = pair[0] if pair else None
        category = pair[1] if pair else None
        raw = float(
            issue.deduction
            if issue.category == "global_drawing_displacement" and rule
            else rule.deduction
            if rule
            else issue.deduction
        )
        issue.deduction = round(raw, 2)
        issue.rubric_rule_id = rule.id if rule else None
        issue.score_category = category.id if category else None

        suppression_reason = None
        if issue.classification != "primary":
            suppression_reason = f"{issue.classification} findings are not scored"
        elif (
            issue.confidence not in {"verified", "high"}
            or issue.status == "rejected"
        ):
            suppression_reason = "requires instructor confirmation"
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

        rule_limit = (
            rule.repeat_cap if rule.repeat_cap is not None else float("inf")
        )
        remaining_rule = max(0.0, rule_limit - rule_deductions[rule.id])
        after_rule_cap = min(raw, remaining_rule)

        oid = issue.parent_object_id
        if category.id == "geometry" and oid and oid in obj_remaining:
            after_obj_cap = min(after_rule_cap, obj_remaining[oid])
        else:
            after_obj_cap = after_rule_cap

        category_limit = (
            category.max_deduction
            if category.max_deduction is not None
            else category.weight
        )
        remaining_category = max(
            0.0, category_limit - category_deductions[category.id]
        )
        after_category_cap = min(after_obj_cap, remaining_category)

        if category.id == "geometry" and oid and oid in obj_remaining:
            obj_remaining[oid] = max(
                0.0, obj_remaining[oid] - after_category_cap
            )
        rule_deductions[rule.id] += after_category_cap
        category_deductions[category.id] += after_category_cap
        issue.applied_deduction = round(after_category_cap, 2)

        cap_reasons = []
        if after_rule_cap < raw - 1e-6:
            cap_reasons.append("rule_repeat_cap")
        if after_obj_cap < after_rule_cap - 1e-6:
            cap_reasons.append("object_budget_cap")
        if after_category_cap < after_obj_cap - 1e-6:
            cap_reasons.append("category_cap")
        cap_reason = ",".join(cap_reasons) or None
        if after_category_cap == 0 and raw > 0:
            deduction_status = "capped"
        elif after_category_cap < raw - 1e-6:
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
                after_category_cap=after_category_cap,
                cap_reason=cap_reason,
                deduction_status=deduction_status,
            )
        )

    audit.append(
        {
            "issue_id": None,
            "primary_issue_id": None,
            "category": "completion",
            "finding_category": "object_part_budget_policy",
            "score_category": "completion",
            "classification": "informational",
            "rule_id": "OBJECT-PART-BUDGET",
            "applied_rule": "OBJECT-PART-BUDGET",
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
                    "property": "object_part_budget_split",
                    "completion_percentage": completion_percentage,
                    "missing_part_deduction": rubric.missing_part_deduction,
                    "geometry_missing_deduction": geom_missing_ded,
                    "completion_missing_deduction": comp_missing_ded,
                    "object_budgets": {
                        k: round(v, 4) for k, v in obj_budgets.items()
                    },
                }
            ],
            "suppressed_findings": [],
            "suppression_reason": None,
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

    for cat in rubric.categories:
        category_deductions.setdefault(cat.id, 0.0)

    deduction = round(sum(category_deductions.values()), 2)
    score = max(0.0, round(100.0 - deduction, 2))
    breakdown = _category_breakdown(rubric, category_deductions, audit)
    visible_applied = round(
        sum(float(entry["final_applied_contribution"]) for entry in audit), 2
    )
    if abs(visible_applied - deduction) > 0.01:
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
            "missing_part_deduction": rubric.missing_part_deduction,
            "construction_requirement": rubric.construction_requirement,
            "issues": [
                entry
                for entry in audit
                if entry.get("primary_issue_id") is not None
            ],
            "suppressed_findings": [
                entry
                for entry in audit
                if entry["classification"] == "suppressed"
            ],
            "category_subtotals": breakdown,
            "total_applied_deduction": deduction,
            "final_score": score,
            "unrounded_final_score": max(0.0, 100.0 - deduction),
        },
    }


def score_issues(
    issues: list[Issue],
    rubric: Rubric,
    completion_percentage: float,
    suppressed_findings: list[dict[str, Any]],
    canonical_match: Any = None,
) -> dict[str, Any]:
    """Apply visible rubric deductions after causal consolidation."""
    if rubric.completion_scoring_mode == "object_part_deduction":
        return _score_object_part_deduction(
            issues,
            rubric,
            completion_percentage,
            suppressed_findings,
            canonical_match,
        )

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
            else rule.deduction
            if rule
            else 0.0
        )
        issue.deduction = raw
        issue.rubric_rule_id = rule.id if rule else None
        issue.score_category = category.id if category else None

        suppression_reason = None
        if issue.classification != "primary":
            suppression_reason = f"{issue.classification} findings are not scored"
        elif (
            issue.confidence not in {"verified", "high"}
            or issue.status == "rejected"
        ):
            suppression_reason = "requires instructor confirmation"
        elif (
            issue.category == "missing_geometry"
            and rubric.completion_scoring_mode == "proportional"
        ):
            suppression_reason = (
                "fixed missing deduction suppressed by proportional completion policy"
            )
        elif (
            rubric.rubric_version == "2.0"
            and rubric.completion_scoring_mode == "proportional"
            and category
            and category.id == "geometry"
            and issue.category != "global_drawing_displacement"
        ):
            suppression_reason = (
                "fixed geometry deduction superseded by canonical proportional accuracy scoring"
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

        rule_limit = (
            rule.repeat_cap if rule.repeat_cap is not None else float("inf")
        )
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
    geometry_category = next(
        (category for category in rubric.categories if category.id == "geometry"),
        None,
    )
    if rubric.completion_scoring_mode == "proportional":
        if rubric.rubric_version == "2.0":
            comp_frac = (
                getattr(canonical_match, "completion_fraction", None)
                if canonical_match is not None
                else completion_percentage / 100.0
            )
            if comp_frac is None:
                comp_frac = completion_percentage / 100.0
            acc_frac = (
                getattr(canonical_match, "accuracy_fraction", None)
                if canonical_match is not None
                else comp_frac
            )
            if acc_frac is None:
                acc_frac = comp_frac

            raw_completion = (
                completion_category.weight
                - comp_frac * completion_category.weight
            )
            raw_accuracy = (
                geometry_category.weight - acc_frac * geometry_category.weight
                if geometry_category is not None
                else 0.0
            )
            completion_limit = completion_category.weight
        else:
            raw_completion = round(
                (100.0 - completion_percentage)
                / 100.0
                * completion_category.weight,
                2,
            )
            raw_accuracy = 0.0
            completion_limit = (
                completion_category.max_deduction
                if completion_category.max_deduction is not None
                else completion_category.weight
            )

        remaining_completion = max(
            0.0, completion_limit - category_deductions["completion"]
        )
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
                    "category_cap"
                    if completion_applied < raw_completion
                    else None
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

        if rubric.rubric_version == "2.0" and geometry_category is not None:
            geom_limit = geometry_category.weight
            remaining_geom = max(
                0.0, geom_limit - category_deductions["geometry"]
            )
            geom_applied = min(raw_accuracy, remaining_geom)
            category_deductions["geometry"] += geom_applied
            audit.append(
                {
                    "issue_id": None,
                    "primary_issue_id": None,
                    "category": "geometry",
                    "finding_category": "proportional_accuracy",
                    "score_category": "geometry",
                    "classification": "primary",
                    "rule_id": "ACCURACY-PROPORTIONAL",
                    "applied_rule": "ACCURACY-PROPORTIONAL",
                    "requested": raw_accuracy,
                    "raw_deduction": raw_accuracy,
                    "deduction_after_rule_cap": raw_accuracy,
                    "deduction_after_category_cap": geom_applied,
                    "final_applied_contribution": geom_applied,
                    "applied": geom_applied,
                    "deduction_status": (
                        "applied" if geom_applied else "informational"
                    ),
                    "cap_reason": (
                        "category_cap"
                        if geom_applied < raw_accuracy
                        else None
                    ),
                    "derived_observations": [],
                    "supporting_evidence": [
                        {
                            "property": "accuracy_fraction",
                            "expected": 1.0,
                            "actual": acc_frac,
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

    if rubric.rubric_version == "2.0":
        category_deductions = {
            cat_id: fsum(
                float(entry["final_applied_contribution"])
                for entry in audit
                if entry.get("score_category") == cat_id
            )
            for cat_id in {c.id for c in rubric.categories}
        }
        deduction = round(fsum(category_deductions.values()), 2)
        score = max(0.0, round(100.0 - deduction, 2))
    else:
        deduction = round(sum(category_deductions.values()), 2)
        score = max(0.0, round(100.0 - deduction, 1))

    breakdown = _category_breakdown(rubric, category_deductions, audit)
    visible_applied = round(
        sum(float(entry["final_applied_contribution"]) for entry in audit), 2
    )
    if abs(visible_applied - deduction) > 0.01:
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
                entry
                for entry in audit
                if entry.get("primary_issue_id") is not None
            ],
            "suppressed_findings": [
                entry
                for entry in audit
                if entry["classification"] == "suppressed"
            ],
            "category_subtotals": breakdown,
            "total_applied_deduction": deduction,
            "final_score": score,
            "unrounded_final_score": max(0.0, 100.0 - deduction),
        },
    }
