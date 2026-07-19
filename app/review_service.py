from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

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
    comparison = compare_drawings(reference, student, rubric=selected_rubric)
    return GradingPipelineOutput(
        reference_id=reference_id,
        rubric_id=selected_id,
        rubric_source=rubric_source,
        rubric=selected_rubric,
        reference=reference,
        student=student,
        validation=validation,
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
        issues.append(payload)
    return issues


def build_review_response(output: GradingPipelineOutput) -> dict[str, Any]:
    """Build the stable JSON/SVG contract after successful deterministic grading."""

    reviewed = build_reviewed_drawing(
        output.reference,
        output.student,
        output.comparison,
        output.validation,
    )
    issues = _issue_payload(reviewed)
    return {
        "score": output.comparison["score"],
        "reference_id": output.reference_id,
        "rubric_selection": output.rubric_selection,
        "rubric": output.rubric.model_dump(),
        "completion_scoring_mode": output.rubric.completion_scoring_mode,
        "units": reviewed.units,
        "extents": list(reviewed.extents),
        "issues": issues,
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
