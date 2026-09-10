import argparse
import io
from pathlib import Path

import ezdxf


ROOT = Path(__file__).resolve().parents[1]


def make(path: Path, *, missing_wall=False, bad_door=False, bad_window=False):
    path = Path(path).resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Generated test files must be outside the repository.")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    stream = io.StringIO()
    doc.write(stream)
    path.write_bytes(stream.getvalue().encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic DXF demonstrations outside the repository.")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        make(args.output_dir / "reference.dxf")
        make(args.output_dir / "student_good.dxf")
        make(args.output_dir / "student_missing_wall.dxf", missing_wall=True)
        make(args.output_dir / "student_door_window_errors.dxf", bad_door=True, bad_window=True)
    except (ValueError, OSError):
        parser.exit(1, "Generation failed: use a writable directory outside the repository.\n")
    print("Created four synthetic DXF files outside the repository.")
