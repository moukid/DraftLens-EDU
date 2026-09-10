from pathlib import Path
from app.compare import compare_drawings
from app.dxf import parse_dxf_path
from app.models import Drawing, Entity
from app.rubric import default_rubric
S=Path(__file__).parents[1]/"samples"
def test_good_scores_full(): assert compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_good.dxf"))["score"]==100
def test_missing_wall_detected(): assert "MISSING_WALL" in {i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_missing_wall.dxf"))["issues"]}
def test_door_window_detected():
 c={i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_door_window_errors.dxf"))["issues"]}; assert {"DOOR_SWING","WINDOW_GEOMETRY"}<=c


def test_missing_entity_has_nullable_measurement_and_feedback():
 result=compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_missing_wall.dxf",source="student"))
 issue=next(i for i in result["issues"] if i["category"]=="missing_geometry")
 assert issue["measurement"] is None
 assert issue["expected"] is None and issue["actual"] is None
 assert issue["technical_feedback"]

def _line(entity_id, start, end, *, source="reference", layer=None):
    points = [tuple(start), tuple(end)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer=layer or entity_id,
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2),
    )


def _circle(entity_id, center, radius, *, source="reference", layer=None):
    x, y = center
    return Entity(
        id=entity_id,
        kind="circle",
        layer=layer or entity_id,
        source=source,
        points=[tuple(center)],
        radius=radius,
        bbox=(x - radius, y - radius, x + radius, y + radius),
        centroid=tuple(center),
    )


def _drawing(*entities):
    boxes = [entity.bbox for entity in entities]
    return Drawing(
        entities=list(entities),
        bbox=(
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
    )


def _approved_rubric(mode="translation"):
    return default_rubric().model_copy(
        update={"approved": True, "normalization_mode": mode}
    )


def test_strict_mode_preserves_coordinates_and_applies_zero_translation():
    reference = _drawing(_line("R-1", (-10, -5), (0, -5), layer="wall"))
    student = _drawing(
        _line("S-1", (-5, -5), (5, -5), source="student", layer="wall")
    )
    original_points = list(student.entities[0].points)

    result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))

    assert result["normalization"]["reference"]["translation"] == [0.0, 0.0]
    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert result["normalization"]["student"]["rejection_reason"] == "strict_mode"
    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_position"
    ]
    assert student.entities[0].points == original_points


def test_translation_mode_uses_multi_entity_consensus():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 50), (25, 50), layer="c"),
    )
    student = _drawing(
        _line("S-1", (30, -12), (40, -12), source="student", layer="a"),
        _line("S-2", (30, 8), (45, 8), source="student", layer="b"),
        _line("S-3", (30, 38), (55, 38), source="student", layer="c"),
    )
    original_points = [list(entity.points) for entity in student.entities]

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-30.0, 12.0]
    assert normalization["support_count"] == 3
    assert normalization["support_ratio"] == 1.0
    assert normalization["rejection_reason"] is None
    assert result["score"] == 100
    assert result["issues"] == []
    assert [entity.points for entity in student.entities] == original_points


def test_translation_consensus_rejects_displacement_outlier():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _line("R-4", (0, 60), (25, 60), layer="d"),
        _circle("R-5", (80, 30), 6, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (12, 7), (22, 7), source="student", layer="a"),
        _line("S-2", (12, 27), (27, 27), source="student", layer="b"),
        _line("S-3", (12, 47), (32, 47), source="student", layer="c"),
        _line("S-4", (12, 67), (37, 67), source="student", layer="d"),
        _circle("S-5", (120, 37), 6, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-12.0, -7.0]
    assert normalization["support_count"] == 4
    assert normalization["evidence_count"] == 5
    assert normalization["support_ratio"] == 0.8


def test_one_moved_entity_does_not_create_global_transform():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _circle("R-4", (60, 20), 5, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="a"),
        _line("S-2", (0, 20), (15, 20), source="student", layer="b"),
        _line("S-3", (0, 40), (20, 40), source="student", layer="c"),
        _circle("S-4", (68, 20), 5, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric("translation"))

    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert (
        result["normalization"]["student"]["rejection_reason"]
        == "consensus_translation_within_position_tolerance"
    )
    assert result["issues"] == []
    assert len(result["suppressed_findings"]) == 1
    assert result["suppressed_findings"][0]["category"] == "incorrect_position"
    assert result["match_count"] == 4

    strict_result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))
    assert [issue["category"] for issue in strict_result["issues"]] == [
        "incorrect_position"
    ]
    assert strict_result["match_count"] == 4


def test_one_resized_extreme_entity_does_not_create_global_transform():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _circle("R-4", (-100, -100), 50, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="a"),
        _line("S-2", (0, 20), (15, 20), source="student", layer="b"),
        _line("S-3", (0, 40), (20, 40), source="student", layer="c"),
        _circle("S-4", (-100, -100), 40, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert result["match_count"] == 4
    assert not [
        issue
        for issue in result["issues"]
        if issue["category"] == "incorrect_position"
    ]


def test_majority_rigid_translation_is_accepted():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _line("R-4", (0, 60), (25, 60), layer="d"),
        _line("R-5", (0, 80), (30, 80), layer="e"),
    )
    student = _drawing(
        _line("S-1", (20, -6), (30, -6), source="student", layer="a"),
        _line("S-2", (20, 14), (35, 14), source="student", layer="b"),
        _line("S-3", (20, 34), (40, 34), source="student", layer="c"),
        _line("S-4", (20, 54), (45, 54), source="student", layer="d"),
        _line("S-5", (45, 74), (75, 74), source="student", layer="e"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-20.0, 6.0]
    assert normalization["support_count"] == 4
    assert normalization["support_ratio"] == 0.8
    assert normalization["rejection_reason"] is None


def test_insufficient_transform_support_is_rejected():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
    )
    student = _drawing(
        _line("S-1", (30, 5), (40, 5), source="student", layer="a"),
        _line("S-2", (30, 25), (45, 25), source="student", layer="b"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["candidate_translation"] == [-30.0, -5.0]
    assert normalization["translation"] == [0.0, 0.0]
    assert normalization["support_count"] == 2
    assert normalization["rejection_reason"] == "insufficient_support"


def test_repeated_geometry_matching_is_deterministic():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="same"),
        _line("R-2", (0, 0), (10, 0), layer="same"),
        _line("R-3", (0, 20), (20, 20), layer="unique"),
    )
    first_student = _drawing(
        _line("S-2", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-1", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-3", (0, 20), (20, 20), source="student", layer="unique"),
    )
    second_student = _drawing(*reversed(first_student.entities))

    first = compare_drawings(reference, first_student, rubric=_approved_rubric())
    repeated = compare_drawings(reference, first_student, rubric=_approved_rubric())
    reordered = compare_drawings(reference, second_student, rubric=_approved_rubric())

    assert first["matches"] == repeated["matches"]
    assert first["matches"] == reordered["matches"]


def test_exact_matches_are_locked_before_approximate_matching():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="same"),
        _line("R-2", (0, 4), (10, 4), layer="same"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-2", (0, 7), (10, 7), source="student", layer="same"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())
    matches = {
        item["reference_entity_id"]: item["student_entity_id"]
        for item in result["matches"]
    }

    assert matches["R-1"] == "S-1"
    assert matches["R-2"] == "S-2"


def test_reversed_line_endpoints_are_exactly_equivalent():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="wall")
    )
    student = _drawing(
        _line("S-1", (10, 0), (0, 0), source="student", layer="wall")
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))

    assert result["score"] == 100
    assert result["issues"] == []
    assert result["matches"][0]["confidence"] == 1.0
