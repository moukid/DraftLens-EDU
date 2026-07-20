from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
import json
import math
from typing import Iterable

from .models import Drawing, Entity


Point = tuple[float, float]


def _stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(payload.encode('utf-8')).hexdigest()[:12].upper()}"


def _point(point: Point) -> list[float]:
    return [float(point[0]), float(point[1])]


@dataclass(frozen=True, slots=True)
class TopologyEndpoint:
    id: str
    entity_id: str
    role: str
    point: Point
    node_id: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "role": self.role,
            "point": _point(self.point),
            "node_id": self.node_id,
        }


@dataclass(frozen=True, slots=True)
class TopologyNode:
    id: str
    point: Point
    endpoint_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    interior_entity_ids: tuple[str, ...]
    kind: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "point": _point(self.point),
            "endpoint_ids": list(self.endpoint_ids),
            "entity_ids": list(self.entity_ids),
            "interior_entity_ids": list(self.interior_entity_ids),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class TopologyConnection:
    id: str
    node_id: str
    kind: str
    point: Point
    endpoint_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    interior_entity_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "kind": self.kind,
            "point": _point(self.point),
            "endpoint_ids": list(self.endpoint_ids),
            "entity_ids": list(self.entity_ids),
            "interior_entity_ids": list(self.interior_entity_ids),
        }


@dataclass(frozen=True, slots=True)
class TopologyComponent:
    id: str
    entity_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    connection_ids: tuple[str, ...]
    intentional_terminal_endpoint_ids: tuple[str, ...]
    closed: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_ids": list(self.entity_ids),
            "node_ids": list(self.node_ids),
            "connection_ids": list(self.connection_ids),
            "intentional_terminal_endpoint_ids": list(
                self.intentional_terminal_endpoint_ids
            ),
            "closed": self.closed,
        }


@dataclass(frozen=True, slots=True)
class TopologyGraph:
    tolerance: float
    endpoints: tuple[TopologyEndpoint, ...]
    nodes: tuple[TopologyNode, ...]
    connections: tuple[TopologyConnection, ...]
    components: tuple[TopologyComponent, ...]
    explicitly_closed_entity_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "tolerance": self.tolerance,
            "endpoints": [item.to_dict() for item in self.endpoints],
            "nodes": [item.to_dict() for item in self.nodes],
            "connections": [item.to_dict() for item in self.connections],
            "components": [item.to_dict() for item in self.components],
            "explicitly_closed_entity_ids": list(self.explicitly_closed_entity_ids),
        }


@dataclass(frozen=True, slots=True)
class JunctionComparison:
    id: str
    reference_connection_id: str
    kind: str
    status: str
    expected_point: Point
    actual_points: tuple[Point, ...]
    gap_distance: float | None
    reference_entity_ids: tuple[str, ...]
    student_entity_ids: tuple[str, ...]
    actual_node_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reference_connection_id": self.reference_connection_id,
            "kind": self.kind,
            "status": self.status,
            "expected_point": _point(self.expected_point),
            "actual_points": [_point(point) for point in self.actual_points],
            "gap_distance": self.gap_distance,
            "reference_entity_ids": list(self.reference_entity_ids),
            "student_entity_ids": list(self.student_entity_ids),
            "actual_node_ids": list(self.actual_node_ids),
        }


@dataclass(frozen=True, slots=True)
class EndpointGap:
    issue_id: str
    junction_id: str
    reference_connection_id: str
    distance: float
    expected_point: Point
    actual_points: tuple[Point, ...]
    region: tuple[float, float, float, float]
    reference_entity_ids: tuple[str, ...]
    student_entity_ids: tuple[str, ...]
    primary_reference_entity_id: str
    primary_student_entity_id: str

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "junction_id": self.junction_id,
            "reference_connection_id": self.reference_connection_id,
            "distance": self.distance,
            "expected_point": _point(self.expected_point),
            "actual_points": [_point(point) for point in self.actual_points],
            "region": list(self.region),
            "reference_entity_ids": list(self.reference_entity_ids),
            "student_entity_ids": list(self.student_entity_ids),
            "primary_reference_entity_id": self.primary_reference_entity_id,
            "primary_student_entity_id": self.primary_student_entity_id,
        }


@dataclass(frozen=True, slots=True)
class ClosedShapeComparison:
    reference_component_id: str
    reference_entity_ids: tuple[str, ...]
    expected_closed: bool
    student_component_ids: tuple[str, ...]
    actual_closed: bool | None

    def to_dict(self) -> dict:
        return {
            "reference_component_id": self.reference_component_id,
            "reference_entity_ids": list(self.reference_entity_ids),
            "expected_closed": self.expected_closed,
            "student_component_ids": list(self.student_component_ids),
            "actual_closed": self.actual_closed,
        }


@dataclass(frozen=True, slots=True)
class TopologyComparison:
    reference: TopologyGraph
    student: TopologyGraph
    junctions: tuple[JunctionComparison, ...]
    endpoint_gaps: tuple[EndpointGap, ...]
    closed_shapes: tuple[ClosedShapeComparison, ...]

    def to_dict(self) -> dict:
        return {
            "reference": self.reference.to_dict(),
            "student": self.student.to_dict(),
            "junctions": [item.to_dict() for item in self.junctions],
            "endpoint_gaps": [item.to_dict() for item in self.endpoint_gaps],
            "closed_shapes": [item.to_dict() for item in self.closed_shapes],
        }


@dataclass(frozen=True, slots=True)
class _EndpointCandidate:
    id: str
    entity_id: str
    role: str
    point: Point


@dataclass(frozen=True, slots=True)
class _SegmentCandidate:
    entity_id: str
    start: Point
    end: Point
    bounds: tuple[float, float, float, float]


def _entity_endpoint_points(entity: Entity) -> tuple[tuple[str, Point], ...]:
    if entity.kind == "line" and len(entity.points) >= 2:
        return (("start", entity.points[0]), ("end", entity.points[-1]))
    if entity.kind == "arc" and entity.points and entity.radius is not None:
        center_x, center_y = entity.points[0]
        start = math.radians(entity.start_angle or 0.0)
        end = math.radians(entity.end_angle or 0.0)
        return (
            (
                "start",
                (
                    center_x + entity.radius * math.cos(start),
                    center_y + entity.radius * math.sin(start),
                ),
            ),
            (
                "end",
                (
                    center_x + entity.radius * math.cos(end),
                    center_y + entity.radius * math.sin(end),
                ),
            ),
        )
    if entity.kind == "polyline" and not entity.closed and len(entity.points) >= 2:
        return (("start", entity.points[0]), ("end", entity.points[-1]))
    return ()


def _segments(entity: Entity) -> tuple[tuple[Point, Point], ...]:
    if entity.kind == "line" and len(entity.points) >= 2:
        return ((entity.points[0], entity.points[-1]),)
    if entity.kind == "polyline" and len(entity.points) >= 2:
        segments = list(zip(entity.points, entity.points[1:]))
        if entity.closed:
            segments.append((entity.points[-1], entity.points[0]))
        return tuple(segments)
    return ()


def _projection(point: Point, start: Point, end: Point) -> tuple[float, Point, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return 0.0, start, math.dist(point, start)
    factor = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    clamped = min(1.0, max(0.0, factor))
    projected = (start[0] + clamped * dx, start[1] + clamped * dy)
    return factor, projected, math.dist(point, projected)


def _closest_point(entity: Entity, point: Point, *, interior_only: bool) -> tuple[Point, float] | None:
    candidates: list[tuple[float, Point]] = []
    for start, end in _segments(entity):
        factor, projected, distance = _projection(point, start, end)
        if interior_only and not 1e-9 < factor < 1.0 - 1e-9:
            continue
        candidates.append((distance, projected))
    if not candidates:
        return None
    distance, projected = min(candidates, key=lambda item: (item[0], item[1]))
    return projected, distance


def _union_find(items: Iterable[str]):
    parent = {item: item for item in items}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(first: str, second: str) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        low, high = sorted((first_root, second_root))
        parent[high] = low

    return parent, find, union


def _grid_cell(point: Point, cell_size: float) -> tuple[int, int]:
    return math.floor(point[0] / cell_size), math.floor(point[1] / cell_size)


def _cluster_endpoint_candidates(
    candidates: tuple[_EndpointCandidate, ...],
    tolerance: float,
    union_endpoint,
) -> None:
    buckets: dict[tuple[int, int], list[_EndpointCandidate]] = {}
    for candidate in candidates:
        cell_x, cell_y = _grid_cell(candidate.point, tolerance)
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for other in buckets.get(
                    (cell_x + offset_x, cell_y + offset_y), ()
                ):
                    if math.dist(candidate.point, other.point) <= tolerance:
                        union_endpoint(candidate.id, other.id)
        buckets.setdefault((cell_x, cell_y), []).append(candidate)


def _segment_candidates(
    entities: list[Entity],
) -> tuple[_SegmentCandidate, ...]:
    return tuple(
        _SegmentCandidate(
            entity.id,
            start,
            end,
            (
                min(start[0], end[0]),
                min(start[1], end[1]),
                max(start[0], end[0]),
                max(start[1], end[1]),
            ),
        )
        for entity in entities
        for start, end in _segments(entity)
    )


def _segment_spatial_index(
    segments: tuple[_SegmentCandidate, ...],
    tolerance: float,
) -> tuple[
    float,
    dict[tuple[int, int], list[_SegmentCandidate]],
    tuple[_SegmentCandidate, ...],
]:
    if not segments:
        return tolerance, {}, ()
    min_x = min(segment.bounds[0] for segment in segments)
    min_y = min(segment.bounds[1] for segment in segments)
    max_x = max(segment.bounds[2] for segment in segments)
    max_y = max(segment.bounds[3] for segment in segments)
    span = max(max_x - min_x, max_y - min_y, tolerance)
    cell_size = max(tolerance * 2.0, span / max(1.0, math.sqrt(len(segments))))
    buckets: dict[tuple[int, int], list[_SegmentCandidate]] = {}
    long_segments: list[_SegmentCandidate] = []
    for segment in segments:
        min_cell = _grid_cell(
            (segment.bounds[0] - tolerance, segment.bounds[1] - tolerance),
            cell_size,
        )
        max_cell = _grid_cell(
            (segment.bounds[2] + tolerance, segment.bounds[3] + tolerance),
            cell_size,
        )
        cell_count = (max_cell[0] - min_cell[0] + 1) * (
            max_cell[1] - min_cell[1] + 1
        )
        if cell_count > 256:
            long_segments.append(segment)
            continue
        for cell_x in range(min_cell[0], max_cell[0] + 1):
            for cell_y in range(min_cell[1], max_cell[1] + 1):
                buckets.setdefault((cell_x, cell_y), []).append(segment)
    return cell_size, buckets, tuple(long_segments)


def build_topology(drawing: Drawing, tolerance: float = 1e-6) -> TopologyGraph:
    """Build a deterministic endpoint graph without treating terminals as errors."""

    tolerance = max(float(tolerance), 1e-9)
    entities = sorted(drawing.entities, key=lambda item: item.id)
    entity_by_id = {entity.id: entity for entity in entities}
    candidates = tuple(
        _EndpointCandidate(
            _stable_id("EP", entity.id, role), entity.id, role, tuple(point)
        )
        for entity in entities
        for role, point in _entity_endpoint_points(entity)
    )
    _, find_endpoint, union_endpoint = _union_find(item.id for item in candidates)
    _cluster_endpoint_candidates(candidates, tolerance, union_endpoint)

    clusters: dict[str, list[_EndpointCandidate]] = {}
    for candidate in candidates:
        clusters.setdefault(find_endpoint(candidate.id), []).append(candidate)
    for members in clusters.values():
        members.sort(key=lambda item: item.id)

    candidate_cluster = {
        candidate.id: root for root, members in clusters.items() for candidate in members
    }
    interior_contacts: dict[str, dict[str, tuple[Point, float]]] = {
        root: {} for root in clusters
    }
    cluster_entity_ids = {
        root: {item.entity_id for item in members}
        for root, members in clusters.items()
    }
    segments = _segment_candidates(entities)
    segment_cell_size, segment_buckets, long_segments = _segment_spatial_index(
        segments, tolerance
    )
    for candidate in candidates:
        root = candidate_cluster[candidate.id]
        nearby_segments = segment_buckets.get(
            _grid_cell(candidate.point, segment_cell_size), ()
        )
        for segment in (*nearby_segments, *long_segments):
            if segment.entity_id in cluster_entity_ids[root]:
                continue
            factor, projected, distance = _projection(
                candidate.point, segment.start, segment.end
            )
            if not 1e-9 < factor < 1.0 - 1e-9 or distance > tolerance:
                continue
            contact = (projected, distance)
            previous = interior_contacts[root].get(segment.entity_id)
            if previous is None or (contact[1], contact[0]) < (
                previous[1], previous[0]
            ):
                interior_contacts[root][segment.entity_id] = contact

    node_by_root: dict[str, TopologyNode] = {}
    for root, members in sorted(clusters.items(), key=lambda item: tuple(x.id for x in item[1])):
        interior_ids = tuple(sorted(interior_contacts[root]))
        endpoint_ids = tuple(item.id for item in members)
        entity_ids = tuple(sorted({item.entity_id for item in members} | set(interior_ids)))
        point = (
            sum(item.point[0] for item in members) / len(members),
            sum(item.point[1] for item in members) / len(members),
        )
        node_id = _stable_id("NODE", endpoint_ids, interior_ids)
        node_by_root[root] = TopologyNode(
            node_id,
            point,
            endpoint_ids,
            entity_ids,
            interior_ids,
            "junction" if len(endpoint_ids) > 1 or interior_ids else "terminal",
        )

    endpoints = tuple(
        TopologyEndpoint(
            candidate.id,
            candidate.entity_id,
            candidate.role,
            candidate.point,
            node_by_root[candidate_cluster[candidate.id]].id,
        )
        for candidate in sorted(candidates, key=lambda item: item.id)
    )
    connections: list[TopologyConnection] = []
    for root, members in clusters.items():
        node = node_by_root[root]
        if len(members) > 1:
            connections.append(
                TopologyConnection(
                    _stable_id("CONN", "endpoint_endpoint", node.endpoint_ids),
                    node.id,
                    "endpoint_endpoint",
                    node.point,
                    node.endpoint_ids,
                    tuple(sorted({item.entity_id for item in members})),
                )
            )
        for entity_id, (contact_point, _) in sorted(
            interior_contacts[root].items(), key=lambda item: (item[0], item[1][0])
        ):
            connections.append(
                TopologyConnection(
                    _stable_id(
                        "CONN", "endpoint_interior", node.endpoint_ids, entity_id
                    ),
                    node.id,
                    "endpoint_interior",
                    contact_point,
                    node.endpoint_ids,
                    tuple(sorted({item.entity_id for item in members} | {entity_id})),
                    (entity_id,),
                )
            )
    connections.sort(key=lambda item: item.id)

    _, find_entity, union_entity = _union_find(entity_by_id)
    for connection in connections:
        for first, second in combinations(connection.entity_ids, 2):
            union_entity(first, second)
    entity_groups: dict[str, list[str]] = {}
    for entity_id in sorted(entity_by_id):
        entity_groups.setdefault(find_entity(entity_id), []).append(entity_id)
    endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
    explicitly_closed = tuple(
        entity.id
        for entity in entities
        if entity.kind == "circle" or (entity.kind == "polyline" and entity.closed)
    )
    components: list[TopologyComponent] = []
    connected_endpoint_ids = {
        endpoint_id for connection in connections for endpoint_id in connection.endpoint_ids
    }
    for entity_ids in entity_groups.values():
        entity_set = set(entity_ids)
        component_endpoints = tuple(
            endpoint.id
            for endpoint in endpoints
            if endpoint.entity_id in entity_set
        )
        terminal_ids = tuple(
            endpoint_id
            for endpoint_id in component_endpoints
            if endpoint_id not in connected_endpoint_ids
        )
        component_connections = tuple(
            connection.id
            for connection in connections
            if set(connection.entity_ids) <= entity_set
        )
        node_ids = tuple(
            sorted(
                {
                    endpoint_by_id[endpoint_id].node_id
                    for endpoint_id in component_endpoints
                }
            )
        )
        closed = bool(component_endpoints) and not terminal_ids
        if not component_endpoints:
            closed = bool(entity_set) and entity_set <= set(explicitly_closed)
        component_id = _stable_id("COMP", tuple(entity_ids))
        components.append(
            TopologyComponent(
                component_id,
                tuple(entity_ids),
                node_ids,
                component_connections,
                terminal_ids,
                closed,
            )
        )
    components.sort(key=lambda item: item.id)
    return TopologyGraph(
        tolerance,
        endpoints,
        tuple(sorted(node_by_root.values(), key=lambda item: item.id)),
        tuple(connections),
        tuple(components),
        explicitly_closed,
    )


def _endpoint_correspondence(
    reference: TopologyGraph,
    student: TopologyGraph,
    matched: list[tuple[Entity, Entity, float]],
) -> tuple[dict[str, TopologyEndpoint], dict[str, str]]:
    reference_by_entity: dict[str, list[TopologyEndpoint]] = {}
    student_by_entity: dict[str, list[TopologyEndpoint]] = {}
    for endpoint in reference.endpoints:
        reference_by_entity.setdefault(endpoint.entity_id, []).append(endpoint)
    for endpoint in student.endpoints:
        student_by_entity.setdefault(endpoint.entity_id, []).append(endpoint)
    endpoint_map: dict[str, TopologyEndpoint] = {}
    entity_map: dict[str, str] = {}
    for reference_entity, student_entity, _ in sorted(
        matched, key=lambda item: (item[0].id, item[1].id)
    ):
        entity_map[reference_entity.id] = student_entity.id
        reference_endpoints = sorted(
            reference_by_entity.get(reference_entity.id, []), key=lambda item: item.role
        )
        student_endpoints = sorted(
            student_by_entity.get(student_entity.id, []), key=lambda item: item.role
        )
        if len(reference_endpoints) != len(student_endpoints):
            continue
        if len(reference_endpoints) == 2:
            direct = sum(
                math.dist(reference_endpoint.point, student_endpoint.point)
                for reference_endpoint, student_endpoint in zip(
                    reference_endpoints, student_endpoints
                )
            )
            reversed_students = list(reversed(student_endpoints))
            reverse = sum(
                math.dist(reference_endpoint.point, student_endpoint.point)
                for reference_endpoint, student_endpoint in zip(
                    reference_endpoints, reversed_students
                )
            )
            if reverse < direct:
                student_endpoints = reversed_students
        for reference_endpoint, student_endpoint in zip(
            reference_endpoints, student_endpoints
        ):
            endpoint_map[reference_endpoint.id] = student_endpoint
    return endpoint_map, entity_map


def _gap_region(expected: Point, actual: tuple[Point, ...]) -> tuple[float, float, float, float]:
    points = (expected, *actual)
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def compare_topology(
    reference_drawing: Drawing,
    student_drawing: Drawing,
    matched: list[tuple[Entity, Entity, float]],
    tolerance: float,
) -> TopologyComparison:
    """Compare only junctions required by the reference topology."""

    reference = build_topology(reference_drawing, tolerance)
    student = build_topology(student_drawing, tolerance)
    endpoint_map, entity_map = _endpoint_correspondence(reference, student, matched)
    reference_endpoint_by_id = {item.id: item for item in reference.endpoints}
    student_entity_by_id = {item.id: item for item in student_drawing.entities}
    student_component_by_entity = {
        entity_id: component
        for component in student.components
        for entity_id in component.entity_ids
    }
    junctions: list[JunctionComparison] = []
    gaps: list[EndpointGap] = []

    for connection in reference.connections:
        actual_endpoints = [endpoint_map.get(item) for item in connection.endpoint_ids]
        actual_points: tuple[Point, ...] = ()
        distance: float | None = None
        status = "unavailable"
        actual_node_ids: tuple[str, ...] = ()
        if all(actual_endpoints):
            resolved_endpoints = [item for item in actual_endpoints if item is not None]
            actual_node_ids = tuple(sorted({item.node_id for item in resolved_endpoints}))
            if connection.kind == "endpoint_endpoint":
                actual_points = tuple(item.point for item in resolved_endpoints)
                distance = max(
                    (math.dist(first, second) for first, second in combinations(actual_points, 2)),
                    default=0.0,
                )
            else:
                interior_reference_id = connection.interior_entity_ids[0]
                interior_student_id = entity_map.get(interior_reference_id)
                interior_student = student_entity_by_id.get(interior_student_id or "")
                if interior_student is not None:
                    branch_point = resolved_endpoints[0].point
                    closest = _closest_point(
                        interior_student, branch_point, interior_only=False
                    )
                    if closest is not None:
                        actual_points = (branch_point, closest[0])
                        distance = closest[1]
            if distance is not None:
                status = "preserved" if distance <= tolerance else "gap"

        junction_id = _stable_id("JUNCTION", connection.id)
        student_entity_ids = tuple(
            entity_map[item]
            for item in connection.entity_ids
            if item in entity_map
        )
        junctions.append(
            JunctionComparison(
                junction_id,
                connection.id,
                connection.kind,
                status,
                connection.point,
                actual_points,
                distance,
                connection.entity_ids,
                student_entity_ids,
                actual_node_ids,
            )
        )
        if status != "gap" or distance is None:
            continue
        candidate_pairs = [
            (
                math.dist(endpoint_map[endpoint_id].point, connection.point),
                endpoint_id,
                endpoint_map[endpoint_id],
            )
            for endpoint_id in connection.endpoint_ids
            if endpoint_id in endpoint_map
        ]
        _, primary_endpoint_id, primary_student_endpoint = max(
            candidate_pairs, key=lambda item: (item[0], item[1])
        )
        primary_reference_id = reference_endpoint_by_id[
            primary_endpoint_id
        ].entity_id
        gaps.append(
            EndpointGap(
                _stable_id("T-GAP", connection.id),
                junction_id,
                connection.id,
                distance,
                connection.point,
                actual_points,
                _gap_region(connection.point, actual_points),
                connection.entity_ids,
                student_entity_ids,
                primary_reference_id,
                primary_student_endpoint.entity_id,
            )
        )

    closed_shapes: list[ClosedShapeComparison] = []
    for component in reference.components:
        if not component.closed:
            continue
        mapped_student_ids = [
            entity_map[entity_id]
            for entity_id in component.entity_ids
            if entity_id in entity_map
        ]
        student_components = {
            student_component_by_entity[entity_id].id
            for entity_id in mapped_student_ids
            if entity_id in student_component_by_entity
        }
        actual_closed: bool | None = None
        if len(mapped_student_ids) == len(component.entity_ids) and len(student_components) == 1:
            actual_closed = student_component_by_entity[mapped_student_ids[0]].closed
        closed_shapes.append(
            ClosedShapeComparison(
                component.id,
                component.entity_ids,
                True,
                tuple(sorted(student_components)),
                actual_closed,
            )
        )

    return TopologyComparison(
        reference,
        student,
        tuple(sorted(junctions, key=lambda item: item.id)),
        tuple(sorted(gaps, key=lambda item: item.issue_id)),
        tuple(sorted(closed_shapes, key=lambda item: item.reference_component_id)),
    )
