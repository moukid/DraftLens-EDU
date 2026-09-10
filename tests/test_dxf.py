from tests.synthetic_data import fixture_root, samples_root
from pathlib import Path
import io
import ezdxf
import pytest

from app.dxf import DXFParseError, entity_length, parse_dxf_bytes, parse_dxf_path


SAMPLES = samples_root()


def test_translation_parse_preserves_absolute_reference_coordinates():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf")
    assert drawing.bbox == (0.0, -20.0, 100.0, 88.0)
    assert drawing.normalization["mode"] == "translation"
    assert drawing.normalization["translation"] == [0.0, 0.0]
    assert (
        drawing.normalization["rejection_reason"]
        == "pending_pairwise_transform_estimation"
    )
    assert {e.kind for e in drawing.entities} >= {"line", "arc", "text", "dimension"}


def test_strict_parse_preserves_the_same_absolute_coordinates():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf", normalize=False)
    assert drawing.bbox == (0.0, -20.0, 100.0, 88.0)
    assert drawing.normalization["mode"] == "strict"
    assert drawing.normalization["translation"] == [0, 0]


def test_preserves_scale():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf")
    wall = next(e for e in drawing.entities if e.layer == "WALLS")
    assert entity_length(wall) == 100


def test_source_ids_and_units_are_preserved():
    drawing = parse_dxf_path(SAMPLES / "reference.dxf", source="student")
    assert all(entity.id.startswith("S-") for entity in drawing.entities)
    assert drawing.units == "m"
    assert drawing.normalization["scale"] == 1

def _dxf_bytes(document):
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def test_rejects_empty_and_invalid_dxf():
    with pytest.raises(DXFParseError, match="empty"):
        parse_dxf_bytes(b"")
    with pytest.raises(DXFParseError, match="Invalid or unsupported"):
        parse_dxf_bytes(b"not a dxf")


def test_canonicalizes_reversed_line_endpoints_and_reports_unsupported():
    document = ezdxf.new("R2010")
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    modelspace.add_line((10, 0), (0, 0))
    modelspace.add_hatch()
    drawing = parse_dxf_bytes(_dxf_bytes(document))
    line = next(entity for entity in drawing.entities if entity.kind == "line")
    assert line.points == [(0.0, 0.0), (10.0, 0.0)]
    assert drawing.units == "mm"
    assert drawing.unsupported_entities[0]["entity_type"] == "HATCH"
