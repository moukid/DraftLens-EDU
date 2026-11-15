from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from fractions import Fraction
import math
from statistics import median
from typing import Any, Literal

from .models import Drawing, Entity


Point = tuple[float, float]
ComponentKind = Literal[
    "segment", "circle", "arc", "ellipse", "spline", "text", "dimension"
]


@dataclass(slots=True)
class CanonicalComponent:
    id: str
    kind: ComponentKind
    source_entity_id: str
    source_handle: str | None
    layer: str
    source: Literal["reference", "student"]
    parent_object_id: str | None = None
    source_entity_ids: list[str] = field(default_factory=list)
    # For straight segments:
    start: Point | None = None
    end: Point | None = None
    length: float = 0.0
    # For circles & arcs:
    center: Point | None = None
    radius: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    # Bounding box and centroid:
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    centroid: Point = (0.0, 0.0)
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source_entity_id": self.source_entity_id,
            "source_entity_ids": (
                list(self.source_entity_ids)
                if self.source_entity_ids
                else [self.source_entity_id]
            ),
            "source_handle": self.source_handle,
            "layer": self.layer,
            "source": self.source,
            "parent_object_id": self.parent_object_id,
            "start": list(self.start) if self.start else None,
            "end": list(self.end) if self.end else None,
            "length": round(self.length, 6),
            "center": list(self.center) if self.center else None,
            "radius": round(self.radius, 6) if self.radius is not None else None,
            "start_angle": (
                round(self.start_angle, 6) if self.start_angle is not None else None
            ),
            "end_angle": (
                round(self.end_angle, 6) if self.end_angle is not None else None
            ),
            "bbox": [round(v, 6) for v in self.bbox],
            "centroid": [round(v, 6) for v in self.centroid],
        }


@dataclass(slots=True)
class AssessmentObject:
    object_id: str
    components: list[CanonicalComponent] = field(default_factory=list)
    weight: float = 0.0
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    centroid: Point = (0.0, 0.0)
    is_closed: bool = False
    source_entity_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "component_count": len(self.components),
            "weight": round(self.weight, 6),
            "bounds": [round(v, 6) for v in self.bounds],
            "centroid": [round(v, 6) for v in self.centroid],
            "is_closed": self.is_closed,
            "source_entity_ids": self.source_entity_ids,
            "components": [c.to_dict() for c in self.components],
        }


def _canonical_segment(
    p1: Point,
    p2: Point,
    entity: Entity,
    comp_idx: int,
) -> CanonicalComponent:
    x1, y1 = round(p1[0], 6), round(p1[1], 6)
    x2, y2 = round(p2[0], 6), round(p2[1], 6)
    if (x1, y1) > (x2, y2):
        start, end = (x2, y2), (x1, y1)
    else:
        start, end = (x1, y1), (x2, y2)
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    bbox = (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )
    centroid = ((start[0] + end[0]) / 2.0, ((start[1] + end[1]) / 2.0))
    cid = f"{entity.id}-S{comp_idx:02d}"
    return CanonicalComponent(
        id=cid,
        kind="segment",
        source_entity_id=entity.id,
        source_entity_ids=[entity.id],
        source_handle=entity.source_handle,
        layer=entity.layer,
        source=entity.source,
        start=start,
        end=end,
        length=length,
        bbox=bbox,
        centroid=centroid,
    )


def extract_canonical_components(drawing: Drawing) -> list[CanonicalComponent]:
    """Decompose all supported drawing entities into canonical components."""
    components: list[CanonicalComponent] = []
    for entity in drawing.entities:
        if entity.kind == "line":
            if len(entity.points) >= 2:
                p1 = (float(entity.points[0][0]), float(entity.points[0][1]))
                p2 = (float(entity.points[1][0]), float(entity.points[1][1]))
                if math.dist(p1, p2) > 1e-6:
                    components.append(_canonical_segment(p1, p2, entity, 0))
        elif entity.kind == "polyline":
            if entity.properties.get("raw_xyb"):
                from ezdxf.math import bulge_to_arc

                xyb = entity.properties["raw_xyb"]
                n = len(xyb)
                if n >= 2:
                    for i in range(n - 1):
                        p1 = (float(xyb[i][0]), float(xyb[i][1]))
                        p2 = (float(xyb[i + 1][0]), float(xyb[i + 1][1]))
                        b = float(xyb[i][2])
                        if abs(b) >= 1e-4 and math.dist(p1, p2) > 1e-6:
                            c, sa, ea, r = bulge_to_arc(p1, p2, b)
                            sa_deg = math.degrees(sa) % 360.0
                            ea_deg = math.degrees(ea) % 360.0
                            span = (ea_deg - sa_deg) % 360.0
                            if span == 0.0:
                                span = 360.0
                            arc_len = 2.0 * math.pi * float(r) * (span / 360.0)
                            cx, cy = float(c.x), float(c.y)
                            p1_round = (round(p1[0], 6), round(p1[1], 6))
                            p2_round = (round(p2[0], 6), round(p2[1], 6))
                            components.append(
                                CanonicalComponent(
                                    id=f"{entity.id}-A{i:02d}",
                                    kind="arc",
                                    source_entity_id=entity.id,
                                    source_entity_ids=[entity.id],
                                    source_handle=entity.source_handle,
                                    layer=entity.layer,
                                    source=entity.source,
                                    start=p1_round,
                                    end=p2_round,
                                    center=(cx, cy),
                                    radius=float(r),
                                    start_angle=sa_deg,
                                    end_angle=ea_deg,
                                    length=arc_len,
                                    bbox=(
                                        cx - float(r),
                                        cy - float(r),
                                        cx + float(r),
                                        cy + float(r),
                                    ),
                                    centroid=(cx, cy),
                                )
                            )
                        elif math.dist(p1, p2) > 1e-6:
                            components.append(_canonical_segment(p1, p2, entity, i))
                    if (
                        entity.closed
                        and math.dist(
                            (xyb[-1][0], xyb[-1][1]), (xyb[0][0], xyb[0][1])
                        )
                        > 1e-6
                    ):
                        p1 = (float(xyb[-1][0]), float(xyb[-1][1]))
                        p2 = (float(xyb[0][0]), float(xyb[0][1]))
                        b = float(xyb[-1][2])
                        if abs(b) >= 1e-4:
                            c, sa, ea, r = bulge_to_arc(p1, p2, b)
                            sa_deg = math.degrees(sa) % 360.0
                            ea_deg = math.degrees(ea) % 360.0
                            span = (ea_deg - sa_deg) % 360.0
                            if span == 0.0:
                                span = 360.0
                            arc_len = 2.0 * math.pi * float(r) * (span / 360.0)
                            cx, cy = float(c.x), float(c.y)
                            p1_round = (round(p1[0], 6), round(p1[1], 6))
                            p2_round = (round(p2[0], 6), round(p2[1], 6))
                            components.append(
                                CanonicalComponent(
                                    id=f"{entity.id}-A{n - 1:02d}",
                                    kind="arc",
                                    source_entity_id=entity.id,
                                    source_entity_ids=[entity.id],
                                    source_handle=entity.source_handle,
                                    layer=entity.layer,
                                    source=entity.source,
                                    start=p1_round,
                                    end=p2_round,
                                    center=(cx, cy),
                                    radius=float(r),
                                    start_angle=sa_deg,
                                    end_angle=ea_deg,
                                    length=arc_len,
                                    bbox=(
                                        cx - float(r),
                                        cy - float(r),
                                        cx + float(r),
                                        cy + float(r),
                                    ),
                                    centroid=(cx, cy),
                                )
                            )
                        else:
                            components.append(
                                _canonical_segment(p1, p2, entity, n - 1)
                            )
            else:
                pts = [(float(p[0]), float(p[1])) for p in entity.points]
                if len(pts) >= 2:
                    for i in range(len(pts) - 1):
                        if math.dist(pts[i], pts[i + 1]) > 1e-6:
                            components.append(
                                _canonical_segment(pts[i], pts[i + 1], entity, i)
                            )
                    if entity.closed and math.dist(pts[-1], pts[0]) > 1e-6:
                        components.append(
                            _canonical_segment(
                                pts[-1], pts[0], entity, len(pts) - 1
                            )
                        )
        elif entity.kind == "circle":
            cx, cy = float(entity.points[0][0]), float(entity.points[0][1])
            r = float(entity.radius or 0.0)
            components.append(
                CanonicalComponent(
                    id=f"{entity.id}-C00",
                    kind="circle",
                    source_entity_id=entity.id,
                    source_entity_ids=[entity.id],
                    source_handle=entity.source_handle,
                    layer=entity.layer,
                    source=entity.source,
                    center=(cx, cy),
                    radius=r,
                    length=2.0 * math.pi * r,
                    bbox=(cx - r, cy - r, cx + r, cy + r),
                    centroid=(cx, cy),
                )
            )
        elif entity.kind == "arc":
            cx, cy = float(entity.points[0][0]), float(entity.points[0][1])
            r = float(entity.radius or 0.0)
            sa = float(entity.start_angle or 0.0)
            ea = float(entity.end_angle or 0.0)
            span = (ea - sa) % 360.0
            if span == 0.0:
                span = 360.0
            arc_len = 2.0 * math.pi * r * (span / 360.0)
            arc_start = (
                round(cx + r * math.cos(math.radians(sa)), 6),
                round(cy + r * math.sin(math.radians(sa)), 6),
            )
            arc_end = (
                round(cx + r * math.cos(math.radians(ea)), 6),
                round(cy + r * math.sin(math.radians(ea)), 6),
            )
            components.append(
                CanonicalComponent(
                    id=f"{entity.id}-A00",
                    kind="arc",
                    source_entity_id=entity.id,
                    source_entity_ids=[entity.id],
                    source_handle=entity.source_handle,
                    layer=entity.layer,
                    source=entity.source,
                    start=arc_start,
                    end=arc_end,
                    center=(cx, cy),
                    radius=r,
                    start_angle=sa,
                    end_angle=ea,
                    length=arc_len,
                    bbox=(cx - r, cy - r, cx + r, cy + r),
                    centroid=(cx, cy),
                )
            )
        elif entity.kind == "ellipse":
            cx, cy = float(entity.points[0][0]), float(entity.points[0][1])
            props = dict(entity.properties)
            major = props.get("major_axis", (1.0, 0.0))
            ratio = float(props.get("ratio", 1.0))
            mx, my = float(major[0]), float(major[1])
            a = math.hypot(mx, my)
            b = a * ratio
            dx = math.hypot(mx, my * ratio)
            dy = math.hypot(my, mx * ratio)
            components.append(
                CanonicalComponent(
                    id=f"{entity.id}-E00",
                    kind="ellipse",
                    source_entity_id=entity.id,
                    source_entity_ids=[entity.id],
                    source_handle=entity.source_handle,
                    layer=entity.layer,
                    source=entity.source,
                    center=(cx, cy),
                    length=2.0 * math.pi * math.sqrt((a * a + b * b) / 2.0),
                    bbox=(cx - dx, cy - dy, cx + dx, cy + dy),
                    centroid=(cx, cy),
                    properties=props,
                )
            )
        elif entity.kind == "spline":
            cx, cy = (
                entity.centroid
                if entity.centroid
                else (float(entity.points[0][0]), float(entity.points[0][1]))
            )
            props = dict(entity.properties)
            props["sample_points"] = [
                (float(p[0]), float(p[1])) for p in entity.points
            ]
            components.append(
                CanonicalComponent(
                    id=f"{entity.id}-SP00",
                    kind="spline",
                    source_entity_id=entity.id,
                    source_entity_ids=[entity.id],
                    source_handle=entity.source_handle,
                    layer=entity.layer,
                    source=entity.source,
                    bbox=entity.bbox or (cx, cy, cx, cy),
                    centroid=(cx, cy),
                    properties=props,
                )
            )
        elif entity.kind in {"text", "dimension"}:
            cx, cy = float(entity.points[0][0]), float(entity.points[0][1])
            components.append(
                CanonicalComponent(
                    id=f"{entity.id}-T00",
                    kind=entity.kind,
                    source_entity_id=entity.id,
                    source_entity_ids=[entity.id],
                    source_handle=entity.source_handle,
                    layer=entity.layer,
                    source=entity.source,
                    bbox=entity.bbox or (cx, cy, cx, cy),
                    centroid=(cx, cy),
                    properties=dict(entity.properties),
                )
            )
    return components


NUMERICAL_EPSILON: float = 1e-6


def _merge_collinear_stable_components(
    components: list[CanonicalComponent],
    tol: float = 1e-3,
) -> list[CanonicalComponent]:
    """Merge contiguous collinear segments that meet at vertices of degree 2 within an object."""
    non_segments = [
        c for c in components if c.kind != "segment" or not c.start or not c.end
    ]
    segments = [c for c in components if c.kind == "segment" and c.start and c.end]
    if len(segments) <= 1:
        return components

    effective_tol = max(tol, NUMERICAL_EPSILON)

    def pt_key(p: Point) -> tuple[int, int]:
        return (round(p[0] / effective_tol), round(p[1] / effective_tol))

    merged = True
    while merged:
        merged = False
        pt_map: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
        for idx, seg in enumerate(segments):
            pt_map[pt_key(seg.start)].append((idx, "start"))
            pt_map[pt_key(seg.end)].append((idx, "end"))

        merge_candidate = None
        for _, seg_ends in pt_map.items():
            if len(seg_ends) == 2:
                idx1, end1 = seg_ends[0]
                idx2, end2 = seg_ends[1]
                if idx1 == idx2:
                    continue
                s1, s2 = segments[idx1], segments[idx2]
                P_shared = s1.start if end1 == "start" else s1.end
                P1_other = s1.end if end1 == "start" else s1.start
                P2_other = s2.end if end2 == "start" else s2.start

                v1 = (P1_other[0] - P_shared[0], P1_other[1] - P_shared[1])
                v2 = (P2_other[0] - P_shared[0], P2_other[1] - P_shared[1])
                l1 = math.hypot(v1[0], v1[1])
                l2 = math.hypot(v2[0], v2[1])
                if l1 < 1e-6 or l2 < 1e-6:
                    continue
                dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
                cross = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)
                if dot < -0.999 and cross < 1e-3:
                    merge_candidate = (idx1, idx2, P1_other, P2_other)
                    break

        if merge_candidate is not None:
            idx1, idx2, p_start, p_end = merge_candidate
            s1 = segments[idx1]
            s2 = segments[idx2]
            x1, y1 = round(p_start[0], 6), round(p_start[1], 6)
            x2, y2 = round(p_end[0], 6), round(p_end[1], 6)
            if (x1, y1) > (x2, y2):
                new_start, new_end = (x2, y2), (x1, y1)
            else:
                new_start, new_end = (x1, y1), (x2, y2)
            new_len = math.hypot(
                new_end[0] - new_start[0], new_end[1] - new_start[1]
            )
            new_bbox = (
                min(new_start[0], new_end[0]),
                min(new_start[1], new_end[1]),
                max(new_start[0], new_end[0]),
                max(new_start[1], new_end[1]),
            )
            new_cen = (
                (new_start[0] + new_end[0]) / 2.0,
                (new_start[1] + new_end[1]) / 2.0,
            )
            merged_ids = sorted(
                set(
                    (s1.source_entity_ids or [s1.source_entity_id])
                    + (s2.source_entity_ids or [s2.source_entity_id])
                )
            )
            merged_comp = CanonicalComponent(
                id=s1.id,
                kind="segment",
                source_entity_id=s1.source_entity_id,
                source_entity_ids=merged_ids,
                source_handle=s1.source_handle,
                layer=s1.layer,
                source=s1.source,
                parent_object_id=s1.parent_object_id,
                start=new_start,
                end=new_end,
                length=new_len,
                bbox=new_bbox,
                centroid=new_cen,
            )
            high, low = max(idx1, idx2), min(idx1, idx2)
            del segments[high]
            del segments[low]
            segments.append(merged_comp)
            merged = True

    return non_segments + segments


def _split_at_junctions(
    components: list[CanonicalComponent],
) -> list[CanonicalComponent]:
    """Preserve T junctions when a source LINE passes through a non-collinear endpoint."""
    junction_sources: list[tuple[Point, Point | None, str]] = []
    for c in components:
        if c.kind == "segment" and c.start and c.end and c.length >= 1e-9:
            ux = (c.end[0] - c.start[0]) / c.length
            uy = (c.end[1] - c.start[1]) / c.length
            junction_sources.append((c.start, (ux, uy), c.layer or ""))
            junction_sources.append((c.end, (ux, uy), c.layer or ""))
        elif c.kind == "arc" and c.start and c.end:
            junction_sources.append((c.start, None, c.layer or ""))
            junction_sources.append((c.end, None, c.layer or ""))

    result = []
    for c in components:
        if c.kind != "segment" or not c.start or not c.end or c.length < 1e-9:
            result.append(c)
            continue
        a, b = c.start, c.end
        ux, uy = (b[0] - a[0]) / c.length, (b[1] - a[1]) / c.length
        cuts = {0.0, c.length}
        for (x, y), dir_vec, _layer in junction_sources:
            if dir_vec is not None:
                # Never split a segment at the endpoint of a collinear overlapping segment
                dot = abs(ux * dir_vec[0] + uy * dir_vec[1])
                if dot >= math.cos(math.radians(2.0)):
                    continue
            t = (x - a[0]) * ux + (y - a[1]) * uy
            if (
                1e-4 < t < c.length - 1e-4
                and abs((x - a[0]) * uy - (y - a[1]) * ux) < 1e-3
            ):
                cuts.add(round(t, 6))
        spans = list(zip(sorted(cuts), sorted(cuts)[1:]))
        for i, (lo, hi) in enumerate(spans):
            if hi - lo < 1e-6:
                continue
            start = (a[0] + lo * ux, a[1] + lo * uy)
            end = (a[0] + hi * ux, a[1] + hi * uy)
            result.append(
                replace(
                    c,
                    id=c.id if len(spans) == 1 else f"{c.id}-J{i:02d}",
                    start=start,
                    end=end,
                    length=hi - lo,
                    centroid=((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
                    bbox=(
                        min(start[0], end[0]),
                        min(start[1], end[1]),
                        max(start[0], end[0]),
                        max(start[1], end[1]),
                    ),
                )
            )
    return result


def extract_assessment_objects(
    drawing: Drawing,
    tolerance: float = 2.0,
    confirmed_objects: list[dict[str, Any]] | None = None,
) -> list[AssessmentObject]:
    """Cluster canonical components into parent assessment objects."""
    components = [
        c
        for c in _split_at_junctions(extract_canonical_components(drawing))
        if c.kind not in {"text", "dimension"}
    ]
    if not components:
        return []

    if confirmed_objects:
        obj_by_id: dict[str, list[CanonicalComponent]] = {}
        entity_to_obj: dict[str, str] = {}
        for obj_spec in confirmed_objects:
            oid = obj_spec.get("occurrence_id") or obj_spec.get("id") or "OBJ"
            for eid in obj_spec.get("member_entity_ids", []):
                entity_to_obj[eid] = oid

        unassigned: list[CanonicalComponent] = []
        for comp in components:
            target_oid = entity_to_obj.get(comp.source_entity_id)
            if target_oid:
                obj_by_id.setdefault(target_oid, []).append(comp)
            else:
                unassigned.append(comp)

        results: list[AssessmentObject] = []
        tol = max(tolerance, 1e-4)
        for oid, comps in sorted(obj_by_id.items()):
            comps = _merge_collinear_stable_components(comps, tolerance)
            all_boxes = [c.bbox for c in comps]
            min_x = min(b[0] for b in all_boxes)
            min_y = min(b[1] for b in all_boxes)
            max_x = max(b[2] for b in all_boxes)
            max_y = max(b[3] for b in all_boxes)
            cen_x = sum(c.centroid[0] for c in comps) / len(comps)
            cen_y = sum(c.centroid[1] for c in comps) / len(comps)
            eids = sorted(
                {
                    eid
                    for c in comps
                    for eid in (c.source_entity_ids or [c.source_entity_id])
                }
            )
            for c in comps:
                c.parent_object_id = oid
            is_closed = _check_object_closed(comps, tol)
            results.append(
                AssessmentObject(
                    object_id=oid,
                    components=comps,
                    bounds=(min_x, min_y, max_x, max_y),
                    centroid=(cen_x, cen_y),
                    is_closed=is_closed,
                    source_entity_ids=eids,
                )
            )
        if unassigned:
            extra_objs = _cluster_geometrically(
                unassigned, tolerance, prefix="OBJ-EXTRA"
            )
            results.extend(extra_objs)

        if results:
            w_per_obj = 1.0 / len(results)
            for obj in results:
                obj.weight = w_per_obj
        return results

    return _cluster_geometrically(components, tolerance)


def _check_object_closed(
    stable_comps: list[CanonicalComponent], tol: float
) -> bool:
    if not stable_comps:
        return False
    effective_tol = max(tol, NUMERICAL_EPSILON)
    if len(stable_comps) == 1:
        c0 = stable_comps[0]
        if c0.kind == "circle":
            return True
        if c0.kind == "ellipse":
            props = c0.properties or {}
            sp, ep = props.get("start_param"), props.get("end_param")
            if sp is None or ep is None:
                return True
            try:
                return float(ep) >= float(sp) + math.tau - 1e-6
            except (TypeError, ValueError):
                return True
        return False

    if len(stable_comps) >= 2 and all(c.kind in ("segment", "arc") for c in stable_comps):
        ep_counts: dict[tuple[int, int], int] = {}
        for c in stable_comps:
            if c.start and c.end:
                k1 = (round(c.start[0] / effective_tol), round(c.start[1] / effective_tol))
                k2 = (round(c.end[0] / effective_tol), round(c.end[1] / effective_tol))
                ep_counts[k1] = ep_counts.get(k1, 0) + 1
                ep_counts[k2] = ep_counts.get(k2, 0) + 1
        if ep_counts and all(cnt >= 2 for cnt in ep_counts.values()):
            return True

    closed_loops: list[tuple[set[str], tuple[float, float, float, float]]] = []
    for c in stable_comps:
        if c.kind == "circle":
            closed_loops.append(({c.id}, c.bbox))
        elif c.kind == "ellipse" and _check_object_closed([c], effective_tol):
            closed_loops.append(({c.id}, c.bbox))

    active = [
        c
        for c in stable_comps
        if c.kind in ("segment", "arc") and c.start and c.end
    ]
    while len(active) >= 2:
        ep_counts = {}
        for c in active:
            k1 = (round(c.start[0] / effective_tol), round(c.start[1] / effective_tol))
            k2 = (round(c.end[0] / effective_tol), round(c.end[1] / effective_tol))
            ep_counts[k1] = ep_counts.get(k1, 0) + 1
            ep_counts[k2] = ep_counts.get(k2, 0) + 1
        next_active = [
            c
            for c in active
            if ep_counts[(round(c.start[0] / effective_tol), round(c.start[1] / effective_tol))] >= 2
            and ep_counts[(round(c.end[0] / effective_tol), round(c.end[1] / effective_tol))] >= 2
        ]
        if len(next_active) == len(active):
            break
        active = next_active

    if len(active) >= 2:
        c_parent = {c.id: c.id for c in active}

        def _find_c(cid: str) -> str:
            while c_parent[cid] != cid:
                c_parent[cid] = c_parent[c_parent[cid]]
                cid = c_parent[cid]
            return cid

        ep_owner: dict[tuple[int, int], str] = {}
        for c in active:
            for pt in (c.start, c.end):
                if pt:
                    k = (round(pt[0] / effective_tol), round(pt[1] / effective_tol))
                    if k in ep_owner:
                        r1, r2 = _find_c(c.id), _find_c(ep_owner[k])
                        if r1 != r2:
                            c_parent[r2] = r1
                    else:
                        ep_owner[k] = c.id

        loop_groups: dict[str, list[CanonicalComponent]] = defaultdict(list)
        for c in active:
            loop_groups[_find_c(c.id)].append(c)

        for l_comps in loop_groups.values():
            if len(l_comps) >= 2:
                l_bbox = (
                    min(c.bbox[0] for c in l_comps),
                    min(c.bbox[1] for c in l_comps),
                    max(c.bbox[2] for c in l_comps),
                    max(c.bbox[3] for c in l_comps),
                )
                closed_loops.append(({c.id for c in l_comps}, l_bbox))

    for loop_ids, ob in closed_loops:
        other_comps = [c for c in stable_comps if c.id not in loop_ids]
        if not other_comps:
            return True
        ob_area = (ob[2] - ob[0]) * (ob[3] - ob[1])
        all_contained = True
        for c in other_comps:
            ib = c.bbox
            cen_x = (ib[0] + ib[2]) / 2.0
            cen_y = (ib[1] + ib[3]) / 2.0
            ib_area = (ib[2] - ib[0]) * (ib[3] - ib[1])
            is_contained = (
                (
                    ib[0] >= ob[0] - tol
                    and ib[1] >= ob[1] - tol
                    and ib[2] <= ob[2] + tol
                    and ib[3] <= ob[3] + tol
                )
                or (
                    ob[0] - tol <= cen_x <= ob[2] + tol
                    and ob[1] - tol <= cen_y <= ob[3] + tol
                    and ib_area < ob_area * 0.5
                )
            )
            if not is_contained:
                all_contained = False
                break
        if all_contained:
            return True

    return False


def _cluster_geometrically(
    components: list[CanonicalComponent],
    tolerance: float = 2.0,
    prefix: str = "OBJ",
) -> list[AssessmentObject]:
    """Group components into assessment assemblies using connectivity, containment, and layer clustering."""
    parent = {comp.id: comp.id for comp in components}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: str, j: str) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            low, high = sorted((root_i, root_j))
            parent[high] = low

    tol = max(tolerance, 1e-4)
    cell_size = max(tol * 4.0, 1.0)
    grid: dict[tuple[int, int], list[tuple[Point, str]]] = {}

    def add_point(pt: Point, cid: str) -> None:
        cx, cy = math.floor(pt[0] / cell_size), math.floor(pt[1] / cell_size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = (cx + dx, dy + cy)
                for other_pt, other_cid in grid.get(cell, ()):
                    if math.dist(pt, other_pt) <= tol:
                        union(cid, other_cid)
        grid.setdefault((cx, cy), []).append((pt, cid))

    for comp in components:
        if comp.kind in ("segment", "arc") and comp.start and comp.end:
            add_point(comp.start, comp.id)
            add_point(comp.end, comp.id)

    raw_groups: dict[str, list[CanonicalComponent]] = {}
    for comp in components:
        root = find(comp.id)
        raw_groups.setdefault(root, []).append(comp)

    # 1. Containment merging
    group_info = []
    for gid, comps in raw_groups.items():
        min_x = min(c.bbox[0] for c in comps)
        min_y = min(c.bbox[1] for c in comps)
        max_x = max(c.bbox[2] for c in comps)
        max_y = max(c.bbox[3] for c in comps)
        area = (max_x - min_x) * (max_y - min_y)
        layer = comps[0].layer
        group_info.append({
            "gid": gid,
            "comps": comps,
            "bbox": (min_x, min_y, max_x, max_y),
            "area": area,
            "layer": layer,
        })

    group_info.sort(key=lambda g: g["area"], reverse=True)
    g_parent = {g["gid"]: g["gid"] for g in group_info}

    def find_g(i: str) -> str:
        while g_parent[i] != i:
            g_parent[i] = g_parent[g_parent[i]]
            i = g_parent[i]
        return i

    def union_g(i: str, j: str) -> None:
        ri, rj = find_g(i), find_g(j)
        if ri != rj:
            g_parent[rj] = ri

    for i in range(len(group_info)):
        for j in range(i + 1, len(group_info)):
            outer, inner = group_info[i], group_info[j]
            ob, ib = outer["bbox"], inner["bbox"]
            cen_x = (ib[0] + ib[2]) / 2.0
            cen_y = (ib[1] + ib[3]) / 2.0
            is_contained = (
                (ib[0] >= ob[0] - tol and ib[1] >= ob[1] - tol and ib[2] <= ob[2] + tol and ib[3] <= ob[3] + tol)
                or (ob[0] - tol <= cen_x <= ob[2] + tol and ob[1] - tol <= cen_y <= ob[3] + tol and inner["area"] < outer["area"] * 0.5)
            )
            if is_contained:
                if (
                    outer["layer"] == inner["layer"]
                    or not outer["layer"]
                    or not inner["layer"]
                ):
                    union_g(outer["gid"], inner["gid"])

    # 2. Same-layer adjacency merging (merges features on same layer within proximity, preserving large gaps)
    stage2: dict[str, list[CanonicalComponent]] = {}
    for g in group_info:
        stage2.setdefault(find_g(g["gid"]), []).extend(g["comps"])

    stage2_list = []
    for gid, comps in stage2.items():
        min_x = min(c.bbox[0] for c in comps)
        min_y = min(c.bbox[1] for c in comps)
        max_x = max(c.bbox[2] for c in comps)
        max_y = max(c.bbox[3] for c in comps)
        stage2_list.append({
            "gid": gid,
            "comps": comps,
            "bbox": (min_x, min_y, max_x, max_y),
            "area": (max_x - min_x) * (max_y - min_y),
            "layer": comps[0].layer,
        })

    stage2_list.sort(key=lambda g: g["area"], reverse=True)
    s2_parent = {g["gid"]: g["gid"] for g in stage2_list}

    def find_s2(i: str) -> str:
        while s2_parent[i] != i:
            s2_parent[i] = s2_parent[s2_parent[i]]
            i = s2_parent[i]
        return i

    def union_s2(i: str, j: str) -> None:
        ri, rj = find_s2(i), find_s2(j)
        if ri != rj:
            s2_parent[rj] = ri

    for i in range(len(stage2_list)):
        for j in range(i + 1, len(stage2_list)):
            g1, g2 = stage2_list[i], stage2_list[j]
            b1, b2 = g1["bbox"], g2["bbox"]
            cen_x = (b2[0] + b2[2]) / 2.0
            cen_y = (b2[1] + b2[3]) / 2.0
            if g1["layer"] == g2["layer"] or not g1["layer"] or not g2["layer"]:
                if (
                    (b2[0] >= b1[0] - tol and b2[1] >= b1[1] - tol and b2[2] <= b1[2] + tol and b2[3] <= b1[3] + tol)
                    or (b1[0] - tol <= cen_x <= b1[2] + tol and b1[1] - tol <= cen_y <= b1[3] + tol and g2["area"] < g1["area"] * 0.5)
                ) and g2["area"] < g1["area"] * 0.95:
                    union_s2(g1["gid"], g2["gid"])
                    continue
            if _check_object_closed(g1["comps"], tol) or _check_object_closed(g2["comps"], tol):
                continue
            if g1["layer"] and g1["layer"] == g2["layer"]:
                x_overlap = max(0.0, min(b1[2], b2[2]) - max(b1[0], b2[0]))
                y_overlap = max(0.0, min(b1[3], b2[3]) - max(b1[1], b2[1]))
                x_gap = max(0.0, max(b1[0], b2[0]) - min(b1[2], b2[2]))
                y_gap = max(0.0, max(b1[1], b2[1]) - min(b1[3], b2[3]))
                if (x_overlap > 0 and y_gap <= tol * 5) or (y_overlap > 0 and x_gap <= tol * 5):
                    union_s2(g1["gid"], g2["gid"])
                elif x_gap <= tol * 5 and y_gap <= tol * 5:
                    union_s2(g1["gid"], g2["gid"])

    final_groups: dict[str, list[CanonicalComponent]] = {}
    for g in stage2_list:
        final_groups.setdefault(find_s2(g["gid"]), []).extend(g["comps"])

    all_all_boxes = [c.bbox for comps in final_groups.values() for c in comps]
    mid_x = (min(b[0] for b in all_all_boxes) + max(b[2] for b in all_all_boxes)) / 2.0 if all_all_boxes else 0.0

    def sort_key(g_comps: list[CanonicalComponent]) -> tuple:
        b_min_x = min(c.bbox[0] for c in g_comps)
        b_min_y = min(c.bbox[1] for c in g_comps)
        b_max_x = max(c.bbox[2] for c in g_comps)
        b_max_y = max(c.bbox[3] for c in g_comps)
        c_x = (b_min_x + b_max_x) / 2.0
        c_y = (b_min_y + b_max_y) / 2.0
        col = 0 if c_x < mid_x else 1
        if col == 0:
            return (0, -c_y, c_x, g_comps[0].id)
        return (1, c_x, -c_y, g_comps[0].id)

    sorted_groups = sorted(final_groups.values(), key=sort_key)

    assessment_objects: list[AssessmentObject] = []
    num_objects = len(sorted_groups)
    obj_weight = 1.0 / max(num_objects, 1)

    for idx, group in enumerate(sorted_groups, 1):
        oid = f"{prefix}-{idx:03d}"
        for comp in group:
            comp.parent_object_id = oid

        stable_comps = _merge_collinear_stable_components(group, tolerance)
        for comp in stable_comps:
            comp.parent_object_id = oid

        all_boxes = [c.bbox for c in stable_comps]
        min_x = min(b[0] for b in all_boxes)
        min_y = min(b[1] for b in all_boxes)
        max_x = max(b[2] for b in all_boxes)
        max_y = max(b[3] for b in all_boxes)
        cen_x = sum(c.centroid[0] for c in stable_comps) / len(stable_comps)
        cen_y = sum(c.centroid[1] for c in stable_comps) / len(stable_comps)
        eids = sorted(
            {
                eid
                for c in stable_comps
                for eid in (c.source_entity_ids or [c.source_entity_id])
            }
        )
        is_closed = _check_object_closed(stable_comps, tol)

        assessment_objects.append(
            AssessmentObject(
                object_id=oid,
                components=stable_comps,
                weight=obj_weight,
                bounds=(min_x, min_y, max_x, max_y),
                centroid=(cen_x, cen_y),
                is_closed=is_closed,
                source_entity_ids=eids,
            )
        )

    return assessment_objects


@dataclass(slots=True)
class ComponentMatch:
    reference_component: CanonicalComponent
    student_components: list[CanonicalComponent]
    presence: float  # p_i in [0, 1]
    correctness: float  # q_i in [0, 1]
    weight: float  # w_i, summing to 1.0 across all reference components
    covered_length: float = 0.0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class CanonicalMatchResult:
    reference_objects: list[AssessmentObject]
    component_matches: list[ComponentMatch]
    missing_components: list[CanonicalComponent]
    extra_student_entities: list[str]
    matched_pairs: list[tuple[str, str, float]]
    completion_fraction: float  # sum(w_i * p_i) in [0, 1]
    accuracy_fraction: float  # sum(w_i * p_i * q_i) in [0, 1]
    object_summary: dict[str, Any] = field(default_factory=dict)
    duplicate_student_entities: list[str] = field(default_factory=list)
    object_translations: dict[str, tuple[float, float]] = field(default_factory=dict)
    matched_objects: list[tuple[str, str, tuple[float, float]]] = field(default_factory=list)
    degenerate_student_entities: list[str] = field(default_factory=list)
    student_overlaps: dict[str, dict[str, Any]] = field(default_factory=dict)
    position_tolerance: float = 2.0
    ambiguous_groups: list[dict[str, Any]] = field(default_factory=list)

    def spatial_correspondences(
        self, pos_tol: float | None = None
    ) -> list[dict[str, Any]]:
        observations = []
        effective_tol = self.position_tolerance if pos_tol is None else pos_tol
        effective_tol = 2.0 if effective_tol is None else float(effective_tol)
        for cm in self.component_matches:
            rc = cm.reference_component
            if cm.presence <= 0 or not cm.student_components:
                continue
            obj_dx, obj_dy = (
                self.object_translations.get(rc.parent_object_id or "", (0.0, 0.0))
                if self.object_translations
                else (0.0, 0.0)
            )
            vectors = []
            for sc in cm.student_components:
                if rc.kind == sc.kind == "segment" and rc.start and rc.end:
                    L = max(rc.length, 1e-12)
                    ux = (rc.end[0] - rc.start[0]) / L
                    uy = (rc.end[1] - rc.start[1]) / L
                    nx = -uy
                    ny = ux
                    eval_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy)
                    sc_p1 = sc.start or sc.centroid
                    sc_p2 = sc.end or sc.centroid
                    t1 = (sc_p1[0] - eval_start[0]) * ux + (sc_p1[1] - eval_start[1]) * uy
                    t2 = (sc_p2[0] - eval_start[0]) * ux + (sc_p2[1] - eval_start[1]) * uy
                    t_min, t_max = min(t1, t2), max(t1, t2)
                    s_len = max(0.0, t_max - t_min)

                    sc_c = sc.centroid
                    d_normal = (sc_c[0] - eval_start[0]) * nx + (sc_c[1] - eval_start[1]) * ny

                    if t_min >= -effective_tol - 1e-6 and t_max <= L + effective_tol + 1e-6:
                        d_along = 0.0
                    elif s_len >= L - effective_tol:
                        t_mid = (t_min + t_max) / 2.0
                        d_along = t_mid - L / 2.0
                    elif t_max > L + effective_tol and t_min > effective_tol:
                        d_along = t_max - L
                    elif t_min < -effective_tol and t_max < L - effective_tol:
                        d_along = t_min
                    else:
                        t_mid = (t_min + t_max) / 2.0
                        d_along = t_mid - L / 2.0

                    vx = obj_dx + d_along * ux + d_normal * nx
                    vy = obj_dy + d_along * uy + d_normal * ny
                    vectors.append((vx, vy))
                elif rc.kind in {"circle", "arc"} and rc.center and sc.center:
                    vectors.append((sc.center[0] - rc.center[0], sc.center[1] - rc.center[1]))
                else:
                    anchor = rc.center or rc.centroid
                    target = sc.center or sc.centroid
                    vectors.append((target[0] - anchor[0], target[1] - anchor[1]))
            observations.append(
                {
                    "reference_component_id": rc.id,
                    "student_component_ids": [
                        sc.id for sc in cm.student_components
                    ],
                    "displacement": [
                        sum(v[j] for v in vectors) / len(vectors) for j in (0, 1)
                    ],
                    "correctness": cm.correctness,
                    "presence": cm.presence,
                }
            )
        return observations

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_objects": [obj.to_dict() for obj in self.reference_objects],
            "spatial_correspondences": self.spatial_correspondences(self.position_tolerance),
            "position_tolerance": self.position_tolerance,
            "component_matches": [
                {
                    "reference_component_id": cm.reference_component.id,
                    "parent_object_id": cm.reference_component.parent_object_id,
                    "presence": round(cm.presence, 6),
                    "correctness": round(cm.correctness, 6),
                    "weight": round(cm.weight, 6),
                    "covered_length": round(cm.covered_length, 6),
                    "student_component_ids": [
                        sc.id for sc in cm.student_components
                    ],
                    "errors": list(cm.errors),
                }
                for cm in self.component_matches
            ],
            "missing_components": [mc.to_dict() for mc in self.missing_components],
            "extra_student_entities": self.extra_student_entities,
            "duplicate_student_entities": self.duplicate_student_entities,
            "matched_pairs": self.matched_pairs,
            "completion_fraction": round(self.completion_fraction, 6),
            "accuracy_fraction": round(self.accuracy_fraction, 6),
            "object_summary": self.object_summary,
            "object_translations": self.object_translations,
            "matched_objects": self.matched_objects,
            "degenerate_student_entities": self.degenerate_student_entities,
            "student_overlaps": self.student_overlaps,
            "ambiguous_groups": self.ambiguous_groups,
        }


def estimate_canonical_translation(
    reference: Drawing, student: Drawing, pos_tol: float = 2.0
) -> dict[str, Any] | None:
    """Return actual distinct-component support; callers enforce policy thresholds."""
    refs = extract_canonical_components(reference)
    students = extract_canonical_components(student)

    def signature(c: CanonicalComponent) -> Any:
        if c.kind == "segment" and c.start and c.end:
            return (
                c.kind,
                round(c.length, 5),
                round(
                    math.atan2(c.end[1] - c.start[1], c.end[0] - c.start[0])
                    % math.pi,
                    5,
                ),
            )
        if c.kind in {"arc", "circle"}:
            return (c.kind, round(c.radius or 0, 5), round(c.length, 5))
        if c.kind == "ellipse":
            return (
                c.kind,
                tuple(c.properties.get("major_axis", ())),
                c.properties.get("ratio"),
                c.properties.get("start_param"),
                c.properties.get("end_param"),
            )
        if c.kind == "spline":
            pts = tuple(
                (round(x - c.centroid[0], 5), round(y - c.centroid[1], 5))
                for x, y in c.properties.get("sample_points", [])
            )
            return (c.kind, min(pts, tuple(reversed(pts))))
        return (c.kind, repr(c.properties))

    pairs = [
        (r, t, (r.centroid[0] - t.centroid[0], r.centroid[1] - t.centroid[1]))
        for r in refs
        for t in students
        if signature(r) == signature(t)
    ]
    if not pairs:
        return None
    best = []
    best_assignment = []
    best_rank = None
    tot_ref_len = math.fsum(getattr(r, "length", 0.0) for r in refs)
    for seed in sorted({v for _, _, v in pairs}, key=lambda v: (math.hypot(*v), v)):
        used_r = set()
        used_s = set()
        assignment = []
        for r, t, vector in sorted(
            pairs, key=lambda p: (math.dist(p[2], seed), p[0].id, p[1].id)
        ):
            if r.id not in used_r and t.id not in used_s:
                assignment.append((r, t, vector))
                used_r.add(r.id)
                used_s.add(t.id)
        inliers = [p for p in assignment if math.dist(p[2], seed) <= pos_tol]
        inlier_len = math.fsum(getattr(r, "length", 0.0) for r, _, _ in inliers)
        majority_len = inlier_len >= 0.5 * tot_ref_len if tot_ref_len > 0 else False
        rank = (
            majority_len,
            len(inliers),
            round(inlier_len, 4),
            -math.fsum(math.dist(v, seed) for _, _, v in assignment),
            -math.hypot(*seed),
        )
        if best_rank is None or rank > best_rank:
            best = inliers
            best_assignment = assignment
            best_rank = rank
    candidate = tuple(float(median(v[j] for _, _, v in best)) for j in (0, 1))
    before = math.fsum(
        math.dist(r.centroid, t.centroid) for r, t, _ in best_assignment
    )
    after = math.fsum(math.dist(v, candidate) for _, _, v in best_assignment)
    has_comp_len = any(getattr(r, "length", 0.0) > 1e-6 for r, _, _ in best_assignment)
    if has_comp_len:
        weighted_before = math.fsum(
            math.dist(r.centroid, t.centroid) * max(getattr(r, "length", 0.0), 1e-3)
            for r, t, _ in best_assignment
        )
        weighted_after = math.fsum(
            math.dist(v, candidate) * max(getattr(r, "length", 0.0), 1e-3)
            for r, _, v in best_assignment
        )
    else:
        weighted_before = before
        weighted_after = after
    ev_count = len(best_assignment)
    tot_comps = max(1, min(len(refs), len(students)))
    max_comps = max(1, max(len(refs), len(students)))
    best_inlier_len = math.fsum(getattr(r, "length", 0.0) for r, _, _ in best)
    best_assign_len = math.fsum(getattr(r, "length", 0.0) for r, _, _ in best_assignment)
    length_support_ratio = (
        best_inlier_len / max(best_assign_len, 1e-9)
        if best_assign_len > 0
        else 0.0
    )
    drawing_length_coverage = (
        best_inlier_len / max(tot_ref_len, 1e-9)
        if tot_ref_len > 0
        else 0.0
    )
    assign_reduction = (
        max(0.0, (weighted_before - weighted_after) / weighted_before)
        if weighted_before > 1e-9
        else 0.0
    )
    inlier_before = math.fsum(
        math.dist(r.centroid, t.centroid) for r, t, _ in best
    )
    inlier_after = math.fsum(math.dist(v, candidate) for _, _, v in best)
    inlier_reduction = max(0.0, (inlier_before - inlier_after) / inlier_before) if inlier_before > 1e-9 else 0.0
    effective_reduction = (
        max(assign_reduction, inlier_reduction)
        if (length_support_ratio >= 0.60 or best_inlier_len >= 0.5 * tot_ref_len)
        else assign_reduction
    )
    return {
        "candidate_translation": candidate,
        "support_count": len(best),
        "evidence_count": ev_count,
        "support_ratio": len(best) / max(1, ev_count),
        "length_support_ratio": length_support_ratio,
        "drawing_length_coverage": drawing_length_coverage,
        "drawing_coverage_ratio": len(best) / tot_comps,
        "overall_coverage_ratio": len(best) / max_comps,
        "error_before": before,
        "error_after": after,
        "error_reduction_ratio": effective_reduction,
    }


def _intersect_intervals(
    intervals: list[tuple[float, float]],
    target: tuple[float, float],
) -> list[tuple[float, float]]:
    t0, t1 = target
    res = []
    for a, b in intervals:
        o0, o1 = max(a, t0), min(b, t1)
        if o1 - o0 > 1e-6:
            res.append((o0, o1))
    return res


def _subtract_intervals(
    intervals: list[tuple[float, float]],
    used: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    curr = list(intervals)
    for u0, u1 in used:
        next_curr = []
        for a, b in curr:
            if u1 <= a or u0 >= b:
                next_curr.append((a, b))
            else:
                if a < u0 - 1e-6:
                    next_curr.append((a, u0))
                if b > u1 + 1e-6:
                    next_curr.append((u1, b))
        curr = next_curr
    return curr


def _merge_intervals(intervals: list[tuple[float, float]]) -> float:
    """Return total length of union of 1D intervals."""
    if not intervals:
        return 0.0
    sorted_intervals = sorted(intervals)
    merged = []
    curr_start, curr_end = sorted_intervals[0]
    for start, end in sorted_intervals[1:]:
        if start <= curr_end + 1e-6:
            curr_end = max(curr_end, end)
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = start, end
    merged.append((curr_start, curr_end))
    return sum(end - start for start, end in merged)


def _arc_to_intervals(sa: float, span: float) -> list[tuple[float, float]]:
    sa = sa % 360.0
    if span >= 360.0:
        return [(0.0, 360.0)]
    ea = sa + span
    if ea <= 360.0:
        return [(sa, ea)]
    return [(sa, 360.0), (0.0, ea - 360.0)]


def _ellipse_interval_length(
    intervals: list[tuple[float, float]], major: float, ratio: float
) -> float:
    """Deterministic Simpson integration of elliptical arc length (degrees)."""
    total = 0.0
    for a, b in intervals:
        lo, hi = math.radians(a), math.radians(b)
        n = 256
        h = (hi - lo) / n

        def speed(t: float) -> float:
            return major * math.hypot(math.sin(t), ratio * math.cos(t))

        total += (
            h
            / 3
            * (
                speed(lo)
                + speed(hi)
                + sum(
                    (4 if i % 2 else 2) * speed(lo + i * h) for i in range(1, n)
                )
            )
        )
    return total


def _arc_overlap(sa1: float, span1: float, sa2: float, span2: float) -> float:
    i1 = _arc_to_intervals(sa1, span1)
    i2 = _arc_to_intervals(sa2, span2)
    tot = 0.0
    for a1, b1 in i1:
        for a2, b2 in i2:
            o0, o1 = max(a1, a2), min(b1, b2)
            if o1 > o0:
                tot += o1 - o0
    return tot


def _evaluate_object_candidate_translation(
    obj: AssessmentObject,
    stu_comps: list[CanonicalComponent],
    used_stu_comp_ids: set[str],
    t_cand: tuple[float, float],
    pos_tol: float,
    len_tol: float,
    ang_tol: float,
    rad_tol: float,
) -> tuple[int, float, float]:
    dx, dy = t_cand
    matched_count = 0
    matched_length = 0.0
    total_error = 0.0
    matched_stu_ids: set[str] = set()

    for rc in obj.components:
        if rc.kind == "circle":
            if not rc.center or rc.radius is None:
                continue
            r_cen = (rc.center[0] + dx, rc.center[1] + dy)
            best_sc = None
            best_dist = math.inf
            for sc in stu_comps:
                if sc.kind != "circle" or sc.id in used_stu_comp_ids or sc.id in matched_stu_ids:
                    continue
                if sc.center and sc.radius is not None:
                    cdist = math.dist(r_cen, sc.center)
                    rdelta = abs(rc.radius - sc.radius)
                    if cdist <= pos_tol * 2.5 and rdelta <= rad_tol * 2.0:
                        err = cdist * 2.0 + rdelta
                        if err < best_dist:
                            best_dist = err
                            best_sc = sc
            if best_sc is not None:
                matched_count += 1
                matched_length += rc.length
                total_error += best_dist
                matched_stu_ids.add(best_sc.id)

        elif rc.kind == "arc":
            if not rc.center or rc.radius is None:
                continue
            r_cen = (rc.center[0] + dx, rc.center[1] + dy)
            sa_ref = rc.start_angle or 0.0
            ea_ref = rc.end_angle or 0.0
            span_ref = (ea_ref - sa_ref) % 360.0 or 360.0
            best_sc = None
            best_dist = math.inf
            for sc in stu_comps:
                if sc.kind != "arc" or sc.id in used_stu_comp_ids or sc.id in matched_stu_ids:
                    continue
                if sc.center and sc.radius is not None:
                    cdist = math.dist(r_cen, sc.center)
                    rdelta = abs(rc.radius - sc.radius)
                    sa_stu = sc.start_angle or 0.0
                    ea_stu = sc.end_angle or 0.0
                    span_stu = (ea_stu - sa_stu) % 360.0 or 360.0
                    ang_delta = abs(span_ref - span_stu)
                    if cdist <= pos_tol * 2.5 and rdelta <= rad_tol * 2.0 and ang_delta <= ang_tol * 3.0:
                        err = cdist * 2.0 + rdelta + ang_delta * 0.1
                        if err < best_dist:
                            best_dist = err
                            best_sc = sc
            if best_sc is not None:
                matched_count += 1
                matched_length += rc.length
                total_error += best_dist
                matched_stu_ids.add(best_sc.id)

        elif rc.kind == "segment":
            if not rc.start or not rc.end:
                continue
            r_start = (rc.start[0] + dx, rc.start[1] + dy)
            r_end = (rc.end[0] + dx, rc.end[1] + dy)
            ref_angle = (
                math.degrees(math.atan2(r_end[1] - r_start[1], r_end[0] - r_start[0]))
                % 180.0
            )
            r_len = rc.length
            r_cen = ((r_start[0] + r_end[0]) / 2.0, (r_start[1] + r_end[1]) / 2.0)

            best_sc = None
            best_err = math.inf
            for sc in stu_comps:
                if sc.kind != "segment" or sc.id in used_stu_comp_ids or sc.id in matched_stu_ids:
                    continue
                if not sc.start or not sc.end:
                    continue
                stu_angle = (
                    math.degrees(math.atan2(sc.end[1] - sc.start[1], sc.end[0] - sc.start[0]))
                    % 180.0
                )
                ang_delta = abs(ref_angle - stu_angle) % 180.0
                ang_delta = min(ang_delta, 180.0 - ang_delta)
                if ang_delta > ang_tol * 2.5:
                    continue

                d1 = math.dist(r_start, sc.start) + math.dist(r_end, sc.end)
                d2 = math.dist(r_start, sc.end) + math.dist(r_end, sc.start)
                min_ep = min(d1, d2)
                cen_dist = math.dist(r_cen, sc.centroid)
                len_delta = abs(r_len - sc.length)

                if min_ep <= pos_tol * 4.0 or (
                    cen_dist <= max(pos_tol * 4.0, len_delta * 0.6)
                    and len_delta <= max(len_tol * 3.0, r_len * 0.35)
                ):
                    err = min(min_ep, cen_dist * 2.0 + len_delta)
                    if err < best_err:
                        best_err = err
                        best_sc = sc
            if best_sc is not None:
                matched_count += 1
                matched_length += rc.length
                total_error += best_err
                matched_stu_ids.add(best_sc.id)

    return (matched_count, matched_length, -total_error)


def _tentative_mark(
    obj: AssessmentObject,
    stu_comps: list[CanonicalComponent],
    used_stu_ids: set[str],
    t_cand: tuple[float, float],
    tolerances: Any,
) -> None:
    dx, dy = t_cand
    pos_tol = float(getattr(tolerances, "position", 2.0))
    len_tol = float(getattr(tolerances, "length", 1.0))
    ang_tol = float(getattr(tolerances, "angle", 3.0))
    rad_tol = float(getattr(tolerances, "radius", 1.0))

    for rc in obj.components:
        if rc.kind in {"circle", "arc"}:
            if not rc.center:
                continue
            r_cen = (rc.center[0] + dx, rc.center[1] + dy)
            for sc in stu_comps:
                if sc.kind != rc.kind or sc.id in used_stu_ids or not sc.center:
                    continue
                if (
                    math.dist(r_cen, sc.center) <= pos_tol * 2.5
                    and abs((rc.radius or 0) - (sc.radius or 0)) <= rad_tol * 2.0
                ):
                    used_stu_ids.add(sc.id)
                    break
        elif rc.kind == "segment":
            if not rc.start or not rc.end:
                continue
            r_cen = ((rc.start[0] + rc.end[0]) / 2.0 + dx, (rc.start[1] + rc.end[1]) / 2.0 + dy)
            for sc in stu_comps:
                if sc.kind != "segment" or sc.id in used_stu_ids:
                    continue
                if (
                    math.dist(r_cen, sc.centroid) <= pos_tol * 2.5
                    and abs(rc.length - sc.length) <= len_tol * 2.0
                ):
                    used_stu_ids.add(sc.id)
                    break


def _find_object_rigid_translation(
    obj: AssessmentObject,
    stu_comps: list[CanonicalComponent],
    used_stu_comp_ids: set[str],
    established_translations: list[tuple[float, float]],
    global_translation: tuple[float, float],
    tolerances: Any,
) -> tuple[float, float]:
    pos_tol = float(getattr(tolerances, "position", 2.0))
    len_tol = float(getattr(tolerances, "length", 1.0))
    ang_tol = float(getattr(tolerances, "angle", 3.0))
    rad_tol = float(getattr(tolerances, "radius", 1.0))

    candidate_set: set[tuple[float, float]] = {(0.0, 0.0)}
    if global_translation != (0.0, 0.0):
        candidate_set.add(global_translation)
    for t in established_translations:
        candidate_set.add(t)

    if stu_comps:
        avail_sc = [sc for sc in stu_comps if sc.id not in used_stu_comp_ids]
        if avail_sc:
            sc_xs = [sc.centroid[0] for sc in avail_sc]
            sc_ys = [sc.centroid[1] for sc in avail_sc]
            s_cen = (float(median(sc_xs)), float(median(sc_ys)))
            candidate_set.add((round(s_cen[0] - obj.centroid[0], 6), round(s_cen[1] - obj.centroid[1], 6)))
            s_min = (min(sc.bbox[0] for sc in avail_sc), min(sc.bbox[1] for sc in avail_sc))
            candidate_set.add((round(s_min[0] - obj.bounds[0], 6), round(s_min[1] - obj.bounds[1], 6)))

    n_comps = len(obj.components)
    if n_comps >= 2:
        raw_candidates: list[tuple[float, float]] = []
        bucket_vectors: dict[tuple[float, float], list[tuple[float, float]]] = defaultdict(list)
        for rc in obj.components:
            for sc in stu_comps:
                if sc.id in used_stu_comp_ids or sc.kind != rc.kind:
                    continue
                if rc.kind in {"circle", "arc"}:
                    if rc.center and sc.center and rc.radius is not None and sc.radius is not None:
                        if abs(rc.radius - sc.radius) <= rad_tol * 2.0:
                            vx = sc.center[0] - rc.center[0]
                            vy = sc.center[1] - rc.center[1]
                            key = (round(vx, 1), round(vy, 1))
                            raw_candidates.append(key)
                            bucket_vectors[key].append((vx, vy))
                elif rc.kind == "segment":
                    if rc.start and rc.end and sc.start and sc.end:
                        if abs(rc.length - sc.length) <= len_tol * 2.0:
                            r_ang = math.degrees(math.atan2(rc.end[1] - rc.start[1], rc.end[0] - rc.start[0])) % 180.0
                            s_ang = math.degrees(math.atan2(sc.end[1] - sc.start[1], sc.end[0] - sc.start[0])) % 180.0
                            a_delta = abs(r_ang - s_ang) % 180.0
                            a_delta = min(a_delta, 180.0 - a_delta)
                            if a_delta <= ang_tol * 2.0:
                                vx = sc.centroid[0] - rc.centroid[0]
                                vy = sc.centroid[1] - rc.centroid[1]
                                key = (round(vx, 1), round(vy, 1))
                                raw_candidates.append(key)
                                bucket_vectors[key].append((vx, vy))
        if raw_candidates:
            counts = Counter(raw_candidates)
            for cand, _ in counts.most_common(15):
                vecs = bucket_vectors.get(cand)
                if vecs:
                    refined = (
                        round(float(median(v[0] for v in vecs)), 6),
                        round(float(median(v[1] for v in vecs)), 6),
                    )
                    candidate_set.add(refined)
                else:
                    candidate_set.add(cand)

    elif n_comps == 1:
        rc = obj.components[0]
        if rc.kind in {"circle", "arc"}:
            for sc in stu_comps:
                if sc.id in used_stu_comp_ids or sc.kind != rc.kind:
                    continue
                if rc.center and sc.center and rc.radius is not None and sc.radius is not None:
                    if abs(rc.radius - sc.radius) <= rad_tol * 2.0:
                        candidate_set.add(
                            (
                                round(sc.center[0] - rc.center[0], 6),
                                round(sc.center[1] - rc.center[1], 6),
                            )
                        )
        elif rc.kind == "segment":
            for sc in stu_comps:
                if sc.id in used_stu_comp_ids or sc.kind != "segment":
                    continue
                if rc.start and rc.end and sc.start and sc.end:
                    if abs(rc.length - sc.length) <= len_tol * 2.0:
                        r_ang = math.degrees(math.atan2(rc.end[1] - rc.start[1], rc.end[0] - rc.start[0])) % 180.0
                        s_ang = math.degrees(math.atan2(sc.end[1] - sc.start[1], sc.end[0] - sc.start[0])) % 180.0
                        a_delta = abs(r_ang - s_ang) % 180.0
                        a_delta = min(a_delta, 180.0 - a_delta)
                        if a_delta <= ang_tol * 2.0:
                            candidate_set.add(
                                (
                                    round(sc.centroid[0] - rc.centroid[0], 6),
                                    round(sc.centroid[1] - rc.centroid[1], 6),
                                )
                            )

    base_score = _evaluate_object_candidate_translation(
        obj, stu_comps, used_stu_comp_ids, (0.0, 0.0), pos_tol, len_tol, ang_tol, rad_tol
    )
    best_cand = (0.0, 0.0)
    best_score = base_score

    def _cand_rank(c: tuple[float, float], sc: tuple[int, float, float]):
        matches, pres, acc = sc
        is_est = 1 if (c in established_translations or (c == global_translation and c != (0.0, 0.0))) else 0
        dist = math.hypot(c[0], c[1])
        return (matches, is_est, pres + acc, -dist)

    best_rank = _cand_rank((0.0, 0.0), base_score)

    for cand in candidate_set:
        if cand == (0.0, 0.0):
            continue
        score = _evaluate_object_candidate_translation(
            obj, stu_comps, used_stu_comp_ids, cand, pos_tol, len_tol, ang_tol, rad_tol
        )
        rank = _cand_rank(cand, score)
        if rank > best_rank:
            best_rank = rank
            best_score = score
            best_cand = cand

    b_matches = base_score[0]
    m_matches = best_score[0]

    if n_comps >= 2:
        if b_matches >= 2:
            if (
                global_translation != (0.0, 0.0)
                and best_cand != (0.0, 0.0)
                and math.hypot(best_cand[0], best_cand[1]) <= pos_tol
                and m_matches >= b_matches
                and best_score[2] > base_score[2] + 1.0
            ):
                return best_cand
            return (0.0, 0.0)
        # If candidate translation matches more components than in-place and has substantial support
        is_best_est = (
            best_cand in established_translations
            or (best_cand == global_translation and best_cand != (0.0, 0.0))
        )
        min_required = 2 if is_best_est else max(2, int(0.20 * n_comps))
        if m_matches > b_matches and m_matches >= min_required:
            return best_cand
        if b_matches > 0:
            return (0.0, 0.0)
        return global_translation

    if n_comps == 1:
        if b_matches == 1:
            return (0.0, 0.0)
        if m_matches == 1:
            return best_cand
        return global_translation

    return (0.0, 0.0)


def _match_assessment_objects(
    ref_objects: list[AssessmentObject],
    stu_objects: list[AssessmentObject],
    stu_comps: list[CanonicalComponent],
    tolerances: Any,
    normalization_mode: str,
    global_translation: tuple[float, float],
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, AssessmentObject],
    list[tuple[str, str, tuple[float, float]]],
]:
    pos_tol = float(getattr(tolerances, "position", 2.0))
    len_tol = float(getattr(tolerances, "length", 1.0))
    ang_tol = float(getattr(tolerances, "angle", 3.0))
    rad_tol = float(getattr(tolerances, "radius", 1.0))

    object_translations: dict[str, tuple[float, float]] = {}
    matched_ref_to_stu: dict[str, AssessmentObject] = {}
    matched_objects_list: list[tuple[str, str, tuple[float, float]]] = []

    if not ref_objects:
        return object_translations, matched_ref_to_stu, matched_objects_list

    assigned_ro_ids: set[str] = set()
    assigned_so_ids: set[str] = set()

    # Pass 1: Exact in-place matches at (0.0, 0.0), ranked by match quality and proximity
    pass1_candidates: list[
        tuple[int, float, float, int, str, str, AssessmentObject, AssessmentObject]
    ] = []
    for ro in ref_objects:
        for so in stu_objects:
            score_zero = _evaluate_object_candidate_translation(
                ro, so.components, set(), (0.0, 0.0), pos_tol, len_tol, ang_tol, rad_tol
            )
            if score_zero[0] == len(ro.components) and score_zero[0] > 0:
                cen_dist = math.dist(ro.centroid, so.centroid)
                pass1_candidates.append(
                    (
                        score_zero[0],
                        score_zero[1] + score_zero[2],
                        -cen_dist,
                        -len(so.components),
                        ro.object_id,
                        so.object_id,
                        ro,
                        so,
                    )
                )
    pass1_candidates.sort(
        key=lambda x: (-x[0], -x[1], -x[2], -x[3], x[4], x[5])
    )
    for _, _, _, _, _, _, ro, so in pass1_candidates:
        if ro.object_id in assigned_ro_ids or so.object_id in assigned_so_ids:
            continue
        t_zero = (0.0, 0.0)
        if normalization_mode == "translation" and global_translation != (0.0, 0.0):
            t_fine = _find_object_rigid_translation(
                ro, so.components, set(), [], global_translation, tolerances
            )
            if math.hypot(t_fine[0], t_fine[1]) <= pos_tol:
                t_zero = t_fine
        object_translations[ro.object_id] = t_zero
        matched_ref_to_stu[ro.object_id] = so
        assigned_ro_ids.add(ro.object_id)
        assigned_so_ids.add(so.object_id)
        matched_objects_list.append((ro.object_id, so.object_id, t_zero))

    # Pass 1b: Anchor protection for incomplete in-place objects (Criterion 3: B >= 2 anchors to (0, 0))
    for ro in ref_objects:
        if ro.object_id in assigned_ro_ids:
            continue
        n_c = len(ro.components)
        if n_c >= 2:
            score_zero = _evaluate_object_candidate_translation(
                ro, stu_comps, set(), (0.0, 0.0), pos_tol, len_tol, ang_tol, rad_tol
            )
            b_matches = score_zero[0]
            if b_matches >= 2:
                t_zero = (0.0, 0.0)
                if normalization_mode == "translation" and global_translation != (0.0, 0.0):
                    t_fine = _find_object_rigid_translation(
                        ro, stu_comps, set(), [], global_translation, tolerances
                    )
                    if math.hypot(t_fine[0], t_fine[1]) <= pos_tol:
                        t_zero = t_fine
                object_translations[ro.object_id] = t_zero
                assigned_ro_ids.add(ro.object_id)
                for so in stu_objects:
                    if so.object_id not in assigned_so_ids:
                        so_score = _evaluate_object_candidate_translation(
                            ro, so.components, set(), t_zero, pos_tol, len_tol, ang_tol, rad_tol
                        )
                        if so_score[0] > 0:
                            assigned_so_ids.add(so.object_id)
                            if ro.object_id not in matched_ref_to_stu:
                                matched_ref_to_stu[ro.object_id] = so
                            matched_objects_list.append((ro.object_id, so.object_id, t_zero))

    established_translations: list[tuple[float, float]] = []
    if global_translation != (0.0, 0.0):
        established_translations.append(global_translation)
    for t_val in object_translations.values():
        if t_val != (0.0, 0.0) and t_val not in established_translations:
            established_translations.append(t_val)

    # Pass 2: Evaluate candidate translations between unassigned ref_objects and stu_objects
    pair_scores: list[tuple[float, int, float, float, AssessmentObject, AssessmentObject, tuple[float, float]]] = []
    t_bucket_ro_ids: dict[tuple[float, float], set[str]] = defaultdict(set)
    for ro in ref_objects:
        if ro.object_id in assigned_ro_ids:
            continue
        for so in stu_objects:
            if so.object_id in assigned_so_ids:
                continue
            so_cen_t = (round(so.centroid[0] - ro.centroid[0], 6), round(so.centroid[1] - ro.centroid[1], 6))
            so_bb_t = (
                round((so.bounds[0] + so.bounds[2]) / 2.0 - (ro.bounds[0] + ro.bounds[2]) / 2.0, 6),
                round((so.bounds[1] + so.bounds[3]) / 2.0 - (ro.bounds[1] + ro.bounds[3]) / 2.0, 6),
            )
            est_with_so = list(established_translations)
            for cand_t in (so_cen_t, so_bb_t):
                if cand_t not in est_with_so:
                    est_with_so.append(cand_t)
            t = _find_object_rigid_translation(
                ro, so.components, set(), est_with_so, global_translation, tolerances
            )
            score = _evaluate_object_candidate_translation(
                ro, so.components, set(), t, pos_tol, len_tol, ang_tol, rad_tol
            )
            matched_count = score[0]
            frac = matched_count / max(len(ro.components), 1)
            acc_sum = score[1] + score[2]
            dist_t = math.hypot(t[0], t[1])
            if matched_count > 0:
                t_bucket_ro_ids[(round(t[0], 1), round(t[1], 1))].add(ro.object_id)
                pair_scores.append((frac, matched_count, acc_sum, -dist_t, ro, so, t))

    pair_scores.sort(
        key=lambda x: (
            x[0],
            x[1],
            x[2],
            len(t_bucket_ro_ids[(round(x[6][0], 1), round(x[6][1], 1))]),
            x[3],
        ),
        reverse=True,
    )
    for frac, count, _, _, ro, so, t in pair_scores:
        if ro.object_id not in assigned_ro_ids and so.object_id not in assigned_so_ids:
            assigned_ro_ids.add(ro.object_id)
            assigned_so_ids.add(so.object_id)
            matched_ref_to_stu[ro.object_id] = so
            object_translations[ro.object_id] = t
            matched_objects_list.append((ro.object_id, so.object_id, t))
            if t != (0.0, 0.0) and t not in established_translations:
                established_translations.append(t)

    # Pass 3: Centroid-based matching for unassigned objects with dimension/radius deviations
    for ro in ref_objects:
        if ro.object_id in assigned_ro_ids:
            continue
        for so in stu_objects:
            if so.object_id in assigned_so_ids:
                continue
            test_cands = [(0.0, 0.0)]
            if global_translation != (0.0, 0.0):
                test_cands.append(global_translation)
            for et in established_translations:
                if et not in test_cands:
                    test_cands.append(et)
            for tc in test_cands:
                t_cen = (ro.centroid[0] + tc[0], ro.centroid[1] + tc[1])
                if math.dist(t_cen, so.centroid) <= pos_tol * 2.5:
                    if len(ro.components) == len(so.components) or any(rc.kind == sc.kind for rc in ro.components for sc in so.components):
                        assigned_ro_ids.add(ro.object_id)
                        assigned_so_ids.add(so.object_id)
                        matched_ref_to_stu[ro.object_id] = so
                        object_translations[ro.object_id] = tc
                        matched_objects_list.append((ro.object_id, so.object_id, tc))
                        if tc != (0.0, 0.0) and tc not in established_translations:
                            established_translations.append(tc)
                        break
        if ro.object_id in assigned_ro_ids:
            break

    # Pass 4: Fallback for any ref_objects that didn't match a whole stu_object
    tentative_used: set[str] = {
        c.id
        for so in stu_objects
        if so.object_id in assigned_so_ids
        for c in so.components
    }
    for ro in ref_objects:
        if ro.object_id not in assigned_ro_ids:
            t_k = _find_object_rigid_translation(
                ro, stu_comps, tentative_used, established_translations, global_translation, tolerances
            )
            score = _evaluate_object_candidate_translation(
                ro, stu_comps, tentative_used, t_k, pos_tol, len_tol, ang_tol, rad_tol
            )
            if score[0] > 0:
                object_translations[ro.object_id] = t_k
                _tentative_mark(ro, stu_comps, tentative_used, t_k, tolerances)
            else:
                object_translations[ro.object_id] = (0.0, 0.0)

    for ro in ref_objects:
        if ro.object_id not in object_translations:
            object_translations[ro.object_id] = (0.0, 0.0)

    # Associate any additional unassigned student objects that match an assigned reference object at its translation
    for ro in ref_objects:
        if ro.object_id in object_translations:
            t = object_translations[ro.object_id]
            for so in stu_objects:
                if so.object_id not in assigned_so_ids:
                    so_score = _evaluate_object_candidate_translation(
                        ro, so.components, set(), t, pos_tol, len_tol, ang_tol, rad_tol
                    )
                    if so_score[0] > 0:
                        assigned_so_ids.add(so.object_id)
                        matched_objects_list.append((ro.object_id, so.object_id, t))

    return object_translations, matched_ref_to_stu, matched_objects_list


def match_canonical_geometry(
    reference: Drawing,
    student: Drawing,
    tolerances: Any,
    translation: tuple[float, float] = (0.0, 0.0),
    confirmed_objects: list[dict[str, Any]] | None = None,
    normalization_mode: str = "strict",
) -> CanonicalMatchResult:
    """Perform representation-independent matching between reference and student drawings."""
    if hasattr(tolerances, "position") and getattr(tolerances, "position") is not None:
        pos_tol = float(getattr(tolerances, "position"))
    elif isinstance(tolerances, dict) and "position" in tolerances and tolerances["position"] is not None:
        pos_tol = float(tolerances["position"])
    else:
        pos_tol = 2.0
    len_tol = float(getattr(tolerances, "length", 1.0))
    ang_tol = float(getattr(tolerances, "angle", 3.0))
    rad_tol = float(getattr(tolerances, "radius", 1.0))

    ref_objects = extract_assessment_objects(
        reference, pos_tol, confirmed_objects
    )
    ref_objects.sort(key=lambda o: (o.source_entity_ids[0] if o.source_entity_ids else o.object_id, o.object_id))
    for ro in ref_objects:
        ro.components.sort(key=lambda c: (c.source_entity_id, c.id))
    stu_objects = extract_assessment_objects(student, pos_tol)
    stu_comp_parent_map: dict[str, str] = {}
    for so in stu_objects:
        for c in so.components:
            stu_comp_parent_map[c.id] = so.object_id
            for sid in c.source_entity_ids or [c.source_entity_id]:
                stu_comp_parent_map[sid] = so.object_id

    degenerate_student_entities = [
        e.id for e in student.entities
        if (e.kind == "line" and len(e.points) >= 2 and math.dist(e.points[0], e.points[1]) <= 1e-4)
        or (e.kind in ("circle", "arc") and (e.radius is None or e.radius <= 1e-4))
    ]

    raw_stu_comps = [
        c
        for c in _split_at_junctions(extract_canonical_components(student))
        if c.kind not in {"text", "dimension"}
    ]

    dx, dy = translation
    stu_comps: list[CanonicalComponent] = []
    base_stu_comps = (
        [c for so in stu_objects for c in so.components]
        if stu_objects
        else raw_stu_comps
    )
    for sc in base_stu_comps:
        parent_oid = stu_comp_parent_map.get(sc.id) or stu_comp_parent_map.get(sc.source_entity_id)
        translated_start = (
            (sc.start[0] + dx, sc.start[1] + dy) if sc.start else None
        )
        translated_end = (sc.end[0] + dx, sc.end[1] + dy) if sc.end else None
        translated_center = (
            (sc.center[0] + dx, sc.center[1] + dy) if sc.center else None
        )
        translated_bbox = (
            sc.bbox[0] + dx,
            sc.bbox[1] + dy,
            sc.bbox[2] + dx,
            sc.bbox[3] + dy,
        )
        translated_centroid = (sc.centroid[0] + dx, sc.centroid[1] + dy)
        stu_comps.append(
            CanonicalComponent(
                id=sc.id,
                kind=sc.kind,
                source_entity_id=sc.source_entity_id,
                source_entity_ids=(
                    list(sc.source_entity_ids)
                    if sc.source_entity_ids
                    else [sc.source_entity_id]
                ),
                source_handle=sc.source_handle,
                layer=sc.layer,
                source=sc.source,
                parent_object_id=parent_oid,
                start=translated_start,
                end=translated_end,
                length=sc.length,
                center=translated_center,
                radius=sc.radius,
                start_angle=sc.start_angle,
                end_angle=sc.end_angle,
                bbox=translated_bbox,
                centroid=translated_centroid,
                properties=dict(sc.properties),
            )
        )
    stu_comps.sort(key=lambda c: (c.source_entity_id, c.id))

    total_components = sum(len(obj.components) for obj in ref_objects)
    if total_components == 0:
        return CanonicalMatchResult(
            reference_objects=[],
            component_matches=[],
            missing_components=[],
            extra_student_entities=[],
            matched_pairs=[],
            completion_fraction=0.0,
            accuracy_fraction=0.0,
            position_tolerance=pos_tol,
        )

    comp_weights: dict[str, float] = {}
    for obj in ref_objects:
        m = len(obj.components)
        for comp in obj.components:
            comp_weights[comp.id] = (obj.weight / m) if m > 0 else 0.0

    if not stu_comps:
        all_missing = [comp for obj in ref_objects for comp in obj.components]
        matches = [
            ComponentMatch(
                reference_component=c,
                student_components=[],
                presence=0.0,
                correctness=0.0,
                weight=comp_weights.get(c.id, 0.0),
            )
            for c in all_missing
        ]
        return CanonicalMatchResult(
            reference_objects=ref_objects,
            component_matches=matches,
            missing_components=all_missing,
            extra_student_entities=[],
            matched_pairs=[],
            completion_fraction=0.0,
            accuracy_fraction=0.0,
            object_summary={
                "total_reference_objects": len(ref_objects),
                "total_reference_components": total_components,
                "matched_components_count": 0,
                "partial_components_count": 0,
                "missing_components_count": total_components,
                "extra_student_entities_count": 0,
            },
            position_tolerance=pos_tol,
        )

    student_available_intervals: dict[str, list[tuple[float, float]]] = {
        sc.id: [(0.0, sc.length)] for sc in stu_comps if sc.kind == "segment"
    }
    used_stu_comp_ids: set[str] = set()
    used_stu_entity_ids: set[str] = set()
    duplicate_student_entities: set[str] = set()
    matched_pairs_set: set[tuple[str, str]] = set()
    matched_pairs: list[tuple[str, str, float]] = []

    component_matches: list[ComponentMatch] = []
    missing_components: list[CanonicalComponent] = []
    ambiguous_groups: list[dict[str, Any]] = []

    def _mark_stu_used(sc: CanonicalComponent) -> None:
        used_stu_comp_ids.add(sc.id)
        for eid in sc.source_entity_ids or [sc.source_entity_id]:
            used_stu_entity_ids.add(eid)

    def _record_pair(
        rc: CanonicalComponent, sc: CanonicalComponent, conf: float
    ) -> None:
        for r_eid in rc.source_entity_ids or [rc.source_entity_id]:
            for s_eid in sc.source_entity_ids or [sc.source_entity_id]:
                pair_key = (r_eid, s_eid)
                if pair_key not in matched_pairs_set:
                    matched_pairs_set.add(pair_key)
                    matched_pairs.append((r_eid, s_eid, conf))

    object_translations, matched_ref_to_stu, matched_objects_list = _match_assessment_objects(
        ref_objects, stu_objects, stu_comps, tolerances, normalization_mode, translation
    )

    exact_matched_ref_comp_ids: set[str] = set()

    # Pre-pass: Claim exact 1-to-1 segment matches across assessment objects
    # to prevent collinear larger objects from stealing exact components (e.g. windows on walls)
    candidate_exact_pairs: list[tuple[int, float, CanonicalComponent, CanonicalComponent, float]] = []
    for obj in ref_objects:
        obj_dx, obj_dy = object_translations.get(obj.object_id, (0.0, 0.0))
        for rc in obj.components:
            if rc.kind != "segment" or not rc.start or not rc.end:
                continue
            r_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy)
            r_end = (rc.end[0] + obj_dx, rc.end[1] + obj_dy)
            r_len = rc.length
            w_i = comp_weights.get(rc.id, 0.0)

            for sc in stu_comps:
                if sc.kind != "segment" or not sc.start or not sc.end or sc.id in used_stu_comp_ids:
                    continue
                d1 = math.dist(r_start, sc.start) + math.dist(r_end, sc.end)
                d2 = math.dist(r_start, sc.end) + math.dist(r_end, sc.start)
                min_ep_dist = min(d1, d2)
                len_delta = abs(r_len - sc.length)
                if min_ep_dist <= pos_tol * 2.0 and len_delta <= len_tol:
                    layer_match = 1 if sc.layer == rc.layer else 0
                    candidate_exact_pairs.append(
                        (layer_match, -min_ep_dist - len_delta, rc, sc, w_i)
                    )

    candidate_exact_pairs.sort(key=lambda x: (-x[0], -x[1], x[2].id, x[3].id))
    claimed_rc_ids: set[str] = set()
    for _, _, rc, sc, w_i in candidate_exact_pairs:
        if rc.id in claimed_rc_ids or sc.id in used_stu_comp_ids:
            continue
        claimed_rc_ids.add(rc.id)
        exact_matched_ref_comp_ids.add(rc.id)
        _mark_stu_used(sc)
        student_available_intervals[sc.id] = []
        _record_pair(rc, sc, 1.0)
        component_matches.append(
            ComponentMatch(
                reference_component=rc,
                student_components=[sc],
                presence=1.0,
                correctness=1.0,
                weight=w_i,
                covered_length=rc.length,
                errors=[],
            )
        )

    # Phase 1: Exact / collinear / concentric matching
    for obj in ref_objects:
        obj_dx, obj_dy = object_translations.get(obj.object_id, (0.0, 0.0))
        target_so = matched_ref_to_stu.get(obj.object_id)
        if normalization_mode == "strict":
            target_stu_comps = stu_comps
        elif not stu_objects:
            target_stu_comps = stu_comps
        else:
            matched_sos = {s_id for r_id, s_id, _ in matched_objects_list if r_id == obj.object_id}
            if target_so is not None:
                matched_sos.add(target_so.object_id)
            other_matched_sos = {
                s_id for r_id, s_id, _ in matched_objects_list if r_id != obj.object_id
            }
            min_x = obj.bounds[0] + obj_dx
            min_y = obj.bounds[1] + obj_dy
            max_x = obj.bounds[2] + obj_dx
            max_y = obj.bounds[3] + obj_dy
            margin = max(pos_tol * 5.0, 25.0)

            target_stu_comps = [
                sc for sc in stu_comps
                if (sc.parent_object_id in matched_sos)
                or (
                    sc.parent_object_id not in other_matched_sos
                    and min_x - margin <= sc.centroid[0] <= max_x + margin
                    and min_y - margin <= sc.centroid[1] <= max_y + margin
                )
            ]

        for ref_comp in obj.components:
            if ref_comp.id in exact_matched_ref_comp_ids:
                continue
            w_i = comp_weights.get(ref_comp.id, 0.0)
            if obj_dx != 0.0 or obj_dy != 0.0:
                eval_comp = replace(
                    ref_comp,
                    start=(ref_comp.start[0] + obj_dx, ref_comp.start[1] + obj_dy) if ref_comp.start else None,
                    end=(ref_comp.end[0] + obj_dx, ref_comp.end[1] + obj_dy) if ref_comp.end else None,
                    center=(ref_comp.center[0] + obj_dx, ref_comp.center[1] + obj_dy) if ref_comp.center else None,
                    centroid=(ref_comp.centroid[0] + obj_dx, ref_comp.centroid[1] + obj_dy),
                    bbox=(ref_comp.bbox[0] + obj_dx, ref_comp.bbox[1] + obj_dy, ref_comp.bbox[2] + obj_dx, ref_comp.bbox[3] + obj_dy),
                )
            else:
                eval_comp = ref_comp

            if ref_comp.kind == "circle":
                best_match = None
                best_cost = math.inf
                for sc in target_stu_comps:
                    if sc.kind != "circle" or sc.id in used_stu_comp_ids:
                        continue
                    if (
                        eval_comp.center
                        and sc.center
                        and eval_comp.radius is not None
                        and sc.radius is not None
                    ):
                        center_dist = math.dist(eval_comp.center, sc.center)
                        rad_delta = abs(eval_comp.radius - sc.radius)
                        if center_dist <= pos_tol * 2.5:
                            cost = center_dist * 2.0 + rad_delta
                            if cost < best_cost:
                                best_cost = cost
                                best_match = sc

                if best_match is not None:
                    _mark_stu_used(best_match)
                    center_dist = math.dist(eval_comp.center, best_match.center)
                    rad_delta = abs(eval_comp.radius - best_match.radius)
                    p_i = 1.0
                    q_i = (
                        1.0
                        if (center_dist <= pos_tol and rad_delta <= rad_tol)
                        else 0.0
                    )
                    errs: list[dict[str, Any]] = []
                    if center_dist > pos_tol:
                        vec = [
                            round(best_match.center[0] - eval_comp.center[0], 4),
                            round(best_match.center[1] - eval_comp.center[1], 4),
                        ]
                        errs.append(
                            {
                                "category": "incorrect_position",
                                "expected": 0.0,
                                "actual": round(center_dist, 4),
                                "deviation": round(center_dist, 4),
                                "vector": vec,
                                "tolerance": pos_tol,
                                "student_entity_id": best_match.source_entity_id,
                            }
                        )
                    if rad_delta > rad_tol:
                        errs.append(
                            {
                                "category": "incorrect_radius",
                                "expected": round(ref_comp.radius, 4),
                                "actual": round(best_match.radius, 4),
                                "tolerance": rad_tol,
                                "student_entity_id": best_match.source_entity_id,
                            }
                        )
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[best_match],
                            presence=p_i,
                            correctness=q_i,
                            weight=w_i,
                            covered_length=ref_comp.length,
                            errors=errs,
                        )
                    )
                    _record_pair(ref_comp, best_match, 1.0 if q_i > 0 else 0.8)
                else:
                    missing_components.append(ref_comp)
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[],
                            presence=0.0,
                            correctness=0.0,
                            weight=w_i,
                        )
                    )

            elif ref_comp.kind == "arc":
                best_match = None
                best_cost = math.inf
                sa_ref = ref_comp.start_angle or 0.0
                ea_ref = ref_comp.end_angle or 0.0
                span_ref = (ea_ref - sa_ref) % 360.0
                if span_ref == 0.0:
                    span_ref = 360.0

                for sc in target_stu_comps:
                    if sc.kind != "arc" or sc.id in used_stu_comp_ids:
                        continue
                    if (
                        eval_comp.center
                        and sc.center
                        and eval_comp.radius is not None
                        and sc.radius is not None
                    ):
                        center_dist = math.dist(eval_comp.center, sc.center)
                        rad_delta = abs(eval_comp.radius - sc.radius)
                        if (
                            center_dist <= pos_tol * 2.5
                            and rad_delta <= rad_tol * 2.5
                        ):
                            sa_stu = sc.start_angle or 0.0
                            ea_stu = sc.end_angle or 0.0
                            span_stu = (ea_stu - sa_stu) % 360.0
                            if span_stu == 0.0:
                                span_stu = 360.0
                            cost = (
                                center_dist
                                + rad_delta
                                + abs(span_ref - span_stu) * 0.1
                            )
                            if cost < best_cost:
                                best_cost = cost
                                best_match = sc

                if best_match is not None:
                    _mark_stu_used(best_match)
                    center_dist = math.dist(eval_comp.center, best_match.center)
                    rad_delta = abs(eval_comp.radius - best_match.radius)
                    sa_stu = best_match.start_angle or 0.0
                    ea_stu = best_match.end_angle or 0.0
                    span_stu = (ea_stu - sa_stu) % 360.0
                    if span_stu == 0.0:
                        span_stu = 360.0
                    ang_overlap = _arc_overlap(
                        sa_ref, span_ref, sa_stu, span_stu
                    )
                    p_i = min(1.0, ang_overlap / span_ref)
                    if p_i >= 1.0 - 1e-4:
                        p_i = 1.0

                    q_i = (
                        1.0
                        if (
                            center_dist <= pos_tol
                            and rad_delta <= rad_tol
                            and span_stu - ang_overlap <= ang_tol
                        )
                        else 0.0
                    )
                    errs = []
                    if center_dist > pos_tol:
                        vec = [
                            round(best_match.center[0] - eval_comp.center[0], 4),
                            round(best_match.center[1] - eval_comp.center[1], 4),
                        ]
                        errs.append(
                            {
                                "category": "incorrect_position",
                                "expected": 0.0,
                                "actual": round(center_dist, 4),
                                "deviation": round(center_dist, 4),
                                "vector": vec,
                                "tolerance": pos_tol,
                                "student_entity_id": best_match.source_entity_id,
                            }
                        )
                    if rad_delta > rad_tol:
                        errs.append(
                            {
                                "category": "incorrect_radius",
                                "expected": round(ref_comp.radius, 4),
                                "actual": round(best_match.radius, 4),
                                "tolerance": rad_tol,
                                "student_entity_id": best_match.source_entity_id,
                            }
                        )
                    if (
                        span_stu - ang_overlap > ang_tol
                        or abs(span_ref - span_stu) > ang_tol
                    ):
                        errs.append(
                            {
                                "category": "incorrect_angle",
                                "expected": round(span_ref, 4),
                                "actual": round(span_stu, 4),
                                "tolerance": ang_tol,
                                "student_entity_id": best_match.source_entity_id,
                            }
                        )
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[best_match],
                            presence=p_i,
                            correctness=q_i,
                            weight=w_i,
                            covered_length=ref_comp.length * p_i,
                            errors=errs,
                        )
                    )
                    _record_pair(ref_comp, best_match, 1.0 if q_i > 0 else 0.8)
                else:
                    missing_components.append(ref_comp)
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[],
                            presence=0.0,
                            correctness=0.0,
                            weight=w_i,
                        )
                    )

            elif ref_comp.kind == "ellipse":
                best_match = None
                best_cost = math.inf
                r_major = ref_comp.properties.get("major_axis", (1.0, 0.0))
                r_len = math.hypot(float(r_major[0]), float(r_major[1]))
                r_ang = (
                    math.atan2(float(r_major[1]), float(r_major[0])) % math.pi
                )
                r_ratio = float(ref_comp.properties.get("ratio", 1.0))

                for sc in target_stu_comps:
                    if sc.kind != "ellipse" or sc.id in used_stu_comp_ids:
                        continue
                    if eval_comp.center and sc.center:
                        c_dist = math.dist(eval_comp.center, sc.center)
                        if c_dist <= pos_tol * 2.5:
                            s_major = sc.properties.get("major_axis", (1.0, 0.0))
                            s_len = math.hypot(
                                float(s_major[0]), float(s_major[1])
                            )
                            s_ang = (
                                math.atan2(
                                    float(s_major[1]), float(s_major[0])
                                )
                                % math.pi
                            )
                            s_ratio = float(sc.properties.get("ratio", 1.0))
                            l_delta = abs(r_len - s_len)
                            a_delta = abs(r_ang - s_ang) % math.pi
                            a_delta = min(a_delta, math.pi - a_delta)
                            ratio_delta = abs(r_ratio - s_ratio)
                            cost = c_dist + l_delta + ratio_delta * 10.0
                            if cost < best_cost:
                                best_cost = cost
                                best_match = (
                                    sc,
                                    c_dist,
                                    l_delta,
                                    a_delta,
                                    ratio_delta,
                                )

                if best_match is not None:
                    sc, c_dist, l_delta, a_delta, ratio_delta = best_match
                    ref_start = math.degrees(
                        float(ref_comp.properties.get("start_param", 0))
                    )
                    ref_span = (
                        math.degrees(
                            float(ref_comp.properties.get("end_param", math.tau))
                            - float(ref_comp.properties.get("start_param", 0))
                        )
                        % 360
                        or 360
                    )
                    s_major = sc.properties.get("major_axis", (1, 0))
                    phase = math.degrees(
                        math.atan2(s_major[1], s_major[0])
                        - math.atan2(r_major[1], r_major[0])
                    )
                    stu_start = (
                        math.degrees(float(sc.properties.get("start_param", 0)))
                        + phase
                    )
                    stu_span = (
                        math.degrees(
                            float(sc.properties.get("end_param", math.tau))
                            - float(sc.properties.get("start_param", 0))
                        )
                        % 360
                        or 360
                    )
                    ref_intervals = _arc_to_intervals(ref_start % 360, ref_span)
                    stu_intervals = _arc_to_intervals(stu_start % 360, stu_span)
                    overlap_intervals = [
                        (max(a, c), min(b, d))
                        for a, b in ref_intervals
                        for c, d in stu_intervals
                        if min(b, d) > max(a, c)
                    ]
                    reference_length = _ellipse_interval_length(
                        ref_intervals, r_len, r_ratio
                    )
                    covered_length = _ellipse_interval_length(
                        overlap_intervals, r_len, r_ratio
                    )
                    presence = min(
                        1.0, covered_length / max(reference_length, 1e-12)
                    )
                    outside_span = stu_span - sum(
                        b - a for a, b in overlap_intervals
                    )
                    _mark_stu_used(sc)
                    q_i = (
                        1.0
                        if (
                            c_dist <= pos_tol
                            and l_delta <= len_tol
                            and math.degrees(a_delta) <= ang_tol
                            and ratio_delta <= 0.05
                            and outside_span <= ang_tol
                        )
                        else 0.0
                    )
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[sc],
                            presence=presence,
                            correctness=q_i,
                            weight=w_i,
                            covered_length=covered_length,
                        )
                    )
                    _record_pair(ref_comp, sc, 1.0 if q_i > 0 else 0.8)
                else:
                    missing_components.append(ref_comp)
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[],
                            presence=0.0,
                            correctness=0.0,
                            weight=w_i,
                        )
                    )

            elif ref_comp.kind == "spline":
                best_match = None
                best_cost = math.inf
                raw_r_pts = ref_comp.properties.get("sample_points", [])
                if obj_dx != 0.0 or obj_dy != 0.0:
                    r_pts = [(p[0] + obj_dx, p[1] + obj_dy) for p in raw_r_pts]
                else:
                    r_pts = raw_r_pts

                for sc in target_stu_comps:
                    if sc.kind != "spline" or sc.id in used_stu_comp_ids:
                        continue
                    c_dist = math.dist(eval_comp.centroid, sc.centroid)
                    if c_dist <= pos_tol * 2.5:
                        s_pts = sc.properties.get("sample_points", [])
                        if r_pts and s_pts and len(r_pts) == len(s_pts):
                            max_pt_dist = min(
                                max(
                                    math.dist(p1, p2)
                                    for p1, p2 in zip(r_pts, traversal)
                                )
                                for traversal in (s_pts, list(reversed(s_pts)))
                            )
                        else:
                            max_pt_dist = math.inf
                        if max_pt_dist < best_cost:
                            best_cost = max_pt_dist
                            best_match = (sc, max_pt_dist)

                if best_match is not None and best_cost <= pos_tol * 2.5:
                    sc, max_pt_dist = best_match
                    _mark_stu_used(sc)
                    q_i = 1.0 if max_pt_dist <= pos_tol else 0.0
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[sc],
                            presence=1.0,
                            correctness=q_i,
                            weight=w_i,
                            covered_length=ref_comp.length,
                        )
                    )
                    _record_pair(ref_comp, sc, 1.0 if q_i > 0 else 0.8)
                else:
                    missing_components.append(ref_comp)
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[],
                            presence=0.0,
                            correctness=0.0,
                            weight=w_i,
                        )
                    )

            elif ref_comp.kind == "segment" and eval_comp.start and eval_comp.end:
                A = eval_comp.start
                B = eval_comp.end
                L = max(eval_comp.length, 1e-9)
                ux = (B[0] - A[0]) / L
                uy = (B[1] - A[1]) / L
                nx = -uy
                ny = ux

                ref_angle = (
                    math.degrees(math.atan2(B[1] - A[1], B[0] - A[0])) % 180.0
                )

                # Compute the contiguous collinear reference span [span_min, span_max] in obj.components
                collinear_ref_intervals: list[tuple[float, float]] = [(0.0, L)]
                for other_rc in obj.components:
                    if other_rc.id == ref_comp.id or other_rc.kind != "segment" or not other_rc.start or not other_rc.end:
                        continue
                    oA = (other_rc.start[0] + obj_dx, other_rc.start[1] + obj_dy)
                    oB = (other_rc.end[0] + obj_dx, other_rc.end[1] + obj_dy)
                    odA = abs((oA[0] - A[0]) * nx + (oA[1] - A[1]) * ny)
                    odB = abs((oB[0] - A[0]) * nx + (oB[1] - A[1]) * ny)
                    if odA <= 1e-3 and odB <= 1e-3:
                        otA = (oA[0] - A[0]) * ux + (oA[1] - A[1]) * uy
                        otB = (oB[0] - A[0]) * ux + (oB[1] - A[1]) * uy
                        collinear_ref_intervals.append((min(otA, otB), max(otA, otB)))
                collinear_ref_intervals.sort()
                merged_ref_spans: list[tuple[float, float]] = []
                cs, ce = collinear_ref_intervals[0]
                for s_iv, e_iv in collinear_ref_intervals[1:]:
                    if s_iv <= ce + 1e-3:
                        ce = max(ce, e_iv)
                    else:
                        merged_ref_spans.append((cs, ce))
                        cs, ce = s_iv, e_iv
                merged_ref_spans.append((cs, ce))
                span_min, span_max = 0.0, L
                for s_iv, e_iv in merged_ref_spans:
                    if s_iv <= 1e-3 and e_iv >= L - 1e-3:
                        span_min, span_max = s_iv, e_iv
                        break
                span_len = max(span_max - span_min, L)

                matched_student_segments = []
                intervals = []

                for sc in target_stu_comps:
                    if sc.kind != "segment" or not sc.start or not sc.end:
                        continue
                    P = sc.start
                    Q = sc.end

                    dP = abs((P[0] - A[0]) * nx + (P[1] - A[1]) * ny)
                    dQ = abs((Q[0] - A[0]) * nx + (Q[1] - A[1]) * ny)
                    if dP > pos_tol * 1.5 or dQ > pos_tol * 1.5:
                        continue

                    stu_angle = (
                        math.degrees(math.atan2(Q[1] - P[1], Q[0] - P[0]))
                        % 180.0
                    )
                    ang_delta = abs(ref_angle - stu_angle) % 180.0
                    ang_delta = min(ang_delta, 180.0 - ang_delta)
                    if ang_delta > ang_tol * 2.0:
                        continue

                    tP = (P[0] - A[0]) * ux + (P[1] - A[1]) * uy
                    tQ = (Q[0] - A[0]) * ux + (Q[1] - A[1]) * uy
                    t_min = min(tP, tQ)
                    t_max = max(tP, tQ)

                    o_min = max(0.0, t_min)
                    o_max = min(L, t_max)
                    overlap = o_max - o_min
                    if overlap <= 1e-4:
                        continue

                    # Skip segments that are translated as a whole along the axis
                    # so Phase 2 matches them 1-to-1 as displaced components.
                    # Only allow an axially shifted segment into Phase 1 when it is a
                    # true collinear sub-span that predominantly overlaps the reference
                    # wall (e.g., X and Y-vertical), not short shifted fragments (422),
                    # near-full-length displaced segments, or extended spans (Z).
                    is_axial_whole_shift = (
                        (t_min > pos_tol and (t_max - L) > pos_tol)
                        or (t_min < -pos_tol and (t_max - L) < -pos_tol)
                    )
                    is_collinear_subspan = (
                        sc.length <= 0.75 * L
                        and overlap >= 0.75 * sc.length
                        and overlap >= 0.40 * L
                    )
                    if is_axial_whole_shift and not is_collinear_subspan:
                        continue
                    # Ignore minor endpoint jitter (< len_tol) from an adjacent segment poking into a sub-segment
                    if sc.length > L + len_tol and overlap <= min(len_tol, L * 0.25):
                        continue

                    denom = max(abs(tQ - tP), 1e-6)
                    s_a = sc.length * (o_min - t_min) / denom
                    s_b = sc.length * (o_max - t_min) / denom
                    s_min, s_max = (
                        max(0.0, min(s_a, s_b)),
                        min(sc.length, max(s_a, s_b)),
                    )

                    cov_on_ref = _intersect_intervals(intervals, (o_min, o_max))
                    cov_len = sum(b - a for a, b in cov_on_ref)
                    if cov_len >= overlap - 1e-4:
                        duplicate_student_entities.add(sc.source_entity_id)
                        continue

                    avail = student_available_intervals.get(
                        sc.id, [(0.0, sc.length)]
                    )
                    usable_on_sc = _intersect_intervals(avail, (s_min, s_max))
                    usable_len = sum(b - a for a, b in usable_on_sc)

                    if usable_len > 1e-4:
                        for ua, ub in usable_on_sc:
                            if s_max - s_min > 1e-6:
                                frac_a = (ua - s_min) / (s_max - s_min)
                                frac_b = (ub - s_min) / (s_max - s_min)
                                r_a = o_min + frac_a * (o_max - o_min)
                                r_b = o_min + frac_b * (o_max - o_min)
                                intervals.append(
                                    (min(r_a, r_b), max(r_a, r_b))
                                )
                            else:
                                intervals.append((o_min, o_max))

                        student_available_intervals[sc.id] = (
                            _subtract_intervals(avail, usable_on_sc)
                        )
                        matched_student_segments.append(sc)
                        _mark_stu_used(sc)
                        _record_pair(ref_comp, sc, 1.0)

                covered = _merge_intervals(intervals)
                presence = min(1.0, covered / L)
                if presence >= 1.0 - 1e-4:
                    presence = 1.0

                if presence > 0.0:
                    correct = True
                    errs = []
                    for sc in matched_student_segments:
                        P, Q = sc.start, sc.end
                        dP = abs((P[0] - A[0]) * nx + (P[1] - A[1]) * ny)
                        dQ = abs((Q[0] - A[0]) * nx + (Q[1] - A[1]) * ny)
                        stu_angle = (
                            math.degrees(
                                math.atan2(Q[1] - P[1], Q[0] - P[0])
                            )
                            % 180.0
                        )
                        ang_delta = abs(ref_angle - stu_angle) % 180.0
                        ang_delta = min(ang_delta, 180.0 - ang_delta)
                        if max(dP, dQ) > pos_tol:
                            correct = False
                            errs.append(
                                {
                                    "category": "incorrect_position",
                                    "expected": 0.0,
                                    "actual": round(max(dP, dQ), 4),
                                    "deviation": round(max(dP, dQ), 4),
                                    "tolerance": pos_tol,
                                    "student_entity_id": sc.source_entity_id,
                                }
                            )
                        if ang_delta > ang_tol:
                            correct = False
                            errs.append(
                                {
                                    "category": "incorrect_angle",
                                    "expected": round(ref_angle, 4),
                                    "actual": round(stu_angle, 4),
                                    "tolerance": ang_tol,
                                    "student_entity_id": sc.source_entity_id,
                                }
                            )

                        tP = (P[0] - A[0]) * ux + (P[1] - A[1]) * uy
                        tQ = (Q[0] - A[0]) * ux + (Q[1] - A[1]) * uy
                        t_min_sc = min(tP, tQ)
                        t_max_sc = max(tP, tQ)
                        if (span_min - t_min_sc) > pos_tol or (t_max_sc - span_max) > pos_tol:
                            correct = False
                            if (
                                len(matched_student_segments) == 1
                                and abs(sc.length - span_len) > len_tol
                            ):
                                errs.append(
                                    {
                                        "category": "incorrect_length",
                                        "expected": round(span_len, 4),
                                        "actual": round(sc.length, 4),
                                        "tolerance": len_tol,
                                        "student_entity_id": sc.source_entity_id,
                                    }
                                )
                            else:
                                act_pos = round(
                                    max(span_min - t_min_sc, t_max_sc - span_max), 4
                                )
                                errs.append(
                                    {
                                        "category": "incorrect_position",
                                        "expected": 0.0,
                                        "actual": act_pos,
                                        "deviation": act_pos,
                                        "tolerance": pos_tol,
                                        "student_entity_id": sc.source_entity_id,
                                    }
                                )
                        elif (
                            len(matched_student_segments) == 1
                            and sc.length - span_len > len_tol
                        ):
                            correct = False
                            errs.append(
                                {
                                    "category": "incorrect_length",
                                    "expected": round(span_len, 4),
                                    "actual": round(sc.length, 4),
                                    "tolerance": len_tol,
                                    "student_entity_id": sc.source_entity_id,
                                }
                            )

                    if L - covered > len_tol:
                        correct = False
                        sc0 = matched_student_segments[0] if matched_student_segments else None
                        sc0_id = sc0.source_entity_id if sc0 else None
                        loc = list(sc0.end if sc0 and sc0.end else (eval_comp.centroid if eval_comp.centroid else [0.0, 0.0]))
                        if not any(
                            e["category"] == "incorrect_length" for e in errs
                        ):
                            errs.append(
                                {
                                    "category": "incorrect_length",
                                    "expected": round(L, 4),
                                    "actual": round(covered, 4),
                                    "tolerance": len_tol,
                                    "student_entity_id": sc0_id,
                                    "location": loc,
                                }
                            )


                    q_i = 1.0 if correct else 0.0
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=matched_student_segments,
                            presence=presence,
                            correctness=q_i,
                            weight=w_i,
                            covered_length=covered,
                            errors=errs,
                        )
                    )
                else:
                    missing_components.append(ref_comp)
                    component_matches.append(
                        ComponentMatch(
                            reference_component=ref_comp,
                            student_components=[],
                            presence=0.0,
                            correctness=0.0,
                            weight=w_i,
                        )
                    )
            else:
                missing_components.append(ref_comp)
                component_matches.append(
                    ComponentMatch(
                        reference_component=ref_comp,
                        student_components=[],
                        presence=0.0,
                        correctness=0.0,
                        weight=w_i,
                    )
                )

    # Phase 2: Local 1-to-1 proximity assignment for displaced / rotated / deformed components
    unmatched_cms = [cm for cm in component_matches if cm.presence == 0.0]
    unused_stu = [
        sc
        for sc in stu_comps
        if sc.id not in used_stu_comp_ids
        and (
            sc.kind != "segment"
            or sum(b - a for a, b in student_available_intervals.get(sc.id, []))
            >= sc.length - 1e-4
        )
    ]

    def _count_endpoint_neighbors(
        arc_comp: CanonicalComponent,
        comps: list[CanonicalComponent],
        conn_eps: float,
    ) -> tuple[int, int]:
        c_start = arc_comp.start
        c_end = arc_comp.end
        if not c_start or not c_end:
            return (0, 0)
        has_start = 0
        has_end = 0
        for other in comps:
            if other.id == arc_comp.id or other.kind not in ("segment", "arc"):
                continue
            if not has_start:
                if other.start and math.dist(c_start, other.start) <= conn_eps:
                    has_start = 1
                elif other.end and math.dist(c_start, other.end) <= conn_eps:
                    has_start = 1
            if not has_end:
                if other.start and math.dist(c_end, other.start) <= conn_eps:
                    has_end = 1
                elif other.end and math.dist(c_end, other.end) <= conn_eps:
                    has_end = 1
            if has_start and has_end:
                break
        return (has_start, has_end)

    if unmatched_cms and unused_stu:
        # Phase 2a: Corner and concentric arc correspondence using corner geometry and neighboring wall connections
        from itertools import combinations

        conn_eps = max(pos_tol * 2.0, 1.0)
        all_ref_comps = [c for o in ref_objects for c in o.components]

        assigned_concentric_rc_ids: set[str] = set()
        assigned_concentric_sc_ids: set[str] = set()

        unmatched_arc_cms = [
            cm for cm in unmatched_cms
            if cm.reference_component.kind == "arc" and cm.presence == 0.0 and cm.reference_component.center
        ]
        unused_arc_scs = [
            sc for sc in unused_stu
            if sc.kind == "arc" and sc.id not in used_stu_comp_ids and sc.center
        ]

        if unmatched_arc_cms and unused_arc_scs:
            ref_arc_clusters: list[list[ComponentMatch]] = []
            for cm in unmatched_arc_cms:
                rc = cm.reference_component
                placed = False
                for cluster in ref_arc_clusters:
                    rep = cluster[0].reference_component
                    if rep.parent_object_id == rc.parent_object_id and rep.center:
                        if math.dist(rep.center, rc.center) <= max(pos_tol * 2.5, 2.0):
                            sa_r = rep.start_angle or 0.0
                            ea_r = rep.end_angle or 0.0
                            sp_r = (ea_r - sa_r) % 360.0 or 360.0
                            sa_c = rc.start_angle or 0.0
                            ea_c = rc.end_angle or 0.0
                            sp_c = (ea_c - sa_c) % 360.0 or 360.0
                            if _arc_overlap(sa_r, sp_r, sa_c, sp_c) >= 0.5 * min(sp_r, sp_c):
                                cluster.append(cm)
                                placed = True
                                break
                if not placed:
                    ref_arc_clusters.append([cm])

            stu_arc_clusters: list[list[CanonicalComponent]] = []
            for sc in unused_arc_scs:
                placed = False
                for cluster in stu_arc_clusters:
                    rep = cluster[0]
                    if rep.center and math.dist(rep.center, sc.center) <= max(pos_tol * 2.5, 2.0):
                        sa_r = rep.start_angle or 0.0
                        ea_r = rep.end_angle or 0.0
                        sp_r = (ea_r - sa_r) % 360.0 or 360.0
                        sa_c = sc.start_angle or 0.0
                        ea_c = sc.end_angle or 0.0
                        sp_c = (ea_c - sa_c) % 360.0 or 360.0
                        if _arc_overlap(sa_r, sp_r, sa_c, sp_c) >= 0.5 * min(sp_r, sp_c):
                            cluster.append(sc)
                            placed = True
                            break
                if not placed:
                    stu_arc_clusters.append([sc])

            for ref_cluster in ref_arc_clusters:
                if len(ref_cluster) < 2:
                    continue
                rep_rc = ref_cluster[0].reference_component
                obj_id = rep_rc.parent_object_id or ""
                obj_dx, obj_dy = object_translations.get(obj_id, (0.0, 0.0))
                rep_rc_center = (rep_rc.center[0] + obj_dx, rep_rc.center[1] + obj_dy)
                obj_ref = next((o for o in ref_objects if o.object_id == obj_id), None)
                obj_span = (
                    max(obj_ref.bounds[2] - obj_ref.bounds[0], obj_ref.bounds[3] - obj_ref.bounds[1])
                    if obj_ref is not None else 0.0
                )
                max_r = max((cm.reference_component.radius or 0.0) for cm in ref_cluster)
                max_dist = max(pos_tol * 8.0, max_r * 2.0, obj_span * 0.15)
                target_so = matched_ref_to_stu.get(obj_id)

                ref_sorted = sorted(ref_cluster, key=lambda cm: cm.reference_component.radius or 0.0)
                M = len(ref_sorted)
                ref_thickness = (ref_sorted[-1].reference_component.radius or 0.0) - (ref_sorted[0].reference_component.radius or 0.0)
                ref_conns = [_count_endpoint_neighbors(cm.reference_component, all_ref_comps, conn_eps) for cm in ref_sorted]
                ref_total_conn = sum(s + e for s, e in ref_conns)

                sa_r = rep_rc.start_angle or 0.0
                ea_r = rep_rc.end_angle or 0.0
                sp_r = (ea_r - sa_r) % 360.0 or 360.0

                candidate_subsets_scored: list[tuple[float, list[CanonicalComponent]]] = []

                for stu_cluster in stu_arc_clusters:
                    if target_so and stu_cluster[0].parent_object_id and stu_cluster[0].parent_object_id != target_so.object_id:
                        continue
                    rep_sc = stu_cluster[0]
                    c_dist = math.dist(rep_rc_center, rep_sc.center)
                    if c_dist > max_dist:
                        continue

                    sa_s = rep_sc.start_angle or 0.0
                    ea_s = rep_sc.end_angle or 0.0
                    sp_s = (ea_s - sa_s) % 360.0 or 360.0
                    if abs(sp_r - sp_s) > max(ang_tol * 5.0, 45.0):
                        continue
                    if _arc_overlap(sa_r, sp_r, sa_s, sp_s) < 0.5 * min(sp_r, sp_s):
                        continue

                    available_scs = [
                        sc for sc in stu_cluster
                        if sc.id not in assigned_concentric_sc_ids and sc.id not in used_stu_comp_ids
                    ]
                    if len(available_scs) < M:
                        continue

                    stu_conns = {
                        sc.id: _count_endpoint_neighbors(sc, stu_comps, conn_eps)
                        for sc in available_scs
                    }

                    for sub in combinations(available_scs, M):
                        sub_sorted = sorted(sub, key=lambda sc: sc.radius or 0.0)

                        all_plausible = True
                        shifts = []
                        center_dists = []
                        for cm_i, sc_i in zip(ref_sorted, sub_sorted):
                            rc_i = cm_i.reference_component
                            rad_delta = abs(rc_i.radius - sc_i.radius)
                            if rad_delta > max(rad_tol * 5.0, rc_i.radius * 0.6):
                                all_plausible = False
                                break
                            shifts.append(sc_i.radius - rc_i.radius)
                            rc_c = (rc_i.center[0] + obj_dx, rc_i.center[1] + obj_dy)
                            center_dists.append(math.dist(rc_c, sc_i.center))

                        if not all_plausible:
                            continue

                        mean_shift = sum(abs(s) for s in shifts) / M
                        shift_spread = max(shifts) - min(shifts)
                        sub_thickness = (sub_sorted[-1].radius or 0.0) - (sub_sorted[0].radius or 0.0)
                        thickness_err = abs(sub_thickness - ref_thickness)
                        mean_cdist = sum(center_dists) / M

                        if ref_total_conn > 0:
                            conn_agreement = sum(
                                min(ref_conns[i][0], stu_conns[sub_sorted[i].id][0]) +
                                min(ref_conns[i][1], stu_conns[sub_sorted[i].id][1])
                                for i in range(M)
                            )
                            conn_mismatch = sum(
                                max(0, ref_conns[i][0] - stu_conns[sub_sorted[i].id][0]) +
                                max(0, ref_conns[i][1] - stu_conns[sub_sorted[i].id][1])
                                for i in range(M)
                            )
                            cost = (
                                mean_shift
                                + 3.0 * thickness_err
                                + 2.0 * shift_spread
                                + 0.5 * mean_cdist
                                + 20.0 * conn_mismatch
                                - 10.0 * conn_agreement
                            )
                        else:
                            cost = (
                                mean_shift
                                + 3.0 * thickness_err
                                + 2.0 * shift_spread
                                + 0.5 * mean_cdist
                            )

                        candidate_subsets_scored.append((cost, list(sub_sorted)))

                if not candidate_subsets_scored:
                    continue

                candidate_subsets_scored.sort(
                    key=lambda item: (
                        round(item[0], 4),
                        tuple(round(sc.radius or 0.0, 2) for sc in item[1]),
                        tuple(sc.source_entity_id or "" for sc in item[1]),
                    )
                )
                best_cost, best_subset = candidate_subsets_scored[0]

                if len(candidate_subsets_scored) >= 2:
                    second_cost, _ = candidate_subsets_scored[1]
                    if (second_cost - best_cost) < 0.1:
                        tied_subsets = [
                            sub for cost, sub in candidate_subsets_scored
                            if (cost - best_cost) < 0.1
                        ]
                        tied_sc_dict = {sc.id: sc for sub in tied_subsets for sc in sub}
                        tied_scs = list(tied_sc_dict.values())
                        for sc in tied_scs:
                            assigned_concentric_sc_ids.add(sc.id)
                            _mark_stu_used(sc)

                        for i, cm_i in enumerate(ref_sorted):
                            rc_i = cm_i.reference_component
                            assigned_concentric_rc_ids.add(rc_i.id)
                            if rc_i in missing_components:
                                missing_components.remove(rc_i)

                            candidate_scs_for_i = [sub[i] for sub in tied_subsets if len(sub) > i]
                            seen_cands = {}
                            for sc in candidate_scs_for_i:
                                if sc.id not in seen_cands:
                                    seen_cands[sc.id] = sc
                            unique_cands_for_i = sorted(
                                seen_cands.values(),
                                key=lambda sc: (round(sc.radius or 0.0, 2), sc.source_entity_id or "", sc.id)
                            )

                            sa_r = rc_i.start_angle or 0.0
                            ea_r = rc_i.end_angle or 0.0
                            sp_r = ((ea_r - sa_r) % 360.0) or 360.0
                            sa_r_norm = sa_r % 360.0

                            cand_ang_info = []
                            for sc in unique_cands_for_i:
                                sa_s = sc.start_angle or 0.0
                                ea_s = sc.end_angle or 0.0
                                sp_s = ((ea_s - sa_s) % 360.0) or 360.0
                                sa_s_norm = sa_s % 360.0
                                sweep_diff = abs(sp_s - sp_r)
                                rot_diff = ((sa_s_norm - sa_r_norm + 180.0) % 360.0) - 180.0
                                rot_dev = abs(rot_diff)
                                cand_ang_info.append({
                                    "sc": sc,
                                    "sweep_diff": sweep_diff,
                                    "rot_diff": rot_diff,
                                    "rot_dev": rot_dev,
                                    "sp_s": sp_s,
                                    "sa_s_norm": sa_s_norm,
                                })

                            all_have_orientation_error = (
                                len(cand_ang_info) == len(unique_cands_for_i)
                                and len(unique_cands_for_i) > 0
                                and all(item["rot_dev"] > ang_tol for item in cand_ang_info)
                            )
                            all_have_sweep_error = (
                                len(cand_ang_info) == len(unique_cands_for_i)
                                and len(unique_cands_for_i) > 0
                                and all(item["sweep_diff"] > ang_tol for item in cand_ang_info)
                            )

                            common_errors = []
                            rep_cand = None

                            if all_have_orientation_error and all_have_sweep_error:
                                min_rot_dev = min(item["rot_dev"] for item in cand_ang_info)
                                min_sweep_diff = min(item["sweep_diff"] for item in cand_ang_info)
                                is_orientation = min_rot_dev >= min_sweep_diff
                            elif all_have_orientation_error:
                                is_orientation = True
                            elif all_have_sweep_error:
                                is_orientation = False
                            else:
                                is_orientation = None

                            if is_orientation is True:
                                min_item = min(cand_ang_info, key=lambda item: item["rot_dev"])
                                rep_cand = min_item["sc"]
                                min_ang_dev = min_item["rot_dev"]
                                actual_ang = round(min_item["sa_s_norm"], 4)
                                expected_ang = round(sa_r_norm, 4)
                                dev_ang = round(min_ang_dev, 4)
                                msg = f"Adjust the orientation angle from {actual_ang:.3f} degrees to {expected_ang:.3f} degrees."
                                common_errors.append({
                                    "category": "incorrect_angle",
                                    "sub_property": "orientation",
                                    "expected": expected_ang,
                                    "actual": actual_ang,
                                    "deviation": dev_ang,
                                    "unit": "degrees",
                                    "tolerance": ang_tol,
                                    "message": msg,
                                    "technical_feedback": msg,
                                    "student_entity_id": rep_cand.source_entity_id,
                                    "location": list(rep_cand.centroid),
                                })
                            elif is_orientation is False:
                                min_item = min(cand_ang_info, key=lambda item: item["sweep_diff"])
                                rep_cand = min_item["sc"]
                                min_sweep_diff = min_item["sweep_diff"]
                                actual_ang = round(min_item["sp_s"], 4)
                                expected_ang = round(sp_r, 4)
                                dev_ang = round(min_sweep_diff, 4)
                                msg = f"Adjust the sweep angle from {actual_ang:.3f} degrees to {expected_ang:.3f} degrees."
                                common_errors.append({
                                    "category": "incorrect_angle",
                                    "sub_property": "sweep",
                                    "expected": expected_ang,
                                    "actual": actual_ang,
                                    "deviation": dev_ang,
                                    "unit": "degrees",
                                    "tolerance": ang_tol,
                                    "message": msg,
                                    "technical_feedback": msg,
                                    "student_entity_id": rep_cand.source_entity_id,
                                    "location": list(rep_cand.centroid),
                                })

                            rc_c = (rc_i.center[0] + obj_dx, rc_i.center[1] + obj_dy) if rc_i.center else None
                            cand_pos_errs = []
                            if rc_c:
                                for sc in unique_cands_for_i:
                                    if sc.center:
                                        c_dist = math.dist(rc_c, sc.center)
                                        if c_dist > pos_tol:
                                            cand_pos_errs.append((c_dist, sc))
                            if rc_c and len(cand_pos_errs) == len(unique_cands_for_i) and len(unique_cands_for_i) > 0:
                                min_pos_item = min(cand_pos_errs, key=lambda item: item[0])
                                min_pos_dev, rep_cand_pos = min_pos_item
                                if rep_cand is None:
                                    rep_cand = rep_cand_pos
                                common_errors.append({
                                    "category": "incorrect_position",
                                    "expected": 0.0,
                                    "actual": round(min_pos_dev, 4),
                                    "deviation": round(min_pos_dev, 4),
                                    "vector": [
                                        round(rep_cand_pos.center[0] - rc_c[0], 4),
                                        round(rep_cand_pos.center[1] - rc_c[1], 4),
                                    ],
                                    "tolerance": pos_tol,
                                    "student_entity_id": rep_cand_pos.source_entity_id,
                                    "location": list(rep_cand_pos.centroid),
                                })

                            cm_i.student_components = [rep_cand] if (common_errors and rep_cand) else []
                            cm_i.presence = 1.0
                            cm_i.correctness = 0.0 if common_errors else 1.0
                            cm_i.covered_length = rc_i.length
                            cm_i.errors = common_errors

                        unique_subsets = []
                        seen_subsets = set()
                        for sub in tied_subsets:
                            key = tuple(round(sc.radius or 0.0, 2) for sc in sub)
                            if key not in seen_subsets:
                                seen_subsets.add(key)
                                unique_subsets.append(list(key))
                        competing_subsets_sorted = sorted(unique_subsets, key=lambda s: tuple(s))

                        candidate_scs_sorted = sorted(
                            tied_scs,
                            key=lambda sc: (round(sc.radius or 0.0, 2), sc.source_entity_id or "", sc.id)
                        )

                        amb_group = {
                            "id": f"AMB-ARC-{len(ambiguous_groups) + 1}",
                            "type": "concentric_arc_ambiguity",
                            "reference_component_ids": [cm.reference_component.id for cm in ref_sorted],
                            "reference_entity_ids": [
                                eid
                                for cm in ref_sorted
                                for eid in (cm.reference_component.source_entity_ids or [cm.reference_component.source_entity_id])
                                if eid
                            ],
                            "candidate_student_component_ids": [sc.id for sc in candidate_scs_sorted],
                            "candidate_student_entity_ids": [
                                sc.source_entity_id for sc in candidate_scs_sorted if sc.source_entity_id
                            ],
                            "reference_radii": [round(cm.reference_component.radius or 0.0, 2) for cm in ref_sorted],
                            "competing_subsets": competing_subsets_sorted,
                            "centroid": list(ref_sorted[0].reference_component.centroid),
                            "location": list(ref_sorted[0].reference_component.center or (0.0, 0.0)),
                            "parent_object_id": ref_sorted[0].reference_component.parent_object_id,
                        }
                        ambiguous_groups.append(amb_group)
                        continue

                for cm_i, sc_i in zip(ref_sorted, best_subset):
                        rc_i = cm_i.reference_component
                        _mark_stu_used(sc_i)
                        if rc_i in missing_components:
                            missing_components.remove(rc_i)
                        assigned_concentric_rc_ids.add(rc_i.id)
                        assigned_concentric_sc_ids.add(sc_i.id)

                        rc_c = (rc_i.center[0] + obj_dx, rc_i.center[1] + obj_dy)
                        c_dist = math.dist(rc_c, sc_i.center)
                        rad_delta = abs(rc_i.radius - sc_i.radius)
                        sa_r = rc_i.start_angle or 0.0
                        ea_r = rc_i.end_angle or 0.0
                        sp_r = (ea_r - sa_r) % 360.0 or 360.0
                        sa_s = sc_i.start_angle or 0.0
                        ea_s = sc_i.end_angle or 0.0
                        sp_s = (ea_s - sa_s) % 360.0 or 360.0
                        ang_ov = _arc_overlap(sa_r, sp_r, sa_s, sp_s)

                        errs = []
                        if c_dist > pos_tol:
                            vec = [
                                round(sc_i.center[0] - rc_c[0], 4),
                                round(sc_i.center[1] - rc_c[1], 4),
                            ]
                            errs.append({
                                "category": "incorrect_position",
                                "expected": 0.0,
                                "actual": round(c_dist, 4),
                                "deviation": round(c_dist, 4),
                                "vector": vec,
                                "tolerance": pos_tol,
                                "student_entity_id": sc_i.source_entity_id,
                                "location": list(sc_i.centroid),
                            })
                        if rad_delta > rad_tol:
                            errs.append({
                                "category": "incorrect_radius",
                                "expected": round(rc_i.radius, 4),
                                "actual": round(sc_i.radius, 4),
                                "tolerance": rad_tol,
                                "student_entity_id": sc_i.source_entity_id,
                                "location": list(sc_i.centroid),
                            })
                        if sp_s - ang_ov > ang_tol or abs(sp_r - sp_s) > ang_tol:
                            errs.append({
                                "category": "incorrect_angle",
                                "expected": round(sp_r, 4),
                                "actual": round(sp_s, 4),
                                "tolerance": ang_tol,
                                "student_entity_id": sc_i.source_entity_id,
                                "location": list(sc_i.centroid),
                            })

                        cm_i.student_components = [sc_i]
                        cm_i.presence = 1.0
                        cm_i.correctness = 0.0 if errs else 1.0
                        cm_i.covered_length = min(rc_i.length, sc_i.length)
                        cm_i.errors = errs
                        _record_pair(rc_i, sc_i, 0.8 if errs else 1.0)

        candidate_pairs: list[
            tuple[float, str, str, ComponentMatch, CanonicalComponent]
        ] = []
        for cm in unmatched_cms:
            rc = cm.reference_component
            if rc.id in assigned_concentric_rc_ids:
                continue
            target_so = matched_ref_to_stu.get(rc.parent_object_id or "")
            if normalization_mode == "strict":
                target_unused = unused_stu
            elif not stu_objects:
                target_unused = unused_stu
            else:
                matched_sos = {s_id for r_id, s_id, _ in matched_objects_list if r_id == rc.parent_object_id}
                if target_so is not None:
                    matched_sos.add(target_so.object_id)
                other_matched_sos = {
                    s_id for r_id, s_id, _ in matched_objects_list if r_id != rc.parent_object_id
                }
                obj_ref = next((o for o in ref_objects if o.object_id == rc.parent_object_id), None)
                if obj_ref:
                    obj_dx_ph2, obj_dy_ph2 = object_translations.get(rc.parent_object_id or "", (0.0, 0.0))
                    min_x = obj_ref.bounds[0] + obj_dx_ph2
                    min_y = obj_ref.bounds[1] + obj_dy_ph2
                    max_x = obj_ref.bounds[2] + obj_dx_ph2
                    max_y = obj_ref.bounds[3] + obj_dy_ph2
                    margin = max(pos_tol * 5.0, 25.0)
                    target_unused = [
                        sc for sc in unused_stu
                        if (sc.parent_object_id in matched_sos)
                        or (
                            sc.parent_object_id not in other_matched_sos
                            and min_x - margin <= sc.centroid[0] <= max_x + margin
                            and min_y - margin <= sc.centroid[1] <= max_y + margin
                        )
                    ]
                else:
                    target_unused = [sc for sc in unused_stu if sc.parent_object_id in matched_sos]
            if not target_unused:
                continue

            obj_ref = next((o for o in ref_objects if o.object_id == rc.parent_object_id), None)
            obj_span = (
                max(
                    obj_ref.bounds[2] - obj_ref.bounds[0],
                    obj_ref.bounds[3] - obj_ref.bounds[1],
                )
                if obj_ref is not None
                else 0.0
            )
            obj_dx, obj_dy = object_translations.get(rc.parent_object_id or "", (0.0, 0.0))
            rc_centroid = (rc.centroid[0] + obj_dx, rc.centroid[1] + obj_dy)
            rc_center = (rc.center[0] + obj_dx, rc.center[1] + obj_dy) if rc.center else None
            rc_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy) if rc.start else None
            rc_end = (rc.end[0] + obj_dx, rc.end[1] + obj_dy) if rc.end else None

            for sc in target_unused:
                if sc.id in assigned_concentric_sc_ids:
                    continue
                if rc.kind != sc.kind:
                    continue
                if rc.kind == "segment" and rc_start and rc_end and sc.start and sc.end:
                    c_dist = math.dist(rc_centroid, sc.centroid)
                    L = max(rc.length, 1e-9)
                    len_delta = abs(rc.length - sc.length)
                    r_ang = (
                        math.degrees(
                            math.atan2(
                                rc_end[1] - rc_start[1], rc_end[0] - rc_start[0]
                            )
                        )
                        % 180.0
                    )
                    s_ang = (
                        math.degrees(
                            math.atan2(
                                sc.end[1] - sc.start[1], sc.end[0] - sc.start[0]
                            )
                        )
                        % 180.0
                    )
                    ang_delta = abs(r_ang - s_ang) % 180.0
                    ang_delta = min(ang_delta, 180.0 - ang_delta)

                    max_local_dist = max(pos_tol * 8.0, L * 1.05, obj_span * 0.12)
                    plausible_shifted_or_resized = (
                        ang_delta <= ang_tol * 2.0
                        and c_dist <= max_local_dist
                        and len_delta <= max(len_tol * 5.0, L * 0.6)
                    )
                    plausible_rotated = (
                        c_dist <= max(pos_tol * 6.0, L * 0.55)
                        and len_delta <= max(len_tol * 3.0, L * 0.35)
                        and ang_delta <= max(ang_tol * 3.0, 15.0)
                    )
                    if plausible_shifted_or_resized or plausible_rotated:
                        cost = c_dist + len_delta * 0.5 + ang_delta * 0.15
                        if ang_delta <= ang_tol and sc.length > L + len_tol:
                            ux = (rc_end[0] - rc_start[0]) / L
                            uy = (rc_end[1] - rc_start[1]) / L
                            nx = -uy
                            ny = ux
                            dP = abs((sc.start[0] - rc_start[0]) * nx + (sc.start[1] - rc_start[1]) * ny)
                            dQ = abs((sc.end[0] - rc_start[0]) * nx + (sc.end[1] - rc_start[1]) * ny)
                            perp_dist = max(dP, dQ)
                            if perp_dist <= pos_tol * 2.5:
                                tP = (sc.start[0] - rc_start[0]) * ux + (sc.start[1] - rc_start[1]) * uy
                                tQ = (sc.end[0] - rc_start[0]) * ux + (sc.end[1] - rc_start[1]) * uy
                                t_min_p2 = min(tP, tQ)
                                t_max_p2 = max(tP, tQ)
                                ov_p2 = max(0.0, min(L, t_max_p2) - max(0.0, t_min_p2))
                                if ov_p2 >= L - 1e-3:
                                    axial_gap = max(0.0, t_min_p2) + max(0.0, L - t_max_p2)
                                    effective_dist = min(c_dist, perp_dist + axial_gap)
                                    cost = effective_dist + len_delta * 0.25 + ang_delta * 0.15
                        candidate_pairs.append((cost, rc.id, sc.id, cm, sc))
                elif (
                    rc.kind == "circle"
                    and rc_center
                    and sc.center
                    and rc.radius is not None
                    and sc.radius is not None
                ):
                    c_dist = math.dist(rc_center, sc.center)
                    rad_delta = abs(rc.radius - sc.radius)
                    if c_dist <= max(pos_tol * 8.0, rc.radius * 3.0, obj_span * 0.15) and rad_delta <= max(
                        rad_tol * 5.0, rc.radius * 0.6
                    ):
                        cost = c_dist + rad_delta * 0.5
                        candidate_pairs.append((cost, rc.id, sc.id, cm, sc))
                elif (
                    rc.kind == "arc"
                    and rc_center
                    and sc.center
                    and rc.radius is not None
                    and sc.radius is not None
                ):
                    c_dist = math.dist(rc_center, sc.center)
                    rad_delta = abs(rc.radius - sc.radius)
                    sa_ref = rc.start_angle or 0.0
                    ea_ref = rc.end_angle or 0.0
                    span_ref = (ea_ref - sa_ref) % 360.0 or 360.0
                    sa_stu = sc.start_angle or 0.0
                    ea_stu = sc.end_angle or 0.0
                    span_stu = (ea_stu - sa_stu) % 360.0 or 360.0
                    span_delta = abs(span_ref - span_stu)
                    if (
                        c_dist <= max(pos_tol * 8.0, rc.radius * 2.0, obj_span * 0.15)
                        and rad_delta <= max(rad_tol * 5.0, rc.radius * 0.6)
                        and span_delta <= max(ang_tol * 5.0, 45.0)
                    ):
                        cost = c_dist + rad_delta * 0.5 + span_delta * 0.15
                        candidate_pairs.append((cost, rc.id, sc.id, cm, sc))

        candidate_pairs.sort(key=lambda item: (item[0], item[1], item[2]))
        assigned_rc: set[str] = set()
        assigned_sc: set[str] = set()
        for _, rc_id, sc_id, cm, sc in candidate_pairs:
            if rc_id in assigned_rc or sc_id in assigned_sc:
                continue
            assigned_rc.add(rc_id)
            assigned_sc.add(sc_id)
            rc = cm.reference_component
            obj_dx, obj_dy = object_translations.get(rc.parent_object_id or "", (0.0, 0.0))
            rc_centroid = (rc.centroid[0] + obj_dx, rc.centroid[1] + obj_dy)
            rc_center = (rc.center[0] + obj_dx, rc.center[1] + obj_dy) if rc.center else None
            rc_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy) if rc.start else None
            rc_end = (rc.end[0] + obj_dx, rc.end[1] + obj_dy) if rc.end else None

            _mark_stu_used(sc)
            if sc.kind == "segment":
                student_available_intervals[sc.id] = []
            if rc in missing_components:
                missing_components.remove(rc)

            errs = []
            if rc.kind == "segment" and rc_start and rc_end and sc.start and sc.end:
                c_dist = math.dist(rc_centroid, sc.centroid)
                len_delta = abs(rc.length - sc.length)
                r_ang = (
                    math.degrees(
                        math.atan2(
                            rc_end[1] - rc_start[1], rc_end[0] - rc_start[0]
                        )
                    )
                    % 180.0
                )
                s_ang = (
                    math.degrees(
                        math.atan2(
                            sc.end[1] - sc.start[1], sc.end[0] - sc.start[0]
                        )
                    )
                    % 180.0
                )
                ang_delta = abs(r_ang - s_ang) % 180.0
                ang_delta = min(ang_delta, 180.0 - ang_delta)

                ep_dists = min(
                    (
                        math.dist(rc_start, sc.start),
                        math.dist(rc_end, sc.end),
                    ),
                    (
                        math.dist(rc_start, sc.end),
                        math.dist(rc_end, sc.start),
                    ),
                    key=sum,
                )
                pivot_aligned = min(ep_dists) <= pos_tol
                intrinsic_changed = (
                    len_delta > len_tol or ang_delta > ang_tol
                )
                if c_dist > pos_tol and (not intrinsic_changed or not pivot_aligned):
                    vec = [
                        round(sc.centroid[0] - rc_centroid[0], 4),
                        round(sc.centroid[1] - rc_centroid[1], 4),
                    ]
                    errs.append(
                        {
                            "category": "incorrect_position",
                            "expected": 0.0,
                            "actual": round(c_dist, 4),
                            "deviation": round(c_dist, 4),
                            "vector": vec,
                            "tolerance": pos_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
                if len_delta > len_tol:
                    errs.append(
                        {
                            "category": "incorrect_length",
                            "expected": round(rc.length, 4),
                            "actual": round(sc.length, 4),
                            "tolerance": len_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
                if ang_delta > ang_tol:
                    errs.append(
                        {
                            "category": "incorrect_angle",
                            "expected": round(r_ang, 4),
                            "actual": round(s_ang, 4),
                            "tolerance": ang_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
            elif (
                rc.kind == "circle"
                and rc_center
                and sc.center
                and rc.radius is not None
                and sc.radius is not None
            ):
                c_dist = math.dist(rc_center, sc.center)
                rad_delta = abs(rc.radius - sc.radius)
                if c_dist > pos_tol:
                    vec = [
                        round(sc.center[0] - rc_center[0], 4),
                        round(sc.center[1] - rc_center[1], 4),
                    ]
                    errs.append(
                        {
                            "category": "incorrect_position",
                            "expected": 0.0,
                            "actual": round(c_dist, 4),
                            "deviation": round(c_dist, 4),
                            "vector": vec,
                            "tolerance": pos_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
                if rad_delta > rad_tol:
                    errs.append(
                        {
                            "category": "incorrect_radius",
                            "expected": round(rc.radius, 4),
                            "actual": round(sc.radius, 4),
                            "tolerance": rad_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
            elif (
                rc.kind == "arc"
                and rc_center
                and sc.center
                and rc.radius is not None
                and sc.radius is not None
            ):
                c_dist = math.dist(rc_center, sc.center)
                rad_delta = abs(rc.radius - sc.radius)
                sa_ref = rc.start_angle or 0.0
                ea_ref = rc.end_angle or 0.0
                span_ref = (ea_ref - sa_ref) % 360.0 or 360.0
                sa_stu = sc.start_angle or 0.0
                ea_stu = sc.end_angle or 0.0
                span_stu = (ea_stu - sa_stu) % 360.0 or 360.0
                ang_overlap = _arc_overlap(sa_ref, span_ref, sa_stu, span_stu)
                if c_dist > pos_tol:
                    vec = [
                        round(sc.center[0] - rc_center[0], 4),
                        round(sc.center[1] - rc_center[1], 4),
                    ]
                    errs.append(
                        {
                            "category": "incorrect_position",
                            "expected": 0.0,
                            "actual": round(c_dist, 4),
                            "deviation": round(c_dist, 4),
                            "vector": vec,
                            "tolerance": pos_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
                if rad_delta > rad_tol:
                    errs.append(
                        {
                            "category": "incorrect_radius",
                            "expected": round(rc.radius, 4),
                            "actual": round(sc.radius, 4),
                            "tolerance": rad_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )
                if span_stu - ang_overlap > ang_tol or abs(span_ref - span_stu) > ang_tol:
                    errs.append(
                        {
                            "category": "incorrect_angle",
                            "expected": round(span_ref, 4),
                            "actual": round(span_stu, 4),
                            "tolerance": ang_tol,
                            "student_entity_id": sc.source_entity_id,
                            "location": list(sc.centroid),
                        }
                    )

            cm.student_components = [sc]
            cm.presence = 1.0
            cm.correctness = 0.0 if errs else 1.0
            cm.covered_length = min(rc.length, sc.length)
            cm.errors = errs
            _record_pair(rc, sc, 0.8 if errs else 1.0)

    # Supersede tiny Phase 1 collinear stub matches (<= 15% presence) when a
    # still-unused displaced full wall in Phase 2 clearly belongs to that reference.
    stub_cms = [
        cm
        for cm in component_matches
        if cm.reference_component.kind == "segment"
        and 0.0 < cm.presence <= 0.15
        and cm.reference_component.start
        and cm.reference_component.end
    ]
    if stub_cms:
        remaining_unused = [
            sc
            for sc in stu_comps
            if sc.kind == "segment"
            and sc.start
            and sc.end
            and sc.id not in used_stu_comp_ids
        ]
        stub_candidates: list[
            tuple[float, str, str, ComponentMatch, CanonicalComponent]
        ] = []
        for cm in stub_cms:
            rc = cm.reference_component
            L = max(rc.length, 1e-9)
            target_so = matched_ref_to_stu.get(rc.parent_object_id or "")
            if normalization_mode == "strict" or not stu_objects:
                target_unused = remaining_unused
            else:
                matched_sos = {
                    s_id
                    for r_id, s_id, _ in matched_objects_list
                    if r_id == rc.parent_object_id
                }
                if target_so is not None:
                    matched_sos.add(target_so.object_id)
                other_matched_sos = {
                    s_id
                    for r_id, s_id, _ in matched_objects_list
                    if r_id != rc.parent_object_id
                }
                obj_ref = next(
                    (o for o in ref_objects if o.object_id == rc.parent_object_id),
                    None,
                )
                if obj_ref:
                    obj_dx_s, obj_dy_s = object_translations.get(
                        rc.parent_object_id or "", (0.0, 0.0)
                    )
                    min_x = obj_ref.bounds[0] + obj_dx_s
                    min_y = obj_ref.bounds[1] + obj_dy_s
                    max_x = obj_ref.bounds[2] + obj_dx_s
                    max_y = obj_ref.bounds[3] + obj_dy_s
                    margin = max(pos_tol * 5.0, 25.0)
                    target_unused = [
                        sc
                        for sc in remaining_unused
                        if (sc.parent_object_id in matched_sos)
                        or (
                            sc.parent_object_id not in other_matched_sos
                            and min_x - margin <= sc.centroid[0] <= max_x + margin
                            and min_y - margin <= sc.centroid[1] <= max_y + margin
                        )
                    ]
                else:
                    target_unused = [
                        sc
                        for sc in remaining_unused
                        if sc.parent_object_id in matched_sos
                    ]
            if not target_unused:
                continue

            obj_ref = next(
                (o for o in ref_objects if o.object_id == rc.parent_object_id),
                None,
            )
            obj_span = (
                max(
                    obj_ref.bounds[2] - obj_ref.bounds[0],
                    obj_ref.bounds[3] - obj_ref.bounds[1],
                )
                if obj_ref is not None
                else 0.0
            )
            obj_dx, obj_dy = object_translations.get(
                rc.parent_object_id or "", (0.0, 0.0)
            )
            rc_centroid = (rc.centroid[0] + obj_dx, rc.centroid[1] + obj_dy)
            rc_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy)
            rc_end = (rc.end[0] + obj_dx, rc.end[1] + obj_dy)
            r_ang = (
                math.degrees(
                    math.atan2(rc_end[1] - rc_start[1], rc_end[0] - rc_start[0])
                )
                % 180.0
            )
            max_local_dist = max(pos_tol * 8.0, L * 1.05, obj_span * 0.12)

            for sc in target_unused:
                if sc.length < 0.50 * L or sc.length < 3.0 * cm.covered_length:
                    continue
                c_dist = math.dist(rc_centroid, sc.centroid)
                len_delta = abs(rc.length - sc.length)
                s_ang = (
                    math.degrees(
                        math.atan2(
                            sc.end[1] - sc.start[1], sc.end[0] - sc.start[0]
                        )
                    )
                    % 180.0
                )
                ang_delta = abs(r_ang - s_ang) % 180.0
                ang_delta = min(ang_delta, 180.0 - ang_delta)
                if (
                    ang_delta <= ang_tol * 2.0
                    and c_dist <= max_local_dist
                    and len_delta <= max(len_tol * 5.0, L * 0.6)
                ):
                    cost = c_dist + len_delta * 0.5 + ang_delta * 0.15
                    stub_candidates.append((cost, rc.id, sc.id, cm, sc))

        stub_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        superseded_rc: set[str] = set()
        superseded_sc: set[str] = set()
        for _, rc_id, sc_id, cm, sc in stub_candidates:
            if rc_id in superseded_rc or sc_id in superseded_sc:
                continue
            superseded_rc.add(rc_id)
            superseded_sc.add(sc_id)
            rc = cm.reference_component
            old_scs = list(cm.student_components)
            cm.student_components = [sc]
            for old_sc in old_scs:
                if not any(
                    other_cm is not cm
                    and any(o.id == old_sc.id for o in other_cm.student_components)
                    for other_cm in component_matches
                ):
                    used_stu_comp_ids.discard(old_sc.id)
                for old_eid in old_sc.source_entity_ids or [old_sc.source_entity_id]:
                    if old_eid and not any(
                        other_cm is not cm
                        and any(
                            old_eid in (o.source_entity_ids or [o.source_entity_id])
                            for o in other_cm.student_components
                        )
                        for other_cm in component_matches
                    ):
                        used_stu_entity_ids.discard(old_eid)
                    for r_eid in rc.source_entity_ids or [rc.source_entity_id]:
                        if r_eid and old_eid:
                            matched_pairs_set.discard((r_eid, old_eid))
                            matched_pairs[:] = [
                                pair
                                for pair in matched_pairs
                                if not (pair[0] == r_eid and pair[1] == old_eid)
                            ]

            _mark_stu_used(sc)
            obj_dx, obj_dy = object_translations.get(
                rc.parent_object_id or "", (0.0, 0.0)
            )
            rc_centroid = (rc.centroid[0] + obj_dx, rc.centroid[1] + obj_dy)
            rc_start = (rc.start[0] + obj_dx, rc.start[1] + obj_dy)
            rc_end = (rc.end[0] + obj_dx, rc.end[1] + obj_dy)
            c_dist = math.dist(rc_centroid, sc.centroid)
            len_delta = abs(rc.length - sc.length)
            r_ang = (
                math.degrees(
                    math.atan2(rc_end[1] - rc_start[1], rc_end[0] - rc_start[0])
                )
                % 180.0
            )
            s_ang = (
                math.degrees(
                    math.atan2(sc.end[1] - sc.start[1], sc.end[0] - sc.start[0])
                )
                % 180.0
            )
            ang_delta = abs(r_ang - s_ang) % 180.0
            ang_delta = min(ang_delta, 180.0 - ang_delta)
            ep_dists = min(
                (math.dist(rc_start, sc.start), math.dist(rc_end, sc.end)),
                (math.dist(rc_start, sc.end), math.dist(rc_end, sc.start)),
                key=sum,
            )
            pivot_aligned = min(ep_dists) <= pos_tol
            intrinsic_changed = len_delta > len_tol or ang_delta > ang_tol
            errs = []
            if c_dist > pos_tol and (not intrinsic_changed or not pivot_aligned):
                errs.append(
                    {
                        "category": "incorrect_position",
                        "expected": 0.0,
                        "actual": round(c_dist, 4),
                        "deviation": round(c_dist, 4),
                        "vector": [
                            round(sc.centroid[0] - rc_centroid[0], 4),
                            round(sc.centroid[1] - rc_centroid[1], 4),
                        ],
                        "tolerance": pos_tol,
                        "student_entity_id": sc.source_entity_id,
                        "location": list(sc.centroid),
                    }
                )
            if len_delta > len_tol:
                errs.append(
                    {
                        "category": "incorrect_length",
                        "expected": round(rc.length, 4),
                        "actual": round(sc.length, 4),
                        "tolerance": len_tol,
                        "student_entity_id": sc.source_entity_id,
                        "location": list(sc.centroid),
                    }
                )
            if ang_delta > ang_tol:
                errs.append(
                    {
                        "category": "incorrect_angle",
                        "expected": round(r_ang, 4),
                        "actual": round(s_ang, 4),
                        "tolerance": ang_tol,
                        "student_entity_id": sc.source_entity_id,
                        "location": list(sc.centroid),
                    }
                )
            cm.presence = 1.0
            cm.correctness = 0.0 if errs else 1.0
            cm.covered_length = min(rc.length, sc.length)
            cm.errors = errs
            _record_pair(rc, sc, 0.8 if errs else 1.0)

    # Preserve overhang findings when a student line was split at a junction (-J00/-J01)
    # and the matched piece was credited while a collinear overhang sibling stayed unused.
    unused_junction_siblings: dict[str, list[CanonicalComponent]] = defaultdict(list)
    for sc2 in stu_comps:
        if (
            sc2.kind == "segment"
            and sc2.start
            and sc2.end
            and sc2.id not in used_stu_comp_ids
            and "-J" in sc2.id
        ):
            unused_junction_siblings[sc2.id.rsplit("-J", 1)[0]].append(sc2)

    if unused_junction_siblings:
        obj_by_id = {obj.object_id: obj for obj in ref_objects}
        for cm in component_matches:
            rc = cm.reference_component
            if (
                cm.presence <= 0.0
                or rc.kind != "segment"
                or not rc.start
                or not rc.end
                or not cm.student_components
            ):
                continue
            junction_bases = [
                sc.id.rsplit("-J", 1)[0]
                for sc in cm.student_components
                if sc.kind == "segment" and "-J" in sc.id
            ]
            if not any(base in unused_junction_siblings for base in junction_bases):
                continue

            obj_dx, obj_dy = (
                object_translations.get(rc.parent_object_id, (0.0, 0.0))
                if rc.parent_object_id
                else (0.0, 0.0)
            )
            A = (rc.start[0] + obj_dx, rc.start[1] + obj_dy)
            B = (rc.end[0] + obj_dx, rc.end[1] + obj_dy)
            L = max(rc.length, 1e-9)
            ux = (B[0] - A[0]) / L
            uy = (B[1] - A[1]) / L
            nx = -uy
            ny = ux

            span_min, span_max = 0.0, L
            parent_obj = obj_by_id.get(rc.parent_object_id) if rc.parent_object_id else None
            if parent_obj is not None:
                collinear_ref_intervals: list[tuple[float, float]] = [(0.0, L)]
                for other_rc in parent_obj.components:
                    if (
                        other_rc.id == rc.id
                        or other_rc.kind != "segment"
                        or not other_rc.start
                        or not other_rc.end
                    ):
                        continue
                    oA = (other_rc.start[0] + obj_dx, other_rc.start[1] + obj_dy)
                    oB = (other_rc.end[0] + obj_dx, other_rc.end[1] + obj_dy)
                    odA = abs((oA[0] - A[0]) * nx + (oA[1] - A[1]) * ny)
                    odB = abs((oB[0] - A[0]) * nx + (oB[1] - A[1]) * ny)
                    if odA <= 1e-3 and odB <= 1e-3:
                        otA = (oA[0] - A[0]) * ux + (oA[1] - A[1]) * uy
                        otB = (oB[0] - A[0]) * ux + (oB[1] - A[1]) * uy
                        collinear_ref_intervals.append((min(otA, otB), max(otA, otB)))
                collinear_ref_intervals.sort()
                merged_ref_spans: list[tuple[float, float]] = []
                cs, ce = collinear_ref_intervals[0]
                for s_iv, e_iv in collinear_ref_intervals[1:]:
                    if s_iv <= ce + 1e-3:
                        ce = max(ce, e_iv)
                    else:
                        merged_ref_spans.append((cs, ce))
                        cs, ce = s_iv, e_iv
                merged_ref_spans.append((cs, ce))
                for s_iv, e_iv in merged_ref_spans:
                    if s_iv <= 1e-3 and e_iv >= L - 1e-3:
                        span_min, span_max = s_iv, e_iv
                        break

            for base in dict.fromkeys(junction_bases):
                for sc2 in unused_junction_siblings.get(base, []):
                    if sc2.id in used_stu_comp_ids or not sc2.start or not sc2.end:
                        continue
                    dP = abs((sc2.start[0] - A[0]) * nx + (sc2.start[1] - A[1]) * ny)
                    dQ = abs((sc2.end[0] - A[0]) * nx + (sc2.end[1] - A[1]) * ny)
                    if max(dP, dQ) > pos_tol * 1.5:
                        continue
                    tP = (sc2.start[0] - A[0]) * ux + (sc2.start[1] - A[1]) * uy
                    tQ = (sc2.end[0] - A[0]) * ux + (sc2.end[1] - A[1]) * uy
                    overhang = max(span_min - min(tP, tQ), max(tP, tQ) - span_max)
                    if overhang > pos_tol:
                        act_pos = round(overhang, 4)
                        cm.correctness = 0.0
                        if not any(
                            e.get("category") == "incorrect_position"
                            and e.get("student_entity_id") == sc2.source_entity_id
                            and float(e.get("actual", 0.0)) >= act_pos - 1e-4
                            for e in cm.errors
                        ):
                            cm.errors.append(
                                {
                                    "category": "incorrect_position",
                                    "expected": 0.0,
                                    "actual": act_pos,
                                    "deviation": act_pos,
                                    "tolerance": pos_tol,
                                    "student_entity_id": sc2.source_entity_id,
                                    "location": list(sc2.centroid),
                                }
                            )
                        _mark_stu_used(sc2)

    unsplit_stu_comps = [
        c
        for c in extract_canonical_components(student)
        if c.kind not in {"text", "dimension"}
    ]
    stu_conn_comps = [
        c
        for c in unsplit_stu_comps
        if c.start is not None and c.end is not None
    ]

    def _in_closed_cycle(
        pt: Point,
        comps: list[CanonicalComponent],
        conn_tol: float,
    ) -> bool:
        for sc0 in comps:
            s0, e0 = sc0.start, sc0.end
            if s0 is None or e0 is None:
                continue
            if math.dist(s0, pt) <= conn_tol:
                start_pt = e0
            elif math.dist(e0, pt) <= conn_tol:
                start_pt = s0
            else:
                continue
            frontier_c: list[tuple[Point, int]] = [(start_pt, 1)]
            visited_c: set[str] = {sc0.id}
            while frontier_c:
                cur_pt, depth = frontier_c.pop(0)
                for sc in comps:
                    if sc.id in visited_c:
                        continue
                    s_pt, e_pt = sc.start, sc.end
                    if s_pt is None or e_pt is None:
                        continue
                    if math.dist(s_pt, cur_pt) <= conn_tol:
                        nxt = e_pt
                    elif math.dist(e_pt, cur_pt) <= conn_tol:
                        nxt = s_pt
                    else:
                        continue
                    if depth >= 2 and math.dist(nxt, pt) <= conn_tol:
                        return True
                    visited_c.add(sc.id)
                    frontier_c.append((nxt, depth + 1))
        return False

    def _points_connected_in_student(
        pt_a: Point,
        pt_b: Point,
        comps: list[CanonicalComponent],
        tol: float,
    ) -> bool:
        conn_tol = max(tol, 1e-2)
        gap_dist = math.dist(pt_a, pt_b)
        if gap_dist <= conn_tol:
            return True
        deg_a = 0
        deg_b = 0
        for sc in comps:
            s_pt, e_pt = sc.start, sc.end
            if s_pt is None or e_pt is None:
                continue
            if math.dist(s_pt, pt_a) <= conn_tol or math.dist(e_pt, pt_a) <= conn_tol:
                deg_a += 1
            if math.dist(s_pt, pt_b) <= conn_tol or math.dist(e_pt, pt_b) <= conn_tol:
                deg_b += 1

        is_closed_junction = (
            deg_a >= 2
            and deg_b >= 2
            and _in_closed_cycle(pt_a, comps, conn_tol)
            and _in_closed_cycle(pt_b, comps, conn_tol)
        )
        mid = ((pt_a[0] + pt_b[0]) * 0.5, (pt_a[1] + pt_b[1]) * 0.5)
        max_local_radius = max((3.5 if is_closed_junction else 1.6) * gap_dist, conn_tol)
        max_path_len = max((7.0 if is_closed_junction else 2.2) * gap_dist, conn_tol)

        frontier: list[tuple[Point, float]] = [(pt_a, 0.0)]
        visited_ids: set[str] = set()
        while frontier:
            cur_pt, acc_len = frontier.pop(0)
            for sc in comps:
                if sc.id in visited_ids:
                    continue
                s_pt, e_pt = sc.start, sc.end
                if s_pt is None or e_pt is None:
                    continue
                if math.dist(s_pt, cur_pt) <= conn_tol:
                    nxt = e_pt
                elif math.dist(e_pt, cur_pt) <= conn_tol:
                    nxt = s_pt
                else:
                    continue
                seg_len = sc.length if sc.length > 0.0 else math.dist(s_pt, e_pt)
                new_len = acc_len + seg_len
                if new_len > max_path_len + conn_tol:
                    continue
                if math.dist(nxt, pt_b) <= conn_tol:
                    return True
                if math.dist(nxt, mid) <= max_local_radius + conn_tol:
                    visited_ids.add(sc.id)
                    frontier.append((nxt, new_len))
        return False

    # Check objects for genuine corner endpoint gaps between present adjacent components
    cm_by_rc_id = {cm.reference_component.id: cm for cm in component_matches}
    for obj in ref_objects:
        if len(obj.components) < 2:
            continue
        obj_dx, obj_dy = object_translations.get(obj.object_id, (0.0, 0.0))
        obj_cms = [
            cm_by_rc_id[c.id] for c in obj.components if c.id in cm_by_rc_id
        ]
        if not obj_cms:
            continue
        is_all_present_closed = obj.is_closed and len(obj.components) >= 3 and all(cm.presence > 0.0 for cm in obj_cms)
        # Check each shared reference corner vertex between present components
        vertex_map: dict[
            tuple[int, int], list[tuple[ComponentMatch, Point]]
        ] = defaultdict(list)
        for cm in obj_cms:
            if cm.presence <= 0.0:
                continue
            rc = cm.reference_component
            if rc.kind == "segment" and rc.start and rc.end:
                for pt in (rc.start, rc.end):
                    k = (round(pt[0] / max(pos_tol, 1e-4)), round(pt[1] / max(pos_tol, 1e-4)))
                    vertex_map[k].append((cm, pt))
        for _, entries in vertex_map.items():
            if len(entries) != 2:
                continue
            (cm1, ref_pt1), (cm2, ref_pt2) = entries
            if cm1.reference_component.id == cm2.reference_component.id:
                continue
            if not cm1.student_components or not cm2.student_components:
                continue
            if not is_all_present_closed and not (cm1.errors or cm2.errors):
                continue
            ref_corner = (
                (ref_pt1[0] + ref_pt2[0]) / 2.0 + obj_dx,
                (ref_pt1[1] + ref_pt2[1]) / 2.0 + obj_dy,
            )
            pts1 = [
                p
                for sc in cm1.student_components
                for p in (sc.start, sc.end)
                if p is not None
            ]
            pts2 = [
                p
                for sc in cm2.student_components
                for p in (sc.start, sc.end)
                if p is not None
            ]
            if not pts1 or not pts2:
                continue
            p1 = min(pts1, key=lambda p: math.dist(p, ref_corner))
            p2 = min(pts2, key=lambda p: math.dist(p, ref_corner))
            gap_dist = math.dist(p1, p2)
            if gap_dist > pos_tol and not _points_connected_in_student(
                p1, p2, stu_conn_comps, pos_tol
            ):
                # Attribute endpoint gap to the component with an existing primary error, or whose endpoint moved further from ref_corner
                if cm1.errors and not cm2.errors:
                    target_cm = cm1
                elif cm2.errors and not cm1.errors:
                    target_cm = cm2
                else:
                    target_cm = (
                        cm1
                        if math.dist(p1, ref_corner) >= math.dist(p2, ref_corner)
                        else cm2
                    )
                if not any(
                    e["category"] == "endpoint_gap" for e in target_cm.errors
                ):
                    sc0 = target_cm.student_components[0]
                    target_cm.errors.append(
                        {
                            "category": "endpoint_gap",
                            "expected": 0.0,
                            "actual": round(gap_dist, 4),
                            "tolerance": pos_tol,
                            "student_entity_id": sc0.source_entity_id,
                            "location": list(ref_corner),
                            "actual_points": [list(p1), list(p2)],
                            "expected_point": list(ref_corner),
                            "supporting_only": not is_all_present_closed,
                        }
                    )

    # Detect student-to-student collinear overlaps and coincident duplicates
    stu_entity_total_len: dict[str, float] = defaultdict(float)
    stu_entity_handle: dict[str, str | None] = {}
    for c in unsplit_stu_comps:
        stu_entity_total_len[c.source_entity_id] += c.length
        stu_entity_handle[c.source_entity_id] = c.source_handle

    pair_overlaps: dict[tuple[str, str], dict[str, Any]] = {}
    for i in range(len(unsplit_stu_comps)):
        c1 = unsplit_stu_comps[i]
        for j in range(i + 1, len(unsplit_stu_comps)):
            c2 = unsplit_stu_comps[j]
            if c1.source_entity_id == c2.source_entity_id or c1.kind != c2.kind:
                continue
            e1, e2 = sorted((c1.source_entity_id, c2.source_entity_id))
            if c1.kind == "segment" and c1.start and c1.end and c2.start and c2.end:
                longer, shorter = (c1, c2) if c1.length >= c2.length else (c2, c1)
                if shorter.length <= 1e-4:
                    continue
                ang1 = math.degrees(math.atan2(longer.end[1] - longer.start[1], longer.end[0] - longer.start[0])) % 180.0
                ang2 = math.degrees(math.atan2(shorter.end[1] - shorter.start[1], shorter.end[0] - shorter.start[0])) % 180.0
                ad = abs(ang1 - ang2) % 180.0
                ad = min(ad, 180.0 - ad)
                if ad > 1.0:
                    continue
                L_long = max(longer.length, 1e-9)
                ux_l = (longer.end[0] - longer.start[0]) / L_long
                uy_l = (longer.end[1] - longer.start[1]) / L_long
                nx_l, ny_l = -uy_l, ux_l
                d1 = abs((shorter.start[0] - longer.start[0]) * nx_l + (shorter.start[1] - longer.start[1]) * ny_l)
                d2 = abs((shorter.end[0] - longer.start[0]) * nx_l + (shorter.end[1] - longer.start[1]) * ny_l)
                if max(d1, d2) > min(pos_tol * 0.25, 0.5):
                    continue
                t1 = (shorter.start[0] - longer.start[0]) * ux_l + (shorter.start[1] - longer.start[1]) * uy_l
                t2 = (shorter.end[0] - longer.start[0]) * ux_l + (shorter.end[1] - longer.start[1]) * uy_l
                o0 = max(0.0, min(t1, t2))
                o1 = min(L_long, max(t1, t2))
                ov = o1 - o0
                if ov >= max(len_tol * 1.5, 1.5):
                    t_mid = (o0 + o1) / 2.0
                    mid_pt = (
                        longer.start[0] + t_mid * ux_l + dx,
                        longer.start[1] + t_mid * uy_l + dy,
                    )
                    rec = pair_overlaps.setdefault(
                        (e1, e2),
                        {"overlap_length": 0.0, "locations": []},
                    )
                    rec["overlap_length"] += ov
                    rec["locations"].append(mid_pt)
            elif c1.kind in {"circle", "arc"} and c1.center and c2.center and c1.radius and c2.radius:
                if math.dist(c1.center, c2.center) <= min(pos_tol * 0.25, 0.5) and abs(c1.radius - c2.radius) <= min(rad_tol * 0.25, 0.5):
                    ov = min(c1.length, c2.length)
                    rec = pair_overlaps.setdefault(
                        (e1, e2),
                        {"overlap_length": 0.0, "locations": []},
                    )
                    rec["overlap_length"] += ov
                    rec["locations"].append((c1.center[0] + dx, c1.center[1] + dy))

    student_overlaps: dict[str, dict[str, Any]] = {}
    for (e1, e2), rec in sorted(pair_overlaps.items()):
        ov_len = float(rec["overlap_length"])
        len1 = max(stu_entity_total_len.get(e1, 0.0), 1e-6)
        len2 = max(stu_entity_total_len.get(e2, 0.0), 1e-6)
        u1 = e1 in used_stu_entity_ids
        u2 = e2 in used_stu_entity_ids
        if u1 and not u2:
            dup_eid, partner_eid = e2, e1
        elif u2 and not u1:
            dup_eid, partner_eid = e1, e2
        elif len1 < len2 - 1e-3:
            dup_eid, partner_eid = e1, e2
        elif len2 < len1 - 1e-3:
            dup_eid, partner_eid = e2, e1
        else:
            dup_eid, partner_eid = max(e1, e2), min(e1, e2)

        dup_len = max(stu_entity_total_len.get(dup_eid, 0.0), 1e-6)
        partner_len = max(stu_entity_total_len.get(partner_eid, 0.0), 1e-6)
        pct = min(100.0, round(100.0 * ov_len / dup_len, 1))
        partner_pct = min(100.0, round(100.0 * ov_len / partner_len, 1))
        locs = rec["locations"]
        avg_loc = (
            sum(p[0] for p in locs) / len(locs),
            sum(p[1] for p in locs) / len(locs),
        ) if locs else None

        duplicate_student_entities.add(dup_eid)
        existing = student_overlaps.get(dup_eid)
        if existing is None or ov_len > existing["overlap_length"]:
            student_overlaps[dup_eid] = {
                "entity_id": dup_eid,
                "entity_handle": stu_entity_handle.get(dup_eid),
                "partner_entity_id": partner_eid,
                "partner_handle": stu_entity_handle.get(partner_eid),
                "overlap_length": round(ov_len, 4),
                "overlap_percentage": pct,
                "partner_overlap_percentage": partner_pct,
                "is_full_duplicate": ov_len >= dup_len - len_tol,
                "location": list(avg_loc) if avg_loc else None,
            }

    all_student_entity_ids = {
        e.id for e in student.entities if e.kind not in {"text", "dimension"}
    }
    duplicate_student_entities = {
        eid
        for eid in duplicate_student_entities
        if eid not in used_stu_entity_ids
    }
    extra_student_entities = sorted(
        all_student_entity_ids
        - used_stu_entity_ids
        - duplicate_student_entities
        - set(degenerate_student_entities)
    )

    weight_sum = sum(
        (Fraction(cm.weight) for cm in component_matches), Fraction()
    )
    P = float(
        sum(
            (
                Fraction(cm.weight) * Fraction(cm.presence)
                for cm in component_matches
            ),
            Fraction(),
        )
        / weight_sum
    )
    Q = float(
        sum(
            (
                Fraction(cm.weight)
                * Fraction(cm.presence)
                * Fraction(cm.correctness)
                for cm in component_matches
            ),
            Fraction(),
        )
        / weight_sum
    )

    obj_summary = {
        "total_reference_objects": len(ref_objects),
        "total_reference_components": total_components,
        "total_student_components": len(stu_comps),
        "matched_components_count": sum(
            1 for cm in component_matches if cm.presence >= 1.0 - 1e-4
        ),
        "partial_components_count": sum(
            1 for cm in component_matches if 0.0 < cm.presence < 1.0 - 1e-4
        ),
        "missing_components_count": sum(
            1 for cm in component_matches if cm.presence == 0.0
        ),
        "extra_student_entities_count": len(extra_student_entities),
    }

    return CanonicalMatchResult(
        reference_objects=ref_objects,
        component_matches=component_matches,
        missing_components=missing_components,
        extra_student_entities=sorted(set(extra_student_entities)),
        duplicate_student_entities=sorted(duplicate_student_entities),
        matched_pairs=matched_pairs,
        completion_fraction=P,
        accuracy_fraction=Q,
        object_summary=obj_summary,
        object_translations=object_translations,
        matched_objects=matched_objects_list,
        degenerate_student_entities=sorted(set(degenerate_student_entities)),
        student_overlaps=student_overlaps,
        position_tolerance=pos_tol,
        ambiguous_groups=ambiguous_groups,
    )
