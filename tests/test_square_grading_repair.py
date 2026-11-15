from __future__ import annotations

import io
import json
import os
import math
from pathlib import Path
import tempfile
import pytest

import ezdxf

from app.compare import compare_drawings
from app.dxf import parse_dxf_bytes, parse_dxf_path
from app.models import Drawing, Entity
from app.rubric import default_rubric, instructor_square_rubric, rubric_v2

REAL_CAD_DIR = Path(os.environ.get("DRAFTLENS_REAL_CAD_DIR", "local-private-cad/Square-test"))
OUTPUT_RUN_DIR = Path(os.environ.get("DRAFTLENS_OUTPUT_RUN_DIR", "local-private-evidence/Square-test"))


def _create_dxf_doc(units=ezdxf.units.MM):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 5  # Centimeters / standard
    doc.units = units
    return doc


def _save_doc_to_temp(doc, tmpdir: Path, name: str) -> Path:
    p = tmpdir / name
    stream = io.StringIO()
    doc.write(stream)
    p.write_bytes(stream.getvalue().encode("utf-8"))
    return p


def _make_square_lines(msp, origin, size=50.0, layer="0"):
    ox, oy = origin
    corners = [(ox, oy), (ox + size, oy), (ox + size, oy + size), (ox, oy + size)]
    lines = []
    for i in range(4):
        p1, p2 = corners[i], corners[(i + 1) % 4]
        lines.append(msp.add_line(p1, p2, dxfattribs={"layer": layer}))
    return lines


def _make_square_polyline(msp, origin, size=50.0, layer="0", closed=True):
    ox, oy = origin
    corners = [(ox, oy), (ox + size, oy), (ox + size, oy + size), (ox, oy + size)]
    return msp.add_lwpolyline(corners, close=closed, dxfattribs={"layer": layer})


def _build_synthetic_10_squares(tmpdir: Path, as_polylines: bool = False, missing_spec: dict[int, list[int]] | None = None) -> tuple[Path, Path]:
    """Build a 10-square reference and student file.

    missing_spec: dict of {square_index: [list of edge indices 0..3 to keep]}.
    If square_index not in missing_spec, square has all 4 edges.
    If missing_spec[square_index] == [], square is entirely absent.
    """
    # 10 squares arranged in 2 rows of 5
    origins = [(c * 100.0, r * 100.0) for r in range(2) for c in range(5)]

    # Reference doc: 40 lines
    ref_doc = _create_dxf_doc()
    ref_msp = ref_doc.modelspace()
    for origin in origins:
        _make_square_lines(ref_msp, origin, size=50.0)
    ref_path = _save_doc_to_temp(ref_doc, tmpdir, "synthetic_ref.dxf")

    # Student doc
    stu_doc = _create_dxf_doc()
    stu_msp = stu_doc.modelspace()
    missing_spec = missing_spec or {}

    for idx, origin in enumerate(origins):
        if idx in missing_spec:
            edges_to_keep = missing_spec[idx]
            if not edges_to_keep:
                continue  # entirely absent square
            ox, oy = origin
            corners = [(ox, oy), (ox + 50.0, oy), (ox + 50.0, oy + 50.0), (ox, oy + 50.0)]
            for e_idx in edges_to_keep:
                p1, p2 = corners[e_idx], corners[(e_idx + 1) % 4]
                stu_msp.add_line(p1, p2, dxfattribs={"layer": "0"})
        else:
            if as_polylines:
                _make_square_polyline(stu_msp, origin, size=50.0)
            else:
                _make_square_lines(stu_msp, origin, size=50.0)

    stu_path = _save_doc_to_temp(stu_doc, tmpdir, "synthetic_stu.dxf")
    return ref_path, stu_path


# ==============================================================================
# SECTION 1: Real CAD File Verification (Skipped cleanly if local CAD root absent)
# ==============================================================================

@pytest.mark.skipif(not REAL_CAD_DIR.exists(), reason="Real CAD test root not present on this machine")
def test_real_square_test_suite_object_part_deduction():
    """Verify all 9 real CAD files under the named instructor policy (object_part_deduction).

    Expected exact grades:
    sq_10-40_test.dxf: 100
    sq_10-10_test.dxf: 100
    sq_09-36_test.dxf: 91
    sq_09-35_test.dxf: 90
    sq_09-34_test.dxf: 89
    sq_08-32_test.dxf: 82
    sq_05-20_test.dxf: 55
    sq_04-16_test.dxf: 46
    sq_04-14_test.dxf: 44
    """
    ref_file = REAL_CAD_DIR / "sq_ref_test.dxf"
    assert ref_file.exists(), f"Reference file missing: {ref_file}"
    reference = parse_dxf_path(ref_file, source="reference")

    rubric = instructor_square_rubric(
        missing_part_deduction=1.0,
        construction_requirement="geometry_only",
        approved=True,
    )

    test_cases = [
        ("sq_10-40_test.dxf", 100.0, 65.0, 25.0, 10.0),
        ("sq_10-10_test.dxf", 100.0, 65.0, 25.0, 10.0),
        ("sq_09-36_test.dxf", 91.0, 58.5, 22.5, 10.0),
        ("sq_09-35_test.dxf", 90.0, 57.78, 22.22, 10.0),
        ("sq_09-34_test.dxf", 89.0, 57.06, 21.94, 10.0),
        ("sq_08-32_test.dxf", 82.0, 52.0, 20.0, 10.0),
        ("sq_05-20_test.dxf", 55.0, 32.5, 12.5, 10.0),
        ("sq_04-16_test.dxf", 46.0, 26.0, 10.0, 10.0),
        ("sq_04-14_test.dxf", 44.0, 24.56, 9.44, 10.0),
    ]

    results = []
    for filename, exp_total, exp_geom, exp_comp, exp_qual in test_cases:
        stu_file = REAL_CAD_DIR / filename
        assert stu_file.exists(), f"Student test file missing: {stu_file}"
        student = parse_dxf_path(stu_file, source="student")

        comparison = compare_drawings(reference, student, rubric=rubric)
        score = comparison["score"]
        breakdown = {c["id"]: c["score"] for c in comparison["rubric_breakdown"]}

        results.append({
            "filename": filename,
            "score": score,
            "expected_score": exp_total,
            "breakdown": breakdown,
            "match_count": comparison["match_count"],
            "issues_count": len(comparison["issues"]),
        })

        assert score == pytest.approx(exp_total, abs=0.01), (
            f"{filename}: expected score {exp_total}, got {score}"
        )
        assert breakdown["geometry"] == pytest.approx(exp_geom, abs=0.02), (
            f"{filename}: geometry score expected {exp_geom}, got {breakdown['geometry']}"
        )
        assert breakdown["completion"] == pytest.approx(exp_comp, abs=0.02), (
            f"{filename}: completion score expected {exp_comp}, got {breakdown['completion']}"
        )
        assert breakdown["quality"] == pytest.approx(exp_qual, abs=0.01), (
            f"{filename}: quality score expected {exp_qual}, got {breakdown['quality']}"
        )

    # Save verification output to external run directory
    try:
        OUTPUT_RUN_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_RUN_DIR / "repaired-square-test.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Notice: could not write external test log: {exc}")


@pytest.mark.skipif(not REAL_CAD_DIR.exists(), reason="Real CAD test root not present on this machine")
def test_real_square_proportional_mode():
    """Verify real CAD files under canonical proportional mode (rubric_version=2.0)."""
    ref_file = REAL_CAD_DIR / "sq_ref_test.dxf"
    reference = parse_dxf_path(ref_file, source="reference")
    rubric = rubric_v2(completion_scoring_mode="proportional", approved=True)

    # In canonical proportional mode: 90 marks / 40 edges = 2.25 marks per edge
    cases = [
        ("sq_10-40_test.dxf", 100.0),
        ("sq_10-10_test.dxf", 100.0),
        ("sq_09-35_test.dxf", 88.75),  # 5 missing edges * 2.25 = 11.25 deduction
        ("sq_09-34_test.dxf", 86.50),  # 6 missing edges * 2.25 = 13.50 deduction
        ("sq_04-14_test.dxf", 41.50),  # 26 missing edges * 2.25 = 58.50 deduction
    ]
    for filename, exp_total in cases:
        stu_file = REAL_CAD_DIR / filename
        student = parse_dxf_path(stu_file, source="student")
        comparison = compare_drawings(reference, student, rubric=rubric)
        assert comparison["score"] == pytest.approx(exp_total, abs=0.01)


# ==============================================================================
# SECTION 2: Synthetic Representation Equivalence & Invariance
# ==============================================================================

def test_synthetic_representation_equivalence():
    """Verify LINE vs LWPOLYLINE equivalence in both directions and mixed representations."""
    rubric = instructor_square_rubric(approved=True)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # 1. 40 LINEs vs 10 LWPOLYLINEs
        ref_path, stu_path = _build_synthetic_10_squares(tdp, as_polylines=True)
        ref_lines = parse_dxf_path(ref_path, source="reference")
        stu_poly = parse_dxf_path(stu_path, source="student")
        res1 = compare_drawings(ref_lines, stu_poly, rubric=rubric)
        assert res1["score"] == 100.0

        # 2. Reverse: 10 LWPOLYLINE reference vs 40 LINE student
        ref_poly = parse_dxf_path(stu_path, source="reference")
        stu_lines = parse_dxf_path(ref_path, source="student")
        res2 = compare_drawings(ref_poly, stu_lines, rubric=rubric)
        assert res2["score"] == 100.0

        # 3. Mixed: 5 squares polyline, 5 squares lines
        mixed_doc = _create_dxf_doc()
        mixed_msp = mixed_doc.modelspace()
        origins = [(c * 100.0, r * 100.0) for r in range(2) for c in range(5)]
        for i, origin in enumerate(origins):
            if i % 2 == 0:
                _make_square_polyline(mixed_msp, origin, size=50.0)
            else:
                _make_square_lines(mixed_msp, origin, size=50.0)
        mixed_path = _save_doc_to_temp(mixed_doc, tdp, "mixed.dxf")
        stu_mixed = parse_dxf_path(mixed_path, source="student")
        res3 = compare_drawings(ref_lines, stu_mixed, rubric=rubric)
        assert res3["score"] == 100.0


def test_synthetic_reordered_and_reversed_edges():
    """Verify reversed entity directions and reordered entities do not affect score."""
    rubric = instructor_square_rubric(approved=True)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ref_path, _ = _build_synthetic_10_squares(tdp)
        ref = parse_dxf_path(ref_path, source="reference")

        stu_doc = _create_dxf_doc()
        stu_msp = stu_doc.modelspace()
        origins = [(c * 100.0, r * 100.0) for r in range(2) for c in range(5)]
        # Add squares in reverse order, with reversed vertex direction
        for origin in reversed(origins):
            ox, oy = origin
            corners = [(ox, oy), (ox, oy + 50.0), (ox + 50.0, oy + 50.0), (ox + 50.0, oy)]  # CCW reversed
            for i in range(4):
                p1, p2 = corners[i], corners[(i + 1) % 4]
                stu_msp.add_line(p2, p1, dxfattribs={"layer": "0"})  # reversed start/end

        stu_path = _save_doc_to_temp(stu_doc, tdp, "reversed_stu.dxf")
        stu = parse_dxf_path(stu_path, source="student")
        res = compare_drawings(ref, stu, rubric=rubric)
        assert res["score"] == 100.0


def test_synthetic_collinear_split_edges():
    """Verify an edge split into two collinear segments is matched without penalty or extra parts."""
    rubric = instructor_square_rubric(approved=True)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ref_path, _ = _build_synthetic_10_squares(tdp)
        ref = parse_dxf_path(ref_path, source="reference")

        stu_doc = _create_dxf_doc()
        stu_msp = stu_doc.modelspace()
        origins = [(c * 100.0, r * 100.0) for r in range(2) for c in range(5)]
        for i, origin in enumerate(origins):
            ox, oy = origin
            corners = [(ox, oy), (ox + 50.0, oy), (ox + 50.0, oy + 50.0), (ox, oy + 50.0)]
            if i == 0:
                # Split bottom edge (0,0)->(50,0) into (0,0)->(20,0) and (20,0)->(50,0)
                stu_msp.add_line((ox, oy), (ox + 20.0, oy), dxfattribs={"layer": "0"})
                stu_msp.add_line((ox + 20.0, oy), (ox + 50.0, oy), dxfattribs={"layer": "0"})
                # other 3 edges normal
                for k in range(1, 4):
                    stu_msp.add_line(corners[k], corners[(k + 1) % 4], dxfattribs={"layer": "0"})
            else:
                _make_square_lines(stu_msp, origin, size=50.0)

        stu_path = _save_doc_to_temp(stu_doc, tdp, "split_stu.dxf")
        stu = parse_dxf_path(stu_path, source="student")
        res = compare_drawings(ref, stu, rubric=rubric)
        assert res["score"] == 100.0


# ==============================================================================
# SECTION 3: Synthetic Deletion Chain & Monotonicity
# ==============================================================================

def test_synthetic_deletion_chain():
    """Verify the exact chain 40 -> 36 -> 35 -> 34 -> 32 -> 20 -> 16 -> 14 under p=1.0."""
    rubric = instructor_square_rubric(missing_part_deduction=1.0, approved=True)

    specs = {
        40: {},  # 10 full squares
        36: {9: []},  # square 9 entirely absent
        35: {8: [0, 1, 2], 9: []},  # square 8 missing 1 edge, square 9 absent
        34: {8: [0, 1], 9: []},  # square 8 missing 2 edges, square 9 absent
        32: {8: [], 9: []},  # squares 8 & 9 absent
        20: {5: [], 6: [], 7: [], 8: [], 9: []},  # 5 absent
        16: {4: [], 5: [], 6: [], 7: [], 8: [], 9: []},  # 6 absent
        14: {3: [0, 1], 4: [], 5: [], 6: [], 7: [], 8: [], 9: []},  # 6 absent + 1 with 2 edges
    }
    expected_scores = {
        40: 100.0,
        36: 91.0,
        35: 90.0,
        34: 89.0,
        32: 82.0,
        20: 55.0,
        16: 46.0,
        14: 44.0,
    }

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for count, spec in specs.items():
            ref_path, stu_path = _build_synthetic_10_squares(tdp, missing_spec=spec)
            ref = parse_dxf_path(ref_path, source="reference")
            stu = parse_dxf_path(stu_path, source="student")
            res = compare_drawings(ref, stu, rubric=rubric)
            exp = expected_scores[count]
            assert res["score"] == pytest.approx(exp, abs=0.01), (
                f"Chain count {count}: expected {exp}, got {res['score']}"
            )


def test_synthetic_targeted_deletions_single_object():
    """Test 4 -> 3 -> 2 -> 1 -> 0 edges of one reference object to prove strict monotonicity."""
    rubric = instructor_square_rubric(missing_part_deduction=1.0, approved=True)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        scores = []
        for edges_kept in [
            [0, 1, 2, 3],  # 4 edges (complete square)
            [0, 1, 2],     # 3 edges (1 missing)
            [0, 1],        # 2 edges (2 missing)
            [0],           # 1 edge  (3 missing)
            [],            # 0 edges (4 missing / whole object absent)
        ]:
            ref_path, stu_path = _build_synthetic_10_squares(tdp, missing_spec={0: edges_kept})
            ref = parse_dxf_path(ref_path, source="reference")
            stu = parse_dxf_path(stu_path, source="student")
            res = compare_drawings(ref, stu, rubric=rubric)
            scores.append(res["score"])

        # Expected:
        # 4 edges: 100.0 (0 deduction)
        # 3 edges: 99.0 (1 missing edge -> 1.0 deduction)
        # 2 edges: 98.0 (2 missing edges -> 2.0 deduction)
        # 1 edge:  97.0 (3 missing edges -> 3.0 deduction)
        # 0 edges: 91.0 (absent square -> 9.0 deduction)
        assert scores == [100.0, 99.0, 98.0, 97.0, 91.0]

        # Verify strict monotonicity: scores strictly decrease
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1], f"Score did not decrease: {scores[i]} vs {scores[i+1]}"


def test_synthetic_configurable_p():
    """Verify configurable p parameter (p=0.5, p=0.25)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # 35 edges: square 8 missing 1 edge, square 9 absent (1*9.0 + 1*p deduction)
        ref_path, stu_path = _build_synthetic_10_squares(tdp, missing_spec={8: [0, 1, 2], 9: []})
        ref = parse_dxf_path(ref_path, source="reference")
        stu = parse_dxf_path(stu_path, source="student")

        # p = 0.5 -> 100 - 9.0 - 0.5 = 90.50
        r_half = instructor_square_rubric(missing_part_deduction=0.5, approved=True)
        res_half = compare_drawings(ref, stu, rubric=r_half)
        assert res_half["score"] == pytest.approx(90.50, abs=0.01)

        # p = 0.25 -> 100 - 9.0 - 0.25 = 90.75
        r_quarter = instructor_square_rubric(missing_part_deduction=0.25, approved=True)
        res_quarter = compare_drawings(ref, stu, rubric=r_quarter)
        assert res_quarter["score"] == pytest.approx(90.75, abs=0.01)

        # Three missing edges with fractional p = 1/3 (square 0 missing 3 edges):
        # Full precision: 100 - 3 * (1/3) = 99.00 (NOT 99.01 from premature rounding)
        ref_p3, stu_p3 = _build_synthetic_10_squares(tdp, missing_spec={0: [0]})
        ref3 = parse_dxf_path(ref_p3, source="reference")
        stu3 = parse_dxf_path(stu_p3, source="student")
        r_third = instructor_square_rubric(missing_part_deduction=1.0 / 3.0, approved=True)
        res_third = compare_drawings(ref3, stu3, rubric=r_third)
        assert res_third["score"] == 99.00
        assert res_third["deduction"] == 1.00


# ==============================================================================
# SECTION 4: Construction Requirements & Dependent Suppression
# ==============================================================================

def test_construction_requirement_closed_polyline():
    """Verify geometry_only accepts lines vs closed_polyline requires joined polylines."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ref_path, stu_path = _build_synthetic_10_squares(tdp, as_polylines=False)
        ref = parse_dxf_path(ref_path, source="reference")
        stu_lines = parse_dxf_path(stu_path, source="student")

        # 1. geometry_only: 4 lines are accepted without deduction
        r_geom = instructor_square_rubric(construction_requirement="geometry_only", approved=True)
        res_geom = compare_drawings(ref, stu_lines, rubric=r_geom)
        assert res_geom["score"] == 100.0

        # 2. closed_polyline: 4 lines receive a construction policy deduction
        r_poly = instructor_square_rubric(construction_requirement="closed_polyline", approved=True)
        res_poly = compare_drawings(ref, stu_lines, rubric=r_poly)
        assert res_poly["score"] < 100.0
        assert any(i["code"] == "CONSTRUCTION_POLICY" for i in res_poly["issues"])


def test_dependent_connectivity_suppression():
    """Verify missing edge suppresses open_polyline/endpoint_gap consequence findings."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # Square 8 has 3 of 4 edges (missing 1 edge)
        ref_path, stu_path = _build_synthetic_10_squares(tdp, missing_spec={8: [0, 1, 2]})
        ref = parse_dxf_path(ref_path, source="reference")
        stu = parse_dxf_path(stu_path, source="student")

        rubric = instructor_square_rubric(approved=True)
        res = compare_drawings(ref, stu, rubric=rubric)

        # Only 1 primary issue (MISSING_PART)
        primary_issues = [i for i in res["issues"] if i["classification"] == "primary"]
        assert len(primary_issues) == 1
        assert primary_issues[0]["code"] == "MISSING_PART"

        # The missing part issue links the open boundary consequence as derived evidence
        derived = primary_issues[0].get("derived_evidence") or []
        assert any(
            d.get("reason") == "consequence_of_missing_part"
            for d in derived
        )

        # When reference is a closed polyline and student has an open polyline missing an edge,
        # open_polyline finding is suppressed with consequence_of_missing_part
        ref_poly_doc = _create_dxf_doc()
        ref_msp = ref_poly_doc.modelspace()
        _make_square_polyline(ref_msp, (0, 0), size=50.0, closed=True)
        ref_poly_path = _save_doc_to_temp(ref_poly_doc, tdp, "ref_poly.dxf")

        stu_open_doc = _create_dxf_doc()
        stu_msp = stu_open_doc.modelspace()
        stu_msp.add_lwpolyline([(0, 0), (50, 0), (50, 50)], close=False, dxfattribs={"layer": "0"})
        stu_open_path = _save_doc_to_temp(stu_open_doc, tdp, "stu_open.dxf")

        res_poly = compare_drawings(
            parse_dxf_path(ref_poly_path, source="reference"),
            parse_dxf_path(stu_open_path, source="student"),
            rubric=rubric,
        )
        assert any(
            s.get("suppression_reason") == "consequence_of_missing_part"
            for s in res_poly["suppressed_findings"]
        )


# ==============================================================================
# SECTION 5: Defect Retainers (Accuracy, Placement, Extra, Duplicate)
# ==============================================================================

def test_defects_receive_intended_penalties():
    """Verify genuine defects (wrong length, wrong position, extra, duplicate) are still penalized."""
    rubric = instructor_square_rubric(approved=True)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ref_path, _ = _build_synthetic_10_squares(tdp)
        ref = parse_dxf_path(ref_path, source="reference")

        # 1. Wrong length edge (shortened by 10 units)
        doc1 = _create_dxf_doc()
        msp1 = doc1.modelspace()
        origins = [(c * 100.0, r * 100.0) for r in range(2) for c in range(5)]
        for i, origin in enumerate(origins):
            ox, oy = origin
            corners = [(ox, oy), (ox + 50.0, oy), (ox + 50.0, oy + 50.0), (ox, oy + 50.0)]
            if i == 0:
                # bottom edge shortened to 40
                msp1.add_line((ox, oy), (ox + 40.0, oy), dxfattribs={"layer": "0"})
                for k in range(1, 4):
                    msp1.add_line(corners[k], corners[(k + 1) % 4], dxfattribs={"layer": "0"})
            else:
                _make_square_lines(msp1, origin, size=50.0)
        p1 = _save_doc_to_temp(doc1, tdp, "wrong_len.dxf")
        res1 = compare_drawings(ref, parse_dxf_path(p1, source="student"), rubric=rubric)
        assert res1["score"] < 100.0
        assert any(i["category"] in {"incorrect_length", "endpoint_gap"} for i in res1["issues"])

        # 2. Extra edge
        doc2 = _create_dxf_doc()
        msp2 = doc2.modelspace()
        for origin in origins:
            _make_square_lines(msp2, origin, size=50.0)
        msp2.add_line((500, 500), (550, 500), dxfattribs={"layer": "0"})  # rogue extra line
        p2 = _save_doc_to_temp(doc2, tdp, "extra.dxf")
        res2 = compare_drawings(ref, parse_dxf_path(p2, source="student"), rubric=rubric)
        assert res2["score"] < 100.0
        assert any(i["category"] == "extra_geometry" for i in res2["issues"])

        # 3. Duplicate edge
        doc3 = _create_dxf_doc()
        msp3 = doc3.modelspace()
        for origin in origins:
            _make_square_lines(msp3, origin, size=50.0)
        ox, oy = origins[0]
        msp3.add_line((ox, oy), (ox + 50.0, oy), dxfattribs={"layer": "0"})  # duplicate bottom line
        p3 = _save_doc_to_temp(doc3, tdp, "duplicate.dxf")
        res3 = compare_drawings(ref, parse_dxf_path(p3, source="student"), rubric=rubric)
        assert res3["score"] < 100.0
        assert any(i["category"] == "duplicate_geometry" for i in res3["issues"])


def test_rule_based_mode_monotonicity():
    """Verify that in rule_based mode, deleting geometry never increases the score."""
    rubric = default_rubric().model_copy(update={"approved": True, "completion_scoring_mode": "rule_based"})

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # Compare 40 edges vs 36 edges vs 20 edges
        ref_path, stu40_path = _build_synthetic_10_squares(tdp, missing_spec={})
        _, stu36_path = _build_synthetic_10_squares(tdp, missing_spec={9: []})
        _, stu20_path = _build_synthetic_10_squares(tdp, missing_spec={5: [], 6: [], 7: [], 8: [], 9: []})

        ref = parse_dxf_path(ref_path, source="reference")
        res40 = compare_drawings(ref, parse_dxf_path(stu40_path, source="student"), rubric=rubric)
        res36 = compare_drawings(ref, parse_dxf_path(stu36_path, source="student"), rubric=rubric)
        res20 = compare_drawings(ref, parse_dxf_path(stu20_path, source="student"), rubric=rubric)

        assert res40["score"] >= res36["score"]
        assert res36["score"] >= res20["score"]


def test_generalization_non_square_objects():
    """Verify object decomposition and budget allocation generalize to non-square shapes."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ref_doc = _create_dxf_doc()
        ref_msp = ref_doc.modelspace()
        # 3 circles and 2 rectangles
        ref_msp.add_circle((0, 0), 20.0)
        ref_msp.add_circle((100, 0), 25.0)
        ref_msp.add_circle((200, 0), 30.0)
        _make_square_lines(ref_msp, (0, 100), size=40.0)
        _make_square_lines(ref_msp, (100, 100), size=60.0)
        ref_path = _save_doc_to_temp(ref_doc, tdp, "mixed_ref.dxf")
        ref = parse_dxf_path(ref_path, source="reference")

        # Student missing 1 circle
        stu_doc = _create_dxf_doc()
        stu_msp = stu_doc.modelspace()
        stu_msp.add_circle((100, 0), 25.0)
        stu_msp.add_circle((200, 0), 30.0)
        _make_square_lines(stu_msp, (0, 100), size=40.0)
        _make_square_lines(stu_msp, (100, 100), size=60.0)
        stu_path = _save_doc_to_temp(stu_doc, tdp, "mixed_stu.dxf")
        stu = parse_dxf_path(stu_path, source="student")

        rubric = instructor_square_rubric(approved=True)
        res = compare_drawings(ref, stu, rubric=rubric)

        # 5 equal objects -> each has 18 marks (65+25 / 5 = 18).
        # Missing 1 object loses 18 marks -> 100 - 18 = 82.0
        assert res["score"] == pytest.approx(82.0, abs=0.01)
