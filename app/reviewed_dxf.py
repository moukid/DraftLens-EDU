from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
import math
from typing import Any

from .models import Drawing, Entity

def project_ellipse_2d(
    major: tuple[float, ...],
    ratio: float,
    extrusion: tuple[float, ...] | None = None
) -> tuple[float, float, float] | None:
    """Project a 3D ellipse to a 2D ellipse (rx, ry, rotation_angle_radians)."""
    ex, ey, ez = (0.0, 0.0, 1.0)
    if extrusion and len(extrusion) >= 3:
        ex, ey, ez = extrusion[:3]
    elif extrusion and len(extrusion) == 2:
        ex, ey = extrusion
    vx, vy, vz = (0.0, 0.0, 0.0)
    if len(major) >= 3:
        vx, vy, vz = major[:3]
    elif len(major) == 2:
        vx, vy = major

    from ezdxf.math import ConstructionEllipse
    try:
        e = ConstructionEllipse((0.0, 0.0, 0.0), (vx, vy, vz), (ex, ey, ez), ratio, 0.0, math.tau)
        u_x, u_y = e.major_axis.x, e.major_axis.y
        v_x, v_y = e.minor_axis.x, e.minor_axis.y
        A = u_x**2 + v_x**2
        C = u_y**2 + v_y**2
        B = u_x*u_y + v_x*v_y
        diff = A - C
        hyp = math.hypot(diff, 2*B)
        rx = math.sqrt(max(0.0, (A + C + hyp) / 2))
        ry = math.sqrt(max(0.0, (A + C - hyp) / 2))
        angle = math.atan2(2*B, diff) / 2
        return rx, ry, angle
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class ReviewedEntity:
    """Immutable rendering snapshot with source provenance."""

    entity_id: str
    source: str
    kind: str
    layer: str
    points: tuple[tuple[float, float], ...]
    radius: float | None
    start_angle: float | None
    end_angle: float | None
    closed: bool
    text: str | None
    bbox: tuple[float, float, float, float] | None
    properties_json: str

    @property
    def properties(self) -> dict[str, Any]:
        return json.loads(self.properties_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["properties"] = json.loads(data.pop("properties_json"))
        return data


@dataclass(frozen=True, slots=True)
class ReviewedIssue:
    """Visual issue record grounded in comparison or validation evidence."""

    issue_id: str
    category: str
    severity: str
    visual_role: str
    source_entity_id: str | None
    expected_entity_id: str | None
    actual_geometry: ReviewedEntity | None
    expected_geometry: ReviewedEntity | None
    region: tuple[float, float, float, float] | None
    technical_feedback: str
    rubric_rule_id: str | None
    deduction: float | None
    raw_deduction: float | None
    applied_deduction: float | None
    deduction_status: str
    score_category: str | None
    raw_rule_deduction: float | None
    deduction_after_rule_cap: float | None
    deduction_after_category_cap: float | None
    final_applied_contribution: float | None
    cap_reason: str | None
    suppression_reason: str | None
    confidence: str
    classification: str
    provenance: str
    measurement_json: str
    correction_guidance_json: str
    recommended_commands: tuple[str, ...]
    parent_object_id: str | None = None
    component_id: str | None = None
    expected_geometries: tuple[ReviewedEntity, ...] = ()
    actual_geometries: tuple[ReviewedEntity, ...] = ()
    category_split: dict[str, float] | None = None
    score_categories: tuple[str, ...] = ()
    badge_label: str | None = None

    @property
    def measurement(self) -> Any:
        return json.loads(self.measurement_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actual_geometry"] = self.actual_geometry.to_dict() if self.actual_geometry else None
        data["expected_geometry"] = self.expected_geometry.to_dict() if self.expected_geometry else None
        data["expected_geometries"] = [g.to_dict() for g in self.expected_geometries]
        data["actual_geometries"] = [g.to_dict() for g in self.actual_geometries]
        data["score_categories"] = list(self.score_categories)
        data["badge_label"] = self.badge_label
        data["measurement"] = json.loads(data.pop("measurement_json"))
        data["correction_guidance"] = json.loads(
            data.pop("correction_guidance_json")
        )
        data["recommended_commands"] = list(data["recommended_commands"])
        return data


@dataclass(frozen=True, slots=True)
class ReviewedDrawing:
    """Complete, assignment-agnostic input for deterministic renderers."""

    reference_entities: tuple[ReviewedEntity, ...]
    student_entities: tuple[ReviewedEntity, ...]
    issues: tuple[ReviewedIssue, ...]
    reference_unsupported_json: tuple[str, ...]
    student_unsupported_json: tuple[str, ...]
    extents: tuple[float, float, float, float]
    units: str
    score: float | None
    aligned_reference_entities: tuple[ReviewedEntity, ...] = ()
    student_extents: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    reference_extents: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def reference_unsupported(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.reference_unsupported_json]

    @property
    def student_unsupported(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.student_unsupported_json]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_entities": [entity.to_dict() for entity in self.reference_entities],
            "student_entities": [entity.to_dict() for entity in self.student_entities],
            "issues": [issue.to_dict() for issue in self.issues],
            "reference_unsupported": self.reference_unsupported,
            "student_unsupported": self.student_unsupported,
            "extents": self.extents,
            "student_extents": self.student_extents,
            "reference_extents": self.reference_extents,
            "units": self.units,
            "score": self.score,
            "aligned_reference_entities": [entity.to_dict() for entity in self.aligned_reference_entities],
        }


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def sample_ellipse_arc(
    center: tuple[float, float],
    major_axis: tuple[float, float] | list[float],
    ratio: float,
    start_param: float | None,
    end_param: float | None,
    num_segments: int = 64,
    extrusion: tuple[float, float, float] | list[float] | None = None,
) -> list[tuple[float, float]] | None:
    """Sample a partial DXF ellipse as an open sequence of 2D points.

    Returns None when the ellipse represents a complete ellipse (start/end params omitted
    or covering a full 2*pi turn), indicating that native full-ellipse rendering should be used.
    Otherwise, returns an open list of points covering [start_param, end_param] counterclockwise.
    """
    if start_param is None or end_param is None:
        return None
    try:
        sp = float(start_param)
        ep = float(end_param)
        r = abs(float(ratio))
        cx, cy = float(center[0]), float(center[1])
        vx, vy = float(major_axis[0]), float(major_axis[1])
        vz = float(major_axis[2]) if len(major_axis) >= 3 else 0.0
        ex = float(extrusion[0]) if extrusion and len(extrusion) >= 1 else 0.0
        ey = float(extrusion[1]) if extrusion and len(extrusion) >= 2 else 0.0
        ez = float(extrusion[2]) if extrusion and len(extrusion) >= 3 else 1.0
    except (TypeError, ValueError, IndexError):
        return None

    if not (
        math.isfinite(sp)
        and math.isfinite(ep)
        and math.isfinite(r)
        and math.isfinite(cx)
        and math.isfinite(cy)
        and math.isfinite(vx)
        and math.isfinite(vy)
        and math.isfinite(vz)
        and math.isfinite(ex)
        and math.isfinite(ey)
        and math.isfinite(ez)
    ):
        return None

    tau = math.tau
    full_turn = sp + tau

    # A forward interval covering a full turn or more (start + tau) represents
    # a complete ellipse. Deliberately partial intervals immediately below this boundary
    # (e.g. math.nextafter(start + tau, -math.inf)) must remain partial.
    if ep >= full_turn:
        return None

    from ezdxf.math import ConstructionEllipse

    # Truly equal parameters represent a degenerate single-point arc
    if sp == ep:
        try:
            e = ConstructionEllipse((cx, cy, 0.0), (vx, vy, vz), (ex, ey, ez), r, sp, ep)
            p = list(e.vertices([sp]))[0]
            return [(p.x, p.y), (p.x, p.y)]
        except Exception:
            return None

    if ep > sp:
        # Known positive forward partial interval strictly within (0, tau).
        # We guard against subtraction rounding to tau (which would make modulo 0).
        span = ep - sp
        if span >= tau:
            span = math.nextafter(tau, -math.inf)
    else:
        # Wrapped counterclockwise interval crossing 0/2*pi.
        diff = ep - sp
        span = diff % tau
        if span <= 0.0:
            span += tau
        if span >= tau:
            span = math.nextafter(tau, -math.inf)

    n = max(32, int(math.ceil(num_segments * (span / tau))))
    step = span / n
    params = [sp + i * step for i in range(n + 1)]

    try:
        e = ConstructionEllipse((cx, cy, 0.0), (vx, vy, vz), (ex, ey, ez), r, sp, ep)
        return [(p.x, p.y) for p in e.vertices(params)]
    except Exception:
        return None


def _entity_bounds(entity: Entity) -> tuple[float, float, float, float] | None:
    points = [(float(x), float(y)) for x, y in entity.points if _finite(x) and _finite(y)]
    if entity.kind in {"circle", "arc"} and points and _finite(entity.radius):
        x, y = points[0]
        radius = abs(float(entity.radius))
        return (x - radius, y - radius, x + radius, y + radius)
    if entity.kind == "ellipse" and points:
        major = entity.properties.get("major_axis", (0.0, 0.0))
        if len(major) >= 2 and _finite(major[0]) and _finite(major[1]):
            sampled = sample_ellipse_arc(
                points[0],
                major,
                float(entity.properties.get("ratio", 1.0)),
                entity.properties.get("start_param"),
                entity.properties.get("end_param"),
                extrusion=entity.properties.get("extrusion"),
            )
            if sampled is not None and sampled:
                xs = [p[0] for p in sampled]
                ys = [p[1] for p in sampled]
                return (min(xs), min(ys), max(xs), max(ys))
            proj = project_ellipse_2d(major, float(entity.properties.get("ratio", 1.0)), entity.properties.get("extrusion"))
            if proj:
                rx, ry, angle_rad = proj
                hw = math.hypot(rx * math.cos(angle_rad), ry * math.sin(angle_rad))
                hh = math.hypot(rx * math.sin(angle_rad), ry * math.cos(angle_rad))
                x, y = points[0]
                return (x - hw, y - hh, x + hw, y + hh)
            rx = math.hypot(float(major[0]), float(major[1]))
            ry = rx * abs(float(entity.properties.get("ratio", 1.0)))
            angle_rad = math.atan2(float(major[1]), float(major[0]))
            hw = math.hypot(rx * math.cos(angle_rad), ry * math.sin(angle_rad))
            hh = math.hypot(rx * math.sin(angle_rad), ry * math.cos(angle_rad))
            x, y = points[0]
            return (x - hw, y - hh, x + hw, y + hh)
    if points:
        xs, ys = zip(*points)
        return (min(xs), min(ys), max(xs), max(ys))
    if entity.bbox and all(_finite(value) for value in entity.bbox):
        return tuple(float(value) for value in entity.bbox)
    return None


def _snapshot(entity: Entity, source: str) -> ReviewedEntity:
    points = tuple((float(x), float(y)) for x, y in entity.points if _finite(x) and _finite(y))
    return ReviewedEntity(
        entity_id=str(entity.id),
        source=source,
        kind=str(entity.kind),
        layer=str(entity.layer),
        points=points,
        radius=float(entity.radius) if _finite(entity.radius) else None,
        start_angle=float(entity.start_angle) if _finite(entity.start_angle) else None,
        end_angle=float(entity.end_angle) if _finite(entity.end_angle) else None,
        closed=bool(entity.closed),
        text=None if entity.text is None else str(entity.text),
        bbox=_entity_bounds(entity),
        properties_json=json.dumps(deepcopy(entity.properties), sort_keys=True, separators=(",", ":"), default=str),
    )


def _translate_reviewed_entity(entity: ReviewedEntity, dx: float, dy: float) -> ReviewedEntity:
    if not dx and not dy:
        return entity
    points = tuple((round(float(p[0]) + dx, 6), round(float(p[1]) + dy, 6)) for p in entity.points)
    bbox = (
        round(float(entity.bbox[0]) + dx, 6),
        round(float(entity.bbox[1]) + dy, 6),
        round(float(entity.bbox[2]) + dx, 6),
        round(float(entity.bbox[3]) + dy, 6),
    ) if entity.bbox else None
    return replace(entity, points=points, bbox=bbox)


def _union_regions(*regions: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    valid = [region for region in regions if region and all(_finite(value) for value in region)]
    if not valid:
        return None
    return (
        min(region[0] for region in valid),
        min(region[1] for region in valid),
        max(region[2] for region in valid),
        max(region[3] for region in valid),
    )


def _role(category: str, severity: str) -> str:
    if severity == "critical":
        return "critical"
    if category in {"missing_geometry", "missing_object", "missing_part"}:
        return "missing"
    if category == "extra_geometry":
        return "extra"
    if category.startswith("incorrect_") or category in {"open_polyline", "wrong_layer", "wrong_entity_type", "construction_policy"}:
        return "inaccurate"
    if category in {"endpoint_gap", "disconnected_geometry", "unwanted_intersection", "overlapping_geometry"}:
        return "connectivity"
    return "warning"


def _deduction_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _deduction_contract(
    raw_issue: dict[str, Any], *, is_formative: bool = False
) -> tuple[float | None, float | None, str, str | None]:
    suppression_reason = raw_issue.get("suppression_reason")
    if is_formative or raw_issue.get("deduction_status") == "diagnostic":
        return (
            None,
            None,
            "diagnostic",
            str(suppression_reason) if suppression_reason else None,
        )
    raw = _deduction_number(raw_issue.get("raw_rule_deduction", raw_issue.get("deduction")))
    applied_value = raw_issue.get("final_applied_contribution", raw_issue.get("applied_deduction"))
    applied = raw if applied_value is None else _deduction_number(applied_value)
    if raw_issue.get("deduction_status"):
        status = str(raw_issue["deduction_status"])
    elif suppression_reason:
        status = "suppressed"
    elif applied < raw:
        status = "capped"
    elif applied > 0:
        status = "applied"
    else:
        status = "none"
    return raw, applied, status, str(suppression_reason) if suppression_reason else None


def _location_region(location: Any) -> tuple[float, float, float, float] | None:
    if isinstance(location, (list, tuple)) and len(location) >= 2 and _finite(location[0]) and _finite(location[1]):
        x, y = float(location[0]), float(location[1])
        return (x, y, x, y)
    return None


def _explicit_region(region: Any) -> tuple[float, float, float, float] | None:
    if (
        isinstance(region, (list, tuple))
        and len(region) == 4
        and all(_finite(value) for value in region)
    ):
        return tuple(float(value) for value in region)
    return None


def _measurement_region(measurement: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(measurement, dict):
        return None
    return _explicit_region(measurement.get("region"))


def _validation_key(finding: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(finding.get("severity", "")),
        str(finding.get("code", "")),
        str(finding.get("entity_id", "")),
        json.dumps(finding.get("location"), sort_keys=True, default=str),
        str(finding.get("message", "")),
    )


ROLE_BADGE_PREFIXES: dict[str, str] = {
    "missing": "M",
    "extra": "E",
    "inaccurate": "I",
    "connectivity": "C",
    "warning": "W",
    "critical": "X",
    "reference": "V",
}


def assign_badge_labels(issues: list[ReviewedIssue]) -> list[ReviewedIssue]:
    """Assign compact, deterministic badge labels (M1, E1, I1, C1, etc.) per visual role."""
    counts: dict[str, int] = {}
    used_labels: set[str] = {iss.badge_label for iss in issues if iss.badge_label}
    seen_prelabelled: set[str] = set()
    result: list[ReviewedIssue] = []
    sorted_issues = sorted(issues, key=lambda iss: iss.issue_id)
    for issue in sorted_issues:
        if issue.badge_label and issue.badge_label not in seen_prelabelled:
            seen_prelabelled.add(issue.badge_label)
            result.append(issue)
            continue
        if issue.provenance == "reference_validation" or issue.category.startswith("reference_"):
            prefix = "V"
        else:
            role = issue.visual_role
            prefix = ROLE_BADGE_PREFIXES.get(role, role[:1].upper() if role else "B")
        while True:
            counts[prefix] = counts.get(prefix, 0) + 1
            badge = f"{prefix}{counts[prefix]}"
            if badge not in used_labels:
                used_labels.add(badge)
                seen_prelabelled.add(badge)
                break
        result.append(replace(issue, badge_label=badge))
    return result


def build_reviewed_drawing(
    reference: Drawing,
    student: Drawing,
    comparison: dict[str, Any],
    validation: dict[str, Any] | None = None,
) -> ReviewedDrawing:
    """Build a detached review snapshot without mutating any input object."""

    reference_entities = tuple(sorted((_snapshot(entity, "reference") for entity in reference.entities), key=lambda item: item.entity_id))
    student_entities = tuple(sorted((_snapshot(entity, "student") for entity in student.entities), key=lambda item: item.entity_id))
    reference_by_id = {entity.entity_id: entity for entity in reference_entities}
    student_by_id = {entity.entity_id: entity for entity in student_entities}
    assessment_objects_by_id = {
        obj["object_id"]: obj
        for obj in comparison.get("assessment_objects", [])
        if isinstance(obj, dict) and "object_id" in obj
    }
    object_translations: dict[str, tuple[float, float]] = (
        comparison.get("object_translations") or {}
    )
    ref_entity_to_translation: dict[str, tuple[float, float]] = {}
    canonical_comp_by_id: dict[str, dict[str, Any]] = {}
    source_eid_comp_count: dict[str, int] = {}
    for obj in comparison.get("assessment_objects", []):
        oid = obj.get("object_id")
        tx = object_translations.get(oid, (0.0, 0.0))
        for eid in obj.get("source_entity_ids", []):
            ref_entity_to_translation[str(eid)] = tx
        for comp in obj.get("components", []) if isinstance(obj, dict) else []:
            if isinstance(comp, dict) and comp.get("id"):
                canonical_comp_by_id[str(comp["id"])] = comp
                seid = str(comp.get("source_entity_id") or "")
                if seid:
                    source_eid_comp_count[seid] = source_eid_comp_count.get(seid, 0) + 1

    def _component_to_reviewed_entity(comp: dict[str, Any]) -> ReviewedEntity | None:
        ckind = str(comp.get("kind") or "")
        cid = str(comp.get("id") or "")
        clayer = str(comp.get("layer") or "0")
        cbbox = comp.get("bbox")
        bbox_t = (
            tuple(float(v) for v in cbbox)
            if isinstance(cbbox, (list, tuple)) and len(cbbox) == 4 and all(_finite(v) for v in cbbox)
            else None
        )
        if ckind == "segment" and comp.get("start") and comp.get("end"):
            s_pt, e_pt = comp["start"], comp["end"]
            return ReviewedEntity(
                entity_id=cid,
                source="reference",
                kind="line",
                layer=clayer,
                points=((float(s_pt[0]), float(s_pt[1])), (float(e_pt[0]), float(e_pt[1]))),
                radius=None,
                start_angle=None,
                end_angle=None,
                closed=False,
                text=None,
                bbox=bbox_t,
                properties_json="{}",
            )
        if ckind in {"circle", "arc"} and comp.get("center") and _finite(comp.get("radius")):
            c_pt = comp["center"]
            return ReviewedEntity(
                entity_id=cid,
                source="reference",
                kind=ckind,
                layer=clayer,
                points=((float(c_pt[0]), float(c_pt[1])),),
                radius=float(comp["radius"]),
                start_angle=float(comp["start_angle"]) if _finite(comp.get("start_angle")) else None,
                end_angle=float(comp["end_angle"]) if _finite(comp.get("end_angle")) else None,
                closed=(ckind == "circle"),
                text=None,
                bbox=bbox_t,
                properties_json="{}",
            )
        return None

    is_formative = (
        comparison.get("assessment_mode") == "formative"
        or (comparison.get("rubric_application") or {}).get("assessment_mode")
        == "formative"
    )
    missing_diags_by_obj: dict[str, list[ReviewedEntity]] = {}
    for raw in comparison.get("issues", []):
        if (
            isinstance(raw, dict)
            and str(raw.get("category") or "") == "missing_geometry"
            and raw.get("parent_object_id")
            and raw.get("component_id")
        ):
            comp = canonical_comp_by_id.get(str(raw["component_id"]))
            if (
                isinstance(comp, dict)
                and str(comp.get("kind") or "") == "segment"
                and comp.get("start")
                and comp.get("end")
            ):
                s_pt, e_pt = comp["start"], comp["end"]
                if abs(float(e_pt[0]) - float(s_pt[0])) > 1e-2 and abs(float(e_pt[1]) - float(s_pt[1])) > 1e-2:
                    diag_rev = _component_to_reviewed_entity(comp)
                    if diag_rev is not None:
                        missing_diags_by_obj.setdefault(str(raw["parent_object_id"]), []).append(diag_rev)

    reviewed_issues: list[ReviewedIssue] = []

    for index, raw in enumerate(comparison.get("issues", []), 1):
        raw_issue = deepcopy(raw)
        issue_id = str(raw_issue.get("error_id") or raw_issue.get("id") or f"E-{index:03d}")
        category = str(raw_issue.get("category") or "warning")
        severity = str(raw_issue.get("severity") or "warning")
        source_id = raw_issue.get("student_entity_id")
        expected_id = raw_issue.get("reference_entity_id")
        parent_object_id = raw_issue.get("parent_object_id")
        component_id = raw_issue.get("component_id")
        actual = student_by_id.get(str(source_id)) if source_id is not None else None
        full_expected_ref = reference_by_id.get(str(expected_id)) if expected_id is not None else None
        expected = full_expected_ref
        if (
            component_id
            and str(component_id) in canonical_comp_by_id
            and source_eid_comp_count.get(str(expected_id), 0) > 1
        ):
            comp_rev = _component_to_reviewed_entity(canonical_comp_by_id[str(component_id)])
            if comp_rev is not None:
                expected = comp_rev
        expected_geoms: list[ReviewedEntity] = []
        is_obj_level = (
            raw_issue.get("code") == "MISSING_OBJECT"
            or (
                (raw_issue.get("code") == "INCORRECT_POSITION" or category == "incorrect_position")
                and not raw_issue.get("component_id")
            )
        )
        if is_obj_level and parent_object_id:
            source_eids = (raw_issue.get("measurement") or {}).get("source_entity_ids") or []
            if not source_eids and parent_object_id in assessment_objects_by_id:
                source_eids = assessment_objects_by_id[parent_object_id].get("source_entity_ids") or []
            for eid in source_eids:
                if str(eid) in reference_by_id and reference_by_id[str(eid)] not in expected_geoms:
                    expected_geoms.append(reference_by_id[str(eid)])
        elif category == "ambiguous_geometry":
            meas = raw_issue.get("measurement") or {}
            derived = raw_issue.get("derived_evidence") or []
            amb_ref_eids = (
                meas.get("reference_entity_ids")
                or (derived[0].get("reference_entity_ids") if derived else [])
                or []
            )
            for eid in amb_ref_eids:
                if str(eid) in reference_by_id and reference_by_id[str(eid)] not in expected_geoms:
                    expected_geoms.append(reference_by_id[str(eid)])
        if not expected_geoms and expected is not None:
            expected_geoms = [expected]
            if (
                component_id
                and full_expected_ref is not None
                and full_expected_ref is not expected
                and full_expected_ref.kind == "polyline"
                and full_expected_ref.closed
                and category != "missing_geometry"
            ):
                expected_geoms.append(full_expected_ref)
            if (
                category == "incorrect_length"
                and parent_object_id
                and expected.kind == "line"
                and len(expected.points) >= 2
            ):
                exp_pts = (expected.points[0], expected.points[-1])
                seen_ids = {g.entity_id for g in expected_geoms}
                for diag_ent in missing_diags_by_obj.get(str(parent_object_id), []):
                    if diag_ent.entity_id in seen_ids or len(diag_ent.points) < 2:
                        continue
                    diag_pts = (diag_ent.points[0], diag_ent.points[-1])
                    if any(
                        math.hypot(ep[0] - dp[0], ep[1] - dp[1]) <= 1e-2
                        for ep in exp_pts
                        for dp in diag_pts
                    ):
                        expected_geoms.append(diag_ent)
                        seen_ids.add(diag_ent.entity_id)
        actual_geoms: list[ReviewedEntity] = [actual] if actual is not None else []
        if is_obj_level and parent_object_id:
            stu_eids = (raw_issue.get("measurement") or {}).get("student_entity_ids") or []
            for eid in stu_eids:
                if str(eid) in student_by_id and student_by_id[str(eid)] not in actual_geoms:
                    actual_geoms.append(student_by_id[str(eid)])
        elif category == "ambiguous_geometry":
            meas = raw_issue.get("measurement") or {}
            derived = raw_issue.get("derived_evidence") or []
            amb_stu_eids = (
                meas.get("student_entity_ids")
                or meas.get("candidate_student_entity_ids")
                or (derived[0].get("candidate_student_entity_ids") if derived else [])
                or []
            )
            for eid in amb_stu_eids:
                if str(eid) in student_by_id and student_by_id[str(eid)] not in actual_geoms:
                    actual_geoms.append(student_by_id[str(eid)])

        dx, dy = (0.0, 0.0)
        if parent_object_id and parent_object_id in object_translations:
            dx, dy = object_translations[parent_object_id]
        elif expected_id and str(expected_id) in ref_entity_to_translation:
            dx, dy = ref_entity_to_translation[str(expected_id)]

        rubric_app = comparison.get("rubric_application") or {}
        norm_student = (comparison.get("normalization") or {}).get("student") or {}
        norm_mode = str(
            rubric_app.get("normalization_mode") or norm_student.get("mode") or ""
        ).strip().lower()
        translate_expected = (category != "incorrect_position") or (
            not is_obj_level and norm_mode != "strict"
        )

        if translate_expected:
            if (dx or dy) and expected_geoms:
                expected_geoms = [_translate_reviewed_entity(eg, dx, dy) for eg in expected_geoms]
            if (dx or dy) and expected:
                expected = _translate_reviewed_entity(expected, dx, dy)

        visual_role = _role(category, severity)
        obj_bbox = None
        if parent_object_id and parent_object_id in assessment_objects_by_id:
            raw_obbox = assessment_objects_by_id[parent_object_id].get("bbox")
            if raw_obbox and len(raw_obbox) == 4 and all(_finite(v) for v in raw_obbox):
                obj_shift_x = dx if translate_expected else 0.0
                obj_shift_y = dy if translate_expected else 0.0
                obj_bbox = (
                    round(float(raw_obbox[0]) + obj_shift_x, 6),
                    round(float(raw_obbox[1]) + obj_shift_y, 6),
                    round(float(raw_obbox[2]) + obj_shift_x, 6),
                    round(float(raw_obbox[3]) + obj_shift_y, 6),
                )

        meas = raw_issue.get("measurement") or {}
        in_student_frame = (
            isinstance(meas, dict) and meas.get("coordinate_frame") == "student"
        )
        raw_loc = raw_issue.get("location")
        shifted_loc = raw_loc
        if raw_loc and isinstance(raw_loc, (list, tuple)) and len(raw_loc) >= 2:
            if category == "incorrect_position" or in_student_frame:
                shifted_loc = raw_loc
            elif actual and len(actual.bbox or ()) == 4 and (actual.bbox[0] - 10 <= raw_loc[0] <= actual.bbox[2] + 10 and actual.bbox[1] - 10 <= raw_loc[1] <= actual.bbox[3] + 10):
                shifted_loc = raw_loc
            elif dx or dy:
                shifted_loc = (
                    round(float(raw_loc[0]) + dx, 6),
                    round(float(raw_loc[1]) + dy, 6),
                )

        if visual_role == "connectivity":
            meas_reg = _measurement_region(meas) or _explicit_region(raw_issue.get("region"))
            if meas_reg:
                region = meas_reg
            else:
                raw_pts = meas.get("actual_points") or []
                pts = []
                for p in raw_pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        px, py = float(p[0]), float(p[1])
                        if in_student_frame:
                            pts.append((px, py))
                        elif actual and len(actual.bbox or ()) == 4 and (actual.bbox[0] - 25 <= px <= actual.bbox[2] + 25 and actual.bbox[1] - 25 <= py <= actual.bbox[3] + 25):
                            pts.append((px, py))
                        else:
                            pts.append((px + dx, py + dy))
                if not pts and shifted_loc:
                    pts.append(shifted_loc)
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    pad = 4.0
                    region = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
                else:
                    region = _location_region(shifted_loc)
        else:
            geom_bboxes = [g.bbox for g in expected_geoms if g.bbox] + [g.bbox for g in actual_geoms if g.bbox]
            if geom_bboxes:
                region = _union_regions(
                    obj_bbox if raw_issue.get("code") == "MISSING_OBJECT" else None,
                    *geom_bboxes,
                )
            else:
                region = _union_regions(
                    obj_bbox if raw_issue.get("code") == "MISSING_OBJECT" else None,
                    expected.bbox if expected else None,
                    actual.bbox if actual else None,
                    _explicit_region(raw_issue.get("region")),
                    _location_region(shifted_loc),
                )
        raw_deduction, applied_deduction, deduction_status, suppression_reason = _deduction_contract(
            raw_issue, is_formative=is_formative
        )
        is_diag = is_formative or deduction_status == "diagnostic"
        reviewed_issues.append(ReviewedIssue(
            issue_id=issue_id,
            category=category,
            severity=severity,
            visual_role=visual_role,
            source_entity_id=str(source_id) if source_id is not None else None,
            expected_entity_id=str(expected_id) if expected_id is not None else None,
            actual_geometry=actual,
            expected_geometry=expected,
            expected_geometries=tuple(expected_geoms),
            actual_geometries=tuple(actual_geoms),
            category_split=None if is_diag else raw_issue.get("category_split"),
            score_categories=() if is_diag else tuple(raw_issue.get("score_categories") or ()),
            region=region,
            technical_feedback=str(raw_issue.get("technical_feedback") or raw_issue.get("message") or "Review this finding."),
            rubric_rule_id=str(raw_issue["rubric_rule_id"]) if raw_issue.get("rubric_rule_id") is not None else None,
            deduction=applied_deduction,
            raw_deduction=raw_deduction,
            applied_deduction=applied_deduction,
            deduction_status=deduction_status,
            score_category=None if is_diag else raw_issue.get("score_category"),
            raw_rule_deduction=None if is_diag else _deduction_number(raw_issue.get("raw_rule_deduction", raw_deduction)),
            deduction_after_rule_cap=None if is_diag else _deduction_number(raw_issue.get("deduction_after_rule_cap", applied_deduction)),
            deduction_after_category_cap=None if is_diag else _deduction_number(raw_issue.get("deduction_after_category_cap", applied_deduction)),
            final_applied_contribution=None if is_diag else _deduction_number(raw_issue.get("final_applied_contribution", applied_deduction)),
            cap_reason=None if is_diag else raw_issue.get("cap_reason"),
            suppression_reason=suppression_reason,
            confidence=str(raw_issue.get("confidence") or "instructor_review_required"),
            classification=str(raw_issue.get("classification") or "primary"),
            provenance="comparison",
            measurement_json=json.dumps(deepcopy(raw_issue.get("measurement")), sort_keys=True, separators=(",", ":"), default=str),
            correction_guidance_json=json.dumps(deepcopy(raw_issue.get("correction_guidance")), sort_keys=True, separators=(",", ":"), default=str),
            recommended_commands=tuple(str(command) for command in raw_issue.get("recommended_commands", [])),
            parent_object_id=str(parent_object_id) if parent_object_id is not None else None,
            component_id=str(component_id) if component_id is not None else None,
        ))

    findings = sorted(deepcopy((validation or {}).get("findings", [])), key=_validation_key)
    for index, finding in enumerate(findings, 1):
        entity_id = finding.get("entity_id")
        expected = reference_by_id.get(str(entity_id)) if entity_id is not None else None
        severity = str(finding.get("severity") or "warning")
        category = "reference_critical" if severity == "critical" else "reference_warning"
        visual_role = "critical" if severity == "critical" else "reference"
        reviewed_issues.append(ReviewedIssue(
            issue_id=f"V-{index:03d}",
            category=category,
            severity=severity,
            visual_role=visual_role,
            source_entity_id=None,
            expected_entity_id=str(entity_id) if entity_id is not None else None,
            actual_geometry=None,
            expected_geometry=expected,
            region=_union_regions(expected.bbox if expected else None, _location_region(finding.get("location"))),
            technical_feedback=str(finding.get("message") or "Review the reference drawing."),
            rubric_rule_id=None,
            deduction=0.0,
            raw_deduction=0.0,
            applied_deduction=0.0,
            deduction_status="informational",
            score_category=None,
            raw_rule_deduction=0.0,
            deduction_after_rule_cap=0.0,
            deduction_after_category_cap=0.0,
            final_applied_contribution=0.0,
            cap_reason=None,
            suppression_reason=None,
            confidence="verified",
            classification="informational",
            provenance="reference_validation",
            measurement_json="null",
            correction_guidance_json="null",
            recommended_commands=(),
        ))

    reviewed_issues = assign_badge_labels(reviewed_issues)

    ref_regions = [entity.bbox for entity in reference_entities if entity.bbox]
    stu_regions = [entity.bbox for entity in student_entities if entity.bbox]
    reference_extents = _union_regions(*ref_regions) or (0.0, 0.0, 0.0, 0.0)

    aligned_ref_list = []
    for entity in reference_entities:
        dx, dy = ref_entity_to_translation.get(entity.entity_id, (0.0, 0.0))
        if dx or dy:
            aligned_ref_list.append(_translate_reviewed_entity(entity, dx, dy))
        elif entity.entity_id in ref_entity_to_translation:
            aligned_ref_list.append(entity)
    aligned_reference_entities = tuple(aligned_ref_list)

    aligned_issue_regions = []
    for iss in reviewed_issues:
        if iss.visual_role in {"missing", "inaccurate"}:
            for eg in (iss.expected_geometries or ((iss.expected_geometry,) if iss.expected_geometry else ())):
                if eg and eg.bbox:
                    aligned_issue_regions.append(eg.bbox)
    student_extents = _union_regions(*stu_regions, *aligned_issue_regions) or (0.0, 0.0, 0.0, 0.0)

    all_regions = [entity.bbox for entity in reference_entities + student_entities if entity.bbox]
    all_regions.extend(issue.region for issue in reviewed_issues if issue.region)
    extents = _union_regions(*all_regions) or (0.0, 0.0, 0.0, 0.0)
    reference_unsupported = tuple(
        json.dumps({**deepcopy(item), "source": "reference"}, sort_keys=True, separators=(",", ":"), default=str)
        for item in sorted(reference.unsupported_entities, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    )
    student_unsupported = tuple(
        json.dumps({**deepcopy(item), "source": "student"}, sort_keys=True, separators=(",", ":"), default=str)
        for item in sorted(student.unsupported_entities, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    )
    score = comparison.get("score")
    return ReviewedDrawing(
        reference_entities=reference_entities,
        student_entities=student_entities,
        issues=tuple(sorted(reviewed_issues, key=lambda issue: issue.issue_id)),
        reference_unsupported_json=reference_unsupported,
        student_unsupported_json=student_unsupported,
        extents=extents,
        units=str(reference.units),
        score=float(score) if _finite(score) else None,
        aligned_reference_entities=aligned_reference_entities,
        student_extents=student_extents,
        reference_extents=reference_extents,
    )
