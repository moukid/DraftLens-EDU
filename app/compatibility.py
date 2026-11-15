from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Literal, get_args

from .canonical_geometry import extract_canonical_components
from .models import Drawing
from .rubric import AssignmentType
from .scale_diagnostics import ScaleDiagnostic


SUPPORTED_CANONICAL_ASSIGNMENT_TYPES: frozenset[str] = frozenset(
    set(get_args(AssignmentType)) | {"Geometry only"}
)


CompatibilityStatus = Literal[
    "compatible", "suspicious", "incompatible", "empty_or_ungradable"
]


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
    spatial_evidence_basis: str = "entities"
    geometric_reference_coverage: float | None = None

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


def _type_overlap(
    reference: Drawing, student: Drawing, canonical: bool = False
) -> float:
    def _counts_overlap(ref_c: Counter, stu_c: Counter) -> float:
        kinds = set(ref_c) | set(stu_c)
        denom = sum(max(ref_c[k], stu_c[k]) for k in kinds)
        if denom == 0:
            return 0.0
        return sum(min(ref_c[k], stu_c[k]) for k in kinds) / denom

    entity_overlap = _counts_overlap(
        Counter(entity.kind for entity in reference.entities),
        Counter(entity.kind for entity in student.entities),
    )
    if canonical:
        ref_comps = extract_canonical_components(reference)
        stu_comps = extract_canonical_components(student)
        comp_overlap = _counts_overlap(
            Counter(c.kind for c in ref_comps),
            Counter(c.kind for c in stu_comps),
        )
        return max(entity_overlap, comp_overlap)
    return entity_overlap


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
    position = float(
        (comparison.get("tolerances") or {}).get("position") or 0.0
    )
    precision_floor = (
        max(_drawing_diagonal(reference), _drawing_diagonal(student), 1.0)
        * COHERENCE_SCALE_FLOOR_RATIO
    )
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


def _use_canonical_spatial(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
) -> bool:
    rubric_app = comparison.get("rubric_application") or {}
    rubric_version = (
        comparison.get("rubric_version")
        or rubric_app.get("rubric_version")
        or "1.0"
    )
    assignment_type = (
        comparison.get("assignment_type")
        or rubric_app.get("assignment_type")
    )
    construction_req = (
        comparison.get("construction_requirement")
        or rubric_app.get("construction_requirement")
    )
    completion_mode = (
        comparison.get("completion_scoring_mode")
        or rubric_app.get("completion_scoring_mode")
    )
    canonical_match = comparison.get("canonical_match") or {}
    has_canonical_geometry_controls = bool(
        canonical_match.get("duplicate_student_entities")
        or canonical_match.get("degenerate_student_entities")
    )
    mode = (
        rubric_app.get("normalization_mode")
        or comparison.get("normalization", {}).get("student", {}).get("mode")
        or "strict"
    )
    has_segmented_or_cross_rep = bool(
        any(
            len(cm.get("student_component_ids", [])) > 1
            and float(cm.get("presence", 0.0)) >= 0.85
            for cm in canonical_match.get("component_matches", [])
        )
        or (
            {e.kind for e in reference.entities} != {e.kind for e in student.entities}
            and any(
                e.kind == "polyline"
                for e in list(reference.entities) + list(student.entities)
            )
        )
    )
    has_substantial_canonical = (
        len(canonical_match.get("matched_objects") or []) >= 2
        and float(canonical_match.get("completion_fraction", 0.0)) >= 0.50
    )
    return (
        rubric_version in {"2.0", "2.1"}
        or completion_mode == "object_part_deduction"
        or bool(comparison.get("confirmed_objects"))
        or (
            assignment_type in SUPPORTED_CANONICAL_ASSIGNMENT_TYPES
            and (
                (mode == "translation" and has_substantial_canonical)
                or has_segmented_or_cross_rep
            )
        )
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
    valid_matches: list[dict[str, Any]] = []
    displacements: list[tuple[float, float]] = []
    for match in confident_matches:
        reference_entity = reference_by_id.get(
            match.get("reference_entity_id")
        )
        student_entity = student_by_id.get(match.get("student_entity_id"))
        if reference_entity is None or student_entity is None:
            continue
        reference_point = _center(reference_entity)
        student_point = _center(student_entity)
        valid_matches.append(match)
        displacements.append(
            (
                student_point[0] - reference_point[0],
                student_point[1] - reference_point[1],
            )
        )

    canonical = comparison.get("canonical_match") or {}
    use_canonical = _use_canonical_spatial(reference, student, comparison)
    observations = (
        canonical.get("spatial_correspondences", []) if use_canonical else None
    )
    reference_denominator = len(reference.entities)
    student_denominator = len(student.entities)
    confident_count = len(confident_matches)
    if observations is not None:
        transform = (
            comparison.get("normalization", {})
            .get("student", {})
            .get("translation")
            or [0.0, 0.0]
        )
        displacements = [
            tuple(o["displacement"][j] - transform[j] for j in (0, 1))
            for o in observations
        ]
        confident_count = len(observations)
        exact_count = sum(
            o["correctness"] >= EXACT_MATCH_THRESHOLD for o in observations
        )
        reference_denominator = max(
            len(reference.entities),
            canonical.get("object_summary", {}).get(
                "total_reference_components", 0
            ),
        )
        student_denominator = max(
            len(student.entities),
            canonical.get("object_summary", {}).get(
                "total_student_components", 0
            ),
        )
    tolerance = _coherence_tolerance(reference, student, comparison)
    vector, support, ratio, residual = _dominant_displacement(
        displacements, tolerance
    )
    if observations is not None:
        obs_inliers = [
            o for o, d in zip(observations, displacements)
            if vector is not None and math.dist(d, vector) <= tolerance
        ]
        coherent_ref_ids = {o["reference_component_id"] for o in obs_inliers}
        coherent_student_ids = {
            sid for o in obs_inliers for sid in o["student_component_ids"]
        }
        reference_coverage = len(coherent_ref_ids) / max(reference_denominator, 1)
        student_coverage = len(coherent_student_ids) / max(student_denominator, 1)
    else:
        inliers = [
            m for m, d in zip(valid_matches, displacements)
            if vector is not None and math.dist(d, vector) <= tolerance
        ]
        coherent_ref_ids = {
            m.get("reference_entity_id")
            for m in inliers
            if m.get("reference_entity_id")
        }
        coherent_stu_ids = {
            m.get("student_entity_id")
            for m in inliers
            if m.get("student_entity_id")
        }
        reference_coverage = len(coherent_ref_ids) / max(reference_denominator, 1)
        student_coverage = len(coherent_stu_ids) / max(student_denominator, 1)
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
    rubric_app = comparison.get("rubric_application", {})
    mode = (
        rubric_app.get("normalization_mode")
        or comparison.get("normalization", {}).get("student", {}).get("mode")
        or "strict"
    )
    rubric_source = rubric_app.get("rubric_source")
    matched_objects = canonical.get("matched_objects", [])

    clusters: list[list[int]] = []
    for i, d in enumerate(displacements):
        assigned = False
        for c in clusters:
            if math.dist(d, displacements[c[0]]) <= tolerance:
                c.append(i)
                assigned = True
                break
        if not assigned:
            clusters.append([i])

    min_cluster_size = 2 if (mode == "translation" and len(matched_objects) >= 2) else 3
    significant_clusters = [c for c in clusters if len(c) >= min_cluster_size]
    sig_indices = [idx for c in significant_clusters for idx in c]

    if observations is not None:
        multi_ref_ids = {observations[i]["reference_component_id"] for i in sig_indices}
        multi_stu_ids = {sid for i in sig_indices for sid in observations[i]["student_component_ids"]}
    else:
        multi_ref_ids = {valid_matches[i].get("reference_entity_id") for i in sig_indices if valid_matches[i].get("reference_entity_id")}
        multi_stu_ids = {valid_matches[i].get("student_entity_id") for i in sig_indices if valid_matches[i].get("student_entity_id")}

    multi_cluster_support = len(sig_indices)
    multi_cluster_ratio = multi_cluster_support / max(len(displacements), 1)
    multi_ref_coverage = len(multi_ref_ids) / max(reference_denominator, 1)
    multi_stu_coverage = len(multi_stu_ids) / max(student_denominator, 1)
    multi_cluster_coherent = bool(
        mode == "translation"
        and rubric_source != "explicit_fallback"
        and len(significant_clusters) >= 2
        and multi_cluster_ratio >= 0.50
        and (multi_ref_coverage >= 0.20 or multi_stu_coverage >= 0.20)
    )

    if identity:
        status = "coherent_identity"
        reason_codes = ("coherent_identity_correspondence",)
    elif translation:
        status = "coherent_translation"
        reason_codes = ("coherent_translation_correspondence",)
    elif multi_cluster_coherent:
        status = "coherent_translation"
        reason_codes = ("multi_cluster_translation_correspondence",)
        support = multi_cluster_support
        ratio = multi_cluster_ratio
        reference_coverage = multi_ref_coverage
        student_coverage = multi_stu_coverage
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
        "confident_count": confident_count,
        "exact_count": exact_count,
        "approximate_count": confident_count - exact_count,
        "coherent_count": support,
        "incoherent_count": max(0, confident_count - support),
        "reference_coverage": reference_coverage,
        "student_coverage": student_coverage,
        "vector": vector,
        "support": support,
        "ratio": ratio,
        "residual_median": residual,
        "status": status,
        "reason_codes": reason_codes,
        "strong": identity or translation or multi_cluster_coherent,
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
    matches = comparison.get("matches", [])
    confident_matches = [
        m
        for m in matches
        if float(m.get("confidence", 0.0)) >= CONFIDENT_MATCH_THRESHOLD
    ]
    matched_ref_ids = {
        m.get("reference_entity_id")
        for m in confident_matches
        if m.get("reference_entity_id")
    }
    matched_stu_ids = {
        m.get("student_entity_id")
        for m in confident_matches
        if m.get("student_entity_id")
    }
    use_canonical = _use_canonical_spatial(reference, student, comparison)
    reference_coverage = min(1.0, len(matched_ref_ids) / max(reference_count, 1))
    student_coverage = min(1.0, len(matched_stu_ids) / max(student_count, 1))
    coherent_reference_coverage = min(1.0, spatial["reference_coverage"])
    coherent_student_coverage = min(1.0, spatial["student_coverage"])
    overlap = _type_overlap(reference, student, canonical=use_canonical)
    normalization = comparison.get("normalization", {}).get("student", {})
    translation = normalization.get("translation") or [0.0, 0.0]
    accepted_transform = any(abs(float(value)) > 1e-9 for value in translation)
    substantial_object_correspondence = bool(
        reference_coverage >= MIN_SUBSTANTIAL_CORRESPONDENCE_COVERAGE
        and student_coverage >= MIN_SUBSTANTIAL_CORRESPONDENCE_COVERAGE
        and spatial["support"] >= 2
        and spatial["ratio"] >= MIN_TRANSLATION_COHERENCE_RATIO
    )
    rubric_app = comparison.get("rubric_application", {})
    mode = (
        rubric_app.get("normalization_mode")
        or normalization.get("mode")
        or "strict"
    )
    rubric_source = rubric_app.get("rubric_source")
    high_q_threshold = 0.85
    high_q_matches = [
        m
        for m in matches
        if float(m.get("match_quality", m.get("confidence", 0.0)))
        >= high_q_threshold
    ]
    high_q_ref_ids = {
        m.get("reference_entity_id")
        for m in high_q_matches
        if m.get("reference_entity_id")
    }
    high_q_stu_ids = {
        m.get("student_entity_id")
        for m in high_q_matches
        if m.get("student_entity_id")
    }
    high_q_count = len(high_q_matches)
    if use_canonical:
        high_q_ref_cov = min(1.0, len(high_q_ref_ids) / max(reference_count, 1))
        high_q_stu_cov = min(1.0, len(high_q_stu_ids) / max(student_count, 1))
    else:
        high_q_ref_cov = high_q_count / max(reference_count, 1)
        high_q_stu_cov = high_q_count / max(student_count, 1)
    mean_quality = (
        (
            sum(
                float(m.get("match_quality", m.get("confidence", 0.0)))
                for m in matches
            )
            / len(matches)
        )
        if matches
        else 0.0
    )
    unmatched_ref = (
        max(0, reference_count - len(matched_ref_ids))
        if matched_ref_ids or use_canonical
        else max(0, reference_count - confident)
    )
    unmatched_stu = (
        max(0, student_count - len(matched_stu_ids))
        if matched_stu_ids or use_canonical
        else max(0, student_count - confident)
    )
    unmatched_geometry_ratio = (unmatched_ref + unmatched_stu) / max(
        reference_count + student_count, 1
    )

    independent_placement_correspondence = bool(
        mode == "translation"
        and rubric_source != "explicit_fallback"
        and high_q_count
        >= min(MIN_TRANSLATION_COHERENCE_SUPPORT, reference_count)
        and high_q_ref_cov >= 0.70
        and high_q_stu_cov >= 0.70
        and mean_quality >= 0.75
        and unmatched_geometry_ratio <= 0.30
        and overlap >= 0.75
    )
    reasons: list[str] = []

    if student_count == 0:
        status = "empty_or_ungradable"
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
        or independent_placement_correspondence
    ):
        status = "compatible"
        confidence = "verified" if reference_coverage >= 0.5 else "high"
        reasons.extend(spatial["reason_codes"])
        if independent_placement_correspondence:
            reasons.append("independent_placement_correspondence")
        elif substantial_object_correspondence and not spatial["strong"]:
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
        negligible_coherent_coverage = bool(
            coherent_reference_coverage < MIN_COHERENT_REFERENCE_COVERAGE
            and coherent_student_coverage < MIN_COHERENT_STUDENT_COVERAGE
        )
        unmatched_dominates = (
            unmatched_geometry_ratio >= UNMATCHED_GEOMETRY_DOMINANCE
        )
        if (
            not spatial["partial_translation_protection"]
            and (
                (unmatched_dominates and (weak_consensus or low_coherent_evidence))
                or (negligible_coherent_coverage and weak_consensus)
            )
        ):
            status = "incompatible"
            confidence = "high"
            if confident == 0:
                reasons.append("no_confident_correspondence")
            else:
                reasons.append("raw_intrinsic_matches_lack_spatial_coherence")
            reasons.extend(spatial["reason_codes"])
            if unmatched_dominates:
                reasons.append("unmatched_geometry_dominates")
        else:
            status = "suspicious"
            confidence = "moderate"
            reasons.extend(spatial["reason_codes"])
            reasons.append("insufficient_coherent_correspondence")

    effective_override = bool(
        instructor_override and status in {"suspicious", "incompatible"}
    )
    unmatched_ref = (
        max(0, reference_count - len(matched_ref_ids))
        if matched_ref_ids or use_canonical
        else max(0, reference_count - confident)
    )
    unmatched_stu = (
        max(0, student_count - len(matched_stu_ids))
        if matched_stu_ids or use_canonical
        else max(0, student_count - confident)
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
        unmatched_reference_count=unmatched_ref,
        unmatched_student_count=unmatched_stu,
        entity_type_overlap=round(overlap, 6),
        accepted_transform=accepted_transform,
        estimated_uniform_scale=scale.estimated_scale_factor,
        scale_confidence=scale.scale_confidence,
        instructor_override=effective_override,
        spatial_evidence_basis="canonical_components"
        if use_canonical
        else "entities",
        geometric_reference_coverage=(
            comparison.get("canonical_match", {}).get("completion_fraction")
            if use_canonical
            else None
        ),
    )
