from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from .models import Drawing
from .scale_diagnostics import ScaleDiagnostic


CompatibilityStatus = Literal[
    "compatible", "suspicious", "incompatible", "empty_or_ungradable"
]


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatibility_status: CompatibilityStatus
    compatibility_confidence: str
    compatibility_reason_codes: tuple[str, ...]
    reference_supported_entity_count: int
    student_supported_entity_count: int
    confident_match_count: int
    reference_match_coverage: float
    student_match_coverage: float
    unmatched_reference_count: int
    unmatched_student_count: int
    entity_type_overlap: float
    accepted_transform: bool
    estimated_uniform_scale: float | None
    scale_confidence: str
    instructor_override: bool

    @property
    def grading_withheld(self) -> bool:
        return (
            self.compatibility_status
            in {"suspicious", "incompatible", "empty_or_ungradable"}
            and not self.instructor_override
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }
        payload["compatibility_reason_codes"] = list(
            self.compatibility_reason_codes
        )
        payload["grading_withheld"] = self.grading_withheld
        return payload


def _type_overlap(reference: Drawing, student: Drawing) -> float:
    reference_counts = Counter(entity.kind for entity in reference.entities)
    student_counts = Counter(entity.kind for entity in student.entities)
    kinds = set(reference_counts) | set(student_counts)
    denominator = sum(
        max(reference_counts[kind], student_counts[kind]) for kind in kinds
    )
    if denominator == 0:
        return 0.0
    return sum(
        min(reference_counts[kind], student_counts[kind]) for kind in kinds
    ) / denominator


def assess_compatibility(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
    scale: ScaleDiagnostic,
    *,
    instructor_override: bool = False,
) -> CompatibilityResult:
    """Classify assignment compatibility from several independent signals."""

    reference_count = len(reference.entities)
    student_count = len(student.entities)
    matches = comparison.get("matches", [])
    confident = sum(float(match.get("confidence", 0.0)) >= 0.75 for match in matches)
    reference_coverage = confident / max(reference_count, 1)
    student_coverage = confident / max(student_count, 1)
    overlap = _type_overlap(reference, student)
    normalization = comparison.get("normalization", {}).get("student", {})
    translation = normalization.get("translation") or [0.0, 0.0]
    accepted_transform = any(abs(float(value)) > 1e-9 for value in translation)
    reasons: list[str] = []

    if student_count == 0:
        status: CompatibilityStatus = "empty_or_ungradable"
        confidence = "verified"
        reasons.append(
            "only_unsupported_entities"
            if student.unsupported_entities
            else "no_supported_student_geometry"
        )
    elif scale.detected_scale_mismatch:
        status = "suspicious"
        confidence = scale.scale_confidence
        reasons.extend(("strong_scale_invariant_correspondence", "global_scale_mismatch"))
    elif confident > 0 or accepted_transform:
        status = "compatible"
        confidence = "verified" if reference_coverage >= 0.5 else "high"
        reasons.append("confident_reference_correspondence")
        if accepted_transform:
            reasons.append("accepted_whole_drawing_translation")
    else:
        almost_all_reference_unmatched = reference_coverage < 0.02
        almost_all_student_unmatched = student_coverage < 0.10
        weak_type_overlap = overlap < 0.10
        severe_count_mismatch = min(reference_count, student_count) / max(
            reference_count, student_count, 1
        ) < 0.10
        if (
            almost_all_reference_unmatched
            and almost_all_student_unmatched
            and (weak_type_overlap or severe_count_mismatch)
        ):
            status = "incompatible"
            confidence = "high"
            reasons.extend(
                (
                    "no_confident_correspondence",
                    "almost_all_reference_geometry_unmatched",
                    "almost_all_student_geometry_unmatched",
                )
            )
            reasons.append(
                "incompatible_entity_type_distribution"
                if weak_type_overlap
                else "severe_supported_entity_count_mismatch"
            )
        else:
            status = "suspicious"
            confidence = "moderate"
            reasons.append("insufficient_confident_correspondence")

    return CompatibilityResult(
        compatibility_status=status,
        compatibility_confidence=confidence,
        compatibility_reason_codes=tuple(reasons),
        reference_supported_entity_count=reference_count,
        student_supported_entity_count=student_count,
        confident_match_count=confident,
        reference_match_coverage=round(reference_coverage, 6),
        student_match_coverage=round(student_coverage, 6),
        unmatched_reference_count=max(0, reference_count - confident),
        unmatched_student_count=max(0, student_count - confident),
        entity_type_overlap=round(overlap, 6),
        accepted_transform=accepted_transform,
        estimated_uniform_scale=scale.estimated_scale_factor,
        scale_confidence=scale.scale_confidence,
        instructor_override=bool(instructor_override),
    )
