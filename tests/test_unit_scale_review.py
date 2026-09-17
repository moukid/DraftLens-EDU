from __future__ import annotations

import pytest

from app.models import Drawing, Entity
from app.scale_diagnostics import ScaleDiagnostic
from app.unit_scale_review import (
    evaluate_unit_scale_review,
    format_scale_factor_direction,
)


def _make_dummy_drawing(units: str, code: int = 0) -> Drawing:
    return Drawing(
        entities=[
            Entity(id="E-001", kind="line", layer="0", points=[(0.0, 0.0), (100.0, 0.0)]),
            Entity(id="E-002", kind="line", layer="0", points=[(100.0, 0.0), (100.0, 50.0)]),
            Entity(id="E-003", kind="line", layer="0", points=[(100.0, 50.0), (0.0, 50.0)]),
            Entity(id="E-004", kind="line", layer="0", points=[(0.0, 50.0), (0.0, 0.0)]),
        ],
        bbox=(0.0, 0.0, 100.0, 50.0),
        units=units,
        units_code=code,
    )


def test_format_scale_factor_direction():
    assert "1:1 scale" in format_scale_factor_direction(1.0)
    assert "approximately 10 times" in format_scale_factor_direction(10.0)
    msg_small = format_scale_factor_direction(0.1)
    assert "approximately 0.1 times" in msg_small
    assert "approximately 10 times student lengths" in msg_small
    assert "could not be determined" in format_scale_factor_direction(None)


def test_diagnostic_state_declared_units_differ():
    ref = _make_dummy_drawing(units="mm", code=4)
    stu = _make_dummy_drawing(units="in", code=1)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=False,
        estimated_scale_factor=1.0,
        scale_support_count=4,
        scale_support_ratio=1.0,
        scale_confidence="high",
        likely_unit_or_scale_mismatch=False,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="mm", intended_unit_confirmed=True
    )
    assert result.declared_units_differ is True
    assert result.diagnostic_state == "declared_units_differ"
    assert "Notice: Declared units differ" in (result.prominent_notice or "")


def test_diagnostic_state_units_unspecified():
    ref = _make_dummy_drawing(units="unitless", code=0)
    stu = _make_dummy_drawing(units="unitless", code=0)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=False,
        estimated_scale_factor=1.0,
        scale_support_count=4,
        scale_support_ratio=1.0,
        scale_confidence="high",
        likely_unit_or_scale_mismatch=False,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="unspecified", intended_unit_confirmed=False
    )
    assert result.units_unspecified is True
    assert result.diagnostic_state == "units_unspecified"
    assert "Notice: Drawing units are unspecified" in (result.prominent_notice or "")


def test_diagnostic_state_geometry_scale_mismatch():
    ref = _make_dummy_drawing(units="mm", code=4)
    stu = _make_dummy_drawing(units="mm", code=4)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=True,
        estimated_scale_factor=2.5,
        scale_support_count=4,
        scale_support_ratio=1.0,
        scale_confidence="high",
        likely_unit_or_scale_mismatch=True,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="mm", intended_unit_confirmed=True
    )
    assert result.geometry_scale_mismatch is True
    assert result.diagnostic_state == "geometry_scale_mismatch"
    assert "Warning: Geometry suggests a relative scale mismatch" in (result.prominent_notice or "")
    assert "approximately 2.5 times" in (result.prominent_notice or "")


def test_diagnostic_state_units_scale_physically_consistent():
    # Reference in mm, Student in cm.
    # 1 cm = 10 mm. So student coordinates should be 0.1x reference.
    ref = _make_dummy_drawing(units="mm", code=4)
    stu = _make_dummy_drawing(units="cm", code=5)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=True,
        estimated_scale_factor=0.1,
        scale_support_count=4,
        scale_support_ratio=1.0,
        scale_confidence="verified",
        likely_unit_or_scale_mismatch=True,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="mm", intended_unit_confirmed=True
    )
    assert result.units_scale_physically_consistent is True
    assert result.diagnostic_state == "units_scale_physically_consistent"
    assert "physically consistent with declared units" in (result.prominent_notice or "")


def test_diagnostic_state_insufficient_evidence():
    ref = _make_dummy_drawing(units="mm", code=4)
    stu = _make_dummy_drawing(units="mm", code=4)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=False,
        estimated_scale_factor=None,
        scale_support_count=1,
        scale_support_ratio=0.2,
        scale_confidence="insufficient_evidence",
        likely_unit_or_scale_mismatch=False,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="mm", intended_unit_confirmed=True
    )
    assert result.insufficient_evidence is True
    assert result.diagnostic_state == "insufficient_evidence"


def test_matching_and_consistent():
    ref = _make_dummy_drawing(units="mm", code=4)
    stu = _make_dummy_drawing(units="mm", code=4)
    diag = ScaleDiagnostic(
        detected_scale_mismatch=False,
        estimated_scale_factor=1.0,
        scale_support_count=4,
        scale_support_ratio=1.0,
        scale_confidence="high",
        likely_unit_or_scale_mismatch=False,
    )
    result = evaluate_unit_scale_review(
        ref, stu, diag, intended_unit="mm", intended_unit_confirmed=True
    )
    assert result.diagnostic_state == "matching_and_consistent"
    assert result.declared_units_differ is False
    assert result.requires_instructor_acknowledgment is False
