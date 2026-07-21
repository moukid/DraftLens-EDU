from __future__ import annotations

from app.compatibility import assess_compatibility
from app.models import Drawing, Entity
from app.scale_diagnostics import ScaleDiagnostic


def _drawing(
    count: int,
    *,
    kind: str = "line",
    unsupported: bool = False,
    source: str = "reference",
    dx: float = 0.0,
    dy: float = 0.0,
) -> Drawing:
    prefix = "R" if source == "reference" else "S"
    entities = [
        Entity(
            id=f"{prefix}-{index}",
            kind=kind,
            layer="0",
            source=source,
            points=[(index + dx, dy), (index + 1 + dx, dy)],
        )
        for index in range(count)
    ]
    return Drawing(
        entities=entities,
        bbox=(dx, dy, dx + max(count, 1), dy + 1),
        unsupported_entities=[{"entity_type": "HATCH"}] if unsupported else [],
    )


def _comparison(matches=(), translation=(0.0, 0.0)):
    return {
        "matches": list(matches),
        "normalization": {"student": {"translation": list(translation)}},
        "tolerances": {"position": 2.0},
    }


def _matches(count: int, confidence: float = 1.0):
    return [
        {
            "reference_entity_id": f"R-{index}",
            "student_entity_id": f"S-{index}",
            "confidence": confidence,
        }
        for index in range(count)
    ]


def _student_with_offsets(offsets: list[tuple[float, float]]) -> Drawing:
    entities = []
    for index, (dx, dy) in enumerate(offsets):
        points = [(index + dx, dy), (index + 1 + dx, dy)]
        entities.append(
            Entity(
                id=f"S-{index}",
                kind="line",
                layer="0",
                source="student",
                points=points,
            )
        )
    all_points = [point for entity in entities for point in entity.points]
    return Drawing(
        entities=entities,
        bbox=(
            min(point[0] for point in all_points),
            min(point[1] for point in all_points),
            max(point[0] for point in all_points),
            max(point[1] for point in all_points),
        ),
    )


def test_complete_translation_forms_one_coherent_consensus():
    result = assess_compatibility(
        _drawing(10),
        _drawing(10, source="student", dx=50, dy=-20),
        _comparison(_matches(10)),
        _scale(),
    )
    assert result.compatibility_status == "compatible"
    assert result.spatial_coherence_status == "coherent_translation"
    assert result.displacement_consensus_vector == (50.0, -20.0)
    assert result.displacement_consensus_support == 10
    assert result.displacement_consensus_ratio == 1.0


def test_partial_coherent_translation_is_protected():
    translated = assess_compatibility(
        _drawing(100),
        _drawing(3, source="student", dx=25, dy=10),
        _comparison(_matches(3)),
        _scale(),
    )
    small = assess_compatibility(
        _drawing(100),
        _drawing(2, source="student", dx=25, dy=10),
        _comparison(_matches(2)),
        _scale(),
    )
    assert translated.compatibility_status == "compatible"
    assert translated.coherent_student_coverage == 1.0
    assert small.compatibility_status == "suspicious"
    assert small.grading_withheld is True


def test_substantial_object_correspondence_preserves_local_position_errors():
    result = assess_compatibility(
        _drawing(3),
        _student_with_offsets([(0, 0), (30, 0), (30, 0)]),
        _comparison(_matches(3, confidence=0.9)),
        _scale(),
    )
    assert result.compatibility_status == "compatible"
    assert result.coherent_match_count == 2
    assert result.displacement_consensus_ratio == 0.666667
    assert "substantial_object_correspondence" in result.compatibility_reason_codes


def test_scattered_intrinsic_matches_are_incompatible():
    result = assess_compatibility(
        _drawing(20),
        _student_with_offsets([(0, 0), (20, 15), (50, -10), (90, 35)]),
        _comparison(_matches(4, confidence=0.9)),
        _scale(),
    )
    assert result.compatibility_status == "incompatible"
    assert result.confident_match_count == 4
    assert result.coherent_match_count == 1
    assert result.incoherent_match_count == 3
    assert result.displacement_consensus_ratio == 0.25
    assert "raw_intrinsic_matches_lack_spatial_coherence" in (
        result.compatibility_reason_codes
    )


def test_entity_type_overlap_and_similar_intrinsics_do_not_establish_compatibility():
    overlap_only = assess_compatibility(
        _drawing(20),
        _drawing(4, source="student", dx=200),
        _comparison(),
        _scale(),
    )
    one_generic_match = assess_compatibility(
        _drawing(100),
        _drawing(1, source="student", dx=200),
        _comparison(_matches(1, confidence=0.95)),
        _scale(),
    )
    assert overlap_only.entity_type_overlap > 0
    assert overlap_only.compatibility_status == "incompatible"
    assert one_generic_match.compatibility_status == "incompatible"
    assert one_generic_match.approximate_match_count == 1




def _scale(*, mismatch=False, factor=None, support=0, ratio=0.0, confidence="none"):
    return ScaleDiagnostic(mismatch, factor, support, ratio, confidence, mismatch)


def test_exact_and_partial_confident_correspondence_are_compatible():
    exact = assess_compatibility(
        _drawing(4),
        _drawing(4, source="student"),
        _comparison(_matches(4)),
        _scale(),
    )
    partial = assess_compatibility(
        _drawing(100),
        _drawing(1, source="student"),
        _comparison(_matches(1)),
        _scale(),
    )
    assert exact.compatibility_status == "compatible"
    assert exact.spatial_coherence_status == "coherent_identity"
    assert exact.coherent_match_count == 4
    assert exact.displacement_consensus_vector == (0.0, 0.0)
    assert partial.compatibility_status == "compatible"
    assert partial.coherent_student_coverage == 1.0


def test_unrelated_severe_count_mismatch_is_incompatible_and_withheld():
    result = assess_compatibility(
        _drawing(139), _drawing(2), _comparison(), _scale()
    )
    assert result.compatibility_status == "incompatible"
    assert result.grading_withheld is True
    assert "no_confident_correspondence" in result.compatibility_reason_codes


def test_scale_invariant_correspondence_is_suspicious_not_incompatible():
    result = assess_compatibility(
        _drawing(20),
        _drawing(20),
        _comparison(),
        _scale(mismatch=True, factor=50, support=20, ratio=1, confidence="verified"),
    )
    assert result.compatibility_status == "suspicious"
    assert result.estimated_uniform_scale == 50
    assert result.grading_withheld is True


def test_empty_supported_geometry_is_ungradable_and_cannot_be_overridden():
    empty = assess_compatibility(
        _drawing(4), _drawing(0, unsupported=True), _comparison(), _scale()
    )
    overridden = assess_compatibility(
        _drawing(4),
        _drawing(0, unsupported=True),
        _comparison(),
        _scale(),
        instructor_override=True,
    )
    assert empty.compatibility_status == "empty_or_ungradable"
    assert empty.grading_withheld is True
    assert overridden.instructor_override is False
    assert overridden.grading_withheld is True
