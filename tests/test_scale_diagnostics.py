from __future__ import annotations

from app.models import Drawing, Entity
from app.scale_diagnostics import diagnose_uniform_scale


def _line(entity_id: str, start: tuple[float, float], end: tuple[float, float]) -> Entity:
    return Entity(
        id=entity_id,
        kind="line",
        layer="0",
        points=[start, end],
        centroid=((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
        bbox=(min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1])),
    )


def _plan(scale: float = 1.0) -> Drawing:
    entities = [
        _line("A", (0, 0), (10 * scale, 0)),
        _line("B", (10 * scale, 0), (10 * scale, 6 * scale)),
        _line("C", (10 * scale, 6 * scale), (0, 6 * scale)),
        _line("D", (0, 6 * scale), (0, 0)),
    ]
    return Drawing(entities=entities, bbox=(0, 0, 10 * scale, 6 * scale))


def test_uniform_scale_factor_fifty_is_diagnosed_without_mutation():
    reference = _plan()
    student = _plan(50)
    before = student.to_dict()
    result = diagnose_uniform_scale(reference, student)
    assert result.detected_scale_mismatch is True
    assert result.estimated_scale_factor == 50
    assert result.scale_support_count == 4
    assert result.scale_support_ratio == 1
    assert result.scale_confidence == "verified"
    assert student.to_dict() == before


def test_near_one_scale_and_local_resize_are_not_global_mismatches():
    assert diagnose_uniform_scale(_plan(), _plan(1.01)).detected_scale_mismatch is False
    local = _plan()
    local.entities[0] = _line("A", (0, 0), (8, 0))
    assert diagnose_uniform_scale(_plan(), local).detected_scale_mismatch is False


def test_too_little_geometry_is_not_promoted_to_global_scale():
    reference = Drawing([_line("A", (0, 0), (10, 0))], (0, 0, 10, 0))
    student = Drawing([_line("A", (0, 0), (500, 0))], (0, 0, 500, 0))
    result = diagnose_uniform_scale(reference, student)
    assert result.detected_scale_mismatch is False
    assert result.scale_confidence == "insufficient_evidence"
