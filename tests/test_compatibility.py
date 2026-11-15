from __future__ import annotations

import pytest

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


def test_unrelated_combinatorial_candidate_matches_with_negligible_coherence_are_incompatible():
    offsets = [(0, 0), (100, 200), (300, -400), (-500, 600), (800, 900)]
    student_dwg = _student_with_offsets(offsets)
    ref_dwg = _drawing(100)
    # 50 candidate matches across 5 student entities and 50 reference entities.
    # Spaced by 10 units so displacements never cluster within position tolerance 2.0.
    combinatorial_matches = [
        {
            "reference_entity_id": f"R-{stu_idx + offset_idx * 10}",
            "student_entity_id": f"S-{stu_idx}",
            "confidence": 0.85,
        }
        for stu_idx in range(5)
        for offset_idx in range(10)
    ]
    unrelated_result = assess_compatibility(
        ref_dwg,
        student_dwg,
        _comparison(combinatorial_matches),
        _scale(),
    )
    # Preconditions: every displacement is isolated so support == 1
    assert unrelated_result.displacement_consensus_support == 1
    assert unrelated_result.displacement_consensus_ratio == 0.02
    assert unrelated_result.unmatched_reference_count == 50
    assert unrelated_result.unmatched_student_count == 0
    assert unrelated_result.unmatched_geometry_ratio == round(50 / 105, 6)
    assert unrelated_result.unmatched_geometry_ratio < 0.60
    assert unrelated_result.coherent_reference_coverage == 0.01
    assert unrelated_result.coherent_reference_coverage < 0.05
    assert unrelated_result.coherent_student_coverage == 0.20
    assert unrelated_result.coherent_student_coverage < 0.35
    assert unrelated_result.spatial_coherence_status == "weak"
    assert "raw_intrinsic_matches_lack_spatial_coherence" in (
        unrelated_result.compatibility_reason_codes
    )
    assert unrelated_result.compatibility_status == "incompatible"
    assert unrelated_result.grading_withheld is True


def test_shared_owner_candidate_matches_do_not_inflate_student_coverage():
    ref_dwg = _drawing(10)
    student_dwg = _student_with_offsets([(0, 0), (50, 50), (100, 100), (150, 150), (200, 200)])
    shared_matches = [
        {"reference_entity_id": f"R-{i}", "student_entity_id": "S-0", "confidence": 0.9}
        for i in range(5)
    ]
    result = assess_compatibility(
        ref_dwg,
        student_dwg,
        _comparison(shared_matches),
        _scale(),
    )
    # Distinct student coverage must be 1 / 5 = 0.20, not 5 / 5 = 1.0 or 5.0
    assert result.displacement_consensus_support == 5
    assert result.coherent_student_coverage == 0.20
    assert result.student_match_coverage == 0.20
    assert result.coherent_reference_coverage == 0.50


def test_partial_coherent_translation_control_is_compatible():
    ref_dwg = _drawing(100)
    partial_dwg = _drawing(5, source="student", dx=25, dy=10)
    coherent_matches = _matches(5)
    partial_result = assess_compatibility(
        ref_dwg,
        partial_dwg,
        _comparison(coherent_matches),
        _scale(),
    )
    assert partial_result.compatibility_status == "compatible"
    assert partial_result.coherent_student_coverage == 1.0
    assert partial_result.spatial_coherence_status == "coherent_translation"
    assert partial_result.displacement_consensus_vector == (25.0, 10.0)
    assert partial_result.displacement_consensus_support == 5


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


def test_legitimate_independent_object_placement_is_compatible():
    """Verify that multiple complete objects independently placed by the student
    in translation mode are assessed as compatible rather than suspicious."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    def _line(eid, p1, p2, src="reference"):
        return Entity(
            id=eid,
            kind="line",
            layer="0",
            source=src,
            points=[p1, p2],
        )

    # Reference: Two 100x80 rectangles at x=0 and x=300
    ref_dwg = Drawing(
        entities=[
            # Rectangle 1
            _line("R-1", (0, 0), (100, 0)),
            _line("R-2", (100, 0), (100, 80)),
            _line("R-3", (100, 80), (0, 80)),
            _line("R-4", (0, 80), (0, 0)),
            # Rectangle 2
            _line("R-5", (300, 0), (400, 0)),
            _line("R-6", (400, 0), (400, 80)),
            _line("R-7", (400, 80), (300, 80)),
            _line("R-8", (300, 80), (300, 0)),
        ],
        bbox=(0.0, 0.0, 400.0, 80.0),
    )
    # Student: Rectangle 1 placed at (40, 30), Rectangle 2 placed at (650, 70) [dx=350, dy=70]
    stu_dwg = Drawing(
        entities=[
            # Rectangle 1 placed at (40, 30)
            _line("S-1", (40, 30), (140, 30), src="student"),
            _line("S-2", (140, 30), (140, 110), src="student"),
            _line("S-3", (140, 110), (40, 110), src="student"),
            _line("S-4", (40, 110), (40, 30), src="student"),
            # Rectangle 2 placed at (650, 70)
            _line("S-5", (650, 70), (750, 70), src="student"),
            _line("S-6", (750, 70), (750, 150), src="student"),
            _line("S-7", (750, 150), (650, 150), src="student"),
            _line("S-8", (650, 150), (650, 70), src="student"),
        ],
        bbox=(40.0, 30.0, 750.0, 150.0),
    )
    rubric = default_rubric().model_copy(update={
        "approved": True,
        "normalization_mode": "translation",
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    comparison = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    assert comparison["score"] == 100.0
    scale = _scale()
    result = assess_compatibility(ref_dwg, stu_dwg, comparison, scale)
    assert result.compatibility_status == "compatible"
    assert result.grading_withheld is False
    assert result.compatibility_confidence in {"verified", "high"}


@pytest.mark.parametrize("mode", ["strict", "translation"])
def test_inplace_half_line_is_compatible(mode: str):
    """Verify that an in-place partially drawn segment (e.g. half-line) does not
    produce a fictitious translation vector and is assessed as compatible with
    grading not withheld under both strict and translation modes."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    ref_dwg = Drawing(
        entities=[
            Entity(
                id="R-1",
                kind="line",
                layer="0",
                source="reference",
                points=[(0.0, 0.0), (100.0, 0.0)],
            )
        ],
        bbox=(0.0, 0.0, 100.0, 0.0),
    )
    stu_dwg = Drawing(
        entities=[
            Entity(
                id="S-1",
                kind="line",
                layer="0",
                source="student",
                points=[(0.0, 0.0), (50.0, 0.0)],
            )
        ],
        bbox=(0.0, 0.0, 50.0, 0.0),
    )
    scale = _scale()
    rubric = default_rubric().model_copy(update={
        "approved": True,
        "normalization_mode": mode,
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    comparison = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    assert comparison["score"] == 97.0
    assert any(
        i["category"] == "incorrect_length"
        and i["expected"] == 100.0
        and i["actual"] == 50.0
        for i in comparison["issues"]
    )
    # Check canonical observation displacement directly: zero fictitious displacement
    canonical_match = comparison.get("canonical_match", {})
    observations = canonical_match.get("spatial_correspondences", [])
    assert len(observations) == 1
    assert observations[0]["displacement"] == [0.0, 0.0]

    result = assess_compatibility(ref_dwg, stu_dwg, comparison, scale)
    assert result.compatibility_status == "compatible", f"{mode}: expected compatible, got {result.compatibility_status}"
    assert result.grading_withheld is False, f"{mode}: expected grading_withheld False"
    assert result.compatibility_confidence in {"verified", "high"}
    assert result.displacement_consensus_vector == (0.0, 0.0)
    assert result.spatial_coherence_status == "coherent_identity"


@pytest.mark.parametrize("mode", ["strict", "translation"])
def test_anchored_partial_square_is_compatible(mode: str):
    """Verify that an anchored in-place partial rectangle with complete bottom edge
    and half-drawn right edge does not conflate missing extent with translation
    and is assessed as compatible with grading not withheld in both modes."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    def _line(eid, p1, p2, src="reference"):
        return Entity(
            id=eid,
            kind="line",
            layer="0",
            source=src,
            points=[p1, p2],
        )

    ref_dwg = Drawing(
        entities=[
            _line("R-1", (0.0, 0.0), (100.0, 0.0)),
            _line("R-2", (100.0, 0.0), (100.0, 80.0)),
            _line("R-3", (100.0, 80.0), (0.0, 80.0)),
            _line("R-4", (0.0, 80.0), (0.0, 0.0)),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    # Student has complete bottom edge and lower 40 units of right edge
    stu_dwg = Drawing(
        entities=[
            _line("S-1", (0.0, 0.0), (100.0, 0.0), src="student"),
            _line("S-2", (100.0, 0.0), (100.0, 40.0), src="student"),
        ],
        bbox=(0.0, 0.0, 100.0, 40.0),
    )
    scale = _scale()
    rubric = default_rubric().model_copy(update={
        "approved": True,
        "normalization_mode": mode,
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
        "missing_part_deduction": 0.5,
    })
    comparison = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    assert comparison["score"] == 96.0
    assert any(
        i["category"] == "incorrect_length"
        and i["expected"] == 80.0
        and i["actual"] == 40.0
        for i in comparison["issues"]
    )
    # Verify both observations have zero fictitious displacement
    canonical_match = comparison.get("canonical_match", {})
    observations = canonical_match.get("spatial_correspondences", [])
    assert len(observations) == 2
    for obs in observations:
        assert obs["displacement"] == [0.0, 0.0]

    result = assess_compatibility(ref_dwg, stu_dwg, comparison, scale)
    assert result.compatibility_status == "compatible", f"{mode}: expected compatible, got {result.compatibility_status}"
    assert result.grading_withheld is False, f"{mode}: expected grading_withheld False"
    assert result.compatibility_confidence in {"verified", "high"}
    assert result.displacement_consensus_support == 2
    assert result.displacement_consensus_ratio == 1.0
    assert result.displacement_consensus_vector == (0.0, 0.0)
    assert result.spatial_coherence_status == "coherent_identity"


def _make_line(eid: str, p1: tuple[float, float], p2: tuple[float, float], src: str = "reference") -> Entity:
    return Entity(
        id=eid,
        kind="line",
        layer="0",
        source=src,
        points=[p1, p2],
        centroid=((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0),
        bbox=(min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])),
    )


@pytest.mark.parametrize("mode", ["strict", "translation"])
@pytest.mark.parametrize("pos_tol,shift", [
    (0.0, 0.5),
    (0.1, 0.5),
    (2.0, 0.5),
    (0.0, 3.0),
    (5.0, 3.0),
])
def test_configurable_displacement_tolerance_honors_configured_values(mode: str, pos_tol: float, shift: float):
    """Verify that canonical displacement calculation carries configured position tolerance,
    preserving zero displacement within tolerance and reporting actual shift when exceeding tolerance."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    ref_dwg = Drawing(
        entities=[
            _make_line("R-1", (0.0, 0.0), (100.0, 0.0)),
            _make_line("R-2", (100.0, 0.0), (100.0, 80.0)),
            _make_line("R-3", (100.0, 80.0), (0.0, 80.0)),
            _make_line("R-4", (0.0, 80.0), (0.0, 0.0)),
            _make_line("R-inner", (20.0, 20.0), (50.0, 20.0)),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    stu_dwg = Drawing(
        entities=[
            _make_line("S-1", (0.0, 0.0), (100.0, 0.0), src="student"),
            _make_line("S-2", (100.0, 0.0), (100.0, 80.0), src="student"),
            _make_line("S-3", (100.0, 80.0), (0.0, 80.0), src="student"),
            _make_line("S-4", (0.0, 80.0), (0.0, 0.0), src="student"),
            _make_line("S-inner", (20.0 + shift, 20.0), (50.0 + shift, 20.0), src="student"),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    rubric = default_rubric().model_copy(deep=True, update={
        "approved": True,
        "normalization_mode": mode,
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
        "missing_part_deduction": 0.5,
    })
    rubric.tolerances.position = pos_tol

    comparison = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    canonical_match = comparison.get("canonical_match", {})
    observations = [
        o for o in canonical_match.get("spatial_correspondences", [])
        if o["reference_component_id"].startswith("R-inner")
    ]
    assert len(observations) == 1
    inner_obs = observations[0]
    target_issues = [
        i for i in comparison["issues"]
        if i.get("reference_entity_id") == "R-inner"
    ]

    if shift <= pos_tol:
        assert inner_obs["displacement"] == [0.0, 0.0]
        assert not [i for i in target_issues if i["category"] == "incorrect_position"]
        assert comparison["score"] == 100.0
    else:
        assert inner_obs["displacement"] == [round(shift, 4), 0.0]
        pos_issues = [i for i in target_issues if i["category"] == "incorrect_position"]
        assert len(pos_issues) == 1
        assert pos_issues[0]["applied_deduction"] == 3.0
        assert comparison["score"] == 97.0


@pytest.mark.parametrize("mode", ["strict", "translation"])
def test_ambiguous_contained_partial_segment_has_zero_movement_charge(mode: str):
    """Verify that a partial segment contained entirely within the reference collinear span
    does not receive an unsupported movement charge from centroid shift alone, retaining
    correct length deduction and zero canonical displacement in both modes."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    ref_dwg = Drawing(
        entities=[
            _make_line("R-1", (0.0, 0.0), (100.0, 0.0)),
            _make_line("R-2", (100.0, 0.0), (100.0, 80.0)),
            _make_line("R-3", (100.0, 80.0), (0.0, 80.0)),
            _make_line("R-4", (0.0, 80.0), (0.0, 0.0)),
            _make_line("R-inner", (20.0, 20.0), (50.0, 20.0)),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    # Student draws (30, 20) -> (45, 20): length 15 (short by 15), contained within (20, 20) -> (50, 20)
    stu_dwg = Drawing(
        entities=[
            _make_line("S-1", (0.0, 0.0), (100.0, 0.0), src="student"),
            _make_line("S-2", (100.0, 0.0), (100.0, 80.0), src="student"),
            _make_line("S-3", (100.0, 80.0), (0.0, 80.0), src="student"),
            _make_line("S-4", (0.0, 80.0), (0.0, 0.0), src="student"),
            _make_line("S-inner", (30.0, 20.0), (45.0, 20.0), src="student"),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    rubric = default_rubric().model_copy(deep=True, update={
        "approved": True,
        "normalization_mode": mode,
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
        "missing_part_deduction": 0.5,
    })
    comparison = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    target_issues = [
        i for i in comparison["issues"]
        if i.get("reference_entity_id") == "R-inner"
    ]
    # Length error must be charged
    length_issues = [i for i in target_issues if i["category"] == "incorrect_length"]
    assert len(length_issues) == 1
    assert length_issues[0]["applied_deduction"] == 3.0
    assert length_issues[0]["expected"] == 30.0
    assert length_issues[0]["actual"] == 15.0

    # No paid position error on contained partial segment
    paid_position = [
        i for i in target_issues
        if i["category"] == "incorrect_position" and i.get("applied_deduction", 0) > 0
    ]
    assert not paid_position, f"Expected no paid position findings, got {paid_position}"

    # Canonical displacement must be zero and presence 0.5
    canonical_match = comparison.get("canonical_match", {})
    observations = [
        o for o in canonical_match.get("spatial_correspondences", [])
        if o["reference_component_id"].startswith("R-inner")
    ]
    assert len(observations) == 1
    assert observations[0]["displacement"] == [0.0, 0.0]
    assert round(observations[0]["presence"], 4) == 0.5

    # Overall score: 100 - 3 (length charge) = 97.0
    assert comparison["score"] == 97.0

    # Compatibility check
    scale = _scale()
    result = assess_compatibility(ref_dwg, stu_dwg, comparison, scale)
    assert result.compatibility_status == "compatible"
    assert result.grading_withheld is False


def test_child_segment_displacement_negative_controls():
    """Verify that real position, transverse offset, and overhang errors are not suppressed."""
    from app.compare import compare_drawings
    from app.rubric import default_rubric

    ref_dwg = Drawing(
        entities=[
            _make_line("R-1", (0.0, 0.0), (100.0, 0.0)),
            _make_line("R-2", (100.0, 0.0), (100.0, 80.0)),
            _make_line("R-3", (100.0, 80.0), (0.0, 80.0)),
            _make_line("R-4", (0.0, 80.0), (0.0, 0.0)),
            _make_line("R-inner", (20.0, 20.0), (50.0, 20.0)),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    rubric = default_rubric().model_copy(deep=True, update={
        "approved": True,
        "normalization_mode": "strict",
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
        "missing_part_deduction": 0.5,
    })

    # Case A: Transverse normal offset of 5.0 (30, 25) -> (45, 25)
    stu_transverse = Drawing(
        entities=[
            _make_line("S-1", (0.0, 0.0), (100.0, 0.0), src="student"),
            _make_line("S-2", (100.0, 0.0), (100.0, 80.0), src="student"),
            _make_line("S-3", (100.0, 80.0), (0.0, 80.0), src="student"),
            _make_line("S-4", (0.0, 80.0), (0.0, 0.0), src="student"),
            _make_line("S-inner", (30.0, 25.0), (45.0, 25.0), src="student"),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    comp_a = compare_drawings(ref_dwg, stu_transverse, rubric=rubric)
    target_a = [i for i in comp_a["issues"] if i.get("reference_entity_id") == "R-inner"]
    pos_a = [i for i in target_a if i["category"] == "incorrect_position" and i.get("applied_deduction", 0) > 0]
    assert len(pos_a) >= 1, "Transverse normal offset must trigger a paid position deduction"

    # Case B: Overhang past the endpoint (40, 20) -> (55, 20)
    stu_overhang = Drawing(
        entities=[
            _make_line("S-1", (0.0, 0.0), (100.0, 0.0), src="student"),
            _make_line("S-2", (100.0, 0.0), (100.0, 80.0), src="student"),
            _make_line("S-3", (100.0, 80.0), (0.0, 80.0), src="student"),
            _make_line("S-4", (0.0, 80.0), (0.0, 0.0), src="student"),
            _make_line("S-inner", (40.0, 20.0), (55.0, 20.0), src="student"),
        ],
        bbox=(0.0, 0.0, 100.0, 80.0),
    )
    comp_b = compare_drawings(ref_dwg, stu_overhang, rubric=rubric)
    target_b = [i for i in comp_b["issues"] if i.get("reference_entity_id") == "R-inner"]
    pos_b = [i for i in target_b if i["category"] == "incorrect_position" and i.get("applied_deduction", 0) > 0]
    assert len(pos_b) >= 1, "Overhanging past endpoint must trigger a paid position deduction"
