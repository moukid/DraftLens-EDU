from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Literal

from .models import Drawing
from .scale_diagnostics import ScaleDiagnostic


CompatibilityStatus = Literal[
    "compatible", "suspicious", "incompatible", "empty_or_ungradable"
]


# Compatibility needs stronger evidence than one plausible intrinsic match.
# These conservative thresholds mirror the existing translation requirements,
# while allowing one correctly placed entity to protect legitimate partial work.
CONFIDENT_MATCH_THRESHOLD = 0.75
EXACT_MATCH_THRESHOLD = 0.9995
MIN_TRANSLATION_COHERENCE_SUPPORT = 3
MIN_TRANSLATION_COHERENCE_RATIO = 0.60
MIN_COHERENT_REFERENCE_COVERAGE = 0.05
MIN_COHERENT_STUDENT_COVERAGE = 0.35
MIN_PARTIAL_STUDENT_COVERAGE = 0.50
MIN_SUBSTANTIAL_CORRESPONDENCE_COVERAGE = 0.80
UNMATCHED_GEOMETRY_DOMINANCE = 0.60
COHERENCE_SCALE_FLOOR_RATIO = 1e-6
GEOMETRY_PRECISION = 6


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatibility_status: CompatibilityStatus
    compatibility_confidence: str
    compatibility_reason_codes: tuple[str, ...]
    reference_supported_entity_count: int
    student_supported_entity_count: int
    confident_match_count: int
    exact_match_count: int
    approximate_match_count: int
    reference_match_coverage: float
    student_match_coverage: float
    coherent_match_count: int
    incoherent_match_count: int
    coherent_reference_coverage: float
    coherent_student_coverage: float
    displacement_consensus_vector: tuple[float, float] | None
    displacement_consensus_support: int
    displacement_consensus_ratio: float
    displacement_residual_median: float | None
    spatial_coherence_status: str
    spatial_coherence_reason_codes: tuple[str, ...]
    unmatched_geometry_ratio: float
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
        payload["spatial_coherence_reason_codes"] = list(
            self.spatial_coherence_reason_codes
        )
        if self.displacement_consensus_vector is not None:
            payload["displacement_consensus_vector"] = list(
                self.displacement_consensus_vector
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


def _center(entity: Any) -> tuple[float, float]:
    if entity.centroid is not None:
        return float(entity.centroid[0]), float(entity.centroid[1])
    if entity.points:
        return float(entity.points[0][0]), float(entity.points[0][1])
    return 0.0, 0.0


def _drawing_diagonal(drawing: Drawing) -> float:
    return math.hypot(
        float(drawing.bbox[2]) - float(drawing.bbox[0]),
        float(drawing.bbox[3]) - float(drawing.bbox[1]),
    )


def _coherence_tolerance(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
) -> float:
    position = float((comparison.get("tolerances") or {}).get("position") or 0.0)
    precision_floor = max(
        _drawing_diagonal(reference), _drawing_diagonal(student), 1.0
    ) * COHERENCE_SCALE_FLOOR_RATIO
    return max(position, precision_floor, 1e-9)


def _dominant_displacement(
    displacements: list[tuple[float, float]], tolerance: float
) -> tuple[tuple[float, float] | None, int, float, float | None]:
    if not displacements:
        return None, 0, 0.0, None

    candidates = []
    for seed in sorted(set(displacements)):
        preliminary = [
            displacement
            for displacement in displacements
            if math.dist(displacement, seed) <= tolerance
        ]
        candidate = (
            float(median(item[0] for item in preliminary)),
            float(median(item[1] for item in preliminary)),
        )
        residuals = [
            math.dist(displacement, candidate)
            for displacement in displacements
            if math.dist(displacement, candidate) <= tolerance
        ]
        residual_median = float(median(residuals)) if residuals else math.inf
        candidates.append(
            (
                -len(residuals),
                round(residual_median, GEOMETRY_PRECISION),
                round(candidate[0], GEOMETRY_PRECISION),
                round(candidate[1], GEOMETRY_PRECISION),
            )
        )
    negative_support, residual, dx, dy = min(candidates)
    support = -negative_support
    return (
        (float(dx), float(dy)),
        support,
        support / len(displacements),
        float(residual),
    )


def _spatial_evidence(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    reference_by_id = {entity.id: entity for entity in reference.entities}
    student_by_id = {entity.id: entity for entity in student.entities}
    confident_matches = [
        match
        for match in comparison.get("matches", [])
        if float(match.get("confidence", 0.0)) >= CONFIDENT_MATCH_THRESHOLD
    ]
    exact_count = sum(
        float(match.get("confidence", 0.0)) >= EXACT_MATCH_THRESHOLD
        for match in confident_matches
    )
    displacements: list[tuple[float, float]] = []
    for match in confident_matches:
        reference_entity = reference_by_id.get(match.get("reference_entity_id"))
        student_entity = student_by_id.get(match.get("student_entity_id"))
        if reference_entity is None or student_entity is None:
            continue
        reference_point = _center(reference_entity)
        student_point = _center(student_entity)
        displacements.append(
            (
                student_point[0] - reference_point[0],
                student_point[1] - reference_point[1],
            )
        )

    tolerance = _coherence_tolerance(reference, student, comparison)
    vector, support, ratio, residual = _dominant_displacement(
        displacements, tolerance
    )
    reference_coverage = support / max(len(reference.entities), 1)
    student_coverage = support / max(len(student.entities), 1)
    identity = bool(
        vector is not None
        and math.dist(vector, (0.0, 0.0)) <= tolerance
        and support >= 1
        and student_coverage >= MIN_PARTIAL_STUDENT_COVERAGE
    )
    translation = bool(
        vector is not None
        and support >= MIN_TRANSLATION_COHERENCE_SUPPORT
        and ratio >= MIN_TRANSLATION_COHERENCE_RATIO
        and student_coverage >= MIN_PARTIAL_STUDENT_COVERAGE
    )
    partial_translation = bool(
        vector is not None
        and support >= 2
        and ratio >= 0.90
        and student_coverage >= MIN_PARTIAL_STUDENT_COVERAGE
    )
    if identity:
        status = "coherent_identity"
        reason_codes = ("coherent_identity_correspondence",)
    elif translation:
        status = "coherent_translation"
        reason_codes = ("coherent_translation_correspondence",)
    elif support:
        status = "weak"
        reason_codes = tuple(
            code
            for condition, code in (
                (
                    support < MIN_TRANSLATION_COHERENCE_SUPPORT,
                    "insufficient_displacement_consensus_support",
                ),
                (
                    ratio < MIN_TRANSLATION_COHERENCE_RATIO,
                    "weak_displacement_consensus_ratio",
                ),
                (
                    reference_coverage < MIN_COHERENT_REFERENCE_COVERAGE,
                    "very_low_coherent_reference_coverage",
                ),
                (
                    student_coverage < MIN_COHERENT_STUDENT_COVERAGE,
                    "very_low_coherent_student_coverage",
                ),
            )
            if condition
        ) or ("insufficient_spatial_coherence",)
    else:
        status = "none"
        reason_codes = ("no_spatially_coherent_matches",)

    return {
        "confident_count": len(confident_matches),
        "exact_count": exact_count,
        "approximate_count": len(confident_matches) - exact_count,
        "coherent_count": support,
        "incoherent_count": max(0, len(confident_matches) - support),
        "reference_coverage": reference_coverage,
        "student_coverage": student_coverage,
        "vector": vector,
        "support": support,
        "ratio": ratio,
        "residual_median": residual,
        "status": status,
        "reason_codes": reason_codes,
        "strong": identity or translation,
        "partial_translation_protection": partial_translation,
    }



def assess_compatibility(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
    scale: ScaleDiagnostic,
    *,
    instructor_override: bool = False,
) -> CompatibilityResult:
    """Classify assignment compatibility from coherent existing matches."""

    reference_count = len(reference.entities)
    student_count = len(student.entities)
    spatial = _spatial_evidence(reference, student, comparison)
    confident = spatial["confident_count"]
    reference_coverage = confident / max(reference_count, 1)
    student_coverage = confident / max(student_count, 1)
    coherent_reference_coverage = spatial["reference_coverage"]
    coherent_student_coverage = spatial["student_coverage"]
    overlap = _type_overlap(reference, student)
    normalization = comparison.get("normalization", {}).get("student", {})
    translation = normalization.get("translation") or [0.0, 0.0]
    accepted_transform = any(abs(float(value)) > 1e-9 for value in translation)
    substantial_object_correspondence = bool(
        reference_coverage >= MIN_SUBSTANTIAL_CORRESPONDENCE_COVERAGE
        and student_coverage >= MIN_SUBSTANTIAL_CORRESPONDENCE_COVERAGE
        and spatial["support"] >= 2
        and spatial["ratio"] >= MIN_TRANSLATION_COHERENCE_RATIO
    )
    unmatched_geometry_ratio = (
        max(0, reference_count - confident) + max(0, student_count - confident)
    ) / max(reference_count + student_count, 1)
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
        reasons.extend(
            ("strong_scale_invariant_correspondence", "global_scale_mismatch")
        )
    elif (
        spatial["strong"]
        or accepted_transform
        or substantial_object_correspondence
    ):
        status = "compatible"
        confidence = "verified" if reference_coverage >= 0.5 else "high"
        reasons.extend(spatial["reason_codes"])
        if substantial_object_correspondence and not spatial["strong"]:
            reasons.append("substantial_object_correspondence")
        if accepted_transform:
            reasons.append("accepted_whole_drawing_translation")
    else:
        weak_consensus = (
            spatial["support"] < MIN_TRANSLATION_COHERENCE_SUPPORT
            or spatial["ratio"] < MIN_TRANSLATION_COHERENCE_RATIO
        )
        low_coherent_evidence = (
            spatial["support"] < MIN_TRANSLATION_COHERENCE_SUPPORT
            or (
                coherent_reference_coverage < MIN_COHERENT_REFERENCE_COVERAGE
                and coherent_student_coverage < MIN_COHERENT_STUDENT_COVERAGE
            )
        )
        unmatched_dominates = (
            unmatched_geometry_ratio >= UNMATCHED_GEOMETRY_DOMINANCE
        )
        if (
            not spatial["partial_translation_protection"]
            and weak_consensus
            and low_coherent_evidence
            and unmatched_dominates
        ):
            status = "incompatible"
            confidence = "high"
            if confident == 0:
                reasons.append("no_confident_correspondence")
            else:
                reasons.append("raw_intrinsic_matches_lack_spatial_coherence")
            reasons.extend(spatial["reason_codes"])
            reasons.append("unmatched_geometry_dominates")
        else:
            status = "suspicious"
            confidence = "moderate"
            reasons.extend(spatial["reason_codes"])
            reasons.append("insufficient_coherent_correspondence")

    effective_override = bool(
        instructor_override and status in {"suspicious", "incompatible"}
    )
    return CompatibilityResult(
        compatibility_status=status,
        compatibility_confidence=confidence,
        compatibility_reason_codes=tuple(reasons),
        reference_supported_entity_count=reference_count,
        student_supported_entity_count=student_count,
        confident_match_count=confident,
        exact_match_count=spatial["exact_count"],
        approximate_match_count=spatial["approximate_count"],
        reference_match_coverage=round(reference_coverage, 6),
        student_match_coverage=round(student_coverage, 6),
        coherent_match_count=spatial["coherent_count"],
        incoherent_match_count=spatial["incoherent_count"],
        coherent_reference_coverage=round(coherent_reference_coverage, 6),
        coherent_student_coverage=round(coherent_student_coverage, 6),
        displacement_consensus_vector=spatial["vector"],
        displacement_consensus_support=spatial["support"],
        displacement_consensus_ratio=round(spatial["ratio"], 6),
        displacement_residual_median=spatial["residual_median"],
        spatial_coherence_status=spatial["status"],
        spatial_coherence_reason_codes=spatial["reason_codes"],
        unmatched_geometry_ratio=round(unmatched_geometry_ratio, 6),
        unmatched_reference_count=max(0, reference_count - confident),
        unmatched_student_count=max(0, student_count - confident),
        entity_type_overlap=round(overlap, 6),
        accepted_transform=accepted_transform,
        estimated_uniform_scale=scale.estimated_scale_factor,
        scale_confidence=scale.scale_confidence,
        instructor_override=effective_override,
    )
