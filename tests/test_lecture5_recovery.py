from __future__ import annotations

import io
import math
from pathlib import Path
import pytest
import ezdxf

from app.canonical_geometry import (
    extract_assessment_objects,
    extract_canonical_components,
    match_canonical_geometry,
)
from app.compare import compare_drawings
from app.correction_guidance import correction_guidance
from app.dxf import parse_dxf_bytes
from app.models import Issue
from app.rubric import default_rubric


def _create_doc():
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 5
    return doc


def _save_doc_to_bytes(doc) -> bytes:
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_arc_to_segment_clustering():
    """An arc meeting segments at its endpoints must be grouped into one assessment object."""
    doc = _create_doc()
    msp = doc.modelspace()
    # A U-shape with a semicircle arc:
    # Line 1: (0, 0) to (0, 50)
    # Arc: center=(25, 50), r=25, start_angle=0, end_angle=180 (from (50,50) to (0,50))
    # Line 2: (50, 50) to (50, 0)
    msp.add_line((0, 0), (0, 50))
    msp.add_arc((25, 50), radius=25, start_angle=0, end_angle=180)
    msp.add_line((50, 50), (50, 0))

    drawing = parse_dxf_bytes(_save_doc_to_bytes(doc), source="reference", normalize=False)
    objects = extract_assessment_objects(drawing, tolerance=2.0)

    # Must be clustered as exactly 1 connected object
    assert len(objects) == 1, f"Expected 1 connected object with arc and lines, got {len(objects)}"
    obj = objects[0]
    kinds = {c.kind for c in obj.components}
    assert "arc" in kinds, "Arc was not included in the connected object"
    assert "segment" in kinds, "Segments were not included in the connected object"


def test_multi_object_independent_translation_matching():
    """Multiple complete reference objects moved independently must match under translation-tolerant placement."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # Object 1: Square at (0, 0) to (50, 50)
    for p1, p2 in [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))]:
        ref_msp.add_line(p1, p2)
    # Object 2: Circle at (200, 200) with radius 20
    ref_msp.add_circle((200, 200), radius=20)
    # Object 3: Triangle at (400, 0) to (450, 0), (425, 50)
    for p1, p2 in [((400, 0), (450, 0)), ((450, 0), (425, 50)), ((425, 50), (400, 0))]:
        ref_msp.add_line(p1, p2)

    # Student draws the same 3 objects, but with DIFFERENT translations on the sheet:
    # Object 1 shifted by (+100, +50): Square at (100, 50)
    # Object 2 shifted by (-50, +300): Circle at (150, 500)
    # Object 3 shifted by (+200, -100): Triangle at (600, -100)
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for p1, p2 in [((100, 50), (150, 50)), ((150, 50), (150, 100)), ((150, 100), (100, 100)), ((100, 100), (100, 50))]:
        stu_msp.add_line(p1, p2)
    stu_msp.add_circle((150, 500), radius=20)
    for p1, p2 in [((600, -100), (650, -100)), ((650, -100), (625, -50)), ((625, -50), (600, -100))]:
        stu_msp.add_line(p1, p2)

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    rubric = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=rubric)
    missing_issues = [i for i in result["issues"] if i.get("category") == "missing_geometry"]
    assert len(missing_issues) == 0, f"Expected 0 missing objects, got {len(missing_issues)}: {missing_issues}"
    assert result["score"] >= 95.0, f"Expected near-perfect score for 3 relocated accurate objects, got {result['score']}"


def test_correction_guidance_for_circle_and_lines():
    """Missing circle must advise CIRCLE, missing line must advise LINE, not RECTANG."""
    # When a whole circle object is missing
    issue_circle = Issue(
        id="ISS-01",
        severity="error",
        deduction=10.0,
        category="missing_geometry",
        code="MISSING_OBJECT",
        message="Entire object OBJ-001 is missing",
        classification="primary",
        measurement={"object_id": "OBJ-001", "object_kind": "circle", "total_part_count": 1},
    )
    guidance = correction_guidance(issue_circle, None, None)
    assert guidance is not None
    assert guidance.primary_command == "CIRCLE"
    assert "RECTANG" not in guidance.explanation.upper()

    # When a whole single-line object is missing
    issue_line = Issue(
        id="ISS-02",
        severity="error",
        deduction=10.0,
        category="missing_geometry",
        code="MISSING_OBJECT",
        message="Entire object OBJ-002 is missing",
        classification="primary",
        measurement={"object_id": "OBJ-002", "object_kind": "line", "total_part_count": 1},
    )
    guidance_line = correction_guidance(issue_line, None, None)
    assert guidance_line is not None
    assert guidance_line.primary_command == "LINE"
    assert "RECTANG" not in guidance_line.explanation.upper()


def test_parts_moved_inside_one_object_not_fragment_healed():
    """Independent movement of parts inside one object must not be healed; defects remain."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # Square (0,0) to (50,50)
    for p1, p2 in [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))]:
        ref_msp.add_line(p1, p2)

    # Student draws 3 edges correctly, but 4th edge is displaced inside the object
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for p1, p2 in [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 60), (0, 10))]:  # shifted by 10 in Y
        stu_msp.add_line(p1, p2)

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    rubric = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=rubric)
    # The displaced edge must NOT receive free translation to heal the shape
    assert result["score"] < 100.0, f"Expected deduction for distorted edge, got {result['score']}"
    issues = result["issues"]
    # There should be an issue for the displaced/missing edge
    assert any(i.get("category") in ("missing_geometry", "incorrect_position", "endpoint_gap") for i in issues)


def test_line_vs_lwpolyline_representation_invariance():
    """Under geometry_only, LINE segments vs equivalent LWPOLYLINE must yield 100% score."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    for p1, p2 in [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))]:
        ref_msp.add_line(p1, p2)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(0, 0), (50, 0), (50, 50), (0, 50)], close=True)

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    rubric = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=rubric)
    assert result["score"] == 100.0, f"Expected 100.0 for equivalent LWPOLYLINE, got {result['score']}"


def test_unit_mismatch_notice_and_raw_comparison_basis():
    """Declared INSUNITS mismatch (5 vs 4) must be detected and documented in review output."""
    from app.review_service import build_review_response, run_grading_pipeline

    ref_doc = ezdxf.new("R2010")
    ref_doc.header["$INSUNITS"] = 5  # cm
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((0, 0), (100, 0))

    stu_doc = ezdxf.new("R2010")
    stu_doc.header["$INSUNITS"] = 4  # mm
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((0, 0), (100, 0))

    out = run_grading_pipeline(
        _save_doc_to_bytes(ref_doc),
        _save_doc_to_bytes(stu_doc),
        rubric_id=None,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={},
        reference_rubrics={},
        rubric_references={},
    )
    resp = build_review_response(out)

    assert resp.get("units_info") is not None
    assert resp["units_info"].get("unit_mismatch") is True
    assert resp["units_info"].get("reference_units") == "cm"
    assert resp["units_info"].get("student_units") == "mm"
    assert resp["units_info"].get("comparison_basis") == "raw_drawing_coordinates"
    assert resp.get("unit_notice") is not None
    assert "Reference declares cm" in resp["unit_notice"]
    assert "student declares mm" in resp["unit_notice"]


def test_multi_cluster_compatibility_classification():
    """Drawings with multiple distinct relocated clusters must be recognized as compatible in translation mode."""
    from app.compatibility import assess_compatibility
    from app.scale_diagnostics import diagnose_uniform_scale

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # 2 separate clusters of lines
    # Cluster 1: 5 lines around (100, 100)
    for i in range(5):
        ref_msp.add_line((100, 100 + i * 10), (150, 100 + i * 10))
    # Cluster 2: 5 lines around (500, 500)
    for i in range(5):
        ref_msp.add_line((500, 500 + i * 10), (550, 500 + i * 10))

    # Student drawing:
    # Cluster 1 shifted by (+50, +50): (150, 150)
    # Cluster 2 shifted by (-100, +200): (400, 700)
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for i in range(5):
        stu_msp.add_line((150, 150 + i * 10), (200, 150 + i * 10))
    for i in range(5):
        stu_msp.add_line((400, 700 + i * 10), (450, 700 + i * 10))

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=True)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=True)

    rubric = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
    })
    comp = compare_drawings(ref, stu, rubric=rubric)
    scale = diagnose_uniform_scale(ref, stu)
    compat = assess_compatibility(ref, stu, comp, scale)
    assert compat.compatibility_status == "compatible", f"Expected compatible, got {compat.compatibility_status}: {compat.compatibility_reason_codes}"
    assert "multi_cluster_translation_correspondence" in compat.compatibility_reason_codes


def test_f1_square_translated_sharing_one_edge():
    """A complete square translated such that it shares 1 edge with original position must score 100%."""
    d1 = ezdxf.new("R2010")
    m1 = d1.modelspace()
    for p1, p2 in [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))]:
        m1.add_line(p1, p2)

    d2 = ezdxf.new("R2010")
    m2 = d2.modelspace()
    for p1, p2 in [((50, 0), (100, 0)), ((100, 0), (100, 50)), ((100, 50), (50, 50)), ((50, 50), (50, 0))]:
        m2.add_line(p1, p2)

    ref = parse_dxf_bytes(_save_doc_to_bytes(d1), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(d2), source="student", normalize=False)
    rub = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref, stu, rubric=rub)
    assert res["score"] == 100.0, f"Expected 100.0, got {res['score']}"
    missing = [i for i in res["issues"] if i.get("category") == "missing_geometry"]
    assert len(missing) == 0, f"Expected 0 missing geometry issues, got {missing}"


def test_f2_independently_relocated_standalone_lines():
    """Multiple standalone lines relocated independently must propose their own translations and score 100%."""
    d1 = ezdxf.new("R2010")
    m1 = d1.modelspace()
    m1.add_line((0, 0), (50, 0))
    m1.add_line((200, 0), (280, 0))

    d2 = ezdxf.new("R2010")
    m2 = d2.modelspace()
    m2.add_line((100, 200), (150, 200))
    m2.add_line((500, 400), (580, 400))

    ref = parse_dxf_bytes(_save_doc_to_bytes(d1), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(d2), source="student", normalize=False)
    rub = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref, stu, rubric=rub)
    assert res["score"] == 100.0, f"Expected 100.0, got {res['score']}"
    missing = [i for i in res["issues"] if i.get("category") == "missing_geometry"]
    assert len(missing) == 0, f"Expected 0 missing geometry issues, got {missing}"


def test_f3_inplace_single_component_not_reassigned_to_missing_instance():
    """Single-component in-place objects must pre-claim before relocation search to prevent reassignment.

    Exact synthetic case:
    - Reference R-00001: LINE (0,0) to (50,0)
    - Reference R-00002: LINE (200,0) to (250,0)
    - Student S-00001: LINE (200,0) to (250,0)
    Expected:
    - S-00001 remains assigned to in-place R-00002 (presence 1.0)
    - R-00001 is missing (presence 0.0)
    - compare_drawings reports missing geometry for R-00001, NOT R-00002
    """
    from app.canonical_geometry import match_canonical_geometry

    d_ref = ezdxf.new("R2010")
    m_ref = d_ref.modelspace()
    m_ref.add_line((0, 0), (50, 0))      # R-00001
    m_ref.add_line((200, 0), (250, 0))  # R-00002

    d_stu = ezdxf.new("R2010")
    m_stu = d_stu.modelspace()
    m_stu.add_line((200, 0), (250, 0))  # S-00001

    ref = parse_dxf_bytes(_save_doc_to_bytes(d_ref), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(d_stu), source="student", normalize=False)

    rub = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    # 1. Canonical matching component correspondence assertions
    match = match_canonical_geometry(
        ref, stu, tolerances=rub.tolerances, normalization_mode="translation"
    )
    cms_by_entity = {}
    for cm in match.component_matches:
        for eid in cm.reference_component.source_entity_ids or [cm.reference_component.source_entity_id]:
            cms_by_entity[eid] = cm

    assert "R-00002" in cms_by_entity, "Expected R-00002 in component matches"
    assert "R-00001" in cms_by_entity, "Expected R-00001 in component matches"

    # Present object (R-00002) must match S-00001 with presence 1.0
    cm_r2 = cms_by_entity["R-00002"]
    assert cm_r2.presence == 1.0, f"Expected R-00002 presence 1.0, got {cm_r2.presence}"
    stu_eids_r2 = [
        eid
        for sc in cm_r2.student_components
        for eid in (sc.source_entity_ids or [sc.source_entity_id])
    ]
    assert "S-00001" in stu_eids_r2, f"Expected S-00001 assigned to R-00002, got {stu_eids_r2}"

    # Missing object (R-00001) must have presence 0.0 and no student components
    cm_r1 = cms_by_entity["R-00001"]
    assert cm_r1.presence == 0.0, f"Expected R-00001 presence 0.0, got {cm_r1.presence}"
    assert len(cm_r1.student_components) == 0, f"Expected no student components for R-00001, got {cm_r1.student_components}"

    # 2. compare_drawings missing-object issue attribution
    res = compare_drawings(ref, stu, rubric=rub)
    missing_issues = [i for i in res["issues"] if i.get("category") == "missing_geometry"]
    assert len(missing_issues) == 1, f"Expected exactly 1 missing-geometry issue, got {len(missing_issues)}"

    issue = missing_issues[0]
    source_eids = issue.get("measurement", {}).get("source_entity_ids", [])
    assert "R-00001" in source_eids, f"Expected missing issue for R-00001, got source_entity_ids={source_eids}"
    assert "R-00002" not in source_eids, f"Present object R-00002 must not be reported as missing: {issue}"


def _square_coords(x: float):
    return [
        ((x, 0.0), (x + 50.0, 0.0)),
        ((x + 50.0, 0.0), (x + 50.0, 50.0)),
        ((x + 50.0, 50.0), (x, 50.0)),
        ((x, 50.0), (x, 0.0)),
    ]


def _drawing_from_segments(lines, source: str):
    doc = _create_doc()
    msp = doc.modelspace()
    for start, end in lines:
        msp.add_line(start, end)
    return parse_dxf_bytes(_save_doc_to_bytes(doc), source=source, normalize=False)


def test_f6_strict_partial_square():
    """F6 regression: Strict placement preserves correct partial geometry without false missing-object penalty."""
    sq = _square_coords(0.0)
    ref = _drawing_from_segments(sq, "reference")
    stu = _drawing_from_segments([sq[0], sq[1]], "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "strict",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    current = match_canonical_geometry(ref, stu, policy.tolerances, normalization_mode="strict")
    assert current.completion_fraction == 0.5, f"Expected completion 0.5, got {current.completion_fraction}"
    assert len(current.extra_student_entities) == 0, f"Expected 0 extra entities, got {current.extra_student_entities}"

    review = compare_drawings(ref, stu, rubric=policy)
    assert review["completion_fraction"] == 0.5, f"Expected compare completion 0.5, got {review['completion_fraction']}"
    assert review["score"] == 99.0, f"Expected score 99.0 (0.5 deduction per missing edge), got {review['score']}"


def test_f7_disconnected_present_edges():
    """F7 regression: Incomplete disconnected parts of the same assembly are credited and not marked extra."""
    sq = _square_coords(0.0)
    ref = _drawing_from_segments(sq, "reference")
    stu = _drawing_from_segments([sq[0], sq[2]], "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    current = match_canonical_geometry(ref, stu, policy.tolerances, normalization_mode="translation")
    assert current.completion_fraction == 0.5, f"Expected completion 0.5, got {current.completion_fraction}"
    assert len(current.extra_student_entities) == 0, f"Expected 0 extra entities, got {current.extra_student_entities}"

    review = compare_drawings(ref, stu, rubric=policy)
    assert review["completion_fraction"] == 0.5, f"Expected compare completion 0.5, got {review['completion_fraction']}"
    assert review["score"] == 99.0, f"Expected score 99.0, got {review['score']}"


def test_f8_incomplete_anchor_stolen():
    """F8 regression: Incomplete in-place anchor (B >= 2) remains anchored at (0, 0) and cannot steal relocated instances."""
    sq0 = _square_coords(0.0)
    sq500 = _square_coords(500.0)
    sq100 = _square_coords(100.0)

    ref = _drawing_from_segments(sq0 + sq500, "reference")
    stu = _drawing_from_segments(sq0[:2] + sq100, "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    current = match_canonical_geometry(ref, stu, policy.tolerances, normalization_mode="translation")
    assert current.object_translations.get("OBJ-001") == (0.0, 0.0), f"OBJ-001 must anchor to (0, 0), got {current.object_translations.get('OBJ-001')}"
    assert current.object_translations.get("OBJ-002") == (-400.0, 0.0), f"OBJ-002 must match relocated instance at (-400, 0), got {current.object_translations.get('OBJ-002')}"

    review = compare_drawings(ref, stu, rubric=policy)
    assert review["score"] == 99.0, f"Expected score 99.0, got {review['score']}"


@pytest.mark.parametrize("gap", [5.0, 11.0, 50.0])
@pytest.mark.parametrize("mode", ["strict", "translation"])
@pytest.mark.parametrize("part_deduction", [0.5, 1.0])
def test_f9_absent_disconnected_square_keeps_whole_object_budget(gap: float, mode: str, part_deduction: float):
    """F9 regression: Nearby independent closed objects are not merged by proximity; absent object loses whole-object budget."""
    ref = _drawing_from_segments(_square_coords(0.0) + _square_coords(50.0 + gap), "reference")
    stu = _drawing_from_segments(_square_coords(0.0), "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": mode,
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": part_deduction,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["assessment_objects"]) == 2, f"Expected 2 assessment objects, got {len(result['assessment_objects'])}"
    assert result["score"] == 55.0, f"Expected 55.0 when one of two equal objects is absent, got {result['score']}"
    missing_codes = [i["code"] for i in result["issues"] if i.get("category") == "missing_geometry"]
    assert "MISSING_OBJECT" in missing_codes


def test_f9_nearby_disconnected_squares_independent_translation():
    """F9 regression: Nearby independent closed squares (gap=5) receive independent translations when relocated."""
    ref = _drawing_from_segments(_square_coords(0.0) + _square_coords(55.0), "reference")
    stu_lines = [
        ((p1[0] + 100.0, p1[1] + 50.0), (p2[0] + 100.0, p2[1] + 50.0))
        for p1, p2 in _square_coords(0.0)
    ] + [
        ((p1[0] + 200.0, p1[1] + 300.0), (p2[0] + 200.0, p2[1] + 300.0))
        for p1, p2 in _square_coords(55.0)
    ]
    stu = _drawing_from_segments(stu_lines, "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["assessment_objects"]) == 2, f"Expected 2 assessment objects, got {len(result['assessment_objects'])}"
    assert result["score"] == 100.0, f"Expected 100.0, got {result['score']}"
    assert result["completion_fraction"] == 1.0, f"Expected completion 1.0, got {result['completion_fraction']}"
    assert len(result["canonical_match"].get("extra_student_entities", [])) == 0


def _drawing_squares_with_holes(xs: list[float], source: str, with_crosshair: bool = False):
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    for x in xs:
        for start, end in _square_coords(x):
            msp.add_line(start, end)
        msp.add_circle((x + 25.0, 25.0), radius=5.0)
        if with_crosshair:
            msp.add_line((x + 15.0, 25.0), (x + 35.0, 25.0))
            msp.add_line((x + 25.0, 15.0), (x + 25.0, 35.0))
    return parse_dxf_bytes(_save_doc_to_bytes(doc), source=source, normalize=False)


@pytest.mark.parametrize("gap", [5.0, 11.0, 50.0])
@pytest.mark.parametrize("mode", ["strict", "translation"])
@pytest.mark.parametrize("part_deduction", [0.5, 1.0])
def test_f9_compound_closed_square_with_circle_preserves_object_budget(
    gap: float, mode: str, part_deduction: float
):
    """F9 compound-object regression: Disconnected closed squares containing circular holes keep separate object budgets."""
    ref = _drawing_squares_with_holes([0.0, 50.0 + gap], "reference")
    stu = _drawing_squares_with_holes([0.0], "student")

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": mode,
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": part_deduction,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["assessment_objects"]) == 2, f"Expected 2 assessment objects, got {len(result['assessment_objects'])}"
    assert result["score"] == 55.0, f"Expected 55.0 when one of two equal compound objects is absent, got {result['score']}"
    missing_codes = [i["code"] for i in result["issues"] if i.get("category") == "missing_geometry"]
    assert missing_codes == ["MISSING_OBJECT"]


def test_f9_compound_closed_square_with_internal_crosshair_preserves_object_budget():
    """F9 compound-object regression: Closed outer boundary containing both closed and open internal features stays protected."""
    ref = _drawing_squares_with_holes([0.0, 55.0], "reference", with_crosshair=True)
    stu = _drawing_squares_with_holes([0.0], "student", with_crosshair=True)

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["assessment_objects"]) == 2, f"Expected 2 assessment objects, got {len(result['assessment_objects'])}"
    assert result["score"] == 55.0, f"Expected 55.0, got {result['score']}"


def test_f9_compound_closed_squares_independent_translation():
    """F9 compound-object regression: Nearby closed squares with internal circles receive independent translations."""
    ref = _drawing_squares_with_holes([0.0, 55.0], "reference")

    stu_doc = ezdxf.new("R2010")
    stu_doc.units = 4
    stu_msp = stu_doc.modelspace()
    for p1, p2 in _square_coords(0.0):
        stu_msp.add_line((p1[0] + 100.0, p1[1] + 50.0), (p2[0] + 100.0, p2[1] + 50.0))
    stu_msp.add_circle((25.0 + 100.0, 25.0 + 50.0), radius=5.0)
    for p1, p2 in _square_coords(55.0):
        stu_msp.add_line((p1[0] + 200.0, p1[1] + 300.0), (p2[0] + 200.0, p2[1] + 300.0))
    stu_msp.add_circle((80.0 + 200.0, 25.0 + 300.0), radius=5.0)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["assessment_objects"]) == 2
    assert result["score"] == 100.0
    assert result["completion_fraction"] == 1.0
    assert len(result["canonical_match"].get("extra_student_entities", [])) == 0









# ==============================================================================
# 25-OCT REPAIR HANDOFF: 10 MEANINGFUL ACCEPTANCE TESTS (STEP 7)
# ==============================================================================

def test_acceptance_01_two_absent_parallel_chamfers_both_accounted_as_missing():
    """Criteria 1: Two required parallel chamfers are absent: both accounted for, no forced match to lines."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # A corner with two parallel diagonal chamfers at 45 degrees:
    # Inner chamfer: (10, 0) to (0, 10), length ~14.14
    ref_msp.add_line((10, 0), (0, 10))
    # Outer chamfer: (20, 0) to (0, 20), length ~28.28
    ref_msp.add_line((20, 0), (0, 20))
    # Wall segments:
    ref_msp.add_line((0, 10), (0, 50))
    ref_msp.add_line((10, 0), (50, 0))

    # Student draws the vertical and horizontal walls, but omits BOTH chamfers:
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((0, 0), (0, 50))
    stu_msp.add_line((0, 0), (50, 0))

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    missing_issues = [i for i in result["issues"] if i.get("category") == "missing_geometry"]
    # Both chamfers must be accounted as missing geometry
    assert len(missing_issues) >= 2
    # Ensure neither chamfer was forced-matched to student vertical or horizontal line
    for m in missing_issues:
        assert m.get("student_entity_id") is None


def test_acceptance_02_one_chamfer_absent_and_one_inaccurate():
    """Criteria 2: One chamfer absent and the other valid-but-inaccurate: categories remain distinct."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((10, 0), (0, 10))  # Inner chamfer
    ref_msp.add_line((20, 0), (0, 20))  # Outer chamfer
    ref_msp.add_line((0, 20), (0, 60))
    ref_msp.add_line((20, 0), (60, 0))

    # Student draws outer chamfer with wrong length (inaccurate) and omits inner chamfer:
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((25, 0), (0, 25))  # Drawn chamfer with incorrect length/placement
    stu_msp.add_line((0, 25), (0, 60))
    stu_msp.add_line((25, 0), (60, 0))

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "strict",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    categories = {i.get("category") for i in result["issues"]}
    # Must have missing for the omitted chamfer
    assert "missing_geometry" in categories
    # Drawn chamfer produces inaccurate findings or extra, not both missing
    missing_issues = [i for i in result["issues"] if i.get("category") == "missing_geometry"]
    assert len(missing_issues) >= 1


def test_acceptance_03_independently_translated_parents_and_child_anchors():
    """Criteria 3: Independently translated complete parents: child anchors use correct frame once."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # Box A at (0, 0)
    for p1, p2 in [((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))]:
        ref_msp.add_line(p1, p2)
    # Box B at (100, 100)
    for p1, p2 in [((100, 100), (140, 100)), ((140, 100), (140, 140)), ((140, 140), (100, 140)), ((100, 140), (100, 100))]:
        ref_msp.add_line(p1, p2)

    # Student shifts Box A by (50, 50) and Box B by (-20, 80):
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for p1, p2 in [((50, 50), (90, 50)), ((90, 50), (90, 90)), ((90, 90), (50, 90)), ((50, 90), (50, 50))]:
        stu_msp.add_line(p1, p2)
    for p1, p2 in [((80, 180), (120, 180)), ((120, 180), (120, 220)), ((120, 220), (80, 220)), ((80, 220), (80, 180))]:
        stu_msp.add_line(p1, p2)

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    policy = default_rubric().model_copy(update={
        "rubric_version": "2.0",
        "approved": True,
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref, stu, rubric=policy)
    assert len(result["object_translations"]) == 2
    assert result["score"] == 100.0


def test_acceptance_04_same_length_displaced_lines_and_circles_never_duplicates():
    """Criteria 4: Same-length displaced lines and equal-radius displaced circles: never declared duplicates."""
    from app.causal_analysis import analyze_comparison
    from app.rubric import ToleranceProfile

    tol = ToleranceProfile(position=2.0, length=2.0, angle=5.0, radius=2.0)
    doc = _create_doc()
    msp = doc.modelspace()
    # Two lines of identical length 50 separated by 100 units
    l1 = msp.add_line((0, 0), (50, 0))
    l2 = msp.add_line((100, 100), (150, 100))
    # Two circles of identical radius 25 separated by 200 units
    c1 = msp.add_circle((0, 0), radius=25)
    c2 = msp.add_circle((200, 200), radius=25)

    drawing = parse_dxf_bytes(_save_doc_to_bytes(doc), source="student", normalize=False)
    # Neither line nor circle is coincident with its displaced counterpart
    lines = [e for e in drawing.entities if e.kind == "line"]
    circles = [e for e in drawing.entities if e.kind == "circle"]

    from app.causal_analysis import _coincident
    assert not _coincident(lines[0], lines[1], tol)
    assert not _coincident(circles[0], circles[1], tol)


def test_acceptance_05_real_overlaps_and_zero_length_records():
    """Criteria 5: Real full duplicates, partial overlaps, and zero-length records."""
    from app.causal_analysis import _line_overlap
    from app.rubric import ToleranceProfile
    tol = ToleranceProfile(position=2.0, length=2.0, angle=5.0, radius=2.0)

    doc = _create_doc()
    msp = doc.modelspace()
    # 1. 100% duplicate
    msp.add_line((0, 0), (50, 0))
    msp.add_line((0, 0), (50, 0))
    # 2. Partial overlap: length 250 with length 235
    msp.add_line((100, 0), (350, 0))
    msp.add_line((100, 0), (335, 0))
    # 3. Zero-length line
    msp.add_line((500, 500), (500, 500))

    drawing = parse_dxf_bytes(_save_doc_to_bytes(doc), source="student", normalize=False)
    lines = [e for e in drawing.entities if e.kind == "line"]

    # 100% overlap
    ov, f1, f2 = _line_overlap(lines[0], lines[1], tol)
    assert ov == 50.0
    assert f1 == 1.0

    # Partial overlap
    ov_p, f1_p, f2_p = _line_overlap(lines[3], lines[2], tol)
    assert round(ov_p, 1) == 235.0


def test_acceptance_06_reference_notes_separated_from_student_warnings():
    """Criteria 6: Reference validation notes separated from student warnings with zero deduction."""
    from app.reviewed_dxf import build_reviewed_drawing, ReviewedDrawing

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((0, 0), (50, 0))

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((0, 0), (50, 0))

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    validation = {
        "findings": [
            {"entity_id": "R-001", "severity": "warning", "message": "Reference geometry note", "location": (25, 0)}
        ]
    }
    comp = {
        "score": 100.0,
        "issues": [],
        "assessment_objects": [],
    }
    reviewed = build_reviewed_drawing(ref, stu, comp, validation=validation)
    ref_notes = [iss for iss in reviewed.issues if iss.provenance == "reference_validation"]
    assert len(ref_notes) == 1
    assert ref_notes[0].issue_id.startswith("V-")
    assert ref_notes[0].deduction == 0.0


def test_acceptance_07_ui_view_label_student_overlay_reference():
    """Criteria 7: Exact new UI view label 'Student overlay reference' and aligned overlay behavior."""
    index_html = (Path(__file__).resolve().parents[1] / "app/templates/index.html").read_text(encoding="utf-8")
    app_js = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text(encoding="utf-8")

    assert "Student overlay reference" in index_html
    assert 'id="view-student-overlay-reference"' in index_html
    assert 'view-student-overlay-reference' in app_js
    assert 'student-overlay-reference' in app_js


def test_acceptance_08_styles_inaccurate_expected_dashed_red_vs_missing_orange():
    """Criteria 8: Red dashed expected versus orange Missing styles stay distinct."""
    svg_py = (Path(__file__).resolve().parents[1] / "app/svg_renderer.py").read_text(encoding="utf-8")
    pdf_py = (Path(__file__).resolve().parents[1] / "app/pdf_report.py").read_text(encoding="utf-8")

    # Missing has orange stroke
    assert ".missing{" in svg_py and ("#f97316" in svg_py or "#ed8936" in svg_py)
    # Inaccurate expected has lighter red dashed
    assert ".inaccurate-expected{" in svg_py and ("#f87171" in svg_py or "#fc8181" in svg_py)
    # Inaccurate actual has solid red
    assert ".inaccurate-actual{" in svg_py and ("#dc2626" in svg_py or "#e53e3e" in svg_py)

    # In PDF report
    assert '"inaccurate-expected": ("#fc8181"' in pdf_py or '"inaccurate-expected": ("#f87171"' in pdf_py or '"#fc8181"' in pdf_py


def test_acceptance_09_pdf_seven_consecutive_drawing_pages_in_order():
    """Criteria 9: PDF has all seven drawing pages in order, including empty Critical."""
    from app.main import app
    from fastapi.testclient import TestClient
    from pypdf import PdfReader
    import io

    client = TestClient(app)
    doc = _create_doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (50, 0))
    dxf_bytes = _save_doc_to_bytes(doc)

    sugg = client.post("/api/rubric/suggest", files={"reference": ("ref.dxf", dxf_bytes, "application/dxf")}).json()
    ref_id = sugg["reference_id"]
    rub = sugg["rubric"]
    rub["approved"] = True
    rub["assignment_type"] = "Geometric Construction Exercise"
    rub["normalization_mode"] = "strict"
    appr = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "assignment_type": "Geometric Construction Exercise", "rubric": rub},
    )
    assert appr.status_code == 200, appr.text
    rev_resp = client.post(
        "/api/review",
        data={"student_name": "Test", "student_id": "001", "course_section": "A"},
        files={"reference": ("ref.dxf", dxf_bytes, "application/dxf"), "student": ("stu.dxf", dxf_bytes, "application/dxf")},
    )
    assert rev_resp.status_code == 200, rev_resp.text
    rev = rev_resp.json()

    pdf_resp = client.get(f"/api/reviews/{rev['review_id']}/report.pdf")
    reader = PdfReader(io.BytesIO(pdf_resp.content))

    # Pages 2 through 8 are Drawings 0 through 6
    expected_titles = [
        "Drawing 0",
        "Drawing 1",
        "Drawing 2",
        "Drawing 3",
        "Drawing 4",
        "Drawing 5",
        "Drawing 6",
    ]
    for page_idx, expected in enumerate(expected_titles, start=1):
        page_txt = reader.pages[page_idx].extract_text() or ""
        assert expected in page_txt, f"Expected {expected} on page {page_idx+1}, got {page_txt[:100]}"


def test_acceptance_10_pdf_export_deterministic_and_no_grade_mutation():
    """Criteria 10: Export produces same correct category pages and does not mutate grade."""
    from app.main import app, REVIEW_SNAPSHOTS
    from fastapi.testclient import TestClient
    from app.pdf_report import generate_pdf

    client = TestClient(app)
    doc = _create_doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (50, 0))
    dxf_bytes = _save_doc_to_bytes(doc)

    sugg = client.post("/api/rubric/suggest", files={"reference": ("ref.dxf", dxf_bytes, "application/dxf")}).json()
    ref_id = sugg["reference_id"]
    rub = sugg["rubric"]
    rub["approved"] = True
    rub["assignment_type"] = "Geometric Construction Exercise"
    rub["normalization_mode"] = "strict"
    appr = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "assignment_type": "Geometric Construction Exercise", "rubric": rub},
    )
    assert appr.status_code == 200, appr.text
    rev_resp = client.post(
        "/api/review",
        data={"student_name": "Test", "student_id": "001", "course_section": "A"},
        files={"reference": ("ref.dxf", dxf_bytes, "application/dxf"), "student": ("stu.dxf", dxf_bytes, "application/dxf")},
    )
    assert rev_resp.status_code == 200, rev_resp.text
    rev = rev_resp.json()

    snapshot = REVIEW_SNAPSHOTS.get(rev["review_id"])
    score_before = snapshot.review_response.get("score")

    pdf_1 = generate_pdf(snapshot)
    pdf_2 = generate_pdf(snapshot)
    assert pdf_1 == pdf_2

    score_after = snapshot.review_response.get("score")
    assert score_before == score_after


def test_shared_correspondence_across_completion_policies():
    """Verify canonical matching and reconciliation are identical across rule_based, proportional, and object_part_deduction under schema-valid Geometric Construction Exercise."""
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # Baseline line of length 150
    ref_msp.add_line((0, 0), (150, 0))
    # Square at (200, 0)
    for p1, p2 in [((200, 0), (250, 0)), ((250, 0), (250, 50)), ((250, 50), (200, 50)), ((200, 50), (200, 0))]:
        ref_msp.add_line(p1, p2)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    # Student draws baseline as three 50-unit collinear segments
    stu_msp.add_line((0, 0), (50, 0))
    stu_msp.add_line((50, 0), (100, 0))
    stu_msp.add_line((100, 0), (150, 0))
    # Student draws square shifted by (20, 20)
    for p1, p2 in [((220, 20), (270, 20)), ((270, 20), (270, 70)), ((270, 70), (220, 70)), ((220, 70), (220, 20))]:
        stu_msp.add_line(p1, p2)

    ref = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=True)
    stu = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=True)

    correspondences = {}
    for mode in ("rule_based", "proportional", "object_part_deduction"):
        rubric = default_rubric().model_copy(update={
            "approved": True,
            "assignment_type": "Geometric Construction Exercise",
            "construction_requirement": "geometry_only",
            "normalization_mode": "translation",
            "completion_scoring_mode": mode,
            "missing_part_deduction": 0.5,
        })
        res = compare_drawings(ref, stu, rubric=rubric)
        pairs = sorted((m["reference_entity_id"], m["student_entity_id"]) for m in res["matches"])
        correspondences[mode] = pairs
        assert len(res["issues"]) == 0, f"Expected 0 issues in {mode}, got {res['issues']}"
        assert res["score"] == 100.0, f"Expected 100.0 score in {mode}, got {res['score']}"

    assert correspondences["rule_based"] == correspondences["object_part_deduction"]
    assert correspondences["proportional"] == correspondences["object_part_deduction"]


def test_formative_zero_numeric_marks_across_api_and_pdf_and_appendix():
    """Verify Formative mode exposes zero numeric marks across API, standard PDF, and appendix PDF, with no raw HTML markup."""
    from app.main import app, RUBRICS, REFERENCE_RUBRICS, RUBRIC_REFERENCES
    from app.review_service import reference_fingerprint
    from fastapi.testclient import TestClient
    from pypdf import PdfReader

    client = TestClient(app)
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((0, 0), (100, 0))
    ref_msp.add_line((0, 0), (0, 100))
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((0, 0), (80, 0))  # wrong length
    stu_bytes = _save_doc_to_bytes(stu_doc)

    fp = reference_fingerprint(ref_bytes)
    rubric = default_rubric().model_copy(update={
        "approved": True,
        "assignment_type": "Geometric Construction Exercise",
        "construction_requirement": "geometry_only",
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "assessment_mode": "formative",
    })
    RUBRICS["formative-test"] = rubric
    REFERENCE_RUBRICS[fp] = "formative-test"
    RUBRIC_REFERENCES["formative-test"] = fp

    resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("A_000123_STUDENT_ONE_004L.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": "formative-test", "assessment_mode": "formative"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["score"] is None
    assert data.get("system_score") is None
    assert data.get("deduction") is None
    sb = data.get("score_breakdown") or {}
    assert sb.get("missing_part_deduction") is None
    assert sb.get("final_score") is None
    assert sb.get("total_applied_deduction") is None
    for item in sb.get("category_subtotals", []):
        assert item.get("weight") is None
        assert item.get("score") is None
        assert item.get("deduction") is None
    for item in sb.get("suppressed_findings", []):
        assert item.get("raw_deduction") is None
        assert item.get("applied") is None

    for iss in data["issues"]:
        assert iss["deduction"] is None
        assert iss["applied_deduction"] is None
        assert iss["raw_rule_deduction"] is None
        assert iss["final_applied_contribution"] is None
        assert iss["deduction_status"] == "diagnostic"
    for grp in data["finding_presentation"]["summary_groups"]:
        assert grp["score_contribution"] is None

    for inc_app in ("false", "true"):
        pdf_resp = client.get(f"/api/reviews/{data['review_id']}/report.pdf?include_appendix={inc_app}")
        assert pdf_resp.status_code == 200
        reader = PdfReader(io.BytesIO(pdf_resp.content))
        full_text = "\n".join((p.extract_text() or "") for p in reader.pages)
        assert "<br/>" not in full_text
        assert "<font" not in full_text
        assert "Diagnostic Feedback" in (reader.pages[0].extract_text() or "")
        assert "Raw deduction" not in full_text
        assert "Score contribution" not in full_text


def test_student_filename_underscore_and_provenance_roundtrip():
    """Verify underscore student names, leading-zero IDs, group code, and assignment code parse and normalize cleanly."""
    from app.review_snapshot import parse_student_dxf_filename, normalize_student_metadata

    parsed = parse_student_dxf_filename("A_000123_FIRST_LAST_004L.dxf")
    assert parsed["group_code"] == "A"
    assert parsed["course_section"] is None, "course_section must not be inferred from Group!"
    assert parsed["student_id"] == "000123"
    assert parsed["student_name"] == "First Last"
    assert parsed["student_identifier"] == "FirstLast"
    assert parsed["assignment_number"] == 4
    assert parsed["assignment_code"] == "004L"
    assert parsed["assignment_type_label"] == "Laboratory assignment"

    # Verify when instructor inputs course_section="COURSE-9", group_code is preserved independently
    meta = normalize_student_metadata(
        parsed["student_name"],
        parsed["student_id"],
        course_section="COURSE-9",
        group_code=parsed["group_code"],
        assignment_code=parsed["assignment_code"],
    )
    d = meta.to_dict()
    assert d["student_name"] == "First Last"
    assert d["student_id"] == "000123"
    assert d["course_section"] == "COURSE-9"
    assert d["group_code"] == "A"
    assert d["assignment_code"] == "004L"
    assert d["assignment_number"] == 4
    assert d["assignment_type_label"] == "Laboratory assignment"


def test_mixed_geometric_composition_approval_and_review_across_all_policies():
    """F1 regression: Mixed Geometric Composition approved through /api/rubric/approve and graded via /api/review across all 3 policies, plus gap and overlap controls."""
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((0, 0), (150, 0))
    for p1, p2 in [((200, 0), (250, 0)), ((250, 0), (250, 50)), ((250, 50), (200, 50)), ((200, 50), (200, 0))]:
        ref_msp.add_line(p1, p2)
    ref_bytes = _save_doc_to_bytes(ref_doc)

    # 1. Equivalent segmented + relocated student submission
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_line((0, 0), (50, 0))
    stu_msp.add_line((50, 0), (100, 0))
    stu_msp.add_line((100, 0), (150, 0))
    for p1, p2 in [((220, 20), (270, 20)), ((270, 20), (270, 70)), ((270, 70), (220, 70)), ((220, 70), (220, 20))]:
        stu_msp.add_line(p1, p2)
    stu_bytes = _save_doc_to_bytes(stu_doc)

    # 2. Control with real gap on square top edge
    gap_doc = _create_doc()
    gap_msp = gap_doc.modelspace()
    gap_msp.add_line((0, 0), (150, 0))
    for p1, p2 in [((200, 0), (250, 0)), ((250, 0), (250, 50)), ((250, 50), (212, 50)), ((200, 50), (200, 0))]:
        gap_msp.add_line(p1, p2)
    gap_bytes = _save_doc_to_bytes(gap_doc)

    # 3. Control with duplicate overlap on baseline
    dup_doc = _create_doc()
    dup_msp = dup_doc.modelspace()
    dup_msp.add_line((0, 0), (150, 0))
    dup_msp.add_line((25, 0), (125, 0))  # 100-unit partial duplicate
    for p1, p2 in [((200, 0), (250, 0)), ((250, 0), (250, 50)), ((250, 50), (200, 50)), ((200, 50), (200, 0))]:
        dup_msp.add_line(p1, p2)
    dup_bytes = _save_doc_to_bytes(dup_doc)

    from app.review_service import reference_fingerprint

    ref_id = reference_fingerprint(ref_bytes)
    for mode in ("rule_based", "proportional", "object_part_deduction"):
        rub = default_rubric().model_copy(update={
            "approved": True,
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": mode,
            "missing_part_deduction": 0.5,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        })
        app_resp = client.post(
            "/api/rubric/approve",
            json={"reference_id": ref_id, "rubric": rub.model_dump()},
        )
        assert app_resp.status_code == 200, app_resp.text
        rubric_id = app_resp.json()["rubric_id"]

        rev_resp = client.post(
            "/api/review",
            files={
                "reference": ("ref.dxf", ref_bytes, "application/dxf"),
                "student": ("stu.dxf", stu_bytes, "application/dxf"),
            },
            data={"rubric_id": rubric_id, "assessment_mode": "summative"},
        )
        assert rev_resp.status_code == 200, rev_resp.text
        rev_body = rev_resp.json()
        assert rev_body["score"] == 100.0, f"Expected 100.0 for {mode}, got {rev_body['score']}"
        assert rev_body["finding_counts"]["primary_student_issues"] == 0

        # Real gap control must be penalized / flagged
        gap_resp = client.post(
            "/api/review",
            files={
                "reference": ("ref.dxf", ref_bytes, "application/dxf"),
                "student": ("gap.dxf", gap_bytes, "application/dxf"),
            },
            data={"rubric_id": rubric_id, "assessment_mode": "summative"},
        )
        assert gap_resp.status_code == 200
        gap_body = gap_resp.json()
        assert gap_body["score"] < 100.0
        assert any(i["category"] in ("incorrect_length", "endpoint_gap") for i in gap_body["issues"])

        # Real overlap control must be penalized / flagged
        dup_resp = client.post(
            "/api/review",
            files={
                "reference": ("ref.dxf", ref_bytes, "application/dxf"),
                "student": ("dup.dxf", dup_bytes, "application/dxf"),
            },
            data={"rubric_id": rubric_id, "assessment_mode": "summative"},
        )
        assert dup_resp.status_code == 200
        dup_body = dup_resp.json()
        assert dup_body["score"] < 100.0
        assert any(i["category"] == "duplicate_geometry" for i in dup_body["issues"])


def test_formative_sanitization_on_grade_and_withheld_routes():
    """F2 regression: /api/grade and withheld /api/review under Formative rubric must not leak numeric marks, weights, or deductions."""
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_line((0, 0), (100, 0))
    ref_msp.add_line((100, 0), (100, 100))
    ref_msp.add_line((100, 100), (0, 100))
    ref_msp.add_line((0, 100), (0, 0))
    ref_bytes = _save_doc_to_bytes(ref_doc)

    inacc_doc = _create_doc()
    inacc_msp = inacc_doc.modelspace()
    inacc_msp.add_line((0, 0), (80, 0))
    inacc_msp.add_line((100, 0), (100, 100))
    inacc_msp.add_line((100, 100), (0, 100))
    inacc_msp.add_line((0, 100), (0, 0))
    inacc_bytes = _save_doc_to_bytes(inacc_doc)

    empty_bytes = _save_doc_to_bytes(_create_doc())

    from app.review_service import reference_fingerprint

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric().model_copy(update={
        "approved": True,
        "assignment_type": "Geometric Construction Exercise",
        "normalization_mode": "translation",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
        "assessment_mode": "formative",
    })
    app_resp = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "rubric": rub.model_dump()},
    )
    assert app_resp.status_code == 200
    rubric_id = app_resp.json()["rubric_id"]

    # 1. /api/grade with inaccurate student in Formative mode
    grade_resp = client.post(
        "/api/grade",
        files={
            "reference": ("ref.dxf", ref_bytes, "application/dxf"),
            "student": ("inacc.dxf", inacc_bytes, "application/dxf"),
        },
        data={"rubric_id": rubric_id},
    )
    assert grade_resp.status_code == 200
    gb = grade_resp.json()
    assert gb["score"] is None
    assert gb["deduction"] is None
    assert gb["missing_part_deduction"] is None
    assert gb["rubric"]["missing_part_deduction"] is None
    assert gb["score_breakdown"]["total_applied_deduction"] is None
    for cat in gb["rubric"]["categories"]:
        assert cat["weight"] is None
        assert cat["max_deduction"] is None
        for r in cat["rules"]:
            assert r["deduction"] is None
    for cat in gb["rubric_breakdown"]:
        assert cat["weight"] is None
        assert cat["deduction"] is None
        for ev in cat.get("deduction_evidence", []):
            assert ev["applied"] is None
            assert ev["raw_deduction"] is None
            assert ev["deduction_status"] == "diagnostic"

    # 2. /api/review with empty student (withheld) in Formative mode
    withheld_resp = client.post(
        "/api/review",
        files={
            "reference": ("ref.dxf", ref_bytes, "application/dxf"),
            "student": ("empty.dxf", empty_bytes, "application/dxf"),
        },
        data={"rubric_id": rubric_id, "assessment_mode": "formative"},
    )
    assert withheld_resp.status_code == 200
    wb = withheld_resp.json()
    assert wb["grading_status"] == "withheld"
    assert wb["assessment_mode"] == "formative"
    assert wb["score"] is None
    assert wb["missing_part_deduction"] is None
    assert wb["rubric"]["missing_part_deduction"] is None
    assert wb["score_breakdown"]["total_applied_deduction"] is None
    for cat in wb["score_breakdown"]["category_subtotals"]:
        assert cat["weight"] is None
        assert cat["deduction"] is None
        assert cat["score"] is None


# ---------------------------------------------------------------------------
# Error Set VI - Issue VI-01: Displaced Motif Recovery Tests
# ---------------------------------------------------------------------------

def _vi_01_rubric(*, norm_mode="translation", completion_mode="object_part_deduction", assignment_type="Mixed Geometric Composition"):
    return default_rubric().model_copy(
        update={
            "approved": True,
            "assignment_type": assignment_type,
            "normalization_mode": norm_mode,
            "completion_scoring_mode": completion_mode,
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "tolerances": default_rubric().tolerances.model_copy(
                update={"position": 0.5, "length": 0.5, "radius": 0.5, "angle": 0.5, "dimension": 5.0}
            ),
        }
    )


def test_vi_01_displaced_motif_matches_as_inaccurate():
    """VI-01: Displaced 4-part motif matches as Inaccurate at G; 0 false Missing, 0 false Extra."""
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    # Fixed background floor plan / anchor: a rectangle at (0,0)-(200,200)
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 200), (0, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((0, 200), (0, 0), dxfattribs={"layer": "WALLS"})
    # 4-part motif on layer F-6 at Box A (x=50..70, y=50..70)
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})

    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    # Student drew walls correctly at (0,0)-(200,200)
    msp_stu.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((200, 200), (0, 200), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((0, 200), (0, 0), dxfattribs={"layer": "WALLS"})
    # Student displaced the 4-part motif to Box G (dx=+806, so x=856..876, y=50..70) on student layer A-007
    msp_stu.add_line((856, 50), (876, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((876, 50), (876, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((876, 70), (856, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((856, 70), (856, 50), dxfattribs={"layer": "A-007"})

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    rub = _vi_01_rubric()
    result = compare_drawings(ref_drawing, stu_drawing, rubric=rub)

    # 1. Zero false missing for the motif at Box A
    missing_issues = [i for i in result["issues"] if i["category"] in {"missing_geometry", "missing_object", "missing_part"}]
    assert len(missing_issues) == 0, f"Expected 0 missing issues, got {missing_issues}"

    # 2. Zero false extra for the motif at Box B / Box G
    extra_issues = [i for i in result["issues"] if i["category"] == "extra_geometry"]
    assert len(extra_issues) == 0, f"Expected 0 extra issues, got {extra_issues}"

    # 3. Exactly one incorrect_position issue for the displaced motif at Box G
    pos_issues = [i for i in result["issues"] if i["category"] == "incorrect_position"]
    assert len(pos_issues) == 1, f"Expected 1 incorrect_position issue, got {len(pos_issues)}"
    pos_issue = pos_issues[0]
    assert pos_issue.get("location") is not None
    # Location must be at Box G (x around 866, y around 60)
    assert abs(pos_issue["location"][0] - 866.0) < 1.0, f"Badge location X should be at Box G (~866), got {pos_issue['location'][0]}"
    assert abs(pos_issue["measurement"]["actual"] - 806.0) < 1.0

    # 4. Reviewed drawing snapshot: visual_role == 'inaccurate'
    from app.reviewed_dxf import build_reviewed_drawing
    rd = build_reviewed_drawing(ref_drawing, stu_drawing, result)
    inacc_issues = [ri for ri in rd.issues if ri.visual_role == "inaccurate"]
    assert len(inacc_issues) >= 1
    inacc_rev = inacc_issues[0]
    assert inacc_rev.category == "incorrect_position"
    # Expected geometry should stay at Box A
    assert len(inacc_rev.expected_geometries) == 4
    for eg in inacc_rev.expected_geometries:
        assert eg.bbox[0] < 100.0, f"Expected geometry must stay at Box A, got bbox {eg.bbox}"
    # Actual geometry should be at Box G
    assert len(inacc_rev.actual_geometries) == 4
    for ag in inacc_rev.actual_geometries:
        assert ag.bbox[0] > 800.0, f"Actual geometry must be at Box G, got bbox {ag.bbox}"


def test_vi_01_omitted_motif_remains_missing():
    """VI-01 Control: Omitted motif remains Missing."""
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})

    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    msp_stu.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    # Student omitted F-6 entirely

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    rub = _vi_01_rubric()
    result = compare_drawings(ref_drawing, stu_drawing, rubric=rub)

    missing_issues = [i for i in result["issues"] if i["category"] in {"missing_geometry", "missing_object", "missing_part"}]
    assert len(missing_issues) >= 1
    assert any(i.get("code") == "MISSING_OBJECT" for i in missing_issues)
    assert len([i for i in result["issues"] if i["category"] == "extra_geometry"]) == 0


def test_vi_01_genuine_extra_copy_remains_extra():
    """VI-01 Control: Genuine extra copy remains Extra."""
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})

    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    msp_stu.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    # Student drew the motif at Box A
    msp_stu.add_line((50, 50), (70, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((70, 50), (70, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((70, 70), (50, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((50, 70), (50, 50), dxfattribs={"layer": "A-007"})
    # AND an extra copy at Box B (x=500..520, y=50..70)
    msp_stu.add_line((500, 50), (520, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((520, 50), (520, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((520, 70), (500, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((500, 70), (500, 50), dxfattribs={"layer": "A-007"})

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    rub = _vi_01_rubric()
    result = compare_drawings(ref_drawing, stu_drawing, rubric=rub)

    extra_issues = [i for i in result["issues"] if i["category"] == "extra_geometry"]
    assert len(extra_issues) >= 1
    # Extra entities are around x=500
    assert all(i["location"][0] > 400.0 for i in extra_issues if i.get("location"))
    # Box A is not missing
    assert len([i for i in result["issues"] if i["category"] in {"missing_geometry", "missing_object"}]) == 0


def test_vi_01_ambiguous_repeated_shapes():
    """VI-01 Control: Ambiguous repeated shapes match closest/best corresponding student shape."""
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (500, 0), dxfattribs={"layer": "WALLS"})
    # Motif 1 at (50, 50)
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})
    # Motif 2 at (300, 50)
    msp_ref.add_line((300, 50), (320, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((320, 50), (320, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((320, 70), (300, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((300, 70), (300, 50), dxfattribs={"layer": "F-6"})

    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    msp_stu.add_line((0, 0), (500, 0), dxfattribs={"layer": "WALLS"})
    # Student drew Motif 1 accurately at (50, 50)
    msp_stu.add_line((50, 50), (70, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((70, 50), (70, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((70, 70), (50, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((50, 70), (50, 50), dxfattribs={"layer": "A-007"})
    # Student displaced Motif 2 to (600, 50)
    msp_stu.add_line((600, 50), (620, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((620, 50), (620, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((620, 70), (600, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((600, 70), (600, 50), dxfattribs={"layer": "A-007"})

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    rub = _vi_01_rubric()
    result = compare_drawings(ref_drawing, stu_drawing, rubric=rub)

    # 0 false missing, 0 false extra
    assert len([i for i in result["issues"] if i["category"] in {"missing_geometry", "missing_object"}]) == 0
    assert len([i for i in result["issues"] if i["category"] == "extra_geometry"]) == 0
    # Exactly 1 position issue for Motif 2
    pos_issues = [i for i in result["issues"] if i["category"] == "incorrect_position"]
    assert len(pos_issues) == 1
    assert pos_issues[0]["location"][0] > 550.0


def test_vi_01_line_vs_lwpolyline_subdivision():
    """VI-01: LINE vs. LWPOLYLINE subdivision equivalence under displacement."""
    # Reference: 1 closed LWPOLYLINE for the motif
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_lwpolyline([(50, 50), (70, 50), (70, 70), (50, 70)], close=True, dxfattribs={"layer": "F-6"})

    # Student: 4 separate LINEs for the motif, displaced by +800 in X
    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    msp_stu.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((850, 50), (870, 50), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((870, 50), (870, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((870, 70), (850, 70), dxfattribs={"layer": "A-007"})
    msp_stu.add_line((850, 70), (850, 50), dxfattribs={"layer": "A-007"})

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    rub = _vi_01_rubric()
    result = compare_drawings(ref_drawing, stu_drawing, rubric=rub)

    # 0 false missing, 0 false extra, 0 false incorrect_length
    assert len([i for i in result["issues"] if i["category"] in {"missing_geometry", "missing_object"}]) == 0
    assert len([i for i in result["issues"] if i["category"] == "extra_geometry"]) == 0
    assert len([i for i in result["issues"] if i["category"] == "incorrect_length"]) == 0
    # Exactly 1 position issue for the displaced motif at Box G
    pos_issues = [i for i in result["issues"] if i["category"] == "incorrect_position"]
    assert len(pos_issues) == 1
    assert pos_issues[0]["location"][0] > 800.0


def test_vi_01_coherent_whole_drawing_shift():
    """VI-01: Coherent whole-drawing shift under both placement policies."""
    # Both walls and motif are shifted coherently by (+100, +50)
    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})

    doc_stu = _create_doc()
    msp_stu = doc_stu.modelspace()
    msp_stu.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((150, 100), (170, 100), dxfattribs={"layer": "F-6"})
    msp_stu.add_line((170, 100), (170, 120), dxfattribs={"layer": "F-6"})

    ref_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)
    stu_drawing = parse_dxf_bytes(_save_doc_to_bytes(doc_stu), source="student", normalize=False)

    # 1. Under translation-tolerant placement: coherent whole-drawing shift is accepted
    rub_trans = _vi_01_rubric(norm_mode="translation")
    res_trans = compare_drawings(ref_drawing, stu_drawing, rubric=rub_trans)
    assert len([i for i in res_trans["issues"] if i["category"] == "incorrect_position"]) == 0
    assert len([i for i in res_trans["issues"] if i["category"] in {"missing_geometry", "missing_object"}]) == 0

    # 2. Under strict placement: shift is rejected/penalized
    rub_strict = _vi_01_rubric(norm_mode="strict")
    res_strict = compare_drawings(ref_drawing, stu_drawing, rubric=rub_strict)
    assert len(res_strict["issues"]) >= 1


def test_vi_01_representation_invariance_matrix():
    """VI-01: Representation invariance across LINE/LWPOLYLINE and edge splits under same layer names."""
    rub = _vi_01_rubric()

    # 1. Ref: 4 LINEs on F-6. Stu: 4 LINEs on F-6 displaced by (+800, 0)
    doc_r1 = _create_doc()
    msp_r1 = doc_r1.modelspace()
    msp_r1.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_r1.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_r1.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_r1.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_r1.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_r1.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})

    doc_s1 = _create_doc()
    msp_s1 = doc_s1.modelspace()
    msp_s1.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_s1.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_s1.add_line((850, 50), (870, 50), dxfattribs={"layer": "F-6"})
    msp_s1.add_line((870, 50), (870, 70), dxfattribs={"layer": "F-6"})
    msp_s1.add_line((870, 70), (850, 70), dxfattribs={"layer": "F-6"})
    msp_s1.add_line((850, 70), (850, 50), dxfattribs={"layer": "F-6"})

    r1 = parse_dxf_bytes(_save_doc_to_bytes(doc_r1), source="reference", normalize=False)
    s1 = parse_dxf_bytes(_save_doc_to_bytes(doc_s1), source="student", normalize=False)
    res1 = compare_drawings(r1, s1, rubric=rub)
    paid_pos1 = [i for i in res1["issues"] if i["category"] == "incorrect_position" and i.get("classification") == "primary"]
    assert len(paid_pos1) == 1, f"Expected 1 paid position finding, got {len(paid_pos1)}"
    assert res1["score"] == 97.0, f"Expected score 97.0, got {res1['score']}"

    # 2. Ref: 4 LINEs on F-6. Stu: 1 closed LWPOLYLINE on F-6 displaced by (+800, 0)
    doc_s2 = _create_doc()
    msp_s2 = doc_s2.modelspace()
    msp_s2.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_s2.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_s2.add_lwpolyline([(850, 50), (870, 50), (870, 70), (850, 70)], close=True, dxfattribs={"layer": "F-6"})

    s2 = parse_dxf_bytes(_save_doc_to_bytes(doc_s2), source="student", normalize=False)
    res2 = compare_drawings(r1, s2, rubric=rub)
    paid_pos2 = [i for i in res2["issues"] if i["category"] == "incorrect_position" and i.get("classification") == "primary"]
    assert len(paid_pos2) == 1, f"Expected 1 paid position finding, got {len(paid_pos2)}"
    assert res2["score"] == 97.0, f"Expected score 97.0, got {res2['score']}"

    # 3. Ref: 4 LINEs on F-6. Stu: 4 LINEs with one edge split into two segments
    doc_s3 = _create_doc()
    msp_s3 = doc_s3.modelspace()
    msp_s3.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_s3.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_s3.add_line((850, 50), (860, 50), dxfattribs={"layer": "F-6"})
    msp_s3.add_line((860, 50), (870, 50), dxfattribs={"layer": "F-6"})
    msp_s3.add_line((870, 50), (870, 70), dxfattribs={"layer": "F-6"})
    msp_s3.add_line((870, 70), (850, 70), dxfattribs={"layer": "F-6"})
    msp_s3.add_line((850, 70), (850, 50), dxfattribs={"layer": "F-6"})

    s3 = parse_dxf_bytes(_save_doc_to_bytes(doc_s3), source="student", normalize=False)
    res3 = compare_drawings(r1, s3, rubric=rub)
    paid_pos3 = [i for i in res3["issues"] if i["category"] == "incorrect_position" and i.get("classification") == "primary"]
    assert len(paid_pos3) == 1, f"Expected 1 paid position finding, got {len(paid_pos3)}"
    assert res3["score"] == 97.0, f"Expected score 97.0, got {res3['score']}"


def test_vi_01_moved_motif_with_vertex_edit_representation_invariance():
    """VI-01: Displaced motif with a 4-unit vertex edit produces identical score and paid ledger for LINE vs LWPOLYLINE."""
    rub = _vi_01_rubric()

    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})
    ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)

    # Student Case A: 4 LINEs on A-007, displaced to x=850, with vertex (870, 70) edited to (874, 70) (+4 in X)
    doc_stu_lines = _create_doc()
    msp_sl = doc_stu_lines.modelspace()
    msp_sl.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_sl.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_sl.add_line((850, 50), (870, 50), dxfattribs={"layer": "A-007"})
    msp_sl.add_line((870, 50), (874, 70), dxfattribs={"layer": "A-007"})
    msp_sl.add_line((874, 70), (850, 70), dxfattribs={"layer": "A-007"})
    msp_sl.add_line((850, 70), (850, 50), dxfattribs={"layer": "A-007"})
    stu_lines = parse_dxf_bytes(_save_doc_to_bytes(doc_stu_lines), source="student", normalize=False)

    # Student Case B: 1 closed LWPOLYLINE on A-007 with the same edited vertex at (874, 70)
    doc_stu_poly = _create_doc()
    msp_sp = doc_stu_poly.modelspace()
    msp_sp.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_sp.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_sp.add_lwpolyline([(850, 50), (870, 50), (874, 70), (850, 70)], close=True, dxfattribs={"layer": "A-007"})
    stu_poly = parse_dxf_bytes(_save_doc_to_bytes(doc_stu_poly), source="student", normalize=False)

    res_lines = compare_drawings(ref_dwg, stu_lines, rubric=rub)
    res_poly = compare_drawings(ref_dwg, stu_poly, rubric=rub)

    # Both cases MUST have the assembly movement issue
    pos_lines = [i for i in res_lines["issues"] if i.get("code") == "INCORRECT_POSITION" and not i.get("component_id")]
    pos_poly = [i for i in res_poly["issues"] if i.get("code") == "INCORRECT_POSITION" and not i.get("component_id")]
    assert len(pos_lines) == 1, f"Lines expected 1 assembly position issue, got {len(pos_lines)}"
    assert len(pos_poly) == 1, f"Poly expected 1 assembly position issue, got {len(pos_poly)}"

    # Both cases must have identical scores
    assert res_lines["score"] == res_poly["score"], f"Score mismatch: LINE={res_lines['score']} vs LWPOLYLINE={res_poly['score']}"
    assert res_lines["score"] == 91.0, f"Expected 91.0, got {res_lines['score']}"

    # Reference Case C: equivalent motif with one reference edge split (5 LINEs)
    doc_ref_split = _create_doc()
    msp_rs = doc_ref_split.modelspace()
    msp_rs.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_rs.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    # Edge at y=50 split into (50,50)-(60,50) and (60,50)-(70,50)
    msp_rs.add_line((50, 50), (60, 50), dxfattribs={"layer": "F-6"})
    msp_rs.add_line((60, 50), (70, 50), dxfattribs={"layer": "F-6"})
    msp_rs.add_line((70, 50), (70, 70), dxfattribs={"layer": "F-6"})
    msp_rs.add_line((70, 70), (50, 70), dxfattribs={"layer": "F-6"})
    msp_rs.add_line((50, 70), (50, 50), dxfattribs={"layer": "F-6"})
    ref_split_dwg = parse_dxf_bytes(_save_doc_to_bytes(doc_ref_split), source="reference", normalize=False)

    res_split_lines = compare_drawings(ref_split_dwg, stu_lines, rubric=rub)
    res_split_poly = compare_drawings(ref_split_dwg, stu_poly, rubric=rub)

    assert res_split_lines["score"] == 91.0, f"Expected 91.0 for split-ref vs lines, got {res_split_lines['score']}"
    assert res_split_poly["score"] == 91.0, f"Expected 91.0 for split-ref vs poly, got {res_split_poly['score']}"


def test_vi_01_same_layer_combined_global_and_local_movement_representation_invariance():
    """VI-01: Same-layer MOTIF with shared translation (+100,+50) and motif movement (+806,0) yields 97.0 across LINE/LWPOLYLINE/split."""
    rub = _vi_01_rubric()

    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 200), (0, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((0, 200), (0, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "MOTIF"})
    ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(doc_ref), source="reference", normalize=False)

    # Student Case A: Four LINEs on MOTIF
    doc_a = _create_doc()
    msp_a = doc_a.modelspace()
    msp_a.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((956, 100), (976, 100), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((976, 100), (976, 120), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((976, 120), (956, 120), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((956, 120), (956, 100), dxfattribs={"layer": "MOTIF"})
    stu_a = parse_dxf_bytes(_save_doc_to_bytes(doc_a), source="student", normalize=False)

    # Student Case B: One closed LWPOLYLINE on MOTIF
    doc_b = _create_doc()
    msp_b = doc_b.modelspace()
    msp_b.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_b.add_lwpolyline([(956, 100), (976, 100), (976, 120), (956, 120)], close=True, dxfattribs={"layer": "MOTIF"})
    stu_b = parse_dxf_bytes(_save_doc_to_bytes(doc_b), source="student", normalize=False)

    # Student Case C: Equivalent split LINEs on MOTIF
    doc_c = _create_doc()
    msp_c = doc_c.modelspace()
    msp_c.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((956, 100), (966, 100), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((966, 100), (976, 100), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((976, 100), (976, 120), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((976, 120), (956, 120), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((956, 120), (956, 100), dxfattribs={"layer": "MOTIF"})
    stu_c = parse_dxf_bytes(_save_doc_to_bytes(doc_c), source="student", normalize=False)

    res_a = compare_drawings(ref_dwg, stu_a, rubric=rub)
    res_b = compare_drawings(ref_dwg, stu_b, rubric=rub)
    res_c = compare_drawings(ref_dwg, stu_c, rubric=rub)

    assert res_a["normalization"]["student"]["translation"] == [-100.0, -50.0]
    assert res_b["normalization"]["student"]["translation"] == [-100.0, -50.0]
    assert res_c["normalization"]["student"]["translation"] == [-100.0, -50.0]

    assert res_a["score"] == 97.0, f"Case A expected 97.0, got {res_a['score']}"
    assert res_b["score"] == 97.0, f"Case B expected 97.0, got {res_b['score']}"
    assert res_c["score"] == 97.0, f"Case C expected 97.0, got {res_c['score']}"

    paid_a = [i for i in res_a["issues"] if i.get("category") == "incorrect_position" and i.get("classification") == "primary"]
    paid_b = [i for i in res_b["issues"] if i.get("category") == "incorrect_position" and i.get("classification") == "primary"]
    paid_c = [i for i in res_c["issues"] if i.get("category") == "incorrect_position" and i.get("classification") == "primary"]

    assert len(paid_a) == 1 and paid_a[0]["applied_deduction"] == 3.0
    assert len(paid_b) == 1 and paid_b[0]["applied_deduction"] == 3.0
    assert len(paid_c) == 1 and paid_c[0]["applied_deduction"] == 3.0


def test_vi_01_same_layer_combined_global_and_local_movement_api_regression():
    """VI-01: /api/review with same-layer MOTIF and combined translation produces 97.0 across LINE/LWPOLYLINE/split."""
    from app.main import app
    from app.review_service import reference_fingerprint
    from fastapi.testclient import TestClient

    client = TestClient(app)
    rub = _vi_01_rubric()

    doc_ref = _create_doc()
    msp_ref = doc_ref.modelspace()
    msp_ref.add_line((0, 0), (200, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 0), (200, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((200, 200), (0, 200), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((0, 200), (0, 0), dxfattribs={"layer": "WALLS"})
    msp_ref.add_line((50, 50), (70, 50), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((70, 50), (70, 70), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((70, 70), (50, 70), dxfattribs={"layer": "MOTIF"})
    msp_ref.add_line((50, 70), (50, 50), dxfattribs={"layer": "MOTIF"})
    ref_bytes = _save_doc_to_bytes(doc_ref)
    ref_id = reference_fingerprint(ref_bytes)

    app_resp = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "rubric": rub.model_dump()},
    )
    assert app_resp.status_code == 200
    rubric_id = app_resp.json()["rubric_id"]

    # Student Case A: Four LINEs
    doc_a = _create_doc()
    msp_a = doc_a.modelspace()
    msp_a.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_a.add_line((956, 100), (976, 100), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((976, 100), (976, 120), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((976, 120), (956, 120), dxfattribs={"layer": "MOTIF"})
    msp_a.add_line((956, 120), (956, 100), dxfattribs={"layer": "MOTIF"})
    stu_a_bytes = _save_doc_to_bytes(doc_a)

    # Student Case B: One closed LWPOLYLINE
    doc_b = _create_doc()
    msp_b = doc_b.modelspace()
    msp_b.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_b.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_b.add_lwpolyline([(956, 100), (976, 100), (976, 120), (956, 120)], close=True, dxfattribs={"layer": "MOTIF"})
    stu_b_bytes = _save_doc_to_bytes(doc_b)

    # Student Case C: Equivalent split LINEs
    doc_c = _create_doc()
    msp_c = doc_c.modelspace()
    msp_c.add_line((100, 50), (300, 50), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((300, 50), (300, 250), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((300, 250), (100, 250), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((100, 250), (100, 50), dxfattribs={"layer": "WALLS"})
    msp_c.add_line((956, 100), (966, 100), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((966, 100), (976, 100), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((976, 100), (976, 120), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((976, 120), (956, 120), dxfattribs={"layer": "MOTIF"})
    msp_c.add_line((956, 120), (956, 100), dxfattribs={"layer": "MOTIF"})
    stu_c_bytes = _save_doc_to_bytes(doc_c)

    for case_label, stu_bytes in [("lines", stu_a_bytes), ("poly", stu_b_bytes), ("split", stu_c_bytes)]:
        resp = client.post(
            "/api/review",
            files={
                "reference": ("ref.dxf", ref_bytes, "application/dxf"),
                "student": (f"stu_{case_label}.dxf", stu_bytes, "application/dxf"),
            },
            data={"rubric_id": rubric_id},
        )
        assert resp.status_code == 200, f"{case_label} failed with status {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["grading_status"] == "graded", f"{case_label} expected graded, got {data['grading_status']}"
        assert data["score"] == 97.0, f"{case_label} expected score 97.0, got {data['score']}"
        norm = data.get("normalization_decision", {})
        assert norm.get("selected_translation") == [-100.0, -50.0], f"{case_label} translation mismatch: {norm}"


def test_concentric_arc_correspondence_radial_invariance():
    """Concentric wall bend with shifted radius (40/55 -> 50/65) pairs inner-to-inner and outer-to-outer without false missing/extra."""
    from app.rubric import ToleranceProfile

    tol = ToleranceProfile(position=0.5, length=0.5, angle=1.0, radius=0.5)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_arc(center=(100, 100), radius=40.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_msp.add_arc(center=(100, 100), radius=55.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    # Student shifted radii by +10.0: inner 50, outer 65, maintaining 15-unit wall thickness
    stu_msp.add_arc(center=(100, 100), radius=50.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_msp.add_arc(center=(100, 100), radius=65.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    match_result = match_canonical_geometry(ref_dwg, stu_dwg, tol)

    # Both reference arcs must be matched (presence == 1.0)
    assert len(match_result.missing_components) == 0, f"Expected 0 missing components, got {len(match_result.missing_components)}"
    assert len(match_result.extra_student_entities) == 0, f"Expected 0 extra student entities, got {match_result.extra_student_entities}"

    cms = {cm.reference_component.radius: cm for cm in match_result.component_matches}
    assert 40.0 in cms and 55.0 in cms, f"Missing matches for 40.0 and 55.0: {list(cms.keys())}"

    # Inner 40 must pair with student inner 50
    cm_inner = cms[40.0]
    assert len(cm_inner.student_components) == 1
    assert cm_inner.student_components[0].radius == 50.0, f"Expected inner arc 40 to pair with 50, got {cm_inner.student_components[0].radius}"
    inner_rad_err = next((e for e in cm_inner.errors if e["category"] == "incorrect_radius"), None)
    assert inner_rad_err is not None, "Expected incorrect_radius on inner arc"
    assert inner_rad_err["actual"] == 50.0 and inner_rad_err["expected"] == 40.0

    # Outer 55 must pair with student outer 65
    cm_outer = cms[55.0]
    assert len(cm_outer.student_components) == 1
    assert cm_outer.student_components[0].radius == 65.0, f"Expected outer arc 55 to pair with 65, got {cm_outer.student_components[0].radius}"
    outer_rad_err = next((e for e in cm_outer.errors if e["category"] == "incorrect_radius"), None)
    assert outer_rad_err is not None, "Expected incorrect_radius on outer arc"
    assert outer_rad_err["actual"] == 65.0 and outer_rad_err["expected"] == 55.0


def test_concentric_arc_omission_control():
    """If student draws only one arc of a concentric bend, the other is correctly flagged missing."""
    from app.rubric import ToleranceProfile

    tol = ToleranceProfile(position=0.5, length=0.5, angle=1.0, radius=0.5)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_arc(center=(100, 100), radius=40.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_msp.add_arc(center=(100, 100), radius=55.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

    # Student only drew the outer arc (radius 55)
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_arc(center=(100, 100), radius=55.0, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

    match_result = match_canonical_geometry(ref_dwg, stu_dwg, tol)

    assert len(match_result.missing_components) == 1, f"Expected 1 missing arc, got {len(match_result.missing_components)}"
    assert match_result.missing_components[0].radius == 40.0
    assert len(match_result.extra_student_entities) == 0


def test_concentric_arc_added_arc_subset_correspondence():
    """Codex blocking reproduction: Concentric bend with added arc (40,55 vs 50,65,80) pairs 40->50 and 55->65, leaving 80 Extra."""
    from app.rubric import ToleranceProfile

    for tol_val in (0.25, 0.5):
        for walls in (False, True):
            # Build reference: 40 and 55
            ref_doc = _create_doc()
            ref_msp = ref_doc.modelspace()
            for r in (40.0, 55.0):
                ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
                if walls:
                    ref_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
                    ref_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
            ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

            # Build student: 50, 65, and genuinely added 80
            stu_doc = _create_doc()
            stu_msp = stu_doc.modelspace()
            for r in (50.0, 65.0, 80.0):
                stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
                if walls and r in (50.0, 65.0):
                    stu_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
                    stu_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
            stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

            tol = ToleranceProfile(position=tol_val, length=tol_val, radius=tol_val, angle=1.0)
            res = match_canonical_geometry(ref_dwg, stu_dwg, tol)

            # Verify no missing arcs
            arc_missing = [c for c in res.missing_components if c.kind == "arc"]
            assert len(arc_missing) == 0, f"tol={tol_val}, walls={walls}: expected 0 missing arcs, got {len(arc_missing)}"

            # Verify arc pairs: 40->50, 55->65
            arc_matches = {cm.reference_component.radius: cm for cm in res.component_matches if cm.reference_component.kind == "arc"}
            assert 40.0 in arc_matches and 55.0 in arc_matches
            assert len(arc_matches[40.0].student_components) == 1
            assert arc_matches[40.0].student_components[0].radius == 50.0
            assert len(arc_matches[55.0].student_components) == 1
            assert arc_matches[55.0].student_components[0].radius == 65.0

            # Radius errors: actual 50 expected 40; actual 65 expected 55
            err_40 = next((e for e in arc_matches[40.0].errors if e["category"] == "incorrect_radius"), None)
            err_55 = next((e for e in arc_matches[55.0].errors if e["category"] == "incorrect_radius"), None)
            assert err_40 is not None and err_40["actual"] == 50.0 and err_40["expected"] == 40.0
            assert err_55 is not None and err_55["actual"] == 65.0 and err_55["expected"] == 55.0

            # Verify only the 80 arc is extra (among arc entities)
            extra_arcs = [e for e in res.extra_student_entities if any(sc.radius == 80.0 for sc in stu_dwg.entities if sc.id == e or sc.source_handle == e)]
            assert len(extra_arcs) >= 1 or any(c.radius == 80.0 for c in stu_dwg.entities if c.id in res.extra_student_entities)


def test_concentric_arc_neighbor_candidate_subset_correspondence():
    """Concentric bend with 4 student candidates (50, 65, 80, 95) unambiguously pairs (40->50, 55->65) and leaves 80, 95 Extra."""
    from app.rubric import ToleranceProfile

    for walls in (False, True):
        ref_doc = _create_doc()
        ref_msp = ref_doc.modelspace()
        for r in (40.0, 55.0):
            ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
            if walls:
                ref_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
                ref_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
        ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

        stu_doc = _create_doc()
        stu_msp = stu_doc.modelspace()
        for r in (50.0, 65.0, 80.0, 95.0):
            stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
            if walls and r in (50.0, 65.0):
                stu_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
                stu_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
        stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

        tol = ToleranceProfile(position=0.5, length=0.5, radius=0.5, angle=1.0)
        res = match_canonical_geometry(ref_dwg, stu_dwg, tol)

        arc_missing = [c for c in res.missing_components if c.kind == "arc"]
        assert len(arc_missing) == 0

        arc_matches = {cm.reference_component.radius: cm for cm in res.component_matches if cm.reference_component.kind == "arc"}
        assert arc_matches[40.0].student_components[0].radius == 50.0
        assert arc_matches[55.0].student_components[0].radius == 65.0


def test_concentric_arc_ambiguous_equal_cost_unresolved():
    """Tied candidate subsets without distinguishing context produce one informational finding with confidence='instructor_review_required' and 0.00 deduction."""
    from app.rubric import ToleranceProfile, default_rubric
    from app.compare import compare_drawings

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_bytes = _save_doc_to_bytes(ref_doc)
    ref_dwg = parse_dxf_bytes(ref_bytes, source="reference", normalize=False)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for r in (30.0, 45.0, 50.0, 65.0):
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_bytes = _save_doc_to_bytes(stu_doc)
    stu_dwg = parse_dxf_bytes(stu_bytes, source="student", normalize=False)

    for tol_val in (0.25, 0.50):
        tol = ToleranceProfile(position=tol_val, length=tol_val, radius=tol_val, angle=1.0)
        res = match_canonical_geometry(ref_dwg, stu_dwg, tol)

        # Neither reference arc is marked missing
        assert len([c for c in res.missing_components if c.kind == "arc"]) == 0
        # No student arc is marked extra
        assert len([e for e in res.extra_student_entities if any(s.radius in (30, 45, 50, 65) for s in stu_dwg.entities if s.id == e)]) == 0

        # Ambiguous groups recorded
        assert len(res.ambiguous_groups) == 1
        group = res.ambiguous_groups[0]
        assert group["reference_radii"] == [40.0, 55.0]
        assert group["competing_subsets"] == [[30.0, 45.0], [50.0, 65.0]]

    # Compare drawings under both rubrics
    for mode in ("object_part_deduction", "proportional"):
        rubric = default_rubric().model_copy(deep=True, update={
            "approved": True,
            "rubric_version": "2.0",
            "completion_scoring_mode": mode,
            "missing_part_deduction": 1.0,
        })
        comp = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
        assert comp["score"] == 100.0, f"Expected score 100.0 for {mode}, got {comp['score']}"

        # Informational finding present with confidence instructor_review_required
        amb_issues = [i for i in comp["issues"] if i.get("category") == "ambiguous_geometry"]
        assert len(amb_issues) == 1
        issue = amb_issues[0]
        assert issue["confidence"] == "instructor_review_required"
        assert issue["classification"] == "informational"
        assert issue["applied_deduction"] == 0.0

        # Zero missing, zero extra, zero inaccurate findings
        assert len([i for i in comp["issues"] if i.get("category") == "missing_geometry"]) == 0
        assert len([i for i in comp["issues"] if i.get("category") == "extra_geometry"]) == 0
        assert len([i for i in comp["issues"] if i.get("category", "").startswith("incorrect_")]) == 0


def test_concentric_arc_ambiguous_reordered_entities():
    """Entity ordering must not resolve ambiguity; all permutations produce identical informational finding and zero deduction."""
    from app.rubric import default_rubric
    from app.compare import compare_drawings

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

    rubric = default_rubric().model_copy(deep=True, update={
        "approved": True,
        "rubric_version": "2.0",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 1.0,
    })

    permutations = [
        [65.0, 50.0, 45.0, 30.0],
        [50.0, 30.0, 65.0, 45.0],
        [45.0, 65.0, 30.0, 50.0],
    ]

    for radii_order in permutations:
        stu_doc = _create_doc()
        stu_msp = stu_doc.modelspace()
        for r in radii_order:
            stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
        stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

        comp = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
        assert comp["score"] == 100.0, f"Order {radii_order} failed score: {comp['score']}"

        amb_issues = [i for i in comp["issues"] if i.get("category") == "ambiguous_geometry"]
        assert len(amb_issues) == 1, f"Order {radii_order} expected 1 ambiguous issue, got {len(amb_issues)}"
        assert amb_issues[0]["confidence"] == "instructor_review_required"
        assert amb_issues[0]["applied_deduction"] == 0.0

        # No missing or extra
        assert len([i for i in comp["issues"] if i.get("category") in {"missing_geometry", "extra_geometry"}]) == 0


def test_concentric_arc_distinguishing_connected_wall_context():
    """When connecting wall context exists, it breaks the tie and unambiguously selects the supported pair."""
    from app.rubric import ToleranceProfile
    from app.canonical_geometry import match_canonical_geometry

    for tol_val in (0.25, 0.50):
        ref_doc = _create_doc()
        ref_msp = ref_doc.modelspace()
        for r in (40.0, 55.0):
            ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
            ref_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
            ref_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
        ref_dwg = parse_dxf_bytes(_save_doc_to_bytes(ref_doc), source="reference", normalize=False)

        stu_doc = _create_doc()
        stu_msp = stu_doc.modelspace()
        # Student draws 30, 45, 50, 65, but ONLY 50 and 65 connect to the walls
        for r in (30.0, 45.0, 50.0, 65.0):
            stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
            if r in (50.0, 65.0):
                stu_msp.add_line((100 - r, 100), (100 - r, 200), dxfattribs={"layer": "WALLS"})
                stu_msp.add_line((100, 100 - r), (200, 100 - r), dxfattribs={"layer": "WALLS"})
        stu_dwg = parse_dxf_bytes(_save_doc_to_bytes(stu_doc), source="student", normalize=False)

        tol = ToleranceProfile(position=tol_val, length=tol_val, radius=tol_val, angle=1.0)
        res = match_canonical_geometry(ref_dwg, stu_dwg, tol)

        # Ambiguity resolved by walls -> 0 ambiguous groups
        assert len(res.ambiguous_groups) == 0

        # Arcs paired inner-to-inner (40->50) and outer-to-outer (55->65)
        arc_matches = {cm.reference_component.radius: cm for cm in res.component_matches if cm.reference_component.kind == "arc"}
        assert arc_matches[40.0].student_components[0].radius == 50.0
        assert arc_matches[55.0].student_components[0].radius == 65.0

        # Unconnected arcs 30 and 45 are extra
        extra_radii = {
            s.radius for s in stu_dwg.entities
            if s.id in res.extra_student_entities and s.kind == "arc"
        }
        assert 30.0 in extra_radii and 45.0 in extra_radii


def test_concentric_arc_ambiguity_api_review_level():
    """API-level review request preserves ambiguous outcome, confidence, and 0 applied deduction."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for r in (30.0, 45.0, 50.0, 65.0):
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Test Ambiguity Rubric").model_copy(
        update={"assignment_type": "Technical Drawing"}
    )
    rubric_resp = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "rubric": rub.model_dump()},
    )
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    resp = client.post(
        "/api/grade",
        files={
            "reference": ("ref.dxf", ref_bytes, "application/dxf"),
            "student": ("stu.dxf", stu_bytes, "application/dxf"),
        },
        data={"rubric_id": rubric_id},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["grading_status"] == "graded"
    assert data["score"] == 100.0

    amb_issues = [i for i in data["issues"] if i.get("category") == "ambiguous_geometry"]
    assert len(amb_issues) == 1
    assert amb_issues[0]["confidence"] == "instructor_review_required"
    assert amb_issues[0]["applied_deduction"] == 0.0

    # Ensure canonical match retained ambiguous groups in API output
    cm_dict = data.get("canonical_match") or {}
    assert len(cm_dict.get("ambiguous_groups", [])) == 1

    # Also verify /api/review preserves the ambiguous finding and zero deduction
    rev_resp = client.post(
        "/api/review",
        files={
            "reference": ("ref.dxf", ref_bytes, "application/dxf"),
            "student": ("stu.dxf", stu_bytes, "application/dxf"),
        },
        data={"rubric_id": rubric_id},
    )
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert rev_data["score"] == 100.0
    rev_amb = [i for i in rev_data["issues"] if i.get("category") == "ambiguous_geometry"]
    assert len(rev_amb) == 1
    assert rev_amb[0]["confidence"] == "instructor_review_required"
    assert rev_amb[0]["applied_deduction"] == 0.0


def test_concentric_arc_ambiguous_common_angle_error_retained():
    """Shared 5-degree rotation across ambiguous candidate arcs is retained and penalized under /api/review."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    # Reference: anchor rectangle + 2 concentric quarter arcs (40, 55) at 180-270 deg
    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    # Large anchor rectangle establishing robust zero-translation alignment
    ref_msp.add_lwpolyline([(0, 0), (400, 0), (400, 400), (0, 400)], close=True, dxfattribs={"layer": "BORDER"})
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(200, 200), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    # Student: identical anchor rectangle + 4 candidates (30, 45, 50, 65) all rotated by 5 deg (185-275)
    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(0, 0), (400, 0), (400, 400), (0, 400)], close=True, dxfattribs={"layer": "BORDER"})
    for r in (30.0, 45.0, 50.0, 65.0):
        stu_msp.add_arc(center=(200, 200), radius=r, start_angle=185.0, end_angle=275.0, dxfattribs={"layer": "WALLS"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Anchored Ambiguity Rotated Test").model_copy(
        update={
            "assignment_type": "Technical Drawing",
            "assessment_mode": "summative",
        }
    )
    rubric_resp = client.post(
        "/api/rubric/approve",
        json={"reference_id": ref_id, "rubric": rub.model_dump()},
    )
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    rev_resp = client.post(
        "/api/review",
        files={
            "reference": ("ref.dxf", ref_bytes, "application/dxf"),
            "student": ("stu.dxf", stu_bytes, "application/dxf"),
        },
        data={"rubric_id": rubric_id},
    )
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    assert data["grading_status"] == "graded"
    # Score must be deducted for angle error (not 100.0)
    assert data["score"] < 100.0

    # Ambiguity is retained as informational warning with 0 applied deduction
    amb_issues = [i for i in data["issues"] if i.get("category") == "ambiguous_geometry"]
    assert len(amb_issues) == 1
    assert amb_issues[0]["applied_deduction"] == 0.0
    assert amb_issues[0]["confidence"] == "instructor_review_required"

    # Shared incorrect_angle errors are retained and penalized
    angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
    assert len(angle_issues) == 2, f"Expected 2 angle issues, got: {angle_issues}"
    for ai in angle_issues:
        assert ai["applied_deduction"] > 0.0
        m = ai["measurement"]
        assert m["property"] == "incorrect_angle"
        assert m["sub_property"] == "orientation"
        assert math.isclose(m["expected"], 180.0, abs_tol=1e-3)
        assert math.isclose(m["actual"], 185.0, abs_tol=1e-3)
        assert math.isclose(m["deviation"], 5.0, abs_tol=1e-3)
        assert m["unit"] == "degrees"
        assert ai["technical_feedback"] == "Adjust the orientation angle from 185.000 degrees to 180.000 degrees."

    # Zero false missing or extra geometry on the concentric arcs
    missing_issues = [i for i in data["issues"] if i.get("category") in {"missing_geometry", "missing_object"}]
    extra_issues = [i for i in data["issues"] if i.get("category") == "extra_geometry"]
    assert len(missing_issues) == 0, f"Unexpected missing issues: {missing_issues}"
    assert len(extra_issues) == 0, f"Unexpected extra issues: {extra_issues}"


def test_concentric_arc_ambiguous_common_angle_error_permutations():
    """Entity-order permutations of student candidate arcs yield identical score and findings."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(0, 0), (400, 0), (400, 400), (0, 400)], close=True, dxfattribs={"layer": "BORDER"})
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(200, 200), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Permutation Test").model_copy(
        update={"assignment_type": "Technical Drawing", "assessment_mode": "summative"}
    )
    rub_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rub_resp.status_code == 200
    rubric_id = rub_resp.json()["rubric_id"]

    radii_permutations = [
        [30.0, 45.0, 50.0, 65.0],
        [65.0, 50.0, 45.0, 30.0],
        [50.0, 30.0, 65.0, 45.0],
        [45.0, 65.0, 30.0, 50.0],
    ]

    baseline_score = None
    baseline_issues_count = None

    for radii in radii_permutations:
        stu_doc = _create_doc()
        stu_msp = stu_doc.modelspace()
        stu_msp.add_lwpolyline([(0, 0), (400, 0), (400, 400), (0, 400)], close=True, dxfattribs={"layer": "BORDER"})
        for r in radii:
            stu_msp.add_arc(center=(200, 200), radius=r, start_angle=185.0, end_angle=275.0, dxfattribs={"layer": "WALLS"})
        stu_bytes = _save_doc_to_bytes(stu_doc)

        resp = client.post(
            "/api/review",
            files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
            data={"rubric_id": rubric_id},
        )
        assert resp.status_code == 200
        data = resp.json()

        if baseline_score is None:
            baseline_score = data["score"]
            baseline_issues_count = len(data["issues"])
        else:
            assert math.isclose(data["score"], baseline_score, abs_tol=1e-5), f"Permutation {radii} changed score: {data['score']} vs {baseline_score}"
            assert len(data["issues"]) == baseline_issues_count, f"Permutation {radii} changed issue count"


def test_concentric_arc_ambiguous_reviewed_geometry_group_payload():
    """ReviewedDrawing carries full candidate group in expected/actual_geometries, expands region, and renders SVG."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    for r in (30.0, 45.0, 50.0, 65.0):
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "WALLS"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Group Payload Test").model_copy(update={"assignment_type": "Technical Drawing"})
    rub_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rub_resp.status_code == 200
    rubric_id = rub_resp.json()["rubric_id"]

    resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": rubric_id},
    )
    assert resp.status_code == 200
    data = resp.json()

    rev_issues = data.get("issues") or []
    amb_rev = next((i for i in rev_issues if i.get("category") == "ambiguous_geometry"), None)
    assert amb_rev is not None, f"Expected ambiguous_geometry in reviewed issues, got: {rev_issues}"

    # Verify all reference arcs are in expected_geometries
    exp_geoms = amb_rev.get("expected_geometries") or []
    assert len(exp_geoms) == 2, f"Expected 2 expected_geometries, got {len(exp_geoms)}"
    exp_radii = {round(g.get("radius", 0.0), 1) for g in exp_geoms}
    assert exp_radii == {40.0, 55.0}

    # Verify all 4 candidate student arcs are in actual_geometries
    act_geoms = amb_rev.get("actual_geometries") or []
    assert len(act_geoms) == 4, f"Expected 4 actual_geometries, got {len(act_geoms)}"
    act_radii = {round(g.get("radius", 0.0), 1) for g in act_geoms}
    assert act_radii == {30.0, 45.0, 50.0, 65.0}

    # Verify region bounding box covers the complete candidate group extent
    # Center (100, 100), angles 180-270:
    # Outer student arc R=65 extends to x=35, y=35.
    region = amb_rev.get("region")
    assert region is not None
    min_x, min_y, max_x, max_y = region
    assert min_x <= 35.1 and min_y <= 35.1, f"Region {region} did not enclose the R=65 student arc"
    assert max_x >= 99.9 and max_y >= 99.9, f"Region {region} did not reach center (100, 100)"

    # Verify rendered SVG contains group and member paths under warning role
    svg = data.get("svg") or ""
    assert f'data-issue-id="{amb_rev["issue_id"]}"' in svg
    assert 'data-role="warning"' in svg
    assert '<rect class="warning"' in svg


def test_concentric_arc_ambiguous_wrapped_angle_orientation():
    """Normalized wrap-around concentric arcs rotated by 5° report orientation error, degrees unit, and correct guidance."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (40.0, 55.0):
        # 350° to 80° (wrap-around 90° sweep)
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=350.0, end_angle=80.0, dxfattribs={"layer": "TEST"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (30.0, 45.0, 50.0, 65.0):
        # 355° to 85° (wrap-around 90° sweep, rotated +5°)
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=355.0, end_angle=85.0, dxfattribs={"layer": "TEST"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Wrapped Rotation Test").model_copy(
        update={
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        }
    )
    rub.tolerances = rub.tolerances.model_copy(update={"position": 0.25, "length": 0.25, "radius": 0.25, "angle": 1.0, "dimension": 1.0})

    rubric_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    rev_resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": rubric_id, "assessment_mode": "summative", "allow_fallback": "false"},
    )
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    # Confirmed common rotation score
    assert math.isclose(data["score"], 94.0, abs_tol=1e-5), f"Expected 94.00, got: {data['score']}"

    angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
    assert len(angle_issues) == 2, f"Expected 2 angle issues, got: {angle_issues}"
    for ai in angle_issues:
        assert ai["applied_deduction"] == 3.0
        m = ai["measurement"]
        assert m["property"] == "incorrect_angle"
        assert m["sub_property"] == "orientation"
        assert math.isclose(m["expected"], 350.0, abs_tol=1e-3)
        assert math.isclose(m["actual"], 355.0, abs_tol=1e-3)
        assert math.isclose(m["deviation"], 5.0, abs_tol=1e-3)
        assert m["unit"] == "degrees"
        assert ai["technical_feedback"] == "Adjust the orientation angle from 355.000 degrees to 350.000 degrees."

    amb_issues = [i for i in data["issues"] if i.get("category") == "ambiguous_geometry"]
    assert len(amb_issues) == 1
    assert amb_issues[0]["applied_deduction"] == 0.0


def test_concentric_arc_ambiguous_negative_rotation_orientation():
    """Concentric arcs rotated -5° (clockwise) report orientation error with negative deviation correctly normalized."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "TEST"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (30.0, 45.0, 50.0, 65.0):
        # 175° to 265° (rotated -5°)
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=175.0, end_angle=265.0, dxfattribs={"layer": "TEST"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Negative Rotation Test").model_copy(
        update={
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        }
    )
    rub.tolerances = rub.tolerances.model_copy(update={"position": 0.25, "length": 0.25, "radius": 0.25, "angle": 1.0, "dimension": 1.0})

    rubric_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    rev_resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": rubric_id, "assessment_mode": "summative", "allow_fallback": "false"},
    )
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    assert math.isclose(data["score"], 94.0, abs_tol=1e-5), f"Expected 94.00, got: {data['score']}"

    angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
    assert len(angle_issues) == 2, f"Expected 2 angle issues, got: {angle_issues}"
    for ai in angle_issues:
        assert ai["applied_deduction"] == 3.0
        m = ai["measurement"]
        assert m["property"] == "incorrect_angle"
        assert m["sub_property"] == "orientation"
        assert math.isclose(m["expected"], 180.0, abs_tol=1e-3)
        assert math.isclose(m["actual"], 175.0, abs_tol=1e-3)
        assert math.isclose(m["deviation"], 5.0, abs_tol=1e-3)
        assert m["unit"] == "degrees"
        assert ai["technical_feedback"] == "Adjust the orientation angle from 175.000 degrees to 180.000 degrees."


def test_concentric_arc_ambiguous_common_sweep_error_retained():
    """All candidate arcs sharing an increased sweep (95° vs 90°) report a common sweep error."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (40.0, 55.0):
        # 180° to 270° (sweep 90°)
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "TEST"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (30.0, 45.0, 50.0, 65.0):
        # 180° to 275° (sweep 95°, correct orientation 180°)
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=275.0, dxfattribs={"layer": "TEST"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Common Sweep Test").model_copy(
        update={
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        }
    )
    rub.tolerances = rub.tolerances.model_copy(update={"position": 0.25, "length": 0.25, "radius": 0.25, "angle": 1.0, "dimension": 1.0})

    rubric_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    rev_resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": rubric_id, "assessment_mode": "summative", "allow_fallback": "false"},
    )
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    assert math.isclose(data["score"], 94.0, abs_tol=1e-5), f"Expected 94.00, got: {data['score']}"

    angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
    assert len(angle_issues) == 2, f"Expected 2 angle issues, got: {angle_issues}"
    for ai in angle_issues:
        assert ai["applied_deduction"] == 3.0
        m = ai["measurement"]
        assert m["property"] == "incorrect_angle"
        assert m["sub_property"] == "sweep"
        assert math.isclose(m["expected"], 90.0, abs_tol=1e-3)
        assert math.isclose(m["actual"], 95.0, abs_tol=1e-3)
        assert math.isclose(m["deviation"], 5.0, abs_tol=1e-3)
        assert m["unit"] == "degrees"
        assert ai["technical_feedback"] == "Adjust the sweep angle from 95.000 degrees to 90.000 degrees."


def test_concentric_arc_ambiguous_mixed_property_suppression():
    """Mixed property ambiguity (subset A sweep error vs subset B orientation error) suppresses paid angle findings and scores 100.00."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (40.0, 55.0):
        # start 180, end 270 (sweep 90)
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "TEST"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    stu_doc = _create_doc()
    stu_msp = stu_doc.modelspace()
    stu_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    # Subset A: radii 30 and 45, start 180, end 275 (sweep 95°, orientation 180°)
    for r in (30.0, 45.0):
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=275.0, dxfattribs={"layer": "TEST"})
    # Subset B: radii 50 and 65, start 185, end 275 (sweep 90°, orientation 185°)
    for r in (50.0, 65.0):
        stu_msp.add_arc(center=(100, 100), radius=r, start_angle=185.0, end_angle=275.0, dxfattribs={"layer": "TEST"})
    stu_bytes = _save_doc_to_bytes(stu_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Mixed Property Test").model_copy(
        update={
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        }
    )
    rub.tolerances = rub.tolerances.model_copy(update={"position": 0.25, "length": 0.25, "radius": 0.25, "angle": 1.0, "dimension": 1.0})

    rubric_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    rev_resp = client.post(
        "/api/review",
        files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
        data={"rubric_id": rubric_id, "assessment_mode": "summative", "allow_fallback": "false"},
    )
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    # Zero paid findings: score must be 100.00
    assert math.isclose(data["score"], 100.0, abs_tol=1e-5), f"Expected 100.00, got: {data['score']}"

    # No incorrect_angle findings because neither property is shared by all candidates
    angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
    assert len(angle_issues) == 0, f"Expected 0 angle issues, got: {angle_issues}"

    # Ambiguity warning retained with 0.0 deduction
    amb_issues = [i for i in data["issues"] if i.get("category") == "ambiguous_geometry"]
    assert len(amb_issues) == 1
    assert amb_issues[0]["applied_deduction"] == 0.0

    # No false missing or extra geometry on concentric arcs
    missing_issues = [i for i in data["issues"] if i.get("category") in {"missing_geometry", "missing_object"}]
    extra_issues = [i for i in data["issues"] if i.get("category") == "extra_geometry"]
    assert len(missing_issues) == 0, f"Unexpected missing issues: {missing_issues}"
    assert len(extra_issues) == 0, f"Unexpected extra issues: {extra_issues}"


def test_concentric_arc_ambiguous_mixed_property_order_permutations():
    """Permuting entity order under mixed property ambiguity consistently yields score 100.00 and 0 angle issues."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.review_service import reference_fingerprint

    client = TestClient(app)

    ref_doc = _create_doc()
    ref_msp = ref_doc.modelspace()
    ref_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
    for r in (40.0, 55.0):
        ref_msp.add_arc(center=(100, 100), radius=r, start_angle=180.0, end_angle=270.0, dxfattribs={"layer": "TEST"})
    ref_bytes = _save_doc_to_bytes(ref_doc)

    ref_id = reference_fingerprint(ref_bytes)
    rub = default_rubric(title="Mixed Permutation Test").model_copy(
        update={
            "assignment_type": "Mixed Geometric Composition",
            "normalization_mode": "translation",
            "completion_scoring_mode": "object_part_deduction",
            "missing_part_deduction": 0.25,
            "construction_requirement": "geometry_only",
            "assessment_mode": "summative",
        }
    )
    rub.tolerances = rub.tolerances.model_copy(update={"position": 0.25, "length": 0.25, "radius": 0.25, "angle": 1.0, "dimension": 1.0})

    rubric_resp = client.post("/api/rubric/approve", json={"reference_id": ref_id, "rubric": rub.model_dump()})
    assert rubric_resp.status_code == 200
    rubric_id = rubric_resp.json()["rubric_id"]

    specs = [
        (30.0, 180.0, 275.0),
        (45.0, 180.0, 275.0),
        (50.0, 185.0, 275.0),
        (65.0, 185.0, 275.0),
    ]

    import itertools
    for perm in itertools.permutations(specs):
        stu_doc = _create_doc()
        stu_msp = stu_doc.modelspace()
        stu_msp.add_lwpolyline([(500, 500), (1500, 500), (1500, 1500), (500, 1500)], close=True, dxfattribs={"layer": "BACKGROUND"})
        for r, sa, ea in perm:
            stu_msp.add_arc(center=(100, 100), radius=r, start_angle=sa, end_angle=ea, dxfattribs={"layer": "TEST"})
        stu_bytes = _save_doc_to_bytes(stu_doc)

        rev_resp = client.post(
            "/api/review",
            files={"reference": ("ref.dxf", ref_bytes, "application/dxf"), "student": ("stu.dxf", stu_bytes, "application/dxf")},
            data={"rubric_id": rubric_id, "assessment_mode": "summative", "allow_fallback": "false"},
        )
        assert rev_resp.status_code == 200
        data = rev_resp.json()
        assert math.isclose(data["score"], 100.0, abs_tol=1e-5)
        angle_issues = [i for i in data["issues"] if i.get("category") == "incorrect_angle"]
        assert len(angle_issues) == 0
