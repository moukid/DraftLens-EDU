from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .analysis import analyze_assignment
from .compare import compare_drawings
from .dxf import parse_dxf_bytes
from .models import Drawing
from .reviewed_dxf import ReviewedDrawing, build_reviewed_drawing
from .rubric import Rubric, ToleranceProfile, default_rubric
from .svg_renderer import render_svg
from .validator import validate_reference


class PipelineContractError(ValueError):
    """Stable client-facing pipeline rejection with an HTTP status."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class GradingPipelineOutput:
    reference_id: str
    rubric_id: str | None
    rubric_source: str
    rubric: Rubric
    reference: Drawing
    student: Drawing
    validation: dict[str, Any]
    analysis: dict[str, Any]
    comparison: dict[str, Any]

    @property
    def rubric_selection(self) -> dict[str, str | None]:
        return {"rubric_id": self.rubric_id, "source": self.rubric_source}


def reference_fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_grading_pipeline(
    reference_bytes: bytes,
    student_bytes: bytes,
    *,
    rubric_id: str | None,
    allow_fallback: bool,
    position_tolerance: float,
    length_tolerance: float,
    angle_tolerance: float,
    dimension_tolerance: float,
    radius_tolerance: float,
    rubrics: Mapping[str, Rubric],
    reference_rubrics: Mapping[str, str],
    rubric_references: Mapping[str, str],
) -> GradingPipelineOutput:
    """Run the shared deterministic selection, parsing, validation, and grading path."""

    reference_id = reference_fingerprint(reference_bytes)
    selected_id = rubric_id or reference_rubrics.get(reference_id)
    if selected_id:
        selected_rubric = rubrics.get(selected_id)
        if selected_rubric is None or not selected_rubric.approved:
            raise PipelineContractError(409, "The selected rubric does not exist or is not approved.")
        if rubric_references.get(selected_id) != reference_id:
            raise PipelineContractError(409, "The selected rubric is not associated with this reference drawing.")
        rubric_source = "explicit_approved" if rubric_id else "associated_approved"
    elif allow_fallback:
        selected_rubric = default_rubric("Explicit 65/25/10 fallback").model_copy(update={"approved": True})
        selected_rubric.tolerances = ToleranceProfile(
            position=position_tolerance,
            length=length_tolerance,
            angle=angle_tolerance,
            radius=radius_tolerance,
            dimension=dimension_tolerance,
            vertex=position_tolerance,
        )
        rubric_source = "explicit_fallback"
    else:
        raise PipelineContractError(
            409,
            "No approved rubric is associated with this reference. Approve a rubric or explicitly enable fallback mode.",
        )
    if selected_rubric.normalization_mode not in {"strict", "translation"}:
        raise PipelineContractError(
            422,
            f"Normalization mode '{selected_rubric.normalization_mode}' is not implemented in V1 foundation grading.",
        )
    normalize = selected_rubric.normalization_mode == "translation"
    reference = parse_dxf_bytes(reference_bytes, source="reference", normalize=normalize)
    student = parse_dxf_bytes(student_bytes, source="student", normalize=normalize)
    validation = validate_reference(reference)
    assignment_analysis = analyze_assignment(reference)
    comparison = compare_drawings(reference, student, rubric=selected_rubric)
    return GradingPipelineOutput(
        reference_id=reference_id,
        rubric_id=selected_id,
        rubric_source=rubric_source,
        rubric=selected_rubric,
        reference=reference,
        student=student,
        validation=validation,
        analysis=assignment_analysis,
        comparison=comparison,
    )


VISUAL_ROLE_CLASSES: dict[str, tuple[str, ...]] = {
    "missing": ("missing",),
    "extra": ("extra",),
    "inaccurate": ("inaccurate-expected", "inaccurate-actual"),
    "connectivity": ("connectivity",),
    "warning": ("warning",),
    "critical": ("critical",),
}


def _issue_payload(reviewed: ReviewedDrawing) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for issue in reviewed.issues:
        payload = issue.to_dict()
        payload["css_classes"] = list(VISUAL_ROLE_CLASSES[issue.visual_role])
        payload["finding_role"] = _finding_role(payload)
        issues.append(payload)
    return issues


def _finding_role(issue: Mapping[str, Any]) -> str:
    if issue.get("category") == "unsupported_entity":
        return "unsupported"
    if issue.get("provenance") == "reference_validation":
        return "reference"
    if issue.get("provenance") == "comparison" and issue.get("classification") == "primary":
        return "primary"
    if issue.get("provenance") == "comparison" and issue.get("classification") in {
        "supporting_evidence",
        "derived",
        "suppressed",
    }:
        return "supporting"
    return "informational"


def _finding_counts(
    issues: list[dict[str, Any]], reviewed: ReviewedDrawing
) -> dict[str, int]:
    return {
        "primary_student_issues": sum(
            issue["finding_role"] == "primary" for issue in issues
        ),
        "supporting_findings": sum(
            issue["finding_role"] == "supporting" for issue in issues
        ),
        "reference_validation_notes": sum(
            issue["finding_role"] == "reference" for issue in issues
        ),
        "unsupported_entities": len(reviewed.reference_unsupported)
        + len(reviewed.student_unsupported),
    }


def normalization_decision(output: GradingPipelineOutput) -> dict[str, Any]:
    """Expose the recorded normalization decision without changing its calculation."""

    requested_mode = output.rubric.normalization_mode
    record = output.comparison["normalization"]["student"]
    if requested_mode == "strict":
        return {
            "requested_mode": "strict",
            "applied_mode": "strict",
            "transform_applied": False,
            "selected_translation": [0.0, 0.0],
            "candidate_translation": None,
            "support_count": 0,
            "evidence_count": 0,
            "support_ratio": 0.0,
            "confidence": "not_applicable",
            "error_before": None,
            "error_after": None,
            "total_error_reduction": None,
            "error_reduction_ratio": None,
            "rejection_reason": None,
        }

    selected = list(record.get("translation") or [0.0, 0.0])
    error_before = float(record.get("error_before") or 0.0)
    error_after = float(record.get("error_after") or 0.0)
    return {
        "requested_mode": requested_mode,
        "applied_mode": str(record.get("mode") or requested_mode),
        "transform_applied": any(abs(float(value)) > 1e-9 for value in selected),
        "selected_translation": selected,
        "candidate_translation": list(
            record.get("candidate_translation") or [0.0, 0.0]
        ),
        "support_count": int(record.get("support_count") or 0),
        "evidence_count": int(record.get("evidence_count") or 0),
        "support_ratio": float(record.get("support_ratio") or 0.0),
        "confidence": str(record.get("confidence") or "none"),
        "error_before": error_before,
        "error_after": error_after,
        "total_error_reduction": round(max(0.0, error_before - error_after), 6),
        "error_reduction_ratio": float(record.get("error_reduction_ratio") or 0.0),
        "rejection_reason": record.get("rejection_reason"),
    }


def build_review_response(output: GradingPipelineOutput) -> dict[str, Any]:
    """Build the stable JSON/SVG contract after successful deterministic grading."""

    reviewed = build_reviewed_drawing(
        output.reference,
        output.student,
        output.comparison,
        output.validation,
    )
    issues = _issue_payload(reviewed)
    finding_counts = _finding_counts(issues, reviewed)
    return {
        "score": output.comparison["score"],
        "reference_id": output.reference_id,
        "rubric_selection": output.rubric_selection,
        "rubric": output.rubric.model_dump(),
        "suggested_assignment_type": output.analysis["suggested_assignment_type"],
        "assignment_type": output.rubric.assignment_type,
        "detected_features": output.analysis["detected_features"],
        "completion_scoring_mode": output.rubric.completion_scoring_mode,
        "normalization_mode": output.rubric.normalization_mode,
        "normalization_decision": normalization_decision(output),
        "units": reviewed.units,
        "extents": list(reviewed.extents),
        "issues": issues,
        "finding_counts": finding_counts,
        "student_issue_count": finding_counts["primary_student_issues"],
        "supporting_finding_count": finding_counts["supporting_findings"],
        "reference_note_count": finding_counts["reference_validation_notes"],
        "unsupported_entity_count": finding_counts["unsupported_entities"],
        "score_breakdown": output.comparison["score_breakdown"],
        "unsupported_entities": {
            "reference": reviewed.reference_unsupported,
            "student": reviewed.student_unsupported,
        },
        "technical_feedback": [
            {"issue_id": issue["issue_id"], "feedback": issue["technical_feedback"]}
            for issue in issues
        ],
        "validation": {
            "valid": output.validation["valid"],
            "can_continue": output.validation["can_continue"],
            "requires_acknowledgement": output.validation["requires_acknowledgement"],
            "summary": output.validation["summary"],
        },
        "svg": render_svg(reviewed),
    }
