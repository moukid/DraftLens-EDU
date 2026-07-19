from __future__ import annotations
import io, math
from pathlib import Path
import ezdxf
from ezdxf.lldxf.const import DXFStructureError
from .models import Drawing, Entity

class DXFParseError(ValueError):
    pass

UNITS = {0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
SUPPORTED = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "TEXT", "MTEXT", "DIMENSION"}

def _xy(value):
    return round(float(value[0]), 6), round(float(value[1]), 6)

def _canonical_polyline(points, closed):
    pts = [tuple(p) for p in points]
    if not pts:
        return pts
    if closed:
        variants = []
        for seq in (pts, list(reversed(pts))):
            start = min(range(len(seq)), key=lambda i: seq[i])
            variants.append(seq[start:] + seq[:start])
        return min(variants)
    return min(pts, list(reversed(pts)))

def _finish(entity):
    xs = [p[0] for p in entity.points]
    ys = [p[1] for p in entity.points]
    if entity.kind in {"circle", "arc"} and entity.radius is not None:
        x, y = entity.points[0]
        entity.bbox = (x-entity.radius, y-entity.radius, x+entity.radius, y+entity.radius)
        entity.centroid = (x, y)
    elif xs:
        entity.bbox = (min(xs), min(ys), max(xs), max(ys))
        entity.centroid = (sum(xs)/len(xs), sum(ys)/len(ys))
    return entity

def parse_dxf_bytes(data: bytes, source: str = "reference", normalize: bool = True) -> Drawing:
    if not data:
        raise DXFParseError("The uploaded DXF is empty.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DXFParseError("The DXF must be an ASCII DXF file.")
    try:
        doc = ezdxf.read(io.StringIO(text, newline=None))
    except (DXFStructureError, ValueError, OSError) as exc:
        raise DXFParseError(f"Invalid or unsupported DXF: {exc}") from exc
    entities, unsupported = [], []
    prefix = "R" if source == "reference" else "S"
    for index, raw in enumerate(doc.modelspace(), 1):
        kind = raw.dxftype()
        base = {"id": f"{prefix}-{index:05d}", "layer": str(raw.dxf.layer), "source": source, "source_handle": str(raw.dxf.handle)}
        entity = None
        if kind == "LINE":
            points = sorted([_xy(raw.dxf.start), _xy(raw.dxf.end)])
            entity = Entity(kind="line", points=points, **base)
        elif kind == "LWPOLYLINE":
            points = [_xy(p) for p in raw.get_points("xy")]
            entity = Entity(kind="polyline", points=_canonical_polyline(points, bool(raw.closed)), closed=bool(raw.closed), **base)
        elif kind == "POLYLINE":
            points = [_xy(v.dxf.location) for v in raw.vertices]
            entity = Entity(kind="polyline", points=_canonical_polyline(points, bool(raw.is_closed)), closed=bool(raw.is_closed), properties={"source_type": "POLYLINE"}, **base)
        elif kind == "CIRCLE":
            entity = Entity(kind="circle", points=[_xy(raw.dxf.center)], radius=float(raw.dxf.radius), **base)
        elif kind == "ARC":
            entity = Entity(kind="arc", points=[_xy(raw.dxf.center)], radius=float(raw.dxf.radius), start_angle=float(raw.dxf.start_angle), end_angle=float(raw.dxf.end_angle), **base)
        elif kind == "ELLIPSE":
            major = _xy(raw.dxf.major_axis)
            entity = Entity(kind="ellipse", points=[_xy(raw.dxf.center)], properties={"major_axis": major, "ratio": float(raw.dxf.ratio), "start_param": float(raw.dxf.start_param), "end_param": float(raw.dxf.end_param)}, **base)
        elif kind == "SPLINE":
            tool = raw.construction_tool()
            points = [_xy(p) for p in tool.approximate(40)]
            entity = Entity(kind="spline", points=points, properties={"control_point_count": len(raw.control_points), "sampled": True}, **base)
        elif kind in {"TEXT", "MTEXT"}:
            entity = Entity(kind="text", points=[_xy(raw.dxf.insert)], text=raw.plain_text() if kind == "MTEXT" else str(raw.dxf.text), properties={"source_type": kind}, **base)
        elif kind == "DIMENSION":
            points = [_xy(getattr(raw.dxf, name)) for name in ("defpoint", "defpoint2", "defpoint3") if raw.dxf.hasattr(name)]
            try:
                measurement = float(raw.get_measurement())
            except (ValueError, TypeError, AttributeError):
                measurement = None
            entity = Entity(kind="dimension", points=points, text=str(raw.dxf.text or ""), measurement=measurement, **base)
        else:
            unsupported.append({"entity_type": kind, "handle": str(raw.dxf.handle), "layer": str(raw.dxf.layer)})
        if entity:
            entities.append(_finish(entity))
    if not entities:
        raise DXFParseError("The DXF contains no supported model-space entities.")
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    drawing = normalize_drawing(entities) if normalize else _drawing(entities)
    drawing.units_code, drawing.units = code, UNITS.get(code, f"code-{code}")
    drawing.unsupported_entities = unsupported
    return drawing

def _drawing(entities):
    boxes = [e.bbox for e in entities if e.bbox]
    bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    return Drawing(entities, tuple(round(x, 6) for x in bbox), normalization={"mode": "strict", "translation": [0, 0], "rotation_degrees": 0, "scale": 1})

def parse_dxf_path(path, source="reference", normalize=True):
    return parse_dxf_bytes(Path(path).read_bytes(), source, normalize=normalize)

def normalize_drawing(entities):
    """Preserve absolute geometry while marking translation estimation as pending.

    Translation-tolerant comparison requires both drawings, so it cannot be
    performed safely while parsing one drawing in isolation. The comparison
    layer estimates and applies one student-to-reference transform later.
    """
    drawing = _drawing(entities)
    drawing.normalization = {
        "mode": "translation",
        "translation": [0.0, 0.0],
        "rotation_degrees": 0,
        "scale": 1,
        "support_count": 0,
        "support_ratio": 0.0,
        "confidence": "none",
        "rejection_reason": "pending_pairwise_transform_estimation",
    }
    return drawing

def entity_length(entity):
    if entity.kind == "line" and len(entity.points) == 2:
        return math.dist(*entity.points)
    if entity.kind in {"polyline", "spline"} and len(entity.points) > 1:
        length = sum(math.dist(a,b) for a,b in zip(entity.points, entity.points[1:]))
        return length + (math.dist(entity.points[-1], entity.points[0]) if entity.closed else 0)
    if entity.kind == "circle" and entity.radius is not None:
        return 2*math.pi*entity.radius
    if entity.kind == "arc" and entity.radius is not None:
        return math.radians(((entity.end_angle or 0)-(entity.start_angle or 0))%360)*entity.radius
    return None
