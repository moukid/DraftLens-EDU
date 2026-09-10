from app.compare import compare_drawings
from app.models import Drawing, Entity
from app.rubric import default_rubric


def line(entity_id, start, end, *, source="reference", layer=None):
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


def circle(entity_id, center, radius, *, source="reference", layer=None):
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


def drawing(*entities):
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


def rubric(mode: str = "strict"):
    return default_rubric().model_copy(update={"approved": True, "normalization_mode": mode})


def test_moved_and_resized_circle_keeps_two_independent_primary_errors():
    reference = drawing(circle("R-1", (0, 0), 10, layer="circle"))
    student = drawing(
        circle("S-1", (3, 0), 8.5, source="student", layer="circle")
    )

    result = compare_drawings(reference, student, rubric=rubric())

    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_position",
        "incorrect_radius",
    ]
    assert all(issue["classification"] == "primary" for issue in result["issues"])
    assert result["deduction"] == 6
    assert result["score"] == 94


def test_translated_and_resized_line_keeps_two_independent_primary_errors():
    reference = drawing(line("R-1", (0, 0), (100, 0), layer="wall"))
    student = drawing(
        line("S-1", (5, 5), (125, 5), source="student", layer="wall")
    )

    result = compare_drawings(reference, student, rubric=rubric())

    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_position",
        "incorrect_length",
    ]
    assert result["deduction"] == 6
    assert result["score"] == 94
    assert result["suppressed_findings"] == []


def test_separate_errors_on_two_entities_keep_separate_deductions():
    reference = drawing(
        line("R-1", (0, 0), (20, 0), layer="first"),
        line("R-2", (0, 30), (30, 30), layer="second"),
    )
    student = drawing(
        line("S-1", (0, 5), (20, 5), source="student", layer="first"),
        line("S-2", (0, 30), (20, 30), source="student", layer="second"),
    )

    result = compare_drawings(reference, student, rubric=rubric())

    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_position",
        "incorrect_length",
    ]
    assert {issue["student_entity_id"] for issue in result["issues"]} == {
        "S-1",
        "S-2",
    }
    assert result["deduction"] == 6


def test_rule_caps_apply_after_causal_consolidation():
    active_rubric = rubric()
    position_rule = next(
        rule
        for category in active_rubric.categories
        for rule in category.rules
        if rule.check == "incorrect_position"
    )
    position_rule.repeat_cap = 4
    reference = drawing(
        line("R-1", (0, 0), (20, 0), layer="first"),
        line("R-2", (0, 30), (30, 30), layer="second"),
    )
    student = drawing(
        line("S-1", (0, 5), (20, 5), source="student", layer="first"),
        line("S-2", (0, 35), (30, 35), source="student", layer="second"),
    )

    result = compare_drawings(reference, student, rubric=active_rubric)
    applied = [
        entry["applied"]
        for entry in result["audit_trail"]
        if entry.get("rule_id") == position_rule.id
    ]

    assert applied == [3.0, 1.0]
    assert result["deduction"] == 4
    assert result["score"] == 96


def test_category_caps_apply_after_causal_consolidation():
    active_rubric = rubric()
    geometry = next(
        category
        for category in active_rubric.categories
        if category.id == "geometry"
    )
    geometry.max_deduction = 4
    reference = drawing(
        line("R-1", (0, 0), (20, 0), layer="first"),
        line("R-2", (0, 30), (30, 30), layer="second"),
    )
    student = drawing(
        line("S-1", (0, 5), (20, 5), source="student", layer="first"),
        line("S-2", (0, 35), (30, 35), source="student", layer="second"),
    )

    result = compare_drawings(reference, student, rubric=active_rubric)
    applied = [
        entry["applied"]
        for entry in result["audit_trail"]
        if entry.get("category") == "incorrect_position"
        and entry.get("primary_issue_id")
    ]

    assert applied == [3.0, 1.0]
    assert result["deduction"] == 4
    assert result["score"] == 96


def test_suppressed_centroid_finding_remains_auditable_without_deduction():
    reference = drawing(line("R-1", (0, 0), (100, 0), layer="wall"))
    student = drawing(
        line("S-1", (0, 0), (80, 0), source="student", layer="wall")
    )

    result = compare_drawings(reference, student, rubric=rubric())

    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_length"
    ]
    length_issue = result["issues"][0]
    assert length_issue["derived_evidence"][0]["property"] == "centroid_shift"
    suppressed = result["suppressed_findings"]
    assert len(suppressed) == 1
    assert suppressed[0]["category"] == "incorrect_position"
    assert suppressed[0]["primary_issue_id"] == length_issue["id"]
    suppressed_audit = [
        entry
        for entry in result["audit_trail"]
        if entry["classification"] == "suppressed"
    ]
    assert len(suppressed_audit) == 1
    assert suppressed_audit[0]["applied"] == 0
    assert sum(entry["applied"] for entry in result["audit_trail"]) == result[
        "deduction"
    ]

def test_duplicate_consolidation_is_independent_of_student_entity_order():
    reference = drawing(line("R-1", (0, 0), (20, 0), layer="wall"))
    first_student = drawing(
        line("S-2", (0, 0), (20, 0), source="student", layer="wall"),
        line("S-1", (0, 0), (20, 0), source="student", layer="wall"),
    )
    second_student = drawing(*reversed(first_student.entities))

    first = compare_drawings(reference, first_student, rubric=rubric())
    second = compare_drawings(reference, second_student, rubric=rubric())

    assert first["issues"] == second["issues"]
    assert first["suppressed_findings"] == second["suppressed_findings"]
    assert [issue["category"] for issue in first["issues"]] == [
        "duplicate_geometry"
    ]
    assert first["score"] == second["score"] == 99
