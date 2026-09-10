"""Procedural CAD test data. Nothing is read from stored drawings or Git history.

Shapes are built from explicit test specifications, not encoded private drawings.
Generated files live in a process-owned temporary directory outside the repository.
"""
from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
from scripts.generate_samples import make

_TEMP: TemporaryDirectory | None = None


def _document():
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    return doc


def _save(doc, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    doc.write(stream)
    path.write_bytes(stream.getvalue().encode("utf-8"))


def _line(msp, start, length, angle=0, *, layer="GEOMETRY"):
    a = math.radians(angle)
    return msp.add_line(start, (start[0] + length * math.cos(a),
                               start[1] + length * math.sin(a)), dxfattribs={"layer": layer})


def _square(msp, origin=(0, 0), size=100):
    x, y = origin
    corners = [(x,y), (x+size,y), (x+size,y+size), (x,y+size)]
    return [msp.add_line(corners[i], corners[(i+1)%4], dxfattribs={"layer":"GEOMETRY"})
            for i in range(4)]


def _controlled(directory):
    names = [
        "00_reference_000-Simple.dxf", "01_exact_copy_should_score_100.dxf",
        "02_missing_line_73B.dxf", "03_wrong_length_73C_80_units.dxf",
        "04_moved_line_73B_plus20Y.dxf", "05_wrong_angle_73D_40deg.dxf",
        "06_moved_circle_722_plus20X.dxf", "07_wrong_circle_radius_40.dxf",
        "08_extra_line_handle_740.dxf", "09_duplicate_line_73B_handle_741.dxf",
        "10_disconnected_square_corner_5_units.dxf",
    ]
    for variant, name in enumerate(names):
        doc = _document()
        msp = doc.modelspace()
        square = _square(msp)
        # Isolated editable lines; 100-unit baseline length and 30-degree angle.
        missing = _line(msp, (200, 0), 100)
        shortened = _line(msp, (200, 100), 100)
        rotated = _line(msp, (200, 200), 100, 30)
        circle = msp.add_circle((400, 100), 50)
        # Unchanged anchors make local edits distinct from drawing translation.
        for i in range(6):
            _line(msp, (i*120, 400), 40+i*7, 12+i*11)
        for i in range(5):
            msp.add_circle((i*130, 600), 12+i*3)
        assert len(msp) == 19
        if variant == 2:
            msp.delete_entity(missing)
        elif variant == 3:
            shortened.dxf.end = (280, 100)
        elif variant == 4:
            missing.translate(0, 20, 0)
        elif variant == 5:
            rotated.dxf.end = (200+100*math.cos(math.radians(40)),
                               200+100*math.sin(math.radians(40)))
        elif variant == 6:
            circle.translate(20, 0, 0)
        elif variant == 7:
            circle.dxf.radius = 40
        elif variant == 8:
            _line(msp, (150, 250), 43, 70)
        elif variant == 9:
            msp.add_line(missing.dxf.start, missing.dxf.end, dxfattribs={"layer":"GEOMETRY"})
        elif variant == 10:
            square[3].dxf.end = (0, 5)
        _save(doc, directory/name)


def _repeated(directory):
    for name, mode in [
        ("01-ARC-Reference.dxf", "exact"), ("01-ARC-Student-OK.dxf", "exact"),
        ("01-ARC-All-Moved.dxf", "all"), ("01-ARC-TwoOnly-Moved.dxf", "two"),
    ]:
        doc = _document()
        for i in range(3):
            dx, dy = ((30, 0) if mode == "all" else
                      (20, -2) if mode == "two" and i > 0 else (0, 0))
            doc.modelspace().add_arc((i*80+dx, dy), 15, 20, 140)
        _save(doc, directory/name)
    for name, gap in [
        ("02-SQUARE-Reference.dxf", 0), ("02-SQUARE-Student-OK.dxf", 0),
        ("02-SQUARE-Gap-1Unit.dxf", 1), ("02-SQUARE-Gap-3Unit.dxf", 3),
    ]:
        doc = _document()
        sides = _square(doc.modelspace())
        sides[2].translate(0, gap, 0)
        _save(doc, directory/name)
    for prefix, through in [("03-T-Junction", False), ("04-T-Crossing", True)]:
        for suffix in ("Reference", "Student-OK"):
            doc = _document()
            msp = doc.modelspace()
            msp.add_line((0, 0), (100, 0))
            msp.add_line((50, -40 if through else 0), (50, 40))
            _save(doc, directory/f"{prefix}-{suffix}.dxf")


def _ref01(directory):
    for variant in range(-1, 8):
        doc = _document()
        msp = doc.modelspace()
        entities = []
        for x, width, height in [(0, 50, 30), (150, 70, 40)]:
            corners = [(x,0), (x+width,0), (x+width,height), (x,height)]
            entities.extend(msp.add_line(corners[i], corners[(i+1)%4]) for i in range(4))
        entities.append(msp.add_lwpolyline([(0,100),(20,100),(20,110),(0,110)], close=True))
        line = msp.add_line((130,120), (110,135), dxfattribs={"layer":"GEOMETRY"})
        entities.append(line)
        for i in range(6):
            entities.append(msp.add_circle((i*65,250), 5+i*2))
        assert len(entities) == 16
        if variant == 1:
            entities[8].translate(17, 0, 0)
        elif variant == 2:
            for i, ent in enumerate(entities):
                dx, dy = (20,20) if i < 4 else (-30,30) if i < 8 else (-2*i,10+2*i)
                ent.translate(dx, dy, 0)
            entities[8].translate(500, 500, 0)
            # Sub-tolerance vertex noise: strict signatures differ at 6 decimals,
            # while tolerant correspondence (4 decimals) retains the same shape.
            vertices = list(entities[8].get_points("xy"))
            vertices[0] = (vertices[0][0] + 0.00002, vertices[0][1])
            entities[8].set_points(vertices, format="xy")
        elif variant in (3,4):
            for ent in entities[:4 if variant == 3 else 8]:
                ent.translate(20, 20, 0)
        elif variant in (5,6,7):
            length = 35 if variant == 7 else 25
            line.dxf.end = (130+length*math.cos(math.radians(160)),
                            120+length*math.sin(math.radians(160)))
            if variant in (6,7):
                line.translate(5, 5, 0)
        name = "Ref-01.dxf" if variant < 0 else f"Ref-01-t{variant:03}.dxf"
        _save(doc, directory/name)


@lru_cache(maxsize=1)
def data_root() -> Path:
    global _TEMP
    _TEMP = TemporaryDirectory(prefix="draftlens-synthetic-")
    root = Path(_TEMP.name).resolve()
    repo = Path(__file__).resolve().parents[1]
    if root == repo or repo in root.parents:
        raise RuntimeError("Synthetic CAD data must be outside the repository.")
    samples = root/"samples"
    samples.mkdir()
    make(samples/"reference.dxf")
    make(samples/"student_good.dxf")
    make(samples/"student_missing_wall.dxf", missing_wall=True)
    make(samples/"student_door_window_errors.dxf", bad_door=True, bad_window=True)
    _controlled(root/"fixtures"/"simple_audit")
    _repeated(root/"fixtures"/"simple_audit-II")
    _ref01(root/"fixtures"/"ref_01")
    return root


def samples_root() -> Path:
    return data_root()/"samples"


def fixture_root() -> Path:
    return data_root()/"fixtures"
