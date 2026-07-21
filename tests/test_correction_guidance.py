from __future__ import annotations

from pathlib import Path

import pytest

from app.compare import compare_drawings
from app.dxf import parse_dxf_bytes
from app.correction_guidance import (
    CorrectionGuidance,
    correction_guidance,
    duplicate_entity_evidence,
    entity_evidence,
)
from app.models import Drawing, Entity, Issue
from app.rubric import default_rubric


def line(entity_id: str, start=(0.0, 0.0), end=(10.0, 0.0), *, source="student") -> Entity:
    points = [start, end]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer="GEOMETRY",
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
    )


def entity(entity_id: str, kind: str, *, source="student") -> Entity:
    return Entity(
        id=entity_id,
        kind=kind,
        layer="GEOMETRY",
        source=source,
        points=[(5.0, 5.0)],
        radius=4.0 if kind in {"circle", "arc"} else None,
        start_angle=0.0 if kind == "arc" else None,
        end_angle=90.0 if kind == "arc" else None,
        bbox=(1.0, 1.0, 9.0, 9.0),
        centroid=(5.0, 5.0),
    )


def issue(category: str, **updates) -> Issue:
    values = {
        "id": "E-TEST",
        "category": category,
        "severity": "major",
        "message": category,
        "deduction": 3.0,
        "rubric_rule_id": "RULE-TEST",
    }
    values.update(updates)
    return Issue(**values)


def test_flat_commands_are_primary_then_alternatives_then_precision_and_unique():
    guidance = CorrectionGuidance("move", ("copy", "MOVE"), ("osnap", "COPY"))
    assert guidance.flattened_commands() == ["MOVE", "COPY", "OSNAP"]
    assert guidance.to_dict()["alternative_commands"] == ["copy", "MOVE"]


@pytest.mark.parametrize(
    ("category", "kind", "primary", "required", "forbidden"),
    (
        ("incorrect_position", "line", "MOVE", {"MOVE", "OSNAP"}, set()),
        ("incorrect_length", "line", "LENGTHEN", {"LENGTHEN", "STRETCH", "EXTEND", "OSNAP"}, {"MOVE"}),
        ("incorrect_angle", "line", "ROTATE", {"ROTATE", "REFERENCE", "POLAR", "OSNAP"}, {"MOVE"}),
        ("incorrect_radius", "circle", "PROPERTIES", {"PROPERTIES", "SCALE", "CIRCLE"}, set()),
        ("incorrect_radius", "arc", "PROPERTIES", {"PROPERTIES", "SCALE", "ARC", "OSNAP"}, set()),
        ("extra_geometry", "line", "ERASE", {"ERASE"}, {"OVERKILL", "SELECTSIMILAR"}),
        ("duplicate_geometry", "line", "OVERKILL", {"OVERKILL", "ERASE"}, set()),
        ("open_polyline", "polyline", "PEDIT", {"PEDIT", "JOIN", "CLOSE"}, set()),
    ),
)
def test_entity_aware_guidance_uses_specific_primary_and_supporting_commands(
    category, kind, primary, required, forbidden
):
    actual = line("S-1") if kind == "line" else entity("S-1", kind)
    guidance = correction_guidance(issue(category), None, actual)
    assert guidance is not None
    assert guidance.primary_command == primary
    assert required <= set(guidance.flattened_commands())
    assert not (forbidden & set(guidance.flattened_commands()))


@pytest.mark.parametrize(
    ("kind", "command"),
    (("line", "LINE"), ("arc", "ARC"), ("circle", "CIRCLE"), ("polyline", "PLINE")),
)
def test_missing_guidance_uses_reference_entity_type(kind, command):
    expected = line("R-1", source="reference") if kind == "line" else entity("R-1", kind, source="reference")
    guidance = correction_guidance(issue("missing_geometry"), expected, None)
    assert guidance is not None
    assert guidance.primary_command == command
    assert guidance.flattened_commands() == [command, "COPY"]


def test_linked_topology_is_explanatory_and_has_no_separate_commands():
    topology = issue(
        "endpoint_gap",
        classification="supporting_evidence",
        measurement={"linked_primary_issue_id": "E-PRIMARY"},
    )
    guidance = correction_guidance(topology, line("R-1", source="reference"), line("S-1"))
    assert guidance is not None
    assert guidance.related_primary_issue_id == "E-PRIMARY"
    assert guidance.primary_command is None
    assert guidance.flattened_commands() == []
    assert "linked primary issue" in guidance.explanation


@pytest.mark.parametrize(
    "candidate",
    (
        issue("incorrect_position", classification="informational"),
        issue("incorrect_position", suppression_reason="suppressed by policy"),
        issue("endpoint_gap", suppression_reason="suppressed by policy"),
    ),
)
def test_noncorrective_or_suppressed_findings_have_no_guidance(candidate):
    assert correction_guidance(candidate, None, line("S-1")) is None


def test_unmatched_and_duplicate_evidence_is_measurable_and_entity_aware():
    unmatched = line("S-X", (-2.0, -3.0), (8.0, -3.0))
    evidence = entity_evidence(unmatched)
    assert {"entity_type", "layer", "bounds", "length", "angle", "position"} <= evidence.keys()
    assert evidence["length"] == pytest.approx(10)
    assert evidence["angle"] == pytest.approx(0)

    coincident = line("S-KEEP", (-2.0, -3.0), (8.0, -3.0))
    duplicate = duplicate_entity_evidence(unmatched, coincident, "mm")
    assert duplicate["overlap_percentage"] == 100
    assert duplicate["duplicate_entity_id"] == "S-X"
    assert duplicate["coincident_entity_id"] == "S-KEEP"


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_drawing(directory: str, filename: str, source: str) -> Drawing:
    return parse_dxf_bytes(
        (FIXTURES / directory / filename).read_bytes(),
        source=source,
        normalize=True,
    )


def approved_rubric(mode="translation"):
    return default_rubric().model_copy(
        update={"approved": True, "normalization_mode": mode}
    )


def test_manual_arc_fixtures_have_no_stale_commands_and_two_moves_are_specific():
    reference = fixture_drawing("simple_audit-II", "01-ARC-Reference.dxf", "reference")
    exact = fixture_drawing("simple_audit-II", "01-ARC-Student-OK.dxf", "student")
    all_moved = fixture_drawing("simple_audit-II", "01-ARC-All-Moved.dxf", "student")
    two_moved = fixture_drawing("simple_audit-II", "01-ARC-TwoOnly-Moved.dxf", "student")

    exact_result = compare_drawings(reference, exact, rubric=approved_rubric())
    translated_result = compare_drawings(reference, all_moved, rubric=approved_rubric())
    local_result = compare_drawings(reference, two_moved, rubric=approved_rubric())

    assert exact_result["score"] == translated_result["score"] == 100
    assert exact_result["issues"] == translated_result["issues"] == []
    assert local_result["score"] == 94
    assert [item["category"] for item in local_result["issues"]] == [
        "incorrect_position",
        "incorrect_position",
    ]
    for moved in local_result["issues"]:
        assert moved["recommended_commands"] == ["MOVE", "OSNAP"]
        assert moved["correction_guidance"]["primary_command"] == "MOVE"
        assert moved["correction_guidance"]["precision_aids"] == ["OSNAP"]
        assert "ARC" not in moved["recommended_commands"]


def test_manual_square_and_valid_junction_fixtures_leave_no_stale_commands():
    cases = (
        ("02-SQUARE-Reference.dxf", "02-SQUARE-Student-OK.dxf"),
        ("02-SQUARE-Reference.dxf", "02-SQUARE-Gap-1Unit.dxf"),
        ("03-T-Junction-Reference.dxf", "03-T-Junction-Student-OK.dxf"),
        ("04-T-Crossing-Reference.dxf", "04-T-Crossing-Student-OK.dxf"),
    )
    for reference_name, student_name in cases:
        reference = fixture_drawing("simple_audit-II", reference_name, "reference")
        student = fixture_drawing("simple_audit-II", student_name, "student")
        result = compare_drawings(reference, student, rubric=approved_rubric())
        assert result["score"] == 100
        assert result["issues"] == []


def test_displaced_square_has_one_move_and_command_free_linked_topology():
    reference = fixture_drawing("simple_audit-II", "02-SQUARE-Reference.dxf", "reference")
    student = fixture_drawing("simple_audit-II", "02-SQUARE-Gap-3Unit.dxf", "student")
    result = compare_drawings(reference, student, rubric=approved_rubric())
    primary = [item for item in result["issues"] if item["classification"] == "primary"]
    supporting = [item for item in result["issues"] if item["classification"] == "supporting_evidence"]

    assert len(primary) == 1
    assert primary[0]["recommended_commands"] == ["MOVE", "OSNAP"]
    assert len(supporting) == 2
    assert all(item["recommended_commands"] == [] for item in supporting)
    assert all(item["correction_guidance"]["related_primary_issue_id"] == primary[0]["id"] for item in supporting)


def test_circle_arc_and_polyline_evidence_exposes_relevant_geometry():
    circle = entity("S-C", "circle")
    arc = entity("S-A", "arc")
    polyline = Entity(
        id="S-P",
        kind="polyline",
        layer="GEOMETRY",
        source="student",
        points=[(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)],
        closed=False,
        bbox=(0.0, 0.0, 3.0, 4.0),
        centroid=(2.0, 4.0 / 3.0),
    )

    assert {"radius", "diameter", "center", "bounds"} <= entity_evidence(circle).keys()
    assert {"radius", "center", "start_angle", "end_angle", "sweep", "bounds"} <= entity_evidence(arc).keys()
    polyline_evidence = entity_evidence(polyline)
    assert polyline_evidence["vertex_count"] == 3
    assert polyline_evidence["closed"] is False
    assert polyline_evidence["total_length"] == pytest.approx(7)


def test_comparison_serializes_structured_and_flat_guidance_deterministically():
    reference_line = line("R-1", source="reference")
    student_line = line("S-1", (4.0, 0.0), (14.0, 0.0))
    reference = Drawing([reference_line], reference_line.bbox)
    student = Drawing([student_line], student_line.bbox)
    rubric = default_rubric().model_copy(
        update={"approved": True, "normalization_mode": "strict"}
    )

    first = compare_drawings(reference, student, rubric=rubric)
    second = compare_drawings(reference, student, rubric=rubric)
    position = first["issues"][0]

    assert first == second
    assert position["category"] == "incorrect_position"
    assert position["correction_guidance"]["primary_command"] == "MOVE"
    assert position["correction_guidance"]["precision_aids"] == ["OSNAP"]
    assert position["recommended_commands"] == ["MOVE", "OSNAP"]
