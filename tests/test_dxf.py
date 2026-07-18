from pathlib import Path

from app.dxf import entity_length, parse_dxf_path


SAMPLES = Path(__file__).parents[1] / "samples"


def test_parses_and_normalizes_reference():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf")
    assert drawing.bbox[0:2] == (0.0, 0.0)
    assert {e.kind for e in drawing.entities} >= {"line", "arc", "text", "dimension"}
    assert all(x >= 0 and y >= 0 for e in drawing.entities for x, y in e.points)


def test_preserves_scale():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf")
    wall = next(e for e in drawing.entities if e.layer == "WALLS")
    assert entity_length(wall) == 100
