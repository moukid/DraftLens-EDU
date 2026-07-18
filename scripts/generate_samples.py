from pathlib import Path

import ezdxf


ROOT = Path(__file__).resolve().parents[1] / "samples"


def make(path: Path, *, missing_wall=False, bad_door=False, bad_window=False):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    walls = [((0, 0), (100, 0)), ((100, 0), (100, 80)), ((100, 80), (0, 80)), ((0, 80), (0, 0))]
    for i, (a, b) in enumerate(walls):
        if not (missing_wall and i == 2):
            msp.add_line(a, b, dxfattribs={"layer": "WALLS"})
    msp.add_arc((20, 0), 20, 0, 60 if bad_door else 90, dxfattribs={"layer": "DOORS"})
    x1, x2 = ((60, 78) if bad_window else (55, 75))
    msp.add_line((x1, 80), (x2, 80), dxfattribs={"layer": "WINDOWS"})
    dim = msp.add_linear_dim(base=(50, -12), p1=(0, 0), p2=(100, 0), angle=0, dxfattribs={"layer": "DIMENSIONS"})
    dim.render()
    msp.add_text("Studio plan", dxfattribs={"layer": "NOTES", "height": 3}).set_placement((5, 88))
    doc.saveas(path)


if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    make(ROOT / "reference.dxf")
    make(ROOT / "student_good.dxf")
    make(ROOT / "student_missing_wall.dxf", missing_wall=True)
    make(ROOT / "student_door_window_errors.dxf", bad_door=True, bad_window=True)

