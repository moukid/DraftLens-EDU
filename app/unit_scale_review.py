from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Literal

from .models import Drawing
from .scale_diagnostics import ScaleDiagnostic

UNIT_DISPLAY_NAMES: dict[str, str] = {
    "mm": "Millimetres (mm)",
    "cm": "Centimetres (cm)",
    "m": "Metres (m)",
    "in": "Inches (in)",
    "ft": "Feet (ft)",
    "unitless": "Unitless",
}

METRIC_FACTORS_TO_METERS: dict[str, float] = {
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "in": 0.0254,
    "ft": 0.3048,
}

DiagnosticState = Literal[
    "declared_units_differ",
    "units_unspecified",
    "geometry_scale_mismatch",
    "units_scale_physically_consistent",
    "insufficient_evidence",
    "matching_and_consistent",
]


@dataclass(frozen=True, slots=True)
class UnitScaleReviewResult:
    reference_declared_unit: str
    student_declared_unit: str
    intended_unit: str
    intended_unit_confirmed: bool
    diagnostic_state: DiagnosticState
    all_diagnostic_flags: list[str]
    declared_units_differ: bool
    units_unspecified: bool
    geometry_scale_mismatch: bool
    units_scale_physically_consistent: bool
    insufficient_evidence: bool
    estimated_scale_factor: float | None
    scale_confidence: str
    factor_direction_explanation: str
    prominent_notice: str | None
    requires_instructor_acknowledgment: bool
    acknowledged: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def format_scale_factor_direction(factor: float | None) -> str:
    """Format clear directional explanation of the estimated factor."""
    if factor is None:
        return "Scale factor could not be determined."
    if abs(factor - 1.0) <= 0.03:
        return "Student lengths approximately match reference lengths (1:1 scale)."
    if factor > 1.0:
        return f"Student lengths are approximately {factor:.4g} times reference lengths."
    inverse = round(1.0 / factor, 4) if factor > 1e-9 else 0.0
    return (
        f"Student lengths are approximately {factor:.4g} times reference lengths "
        f"(reference lengths are approximately {inverse:.4g} times student lengths)."
    )


def evaluate_unit_scale_review(
    reference: Drawing,
    student: Drawing,
    scale_diagnostic: ScaleDiagnostic,
    *,
    intended_unit: str = "unspecified",
    intended_unit_confirmed: bool = False,
    instructor_acknowledged: bool = False,
) -> UnitScaleReviewResult:
    """Evaluate declared units, intended interpretation, and geometric scale evidence."""
    ref_unit = reference.units or "unitless"
    stu_unit = student.units or "unitless"

    flags: list[str] = []
    units_differ = ref_unit != stu_unit
    if units_differ:
        flags.append("declared_units_differ")

    unspecified = (
        ref_unit in {"unitless", "code-0"}
        or stu_unit in {"unitless", "code-0"}
        or intended_unit in {"unspecified", "unitless"}
    )
    if unspecified:
        flags.append("units_unspecified")

    geom_mismatch = (
        scale_diagnostic.detected_scale_mismatch
        and scale_diagnostic.scale_confidence in {"high", "verified"}
    )
    if geom_mismatch:
        flags.append("geometry_scale_mismatch")

    insufficient = scale_diagnostic.scale_confidence in {
        "insufficient_evidence",
        "none",
        "low",
    }
    if insufficient:
        flags.append("insufficient_evidence")

    # Check physical consistency: e.g. ref in mm (0.001m), stu in cm (0.01m).
    # Expected coordinate ratio = ref_m / stu_m.
    # e.g. 0.001 / 0.01 = 0.1 (student coordinates should be 0.1x reference).
    physically_consistent = False
    factor = scale_diagnostic.estimated_scale_factor
    if (
        units_differ
        and ref_unit in METRIC_FACTORS_TO_METERS
        and stu_unit in METRIC_FACTORS_TO_METERS
        and factor is not None
        and factor > 1e-9
        and scale_diagnostic.scale_confidence in {"high", "verified"}
        and scale_diagnostic.scale_support_count >= 3
    ):
        expected_ratio = (
            METRIC_FACTORS_TO_METERS[ref_unit] / METRIC_FACTORS_TO_METERS[stu_unit]
        )
        if abs(math.log(factor / expected_ratio)) <= 0.06:
            physically_consistent = True
            flags.append("units_scale_physically_consistent")

    factor_explanation = (
        "Insufficient corresponding geometry to establish a relative scale factor."
        if insufficient else format_scale_factor_direction(factor)
    )

    # Determine primary diagnostic state
    if physically_consistent:
        primary_state: DiagnosticState = "units_scale_physically_consistent"
    elif geom_mismatch:
        primary_state = "geometry_scale_mismatch"
    elif units_differ:
        primary_state = "declared_units_differ"
    elif unspecified:
        primary_state = "units_unspecified"
    elif insufficient:
        primary_state = "insufficient_evidence"
    else:
        primary_state = "matching_and_consistent"

    # Construct human-readable prominent notice
    prominent_notice: str | None = None
    if physically_consistent:
        prominent_notice = (
            f"Notice: Reference declares {ref_unit} while student declares {stu_unit}. "
            f"Coordinate difference ({factor_explanation}) is physically consistent with declared units. "
            "Evaluation is performed in drawing units; no automatic coordinate rescaling is applied."
        )
    elif units_differ and geom_mismatch:
        prominent_notice = (
            f"Warning: Declared units differ (Reference: {ref_unit}, Student: {stu_unit}) "
            f"and geometry indicates a scale mismatch: {factor_explanation}"
        )
    elif units_differ:
        prominent_notice = (
            f"Notice: Declared units differ (Reference: {ref_unit}, Student: {stu_unit}). "
            "Coordinate geometry does not confirm a physical conversion."
        )
    elif geom_mismatch:
        prominent_notice = (
            f"Warning: Geometry suggests a relative scale mismatch: {factor_explanation}"
        )
    elif unspecified and not intended_unit_confirmed:
        prominent_notice = (
            "Notice: Drawing units are unspecified in file headers. "
            "Confirm the intended assignment unit during reference setup."
        )

    intended_unit_unresolved = (
        not intended_unit_confirmed
        or intended_unit in {"unspecified", "unitless"}
    )
    requires_ack = bool(
        (
            intended_unit_unresolved
            or ((units_differ or geom_mismatch) and not physically_consistent)
        )
        and not instructor_acknowledged
    )

    return UnitScaleReviewResult(
        reference_declared_unit=ref_unit,
        student_declared_unit=stu_unit,
        intended_unit=intended_unit,
        intended_unit_confirmed=intended_unit_confirmed,
        diagnostic_state=primary_state,
        all_diagnostic_flags=flags,
        declared_units_differ=units_differ,
        units_unspecified=unspecified,
        geometry_scale_mismatch=geom_mismatch,
        units_scale_physically_consistent=physically_consistent,
        insufficient_evidence=insufficient,
        estimated_scale_factor=factor,
        scale_confidence=scale_diagnostic.scale_confidence,
        factor_direction_explanation=factor_explanation,
        prominent_notice=prominent_notice,
        requires_instructor_acknowledgment=requires_ack,
        acknowledged=instructor_acknowledged,
    )
