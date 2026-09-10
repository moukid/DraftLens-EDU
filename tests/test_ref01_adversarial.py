from __future__ import annotations

import math
from copy import deepcopy
import pytest

from app.compare import compare_drawings
from app.models import Drawing, Entity
from app.rubric import default_rubric


def _line(entity_id: str, start: tuple[float, float], end: tuple[float, float], *, source: str = "reference", layer: str = "0") -> Entity:
    points = [tuple(start), tuple(end)]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer=layer,
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2),
    )


def _circle(entity_id: str, center: tuple[float, float], radius: float, *, source: str = "reference", layer: str = "0") -> Entity:
    x, y = center
    return Entity(
        id=entity_id,
        kind="circle",
        layer=layer,
        source=source,
        points=[tuple(center)],
        radius=radius,
        bbox=(x - radius, y - radius, x + radius, y + radius),
        centroid=tuple(center),
    )


def _polyline(entity_id: str, points: list[tuple[float, float]], *, source: str = "reference", layer: str = "0", closed: bool = False) -> Entity:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return Entity(
        id=entity_id,
        kind="polyline",
        layer=layer,
        source=source,
        points=[tuple(p) for p in points],
        closed=closed,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=(sum(xs) / len(xs), sum(ys) / len(ys)),
    )


def _drawing(*entities: Entity) -> Drawing:
    boxes = [e.bbox for e in entities]
    return Drawing(
        entities=list(entities),
        bbox=(
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
    )


def _rubric(mode: str = "translation"):
    return default_rubric().model_copy(update={"approved": True, "normalization_mode": mode})


# 1. Independently moved line with wrong length:
#    - Tolerant mode ignores position.
#    - Wrong length remains and is deducted once.
def test_adv01_independently_moved_line_with_wrong_length():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (0, 30), (50, 30), layer="WALL"),
        _line("R-3", (0, 60), (50, 60), layer="WALL"),
    )
    # S-1 moved by (+10, 0) and length increased from 50 to 70 (+20 length error)
    student = _drawing(
        _line("S-1", (10, 0), (80, 0), source="student", layer="WALL"),
        _line("S-2", (0, 30), (50, 30), source="student", layer="WALL"),
        _line("S-3", (0, 60), (50, 60), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 3
    assert len(tol_res["issues"]) == 1
    assert tol_res["issues"][0]["category"] == "incorrect_length"
    assert tol_res["issues"][0]["applied_deduction"] == 3.0
    assert tol_res["score"] == 97.0
    assert len(tol_res["suppressed_findings"]) == 1
    assert tol_res["suppressed_findings"][0]["category"] == "incorrect_position"
    assert tol_res["suppressed_findings"][0]["suppression_reason"] == "translation_tolerant_mode"

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["score"] == 94.0
    cats = {i["category"] for i in strict_res["issues"]}
    assert cats == {"incorrect_position", "incorrect_length"}


# 2. Independently moved line with wrong angle:
#    - Tolerant mode ignores position.
#    - Wrong angle remains.
def test_adv02_independently_moved_line_with_wrong_angle():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (0, 30), (50, 30), layer="WALL"),
        _line("R-3", (0, 60), (50, 60), layer="WALL"),
    )
    # S-1 moved by (+3, +3) and rotated 15 degrees
    ang = math.radians(15)
    dx = 50.0 * math.cos(ang)
    dy = 50.0 * math.sin(ang)
    student = _drawing(
        _line("S-1", (3, 3), (3 + dx, 3 + dy), source="student", layer="WALL"),
        _line("S-2", (0, 30), (50, 30), source="student", layer="WALL"),
        _line("S-3", (0, 60), (50, 60), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 3
    assert len(tol_res["issues"]) == 1
    assert tol_res["issues"][0]["category"] == "incorrect_angle"
    assert tol_res["issues"][0]["applied_deduction"] == 3.0
    assert tol_res["score"] == 97.0
    assert len(tol_res["suppressed_findings"]) == 1
    assert tol_res["suppressed_findings"][0]["category"] == "incorrect_position"

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["score"] == 94.0
    cats = {i["category"] for i in strict_res["issues"]}
    assert cats == {"incorrect_position", "incorrect_angle"}


# 3. Independently moved circle with wrong radius:
#    - Tolerant mode ignores position.
#    - Wrong radius remains.
def test_adv03_independently_moved_circle_with_wrong_radius():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (0, 30), (50, 30), layer="WALL"),
        _circle("R-3", (25, 15), 10.0, layer="FEATURE"),
    )
    # S-3 circle moved to (28, 17) (+3, +2) and radius changed from 10.0 to 15.0
    student = _drawing(
        _line("S-1", (0, 0), (50, 0), source="student", layer="WALL"),
        _line("S-2", (0, 30), (50, 30), source="student", layer="WALL"),
        _circle("S-3", (28, 17), 15.0, source="student", layer="FEATURE"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 3
    assert len(tol_res["issues"]) == 1
    assert tol_res["issues"][0]["category"] == "incorrect_radius"
    assert tol_res["issues"][0]["applied_deduction"] == 3.0
    assert tol_res["score"] == 97.0
    assert len(tol_res["suppressed_findings"]) == 1
    assert tol_res["suppressed_findings"][0]["category"] == "incorrect_position"

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["score"] == 94.0
    cats = {i["category"] for i in strict_res["issues"]}
    assert cats == {"incorrect_position", "incorrect_radius"}


# 4. Missing entity remains missing.
def test_adv04_missing_entity_remains_missing():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (50, 0), (50, 30), layer="WALL"),
        _line("R-3", (50, 30), (0, 30), layer="WALL"),
        _line("R-4", (0, 30), (0, 0), layer="WALL"),
    )
    # Student omits R-4
    student = _drawing(
        _line("S-1", (0, 0), (50, 0), source="student", layer="WALL"),
        _line("S-2", (50, 0), (50, 30), source="student", layer="WALL"),
        _line("S-3", (50, 30), (0, 30), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 3
    assert len(tol_res["issues"]) == 1
    assert tol_res["issues"][0]["category"] == "missing_geometry"
    assert tol_res["score"] == 95.0


# 5. Extra entity remains extra.
def test_adv05_extra_entity_remains_extra():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (50, 0), (50, 30), layer="WALL"),
    )
    # Student has extra line S-EXTRA
    student = _drawing(
        _line("S-1", (0, 0), (50, 0), source="student", layer="WALL"),
        _line("S-2", (50, 0), (50, 30), source="student", layer="WALL"),
        _line("S-EXTRA", (100, 100), (120, 100), source="student", layer="EXTRA"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 2
    assert any(i["category"] == "extra_geometry" for i in tol_res["issues"])
    assert tol_res["score"] == 98.0


# 6. Duplicate entity remains a duplicate.
def test_adv06_duplicate_entity_remains_a_duplicate():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="WALL"),
        _line("R-2", (50, 0), (50, 30), layer="WALL"),
    )
    # Student has S-1 and duplicate S-DUP coincident with S-1
    student = _drawing(
        _line("S-1", (0, 0), (50, 0), source="student", layer="WALL"),
        _line("S-DUP", (0, 0), (50, 0), source="student", layer="WALL"),
        _line("S-2", (50, 0), (50, 30), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 2
    assert any(i["category"] == "duplicate_geometry" for i in tol_res["issues"])
    assert tol_res["score"] == 99.0


# 7. Different entity type with similar size does not become a valid match.
def test_adv07_different_entity_type_does_not_become_valid_match():
    reference = _drawing(
        _circle("R-C", (0, 0), 10.0, layer="GEOM"),  # extent 20x20
        _line("R-L1", (50, 0), (100, 0), layer="WALL"),
        _line("R-L2", (100, 0), (100, 50), layer="WALL"),
    )
    # Student replaces circle with a line of length 20 (similar bounding size)
    student = _drawing(
        _line("S-LINE", (-10, 0), (10, 0), source="student", layer="GEOM"),
        _line("S-L1", (50, 0), (100, 0), source="student", layer="WALL"),
        _line("S-L2", (100, 0), (100, 50), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 2  # lines matched, circle not matched to line
    cats = {i["category"] for i in tol_res["issues"]}
    assert "missing_geometry" in cats
    assert "extra_geometry" in cats


# 8. Unrelated drawing remains suspicious/incompatible and withheld.
def test_adv08_unrelated_drawing_remains_suspicious_or_incompatible():
    from app.compatibility import assess_compatibility
    from app.scale_diagnostics import ScaleDiagnostic

    # Reference has 20 lines
    ref_entities = [_line(f"R-{i}", (i * 10, 0), (i * 10 + 8, 0)) for i in range(20)]
    reference = _drawing(*ref_entities)

    # Student has 2 completely disparate lines at distant coordinates
    student = _drawing(
        _line("S-1", (500, 500), (520, 500), source="student"),
        _line("S-2", (700, 700), (720, 700), source="student"),
    )

    comp = compare_drawings(reference, student, rubric=_rubric("translation"))
    scale = ScaleDiagnostic(False, None, 0, 0.0, "none", False)
    compat = assess_compatibility(reference, student, comp, scale)

    assert compat.compatibility_status in {"incompatible", "suspicious"}
    assert compat.grading_withheld is True


# 9. Uniform whole-drawing translation still scores correctly.
def test_adv09_uniform_whole_drawing_translation_scores_100():
    reference = _drawing(
        _line("R-1", (0, 0), (50, 0)),
        _line("R-2", (50, 0), (50, 30)),
        _line("R-3", (50, 30), (0, 30)),
        _line("R-4", (0, 30), (0, 0)),
        _circle("R-5", (25, 15), 5.0),
    )
    # Translate all entities uniformly by (+100.0, +50.0)
    student = _drawing(
        _line("S-1", (100, 50), (150, 50), source="student"),
        _line("S-2", (150, 50), (150, 80), source="student"),
        _line("S-3", (150, 80), (100, 80), source="student"),
        _line("S-4", (100, 80), (100, 50), source="student"),
        _circle("S-5", (125, 65), 5.0, source="student"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 5
    assert tol_res["score"] == 100.0
    assert len(tol_res["issues"]) == 0
    assert tol_res["normalization"]["student"]["translation"] == [-100.0, -50.0]
    assert tol_res["normalization"]["student"]["support_ratio"] == 1.0

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert strict_res["normalization"]["student"]["rejection_reason"] == "strict_mode"
    assert len(strict_res["issues"]) == 5
    assert all(i["category"] == "incorrect_position" for i in strict_res["issues"])


# 10. Multiple independently moved entities match correctly.
def test_adv10_multiple_independently_moved_entities_match_correctly():
    reference = _drawing(
        _line("R-1", (0, 0), (20, 0), layer="L1"),
        _line("R-2", (0, 30), (25, 30), layer="L2"),
        _line("R-3", (0, 60), (30, 60), layer="L3"),
        _circle("R-4", (50, 10), 8.0, layer="C1"),
        _circle("R-5", (50, 40), 12.0, layer="C2"),
        _line("R-6", (80, 0), (80, 40), layer="L4"),
    )
    # Displace each entity in different directions
    student = _drawing(
        _line("S-1", (15, 10), (35, 10), source="student", layer="L1"),       # shifted (+15, +10)
        _line("S-2", (-10, 40), (15, 40), source="student", layer="L2"),      # shifted (-10, +10)
        _line("S-3", (20, 80), (50, 80), source="student", layer="L3"),       # shifted (+20, +20)
        _circle("S-4", (70, -5), 8.0, source="student", layer="C1"),          # shifted (+20, -15)
        _circle("S-5", (30, 55), 12.0, source="student", layer="C2"),         # shifted (-20, +15)
        _line("S-6", (95, -10), (95, 30), source="student", layer="L4"),      # shifted (+15, -10)
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 6
    assert tol_res["score"] == 100.0
    assert len(tol_res["issues"]) == 0
    assert len(tol_res["suppressed_findings"]) == 6


# 11. Reordering otherwise identical student entities produces the same matches, findings, and score.
def test_adv11_reordering_student_entities_produces_identical_results():
    reference = _drawing(
        _line("R-1", (0, 0), (20, 0), layer="A"),
        _line("R-2", (0, 20), (30, 20), layer="B"),
        _line("R-3", (0, 40), (40, 40), layer="C"),
    )
    student1 = _drawing(
        _line("S-1", (10, 5), (30, 5), source="student", layer="A"),
        _line("S-2", (-5, 25), (25, 25), source="student", layer="B"),
        _line("S-3", (8, 48), (48, 48), source="student", layer="C"),
    )
    student2 = _drawing(*reversed(student1.entities))

    res1 = compare_drawings(reference, student1, rubric=_rubric("translation"))
    res2 = compare_drawings(reference, student2, rubric=_rubric("translation"))

    assert res1["score"] == res2["score"] == 100.0
    assert res1["match_count"] == res2["match_count"] == 3
    assert res1["issues"] == res2["issues"] == []
    assert len(res1["suppressed_findings"]) == len(res2["suppressed_findings"]) == 3


# 12. Repeated or ambiguous geometry is assigned deterministically.
def test_adv12_repeated_geometry_assigned_deterministically():
    # 3 identical circles at different positions
    reference = _drawing(
        _circle("R-C1", (0, 0), 5.0, layer="CIRCLES"),
        _circle("R-C2", (30, 0), 5.0, layer="CIRCLES"),
        _circle("R-C3", (60, 0), 5.0, layer="CIRCLES"),
    )
    # Student has 3 circles moved
    student = _drawing(
        _circle("S-C1", (0, 20), 5.0, source="student", layer="CIRCLES"),
        _circle("S-C2", (30, 25), 5.0, source="student", layer="CIRCLES"),
        _circle("S-C3", (60, 15), 5.0, source="student", layer="CIRCLES"),
    )

    first = compare_drawings(reference, student, rubric=_rubric("translation"))
    reordered_student = _drawing(*reversed(student.entities))
    second = compare_drawings(reference, reordered_student, rubric=_rubric("translation"))

    assert first["score"] == second["score"] == 100.0
    assert first["match_count"] == second["match_count"] == 3
    assert first["issues"] == second["issues"] == []


# 13. Strict-mode results remain unchanged for all relevant cases.
def test_adv13_strict_mode_results_remain_unchanged():
    reference = _drawing(
        _line("R-1", (0, 0), (20, 0), layer="L1"),
        _circle("R-2", (50, 50), 10.0, layer="C1"),
    )
    # Moved line and moved circle
    student = _drawing(
        _line("S-1", (5, 5), (25, 5), source="student", layer="L1"),
        _circle("S-2", (55, 55), 10.0, source="student", layer="C1"),
    )

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["score"] == 94.0  # 2 * -3
    assert len(strict_res["issues"]) == 2
    assert all(i["category"] == "incorrect_position" for i in strict_res["issues"])

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["score"] == 100.0
    assert len(tol_res["issues"]) == 0


# 14. Rubric repeat caps and category caps remain unchanged.
def test_adv14_rubric_repeat_and_category_caps_remain_unchanged():
    # Move 8 lines in disparate non-uniform directions so they become independent position errors
    offsets = [(5, 0), (-5, 0), (0, 5), (0, -5), (4, 4), (-4, -4), (3, -3), (-3, 3)]
    ref_lines = [_line(f"R-{i}", (0, i * 15), (50, i * 15)) for i in range(8)]
    student_lines = [_line(f"S-{i}", (dx, i * 15 + dy), (50 + dx, i * 15 + dy), source="student") for i, (dx, dy) in enumerate(offsets)]

    reference = _drawing(*ref_lines)
    student = _drawing(*student_lines)

    strict_res = compare_drawings(reference, student, rubric=_rubric("strict"))
    assert strict_res["score"] == 85.0
    issues = strict_res["issues"]
    assert len(issues) == 8
    applied = [i for i in issues if i["deduction_status"] == "applied"]
    capped = [i for i in issues if i["deduction_status"] == "capped"]
    assert len(applied) == 5
    assert len(capped) == 3
    assert sum(i["applied_deduction"] for i in issues) == 15.0

    # In translation mode, all 8 are suppressed
    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["score"] == 100.0
    assert len(tol_res["issues"]) == 0
    assert len(tol_res["suppressed_findings"]) == 8


# 15. Causal grouping prevents secondary position/topology symptoms from creating repeated deductions.
def test_adv15_causal_grouping_prevents_secondary_deductions():
    reference = _drawing(
        _line("R-1", (0, 0), (40, 0), layer="WALL"),
        _line("R-2", (40, 0), (40, 30), layer="WALL"),
        _line("R-3", (40, 30), (0, 30), layer="WALL"),
    )
    # S-1 translated (+10, +10) with length 60 instead of 40 (+20 length error)
    student = _drawing(
        _line("S-1", (10, 10), (70, 10), source="student", layer="WALL"),
        _line("S-2", (40, 0), (40, 30), source="student", layer="WALL"),
        _line("S-3", (40, 30), (0, 30), source="student", layer="WALL"),
    )

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["score"] == 97.0
    applied_issues = [i for i in tol_res["issues"] if i["applied_deduction"] > 0]
    assert len(applied_issues) == 1
    assert applied_issues[0]["category"] == "incorrect_length"
    assert applied_issues[0]["applied_deduction"] == 3.0

    # Secondary endpoint gaps are captured as supporting evidence with 0 deduction
    supporting_gaps = [i for i in tol_res["issues"] if i["category"] == "endpoint_gap"]
    assert len(supporting_gaps) > 0
    assert all(gap["applied_deduction"] == 0.0 for gap in supporting_gaps)

    # Secondary position error was suppressed
    assert len(tol_res["suppressed_findings"]) == 1
    assert tol_res["suppressed_findings"][0]["category"] == "incorrect_position"


# 16. Same-count unrelated drawing (10 horizontal vs 10 vertical lines) remains incompatible and withheld.
def test_adv16_same_count_unrelated_drawing_remains_incompatible():
    from app.compatibility import assess_compatibility
    from app.scale_diagnostics import ScaleDiagnostic

    ref = _drawing(*[_line(f"R-{i}", (0, i * 100), (50, i * 100), layer="A") for i in range(10)])
    stu = _drawing(*[_line(f"S-{i}", (i * 100, 0), (i * 100, 200), source="student", layer="B") for i in range(10)])

    rubric = _rubric("translation")
    comp = compare_drawings(ref, stu, rubric=rubric)
    scale = ScaleDiagnostic(False, None, 0, 0.0, "none", False)
    compat = assess_compatibility(ref, stu, comp, scale)

    assert compat.compatibility_status in {"incompatible", "suspicious"}
    assert compat.grading_withheld is True
    confident_matches = [m for m in comp.get("matches", []) if float(m.get("confidence", 0.0)) >= 0.75]
    assert len(confident_matches) == 0


# 17. Entity type matching: LINE vs POLYLINE must not cleanly match or score 100.
def test_adv17_line_vs_polyline_does_not_cross_match():
    reference = _drawing(_line("R-LINE", (0, 0), (50, 0), layer="WALL"))
    student = _drawing(_polyline("S-POLY", [(0, 0), (50, 0)], source="student", layer="WALL"))

    tol_res = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_res["match_count"] == 0
    categories = {i["category"] for i in tol_res["issues"]}
    assert "missing_geometry" in categories
    assert "extra_geometry" in categories
    assert tol_res["score"] < 100.0


# 18. Mostly wrong intrinsic geometry fails tolerant compatibility gate.
def test_adv18_mostly_wrong_intrinsic_geometry_fails_tolerant_gate():
    from app.compatibility import assess_compatibility
    from app.scale_diagnostics import ScaleDiagnostic

    ref = _drawing(*[_line(f"R-{i}", (0, i * 30), (50, i * 30), layer="WALL") for i in range(10)])
    student_entities = [
        _line("S-0", (10, 0), (60, 0), source="student", layer="WALL"),
        _line("S-1", (10, 30), (60, 30), source="student", layer="WALL"),
    ]
    for i in range(2, 10):
        student_entities.append(
            _line(f"S-{i}", (0, i * 30), (0, i * 30 + 200), source="student", layer="WALL")
        )
    stu = _drawing(*student_entities)

    rubric = _rubric("translation")
    comp = compare_drawings(ref, stu, rubric=rubric)
    scale = ScaleDiagnostic(False, None, 0, 0.0, "none", False)
    compat = assess_compatibility(ref, stu, comp, scale)

    assert compat.compatibility_status in {"incompatible", "suspicious"}
    assert compat.grading_withheld is True


# 19. Fallback default invariance: allow_fallback=True behaves identically to 5b8df0f.
def test_adv19_fallback_default_invariance_detects_position_error():
    from pathlib import Path
    from app.review_service import run_grading_pipeline

    fixture_dir = Path(__file__).parent / "fixtures" / "simple_audit"
    ref_path = fixture_dir / "00_reference_000-Simple.dxf"
    moved_path = fixture_dir / "04_moved_line_73B_plus20Y.dxf"
    assert ref_path.exists() and moved_path.exists(), "simple_audit fixtures missing"

    ref_bytes = ref_path.read_bytes()
    moved_bytes = moved_path.read_bytes()
    out = run_grading_pipeline(
        ref_bytes,
        moved_bytes,
        rubric_id=None,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={},
        reference_rubrics={},
        rubric_references={},
    )
    assert not out.compatibility.grading_withheld
    position_issues = [i for i in out.comparison["issues"] if i["category"] == "incorrect_position"]
    assert len(position_issues) == 1
    assert position_issues[0]["applied_deduction"] == 3.0
    assert out.comparison["score"] == 97.0


# 20. Strict override invariance: t002 strict instructor override grades 78.0 with 17 findings.
def test_adv20_strict_override_invariance_t002():
    from pathlib import Path
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_dir = Path(__file__).parent / "fixtures" / "ref_01"
    ref_path = ref_dir / "Ref-01.dxf"
    t002_path = ref_dir / "Ref-01-t002.dxf"
    if not ref_path.exists() or not t002_path.exists():
        pytest.skip("Ref-01 fixtures not found")

    ref_bytes = ref_path.read_bytes()
    t002_bytes = t002_path.read_bytes()
    ref_id = reference_fingerprint(ref_bytes)

    rubric = _rubric("strict")
    rid = "strict-t002-adv"

    out = run_grading_pipeline(
        ref_bytes,
        t002_bytes,
        rubric_id=rid,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rid: rubric},
        reference_rubrics={ref_id: rid},
        rubric_references={rid: ref_id},
        instructor_override=True,
    )
    assert out.compatibility.instructor_override is True
    assert not out.compatibility.grading_withheld
    assert out.comparison["score"] == 78.0
    assert len(out.comparison["matches"]) == 15
    assert len(out.comparison["issues"]) == 17


# 21. Line vs polyline on Path A (Strict): preserves baseline 5b8df0f (1 match, 100 score, 0 findings)
def test_adv21_line_vs_polyline_strict_path_a():
    ref = _drawing(_line("R-LINE", (0, 0), (50, 0), layer="WALL"))
    stu = _drawing(_polyline("S-POLY", [(0, 0), (50, 0)], source="student", layer="WALL"))
    res = compare_drawings(ref, stu, rubric=_rubric("strict"))
    assert res["match_count"] == 1
    assert res["score"] == 100.0
    assert len(res["issues"]) == 0


# 22. Line vs polyline on Path B (Explicit fallback): preserves baseline 5b8df0f (1 match, 100 score, 0 findings)
def test_adv22_line_vs_polyline_fallback_path_b():
    ref = _drawing(_line("R-LINE", (0, 0), (50, 0), layer="WALL"))
    stu = _drawing(_polyline("S-POLY", [(0, 0), (50, 0)], source="student", layer="WALL"))
    rubric = _rubric("translation")
    rubric.rubric_source = "explicit_fallback"
    res = compare_drawings(ref, stu, rubric=rubric)
    assert res["match_count"] == 1
    assert res["score"] == 100.0
    assert len(res["issues"]) == 0


# 23. Line vs polyline on Path C (Approved tolerant): rejects cross-type pair (0 matches, 93 score, missing + extra)
def test_adv23_line_vs_polyline_tolerant_path_c():
    ref = _drawing(_line("R-LINE", (0, 0), (50, 0), layer="WALL"))
    stu = _drawing(_polyline("S-POLY", [(0, 0), (50, 0)], source="student", layer="WALL"))
    rubric = _rubric("translation")
    rubric.rubric_source = "instructor_approved"
    res = compare_drawings(ref, stu, rubric=rubric)
    assert res["match_count"] == 0
    assert res["score"] == 93.0
    categories = {i["category"] for i in res["issues"]}
    assert "missing_geometry" in categories
    assert "extra_geometry" in categories


# 24. Exact 45-degree rotated lines counterexample through real pipeline: must be withheld (score is None)
def test_adv24_counterexample_45_degree_unrelated_lines_withheld():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        ref_ms.add_line((0, i * 100), (50, i * 100), dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    d = 50.0 / math.sqrt(2)
    for i in range(10):
        start = (1000 + i * 173, 2000 + i * 127)
        end = (start[0] + d, start[1] + d)
        stu_ms.add_line(start, end, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-45deg-test"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None
    assert out.compatibility.instructor_override is False


# 25. Nearby angles (30 deg, 60 deg) and reordered entities also fail tolerant gate and remain withheld
def test_adv25_counterexample_nearby_angles_and_reordered():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        ref_ms.add_line((0, i * 100), (60, i * 100), dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    # 30-degree rotation: cos(30)=sqrt(3)/2, sin(30)=0.5
    dx = 60.0 * (math.sqrt(3) / 2)
    dy = 60.0 * 0.5
    indices = list(range(10))
    indices.reverse()
    for i in indices:
        start = (500 + i * 131, 1500 + i * 197)
        end = (start[0] + dx, start[1] + dy)
        stu_ms.add_line(start, end, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-30deg-reordered"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None

    # 60-degree rotation: cos(60)=0.5, sin(60)=sqrt(3)/2
    dx60 = 60.0 * 0.5
    dy60 = 60.0 * (math.sqrt(3) / 2)
    stu_doc60 = ezdxf.new("R2010")
    stu_doc60.layers.add("WALL")
    stu_ms60 = stu_doc60.modelspace()
    for i in indices:
        start = (500 + i * 131, 1500 + i * 197)
        end = (start[0] + dx60, start[1] + dy60)
        stu_ms60.add_line(start, end, dxfattribs={"layer": "WALL"})
    stu_stream60 = io.StringIO()
    stu_doc60.write(stu_stream60)
    stu_bytes60 = stu_stream60.getvalue().encode("utf-8")

    out60 = run_grading_pipeline(
        ref_bytes,
        stu_bytes60,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out60.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out60.compatibility.grading_withheld is True
    assert out60.comparison.get("score") is None


# 26. Negative: 40x10 rectangles vs 25x25 squares (equal perimeter 100, 4 vertices) must be withheld
def test_adv26_counterexample_rectangle_vs_square_withheld():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(0, i * 100), (40, i * 100), (40, i * 100 + 10), (0, i * 100 + 10)]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(10):
        x = 1000 + i * 173
        y = 2000 + i * 127
        pts = [(x, y), (x + 25, y), (x + 25, y + 25), (x, y + 25)]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-rect-sq-adversarial"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None
    # Confirm different shapes do not receive perfect match quality
    matches = out.comparison.get("matches", [])
    assert len(matches) == 10
    for m in matches:
        assert float(m.get("match_quality", 0.0)) < 0.85


# 27. Positive: 40x10 rectangles independently placed score 100 and pass compatibility
def test_adv27_positive_rectangles_independently_placed_scores_100():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(0, i * 100), (40, i * 100), (40, i * 100 + 10), (0, i * 100 + 10)]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(10):
        x = 1000 + i * 173
        y = 2000 + i * 127
        pts = [(x, y), (x + 40, y), (x + 40, y + 10), (x, y + 10)]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-rect-pos"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status == "compatible"
    assert out.compatibility.grading_withheld is False
    assert out.comparison.get("score") == 100.0
    assert len(out.comparison.get("matches", [])) == 10
    assert len(out.comparison.get("issues", [])) == 0


# 28. Equivalent vertex representation: cyclically shifted start and reversed vertex traversal
def test_adv28_positive_rectangles_cyclically_shifted_and_reversed():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(0, i * 100), (40, i * 100), (40, i * 100 + 10), (0, i * 100 + 10)]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(10):
        x = 1000 + i * 173
        y = 2000 + i * 127
        pts = [(x, y), (x + 40, y), (x + 40, y + 10), (x, y + 10)]
        if i % 2 == 1:
            pts = list(reversed(pts))
        shift = i % 4
        pts = pts[shift:] + pts[:shift]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-rect-shifted"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status == "compatible"
    assert out.compatibility.grading_withheld is False
    assert out.comparison.get("score") == 100.0
    assert len(out.comparison.get("matches", [])) == 10
    assert len(out.comparison.get("issues", [])) == 0


# 29. Generalization: 8 30x20 rectangles vs 45x5 rectangles (equal perimeter 100) must be withheld
def test_adv29_generalization_unequal_rectangle_proportions_withheld():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(8):
        pts = [(0, i * 120), (30, i * 120), (30, i * 120 + 20), (0, i * 120 + 20)]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(8):
        x = 800 + i * 239
        y = 1200 + i * 149
        pts = [(x, y), (x + 45, y), (x + 45, y + 5), (x, y + 5)]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-rect-gen"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None
    matches = out.comparison.get("matches", [])
    assert len(matches) == 8
    for m in matches:
        assert float(m.get("match_quality", 0.0)) < 0.85


# 30. Entity ordering invariance in negative and positive cases
def test_adv30_reordered_student_entities_invariance():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    # Common Reference
    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(0, i * 100), (40, i * 100), (40, i * 100 + 10), (0, i * 100 + 10)]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")
    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")
    rubric_id = "r-reorder-invariance"

    indices = list(range(10))
    indices.reverse()

    # Reordered Negative Case (Squares)
    stu_neg_doc = ezdxf.new("R2010")
    stu_neg_doc.layers.add("WALL")
    stu_neg_ms = stu_neg_doc.modelspace()
    for i in indices:
        x = 1000 + i * 173
        y = 2000 + i * 127
        pts = [(x, y), (x + 25, y), (x + 25, y + 25), (x, y + 25)]
        stu_neg_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_neg_stream = io.StringIO()
    stu_neg_doc.write(stu_neg_stream)
    stu_neg_bytes = stu_neg_stream.getvalue().encode("utf-8")

    out_neg = run_grading_pipeline(
        ref_bytes,
        stu_neg_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out_neg.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out_neg.compatibility.grading_withheld is True
    assert out_neg.comparison.get("score") is None

    # Reordered Positive Case (Rectangles)
    stu_pos_doc = ezdxf.new("R2010")
    stu_pos_doc.layers.add("WALL")
    stu_pos_ms = stu_pos_doc.modelspace()
    for i in indices:
        x = 1000 + i * 173
        y = 2000 + i * 127
        pts = [(x, y), (x + 40, y), (x + 40, y + 10), (x, y + 10)]
        stu_pos_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_pos_stream = io.StringIO()
    stu_pos_doc.write(stu_pos_stream)
    stu_pos_bytes = stu_pos_stream.getvalue().encode("utf-8")

    out_pos = run_grading_pipeline(
        ref_bytes,
        stu_pos_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out_pos.compatibility.compatibility_status == "compatible"
    assert out_pos.compatibility.grading_withheld is False
    assert out_pos.comparison.get("score") == 100.0
    assert len(out_pos.comparison.get("matches", [])) == 10
    assert len(out_pos.comparison.get("issues", [])) == 0


# 31. Exact negative case: 8-vertex 40x10 rectangles vs 9-vertex 25x25 squares (equal perimeter 100) must be withheld
def test_adv31_counterexample_unequal_vertex_rectangle_vs_square_withheld():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_local = [(0, 0), (20, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]
    stu_local = [(0, 0), (25/3, 0), (50/3, 0), (25, 0), (25, 12.5), (25, 25), (12.5, 25), (0, 25), (0, 12.5)]

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(x, y + i * 100) for x, y in ref_local]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")
    ref_id = reference_fingerprint(ref_bytes)

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(10):
        pts = [(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in stu_local]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    rubric = _rubric("translation")
    rubric_id = "r-unequal-rect-sq"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None


# 32. Same-boundary positive control: 8-vertex reference rectangle vs 9-vertex student rectangle (same geometry)
def test_adv32_positive_unequal_vertex_rectangles_score_reported():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_local = [(0, 0), (20, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]
    stu_local = [(0, 0), (40/3, 0), (80/3, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]

    ref_doc = ezdxf.new("R2010")
    ref_doc.layers.add("WALL")
    ref_ms = ref_doc.modelspace()
    for i in range(10):
        pts = [(x, y + i * 100) for x, y in ref_local]
        ref_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    ref_stream = io.StringIO()
    ref_doc.write(ref_stream)
    ref_bytes = ref_stream.getvalue().encode("utf-8")
    ref_id = reference_fingerprint(ref_bytes)

    stu_doc = ezdxf.new("R2010")
    stu_doc.layers.add("WALL")
    stu_ms = stu_doc.modelspace()
    for i in range(10):
        pts = [(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in stu_local]
        stu_ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
    stu_stream = io.StringIO()
    stu_doc.write(stu_stream)
    stu_bytes = stu_stream.getvalue().encode("utf-8")

    rubric = _rubric("translation")
    rubric_id = "r-same-rect-unequal-v"

    out = run_grading_pipeline(
        ref_bytes,
        stu_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )

    assert out.compatibility.compatibility_status == "compatible"
    assert out.compatibility.grading_withheld is False
    assert len(out.comparison.get("matches", [])) == 10
    # Boundary similarity recognizes unchanged geometry despite unequal subdivision
    for m in out.comparison.get("matches", []):
        assert m.get("match_quality", 0.0) >= 0.85
    # Existing scoring contract is preserved; 10 shape findings capped at 15 points
    assert out.comparison.get("score") == 85.0
    issues = out.comparison.get("issues", [])
    assert len(issues) == 10
    assert all(iss.get("category") == "incorrect_shape" for iss in issues)


# 33. Representation invariance: cyclic shift, reversed traversal, and reordering
def test_adv33_unequal_vertex_representation_invariance():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_local = [(0, 0), (20, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]
    neg_stu_local = [(0, 0), (25/3, 0), (50/3, 0), (25, 0), (25, 12.5), (25, 25), (12.5, 25), (0, 25), (0, 12.5)]
    pos_stu_local = [(0, 0), (40/3, 0), (80/3, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]

    def make_dxf(entities_points):
        doc = ezdxf.new("R2010")
        doc.layers.add("WALL")
        ms = doc.modelspace()
        for pts in entities_points:
            ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")

    ref_entities = [[(x, y + i * 100) for x, y in ref_local] for i in range(10)]
    ref_bytes = make_dxf(ref_entities)
    ref_id = reference_fingerprint(ref_bytes)
    rubric = _rubric("translation")

    def run_check(stu_pts_list, rubric_suffix):
        rubric_id = f"r-inv-{rubric_suffix}"
        return run_grading_pipeline(
            ref_bytes,
            make_dxf(stu_pts_list),
            rubric_id=rubric_id,
            allow_fallback=True,
            position_tolerance=2.0,
            length_tolerance=1.0,
            angle_tolerance=3.0,
            dimension_tolerance=1.0,
            radius_tolerance=1.0,
            rubrics={rubric_id: rubric},
            reference_rubrics={ref_id: rubric_id},
            rubric_references={rubric_id: ref_id},
        )

    # Negative variations: must remain suspicious/incompatible and withheld
    # 1. Reversed traversal
    neg_rev = [[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in reversed(neg_stu_local)] for i in range(10)]
    out_neg_rev = run_check(neg_rev, "neg-rev")
    assert out_neg_rev.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out_neg_rev.compatibility.grading_withheld is True
    assert out_neg_rev.comparison.get("score") is None

    # 2. Cyclically shifted
    neg_shift = neg_stu_local[3:] + neg_stu_local[:3]
    neg_cyclic = [[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in neg_shift] for i in range(10)]
    out_neg_cyc = run_check(neg_cyclic, "neg-cyc")
    assert out_neg_cyc.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out_neg_cyc.compatibility.grading_withheld is True
    assert out_neg_cyc.comparison.get("score") is None

    # 3. Entity reordered
    neg_reord = list(reversed(neg_rev))
    out_neg_reord = run_check(neg_reord, "neg-reord")
    assert out_neg_reord.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out_neg_reord.compatibility.grading_withheld is True
    assert out_neg_reord.comparison.get("score") is None

    # Positive variations: must remain compatible, not withheld, 10 matches, score 85.0
    # 1. Reversed traversal
    pos_rev = [[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in reversed(pos_stu_local)] for i in range(10)]
    out_pos_rev = run_check(pos_rev, "pos-rev")
    assert out_pos_rev.compatibility.compatibility_status == "compatible"
    assert out_pos_rev.compatibility.grading_withheld is False
    assert len(out_pos_rev.comparison.get("matches", [])) == 10
    assert out_pos_rev.comparison.get("score") == 85.0

    # 2. Cyclically shifted
    pos_shift = pos_stu_local[3:] + pos_stu_local[:3]
    pos_cyclic = [[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in pos_shift] for i in range(10)]
    out_pos_cyc = run_check(pos_cyclic, "pos-cyc")
    assert out_pos_cyc.compatibility.compatibility_status == "compatible"
    assert out_pos_cyc.compatibility.grading_withheld is False
    assert len(out_pos_cyc.comparison.get("matches", [])) == 10
    assert out_pos_cyc.comparison.get("score") == 85.0

    # 3. Entity reordered
    pos_reord = list(reversed(pos_rev))
    out_pos_reord = run_check(pos_reord, "pos-reord")
    assert out_pos_reord.compatibility.compatibility_status == "compatible"
    assert out_pos_reord.compatibility.grading_withheld is False
    assert len(out_pos_reord.comparison.get("matches", [])) == 10
    assert out_pos_reord.comparison.get("score") == 85.0


# 34. Generalization: different subdivision counts and another unequal-proportion rectangle pair
def test_adv34_unequal_vertex_generalization():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    # Case 1: 30x20 rect vs 45x5 rect (both perimeter 100, different proportions)
    r_30_20 = [(0, 0), (30, 0), (30, 20), (0, 20)]
    s_45_5 = [(0, 0), (45, 0), (45, 5), (0, 5)]

    def make_dxf(pts_list):
        doc = ezdxf.new("R2010")
        doc.layers.add("WALL")
        ms = doc.modelspace()
        for pts in pts_list:
            ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")

    ref_dxf = make_dxf([[(x, y + i * 100) for x, y in r_30_20] for i in range(10)])
    stu_dxf = make_dxf([[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in s_45_5] for i in range(10)])
    ref_id = reference_fingerprint(ref_dxf)

    rubric = _rubric("translation")
    rubric_id = "r-gen-proportions"

    out = run_grading_pipeline(
        ref_dxf,
        stu_dxf,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None

    # Case 2: 8-vertex reference rectangle vs 12-vertex student rectangle (further subdivisions of same shape)
    ref_8 = [(0, 0), (20, 0), (40, 0), (40, 5), (40, 10), (20, 10), (0, 10), (0, 5)]
    s_12 = [(0, 0), (10, 0), (20, 0), (30, 0), (40, 0), (40, 5), (40, 10), (30, 10), (20, 10), (10, 10), (0, 10), (0, 5)]

    ref_12_dxf = make_dxf([[(x, y + i * 100) for x, y in ref_8] for i in range(10)])
    stu_12_dxf = make_dxf([[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in s_12] for i in range(10)])
    ref_12_id = reference_fingerprint(ref_12_dxf)
    rubric_12_id = "r-gen-12v"

    out_12 = run_grading_pipeline(
        ref_12_dxf,
        stu_12_dxf,
        rubric_id=rubric_12_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_12_id: rubric},
        reference_rubrics={ref_12_id: rubric_12_id},
        rubric_references={rubric_12_id: ref_12_id},
    )
    assert out_12.compatibility.compatibility_status == "compatible"
    assert out_12.compatibility.grading_withheld is False
    assert len(out_12.comparison.get("matches", [])) == 10


# 35. Unequal counts after removing collinear points: genuine corners remain unequal
def test_adv35_unequal_counts_after_collinear_removal():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    # 4-vertex rectangle (40x10, perimeter 100) vs 6-vertex L-shape (perimeter 100)
    # Neither has collinear redundant vertices; their canonical corner counts are genuinely 4 vs 6.
    ref_rect = [(0, 0), (40, 0), (40, 10), (0, 10)]
    stu_l_shape = [(0, 0), (25, 0), (25, 10), (10, 10), (10, 25), (0, 25)]

    def make_dxf(pts_list):
        doc = ezdxf.new("R2010")
        doc.layers.add("WALL")
        ms = doc.modelspace()
        for pts in pts_list:
            ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")

    ref_dxf = make_dxf([[(x, y + i * 100) for x, y in ref_rect] for i in range(10)])
    stu_dxf = make_dxf([[(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in stu_l_shape] for i in range(10)])
    ref_id = reference_fingerprint(ref_dxf)

    rubric = _rubric("translation")
    rubric_id = "r-unequal-canonical-corners"

    out = run_grading_pipeline(
        ref_dxf,
        stu_dxf,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out.compatibility.compatibility_status in {"suspicious", "incompatible"}
    assert out.compatibility.grading_withheld is True
    assert out.comparison.get("score") is None


# 36. Preserve existing positive controls: identical 4-vertex rectangles translated independently score 100
def test_adv36_preserve_existing_positive_controls_four_vertex_rectangles():
    import io
    import ezdxf
    from app.review_service import run_grading_pipeline, reference_fingerprint

    ref_4 = [(0, 0), (40, 0), (40, 10), (0, 10)]

    def make_dxf(pts_list):
        doc = ezdxf.new("R2010")
        doc.layers.add("WALL")
        ms = doc.modelspace()
        for pts in pts_list:
            ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "WALL"})
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")

    ref_dxf = make_dxf([[(x, y + i * 100) for x, y in ref_4] for i in range(10)])
    cyclic_4 = ref_4[2:] + ref_4[:2]
    rev_4 = list(reversed(ref_4))
    stu_entities = []
    for i in range(10):
        shape = rev_4 if i % 3 == 1 else (cyclic_4 if i % 3 == 2 else ref_4)
        stu_entities.append([(x + 1000 + i * 173, y + 2000 + i * 127) for x, y in shape])
    stu_dxf = make_dxf(stu_entities)
    ref_id = reference_fingerprint(ref_dxf)

    rubric = _rubric("translation")
    rubric_id = "r-pos-4v-100"

    out = run_grading_pipeline(
        ref_dxf,
        stu_dxf,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
    )
    assert out.compatibility.compatibility_status == "compatible"
    assert out.compatibility.grading_withheld is False
    assert len(out.comparison.get("matches", [])) == 10
    assert len(out.comparison.get("issues", [])) == 0
    assert out.comparison.get("score") == 100.0
