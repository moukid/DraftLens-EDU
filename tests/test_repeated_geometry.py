from copy import deepcopy
from pathlib import Path

from app.compare import compare_drawings
from app.dxf import parse_dxf_bytes
from app.models import Drawing, Entity
from app.rubric import default_rubric


FIXTURES = Path(__file__).parent / "fixtures" / "simple_audit-II"


def _rubric(mode="translation"):
    return default_rubric().model_copy(
        update={"approved": True, "normalization_mode": mode}
    )


def _fixture_drawing(filename, source):
    return parse_dxf_bytes(
        (FIXTURES / filename).read_bytes(), source=source, normalize=True
    )


def _arc(entity_id, center, *, source="reference"):
    x, y = center
    radius = 10.0
    return Entity(
        id=entity_id,
        kind="arc",
        layer="arcs",
        source=source,
        points=[(x, y)],
        radius=radius,
        start_angle=15.0,
        end_angle=135.0,
        bbox=(x - radius, y - radius, x + radius, y + radius),
        centroid=(x, y),
    )


def _drawing(*entities):
    return Drawing(
        entities=list(entities),
        bbox=(
            min(entity.bbox[0] for entity in entities),
            min(entity.bbox[1] for entity in entities),
            max(entity.bbox[2] for entity in entities),
            max(entity.bbox[3] for entity in entities),
        ),
    )


def _repeated_arcs(centers, source):
    prefix = "R" if source == "reference" else "S"
    return _drawing(
        *(
            _arc(f"{prefix}-{index}", center, source=source)
            for index, center in enumerate(centers, 1)
        )
    )


def test_three_repeated_arcs_exact_copy_scores_100():
    reference = _repeated_arcs(((0, 0), (30, 0), (60, 0)), "reference")
    student = _repeated_arcs(((0, 0), (30, 0), (60, 0)), "student")

    result = compare_drawings(reference, student, rubric=_rubric())

    assert result["score"] == 100
    assert result["match_count"] == 3
    assert result["issues"] == []


def test_three_repeated_arcs_accept_consistent_translation():
    reference = _repeated_arcs(((0, 0), (30, 0), (60, 0)), "reference")
    student = _repeated_arcs(((20, 10), (50, 10), (80, 10)), "student")

    result = compare_drawings(reference, student, rubric=_rubric())

    assert result["normalization"]["student"]["translation"] == [-20.0, -10.0]
    assert result["normalization"]["student"]["support_count"] == 3
    assert result["score"] == 100
    assert result["issues"] == []


def test_two_locally_moved_repeated_arcs_become_position_issues():
    reference = _repeated_arcs(((0, 0), (30, 0), (60, 0)), "reference")
    student = _repeated_arcs(((0, 0), (50, 0), (80, 0)), "student")

    strict_result = compare_drawings(reference, student, rubric=_rubric("strict"))
    categories = [issue["category"] for issue in strict_result["issues"]]

    assert strict_result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert strict_result["match_count"] == 3
    assert categories == ["incorrect_position", "incorrect_position"]
    assert "missing_geometry" not in categories
    assert "extra_geometry" not in categories
    assert strict_result["score"] == 94

    tol_result = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert tol_result["match_count"] == 3
    assert tol_result["score"] == 100
    assert tol_result["issues"] == []
    assert len(tol_result["suppressed_findings"]) == 2


def test_repeated_arc_matching_is_stable_when_student_order_is_reversed():
    reference = _repeated_arcs(((0, 0), (30, 0), (60, 0)), "reference")
    student = _repeated_arcs(((0, 0), (50, 0), (80, 0)), "student")
    reordered = deepcopy(student)
    reordered.entities.reverse()

    for mode in ("strict", "translation"):
        first = compare_drawings(reference, student, rubric=_rubric(mode))
        second = compare_drawings(reference, reordered, rubric=_rubric(mode))

        assert second["score"] == first["score"]
        assert second["matches"] == first["matches"]
        assert second["issues"] == first["issues"]


def test_repeated_arc_count_shortage_leaves_only_actual_missing_remainder():
    reference = _repeated_arcs(((0, 0), (30, 0)), "reference")
    student = _repeated_arcs(((50, 0),), "student")

    result = compare_drawings(reference, student, rubric=_rubric("strict"))
    categories = [issue["category"] for issue in result["issues"]]

    assert result["match_count"] == 1
    assert categories.count("missing_geometry") == 1
    assert categories.count("extra_geometry") == 0


def test_repeated_arc_surplus_leaves_only_actual_extra_remainder():
    reference = _repeated_arcs(((0, 0),), "reference")
    student = _repeated_arcs(((20, 0), (50, 0)), "student")

    result = compare_drawings(reference, student, rubric=_rubric("strict"))
    categories = [issue["category"] for issue in result["issues"]]

    assert result["match_count"] == 1
    assert categories.count("missing_geometry") == 0
    assert categories.count("extra_geometry") == 1


def test_manual_arc_fixtures_preserve_translation_and_localize_two_moves():
    reference = _fixture_drawing("01-ARC-Reference.dxf", "reference")
    exact = _fixture_drawing("01-ARC-Student-OK.dxf", "student")
    all_moved = _fixture_drawing("01-ARC-All-Moved.dxf", "student")
    two_moved = _fixture_drawing("01-ARC-TwoOnly-Moved.dxf", "student")

    exact_result = compare_drawings(reference, exact, rubric=_rubric())
    translated_result = compare_drawings(reference, all_moved, rubric=_rubric())
    local_result = compare_drawings(reference, two_moved, rubric=_rubric("strict"))
    local_categories = [issue["category"] for issue in local_result["issues"]]

    assert exact_result["score"] == 100
    assert translated_result["score"] == 100
    assert translated_result["normalization"]["student"]["translation"] != [0.0, 0.0]
    assert local_result["score"] == 94
    assert local_result["match_count"] == 3
    assert local_categories == ["incorrect_position", "incorrect_position"]

    local_tol = compare_drawings(reference, two_moved, rubric=_rubric("translation"))
    assert local_tol["score"] == 100
    assert local_tol["match_count"] == 3
    assert local_tol["issues"] == []


def test_manual_all_moved_arcs_remain_position_errors_in_strict_mode():
    reference = _fixture_drawing("01-ARC-Reference.dxf", "reference")
    student = _fixture_drawing("01-ARC-All-Moved.dxf", "student")

    result = compare_drawings(reference, student, rubric=_rubric("strict"))
    categories = [issue["category"] for issue in result["issues"]]

    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert result["match_count"] == 3
    assert categories == ["incorrect_position", "incorrect_position", "incorrect_position"]
    assert "missing_geometry" not in categories
    assert "extra_geometry" not in categories
