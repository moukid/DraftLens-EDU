from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Literal

from .models import Drawing, Entity


STANDARD_INFO_LAYERS = {
    "dl-info",
    "dl-info-tags",
    "dl-info-legend",
    "dl-info-regions",
}

DEFAULT_CODE_MAPPINGS: dict[str, str] = {
    "D1": "Door",
    "W1": "Window",
    "C1": "Column",
    "DD1": "Double Door",
    "SD1": "Sliding Door",
    "S1": "Stairs",
}

ObjectStatus = Literal["detected", "proposed", "confirmed", "unresolved", "excluded"]
CorrespondenceStatus = Literal["present", "partial", "missing", "uncertain"]

MARKER_CODE_RE = re.compile(r"^[A-Z]{1,4}\d{1,3}$")


@dataclass(slots=True)
class ReferenceMarker:
    code: str
    meaning: str | None
    location: tuple[float, float]
    layer: str
    handle: str | None = None
    is_legend: bool = False
    exclusion_reason: str | None = None
    outline_points: list[tuple[float, float]] = field(default_factory=list)
    bounds: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReferenceObject:
    occurrence_id: str
    type_code: str
    meaning: str
    marker_location: tuple[float, float]
    member_entity_ids: list[str] = field(default_factory=list)
    member_handles: list[str] = field(default_factory=list)
    bounds: tuple[float, float, float, float] | None = None
    status: ObjectStatus = "proposed"
    exclusion_reason: str | None = None
    notes: str = ""
    shared_entity_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StudentObjectCorrespondence:
    occurrence_id: str
    type_code: str
    meaning: str
    status: CorrespondenceStatus
    matched_reference_ids: list[str] = field(default_factory=list)
    matched_student_ids: list[str] = field(default_factory=list)
    total_members: int = 0
    matched_members: int = 0
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_info_layer(layer_name: str, custom_layers: set[str] | None = None) -> bool:
    """Case-normalized exact layer matching without overly broad substrings."""
    if not layer_name:
        return False
    normalized = layer_name.strip().lower()
    if normalized in STANDARD_INFO_LAYERS:
        return True
    if custom_layers and normalized in {c.strip().lower() for c in custom_layers}:
        return True
    return False


def _point_in_bbox(point: tuple[float, float], bbox: tuple[float, float, float, float], tol: float = 1e-4) -> bool:
    x, y = point
    return (bbox[0] - tol <= x <= bbox[2] + tol) and (bbox[1] - tol <= y <= bbox[3] + tol)


def _bbox_for_points(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _distance_to_entity(x: float, y: float, entity: Entity) -> float:
    if entity.centroid is not None:
        return math.dist((x, y), entity.centroid)
    if entity.points:
        return min(math.dist((x, y), p) for p in entity.points)
    return float("inf")


def extract_reference_markers_and_legend(
    all_entities: list[Entity],
    unsupported_entities: list[dict[str, Any]],
    *,
    custom_info_layers: set[str] | None = None,
    code_mappings: dict[str, str] | None = None,
    legend_region_bbox: tuple[float, float, float, float] | None = None,
    exclude_table_handle: str | None = None,
) -> tuple[list[ReferenceMarker], list[ReferenceMarker], dict[str, Any]]:
    """Extract information-layer markers and separate plan markers from legend samples."""
    mappings = {**DEFAULT_CODE_MAPPINGS, **(code_mappings or {})}

    # 1. Identify legend regions / ACAD_TABLEs
    legend_tables = []
    for unsup in unsupported_entities:
        etype = str(unsup.get("entity_type", "")).upper()
        if "TABLE" in etype:
            legend_tables.append(unsup)

    info_entities = [
        e for e in all_entities if is_info_layer(e.layer, custom_info_layers)
    ]

    # Find text markers on info layers
    text_entities = [e for e in info_entities if e.kind == "text" and e.text]
    outline_entities = [e for e in info_entities if e.kind != "text"]

    # 2. Check for legend outlines on DL-INFO-LEGEND
    legend_outlines = [
        e for e in info_entities
        if e.layer.strip().lower() == "dl-info-legend" and e.bbox
    ]
    computed_legend_bboxes: list[tuple[float, float, float, float]] = []
    if legend_region_bbox:
        computed_legend_bboxes.append(legend_region_bbox)
    for lo in legend_outlines:
        if lo.bbox:
            computed_legend_bboxes.append(lo.bbox)

    raw_markers: list[ReferenceMarker] = []
    ignored_text: list[dict[str, Any]] = []
    for text_ent in text_entities:
        code = str(text_ent.text or "").strip().upper()
        if not code:
            continue
        if not MARKER_CODE_RE.fullmatch(code):
            ignored_text.append({
                "handle": text_ent.source_handle,
                "layer": text_ent.layer,
                "text": str(text_ent.text or ""),
                "reason": "Text does not match the reference marker code format.",
            })
            continue
        loc = text_ent.points[0] if text_ent.points else (0.0, 0.0)

        # Check for surrounding marker outline (within small distance)
        associated_outline: Entity | None = None
        closest_dist = float("inf")
        for outline in outline_entities:
            dist = _distance_to_entity(loc[0], loc[1], outline)
            if dist < closest_dist and dist < 25.0:
                closest_dist = dist
                associated_outline = outline

        outline_pts = associated_outline.points if associated_outline else []
        marker_bbox = text_ent.bbox or (loc[0]-5, loc[1]-5, loc[0]+5, loc[1]+5)
        if associated_outline and associated_outline.bbox:
            marker_bbox = associated_outline.bbox

        meaning = mappings.get(code)
        is_legend = False
        exclusion_reason = None

        if text_ent.layer.strip().lower() == "dl-info-legend":
            is_legend = True
            exclusion_reason = "Placed on explicit DL-INFO-LEGEND layer"
        elif any(_point_in_bbox(loc, lbox) for lbox in computed_legend_bboxes):
            is_legend = True
            exclusion_reason = "Inside identified legend region / table boundary"

        raw_markers.append(
            ReferenceMarker(
                code=code,
                meaning=meaning,
                location=loc,
                layer=text_ent.layer,
                handle=text_ent.source_handle,
                is_legend=is_legend,
                exclusion_reason=exclusion_reason,
                outline_points=outline_pts,
                bounds=marker_bbox,
            )
        )

    # 3. Sort plan markers deterministically (y descending, x ascending)
    plan_markers = [m for m in raw_markers if not m.is_legend]
    legend_markers = [m for m in raw_markers if m.is_legend]

    plan_markers.sort(key=lambda m: (-round(m.location[1], 3), round(m.location[0], 3), m.code))
    legend_markers.sort(key=lambda m: (-round(m.location[1], 3), round(m.location[0], 3), m.code))

    metadata = {
        "total_markers_detected": len(raw_markers),
        "plan_markers_count": len(plan_markers),
        "legend_samples_count": len(legend_markers),
        "legend_tables_detected": len(legend_tables),
        "table_handles": [t.get("handle") for t in legend_tables if t.get("handle")],
        "ignored_information_text": ignored_text,
    }
    return plan_markers, legend_markers, metadata


def build_proposed_reference_objects(
    plan_markers: list[ReferenceMarker],
    base_reference_entities: list[Entity],
    *,
    code_mappings: dict[str, str] | None = None,
    search_radius: float = 60.0,
) -> tuple[list[ReferenceObject], dict[str, Any]]:
    """Assign deterministic occurrence IDs and propose conservative member geometry."""
    mappings = {**DEFAULT_CODE_MAPPINGS, **(code_mappings or {})}
    code_counters: dict[str, int] = {}

    objects: list[ReferenceObject] = []
    unknown_codes: set[str] = set()

    for marker in plan_markers:
        code = marker.code
        meaning = mappings.get(code)
        if meaning is None:
            unknown_codes.add(code)
            meaning = f"Unmapped ({code})"

        count = code_counters.get(code, 0) + 1
        code_counters[code] = count
        occurrence_id = f"{code}-{count:03d}"

        # Conservative spatial grouping
        proposed_members: list[Entity] = []
        mx, my = marker.location

        # Type-aware candidate selection:
        # Avoid greedy grouping; only gather entities within search radius
        for ent in base_reference_entities:
            dist = _distance_to_entity(mx, my, ent)
            if dist <= search_radius:
                proposed_members.append(ent)

        member_ids = [e.id for e in proposed_members]
        member_handles = [e.source_handle for e in proposed_members if e.source_handle]

        # Compute combined bounding box
        combined_pts: list[tuple[float, float]] = []
        for e in proposed_members:
            combined_pts.extend(e.points)
        if marker.bounds:
            combined_pts.extend([(marker.bounds[0], marker.bounds[1]), (marker.bounds[2], marker.bounds[3])])
        combined_bbox = _bbox_for_points(combined_pts) if combined_pts else marker.bounds

        if meaning.startswith("Unmapped"):
            status: ObjectStatus = "unresolved"
        elif member_ids:
            status = "proposed"
        else:
            status = "detected"

        objects.append(
            ReferenceObject(
                occurrence_id=occurrence_id,
                type_code=code,
                meaning=meaning,
                marker_location=marker.location,
                member_entity_ids=member_ids,
                member_handles=member_handles,
                bounds=combined_bbox,
                status=status,
                notes=f"Detected at ({round(mx, 2)}, {round(my, 2)}) with {len(member_ids)} proposed member entity(ies).",
            )
        )

    # Detect overlapping memberships
    entity_to_objects: dict[str, list[str]] = {}
    for obj in objects:
        for eid in obj.member_entity_ids:
            entity_to_objects.setdefault(eid, []).append(obj.occurrence_id)

    overlap_warnings: list[dict[str, Any]] = []
    for eid, occ_ids in entity_to_objects.items():
        if len(occ_ids) > 1:
            overlap_warnings.append({
                "entity_id": eid,
                "shared_between_objects": occ_ids,
            })
            for obj in objects:
                if obj.occurrence_id in occ_ids:
                    if eid not in obj.shared_entity_ids:
                        obj.shared_entity_ids.append(eid)

    summary = {
        "total_objects": len(objects),
        "counts_by_type": {code: code_counters[code] for code in sorted(code_counters)},
        "counts_by_status": {
            "detected": sum(o.status == "detected" for o in objects),
            "proposed": sum(o.status == "proposed" for o in objects),
            "confirmed": sum(o.status == "confirmed" for o in objects),
            "unresolved": sum(o.status == "unresolved" for o in objects),
            "excluded": sum(o.status == "excluded" for o in objects),
        },
        "unknown_codes": sorted(unknown_codes),
        "has_overlapping_memberships": len(overlap_warnings) > 0,
        "overlapping_memberships": overlap_warnings,
    }
    return objects, summary


def evaluate_student_object_correspondence(
    confirmed_objects: list[ReferenceObject],
    matches: list[dict[str, Any]],
) -> list[StudentObjectCorrespondence]:
    """Read-only student correspondence preview without altering geometry grades."""
    # Match map: reference_entity_id -> student_entity_id
    ref_to_stu: dict[str, str] = {}
    match_quality_map: dict[str, float] = {}
    for m in matches:
        rid = m.get("reference_entity_id") or m.get("reference_id")
        sid = m.get("student_entity_id") or m.get("student_id")
        if rid and sid:
            ref_to_stu[rid] = sid
            match_quality_map[rid] = float(m.get("match_quality", m.get("confidence", 1.0)))

    assigned_student_entities: set[str] = set()
    correspondences: list[StudentObjectCorrespondence] = []

    for obj in confirmed_objects:
        if obj.status != "confirmed":
            continue

        matched_ref_ids: list[str] = []
        matched_stu_ids: list[str] = []
        has_collision = False

        for rid in obj.member_entity_ids:
            sid = ref_to_stu.get(rid)
            if sid:
                if sid in assigned_student_entities:
                    has_collision = True
                assigned_student_entities.add(sid)
                matched_ref_ids.append(rid)
                matched_stu_ids.append(sid)

        total = len(obj.member_entity_ids)
        matched_count = len(matched_ref_ids)

        if total == 0:
            status: CorrespondenceStatus = "uncertain"
            explanation = "No confirmed member entities in reference object definition."
        elif has_collision:
            status = "uncertain"
            explanation = "Shared or ambiguous student entity correspondence detected."
        elif matched_count == total:
            status = "present"
            explanation = f"All {total} reference member entity(ies) correspond to matched student geometry."
        elif matched_count > 0:
            status = "partial"
            explanation = f"{matched_count} of {total} reference member entity(ies) matched in student submission."
        else:
            status = "missing"
            explanation = f"None of the {total} reference member entity(ies) were found in student submission."

        correspondences.append(
            StudentObjectCorrespondence(
                occurrence_id=obj.occurrence_id,
                type_code=obj.type_code,
                meaning=obj.meaning,
                status=status,
                matched_reference_ids=matched_ref_ids,
                matched_student_ids=matched_stu_ids,
                total_members=total,
                matched_members=matched_count,
                explanation=explanation,
            )
        )

    return correspondences
