from pathlib import Path
from app.compare import compare_drawings
from app.dxf import parse_dxf_path
S=Path(__file__).parents[1]/"samples"
def test_good_scores_full(): assert compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_good.dxf"))["score"]==100
def test_missing_wall_detected(): assert "MISSING_WALL" in {i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_missing_wall.dxf"))["issues"]}
def test_door_window_detected():
 c={i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_door_window_errors.dxf"))["issues"]}; assert {"DOOR_SWING","WINDOW_GEOMETRY"}<=c
