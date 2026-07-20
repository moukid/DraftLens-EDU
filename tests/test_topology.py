from time import perf_counter

import pytest

import app.topology as topology
from app.models import Drawing, Entity
from app.topology import build_topology, compare_topology


def line(entity_id, start, end, *, source="reference"):
    points = [tuple(start), tuple(end)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer=entity_id,
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2),
    )


def arc(entity_id, center, radius, start_angle, end_angle, *, source="reference"):
    x, y = center
    return Entity(
        id=entity_id,
        kind="arc",
        layer=entity_id,
        source=source,
        points=[tuple(center)],
        radius=radius,
        start_angle=start_angle,
        end_angle=end_angle,
        bbox=(x - radius, y - radius, x + radius, y + radius),
        centroid=tuple(center),
    )


def drawing(*entities):
    boxes = [entity.bbox for entity in entities]
    return Drawing(
        list(entities),
        (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
        units="mm",
        units_code=4,
    )


def square(prefix, *, source="reference", gap=0, reverse=False):
    entities = [
        line(f"{prefix}-1", (0, 0), (10, 0), source=source),
        line(f"{prefix}-2", (10, gap), (10, 10), source=source),
        line(f"{prefix}-3", (10, 10), (0, 10), source=source),
        line(f"{prefix}-4", (0, 10), (0, 0), source=source),
    ]
    if reverse:
        entities[0].points.reverse()
        entities[2].points.reverse()
    return entities


def matched(reference_entities, student_entities):
    return [
        (reference, student, 1.0)
        for reference, student in zip(reference_entities, student_entities)
    ]


def test_standalone_line_endpoints_are_intentional_terminals():
    graph = build_topology(drawing(line("R-1", (0, 0), (10, 0))), tolerance=0.1)

    assert len(graph.endpoints) == 2
    assert graph.connections == ()
    assert graph.components[0].closed is False
    assert len(graph.components[0].intentional_terminal_endpoint_ids) == 2


def test_standalone_arc_endpoints_are_intentional_terminals():
    graph = build_topology(
        drawing(arc("R-A", (0, 0), 5, 0, 90)), tolerance=0.1
    )

    assert len(graph.endpoints) == 2
    assert graph.connections == ()
    assert len(graph.components[0].intentional_terminal_endpoint_ids) == 2


def test_closed_square_is_closed_and_exact_student_preserves_junctions():
    reference_entities = square("R")
    student_entities = square("S", source="student", reverse=True)
    comparison = compare_topology(
        drawing(*reference_entities),
        drawing(*student_entities),
        matched(reference_entities, student_entities),
        tolerance=0.1,
    )

    assert comparison.reference.components[0].closed is True
    assert comparison.student.components[0].closed is True
    assert len(comparison.reference.connections) == 4
    assert {item.status for item in comparison.junctions} == {"preserved"}
    assert comparison.endpoint_gaps == ()


def test_five_unit_square_gap_is_detected_and_localized():
    reference_entities = square("R")
    student_entities = square("S", source="student", gap=5)
    comparison = compare_topology(
        drawing(*reference_entities),
        drawing(*student_entities),
        matched(reference_entities, student_entities),
        tolerance=2,
    )

    assert comparison.reference.components[0].closed is True
    assert comparison.student.components[0].closed is False
    assert len(comparison.endpoint_gaps) == 1
    gap = comparison.endpoint_gaps[0]
    assert gap.distance == pytest.approx(5)
    assert gap.expected_point == pytest.approx((10, 0))
    assert gap.region == pytest.approx((10, 0, 10, 5))
    assert gap.primary_reference_entity_id == "R-2"
    assert gap.primary_student_entity_id == "S-2"
    assert comparison.closed_shapes[0].actual_closed is False


def test_reference_t_junction_is_an_expected_interior_connection():
    reference_entities = [
        line("R-BASE", (0, 0), (10, 0)),
        line("R-BRANCH", (5, 0), (5, 5)),
    ]
    student_entities = [
        line("S-BASE", (0, 0), (10, 0), source="student"),
        line("S-BRANCH", (5, 0), (5, 5), source="student"),
    ]
    comparison = compare_topology(
        drawing(*reference_entities),
        drawing(*student_entities),
        matched(reference_entities, student_entities),
        tolerance=0.1,
    )

    assert [item.kind for item in comparison.reference.connections] == [
        "endpoint_interior"
    ]
    assert comparison.junctions[0].status == "preserved"
    assert comparison.endpoint_gaps == ()


def test_interior_crossing_is_not_automatically_a_connection():
    graph = build_topology(
        drawing(
            line("R-1", (0, 0), (10, 10)),
            line("R-2", (0, 10), (10, 0)),
        ),
        tolerance=0.1,
    )

    assert graph.connections == ()
    assert len(graph.components) == 2


def test_spatial_endpoint_clustering_preserves_transitive_tolerance_groups():
    graph = build_topology(
        drawing(
            line("R-1", (-0.10, -1), (-0.10, 1)),
            line("R-2", (-0.05, -1), (-0.05, 1)),
            line("R-3", (0.00, -1), (0.00, 1)),
        ),
        tolerance=0.075,
    )

    endpoint_connections = [
        connection
        for connection in graph.connections
        if connection.kind == "endpoint_endpoint"
    ]
    assert len(graph.nodes) == 2
    assert len(endpoint_connections) == 2
    assert {len(connection.endpoint_ids) for connection in endpoint_connections} == {3}


def test_polyline_interior_t_junction_remains_detected():
    base = Entity(
        id="R-BASE",
        kind="polyline",
        layer="BASE",
        source="reference",
        points=[(0, 0), (10, 0), (10, 10)],
        bbox=(0, 0, 10, 10),
        centroid=(20 / 3, 10 / 3),
    )
    graph = build_topology(
        drawing(base, line("R-BRANCH", (5, 0), (5, 5))),
        tolerance=0.1,
    )

    contacts = [
        connection
        for connection in graph.connections
        if connection.kind == "endpoint_interior"
    ]
    assert len(contacts) == 1
    assert contacts[0].interior_entity_ids == ("R-BASE",)
    assert contacts[0].point == pytest.approx((5, 0))


def test_large_spatial_topology_uses_bounded_exact_segment_candidates(monkeypatch):
    entities = [
        line(f"R-{index:04d}", (0, index * 20), (4, index * 20))
        for index in range(800)
    ]
    projection_calls = 0
    original_projection = topology._projection

    def counted_projection(*args):
        nonlocal projection_calls
        projection_calls += 1
        return original_projection(*args)

    monkeypatch.setattr(topology, "_projection", counted_projection)
    started = perf_counter()
    first = build_topology(drawing(*entities), tolerance=0.1).to_dict()
    elapsed = perf_counter() - started
    first_call_count = projection_calls
    repeated = build_topology(drawing(*entities), tolerance=0.1).to_dict()

    assert first == repeated
    assert first["connections"] == []
    assert len(first["components"]) == len(entities)
    assert first_call_count < len(entities) * 100
    assert elapsed < 5


def test_topology_ids_and_results_are_deterministic():
    reference_entities = square("R")
    student_entities = square("S", source="student", gap=5)
    arguments = (
        drawing(*reference_entities),
        drawing(*student_entities),
        matched(reference_entities, student_entities),
        2,
    )

    first = compare_topology(*arguments).to_dict()
    repeated = compare_topology(*arguments).to_dict()

    assert first == repeated
    assert first["endpoint_gaps"][0]["issue_id"].startswith("T-GAP-")
