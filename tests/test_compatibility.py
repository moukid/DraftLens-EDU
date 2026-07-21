from __future__ import annotations

from app.compatibility import assess_compatibility
from app.models import Drawing, Entity
from app.scale_diagnostics import ScaleDiagnostic


def _drawing(count: int, *, kind: str = "line", unsupported: bool = False) -> Drawing:
    entities = [
        Entity(id=f"E-{index}", kind=kind, layer="0", points=[(index, 0), (index + 1, 0)])
        for index in range(count)
    ]
    return Drawing(
        entities=entities,
        bbox=(0, 0, max(count, 1), 1),
        unsupported_entities=[{"entity_type": "HATCH"}] if unsupported else [],
    )


def _comparison(matches=(), translation=(0.0, 0.0)):
    return {
        "matches": list(matches),
        "normalization": {"student": {"translation": list(translation)}},
    }


def _scale(*, mismatch=False, factor=None, support=0, ratio=0.0, confidence="none"):
    return ScaleDiagnostic(mismatch, factor, support, ratio, confidence, mismatch)


def test_exact_and_partial_confident_correspondence_are_compatible():
    exact = assess_compatibility(
        _drawing(4),
        _drawing(4),
        _comparison([{"confidence": 1.0}] * 4),
        _scale(),
    )
    partial = assess_compatibility(
        _drawing(100),
        _drawing(1),
        _comparison([{"confidence": 1.0}]),
        _scale(),
    )
    assert exact.compatibility_status == "compatible"
    assert partial.compatibility_status == "compatible"


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
