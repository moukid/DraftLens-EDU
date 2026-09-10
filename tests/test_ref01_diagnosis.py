import math
from pathlib import Path
import pytest

from app.dxf import parse_dxf_bytes
from app.review_service import run_grading_pipeline, reference_fingerprint
from app.rubric import default_rubric

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ref_01"
REF_PATH = FIXTURE_DIR / "Ref-01.dxf"


@pytest.fixture(scope="module")
def ref_bytes():
    assert REF_PATH.exists(), f"Missing required fixture: {REF_PATH}"
    return REF_PATH.read_bytes()


@pytest.fixture(scope="module")
def ref_fingerprint(ref_bytes):
    return reference_fingerprint(ref_bytes)


def _grade_fixture(ref_bytes, ref_id, student_filename, mode="strict", instructor_override=False):
    student_path = FIXTURE_DIR / student_filename
    assert student_path.exists(), f"Missing required fixture: {student_path}"
    student_bytes = student_path.read_bytes()

    rubric = default_rubric("Ref-01 Rubric").model_copy(update={"approved": True})
    rubric.normalization_mode = mode
    rubric_id = f"r-{mode}-{student_filename}"

    return run_grading_pipeline(
        ref_bytes,
        student_bytes,
        rubric_id=rubric_id,
        allow_fallback=True,
        position_tolerance=2.0,
        length_tolerance=1.0,
        angle_tolerance=3.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={rubric_id: rubric},
        reference_rubrics={ref_id: rubric_id},
        rubric_references={rubric_id: ref_id},
        instructor_override=instructor_override,
    )


def test_ref01_t000_exact_baseline(ref_bytes, ref_fingerprint):
    """Ref-01-t000 is an exact copy of Ref-01; must score 100 in both strict and tolerant modes."""
    for mode in ("strict", "translation"):
        output = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t000.dxf", mode=mode)
        compat = output.compatibility
        comp = output.comparison

        assert compat.compatibility_status == "compatible"
        assert not compat.grading_withheld
        assert compat.exact_match_count == 16
        assert comp["score"] == 100.0
        assert len(comp["issues"]) == 0


def test_ref01_t001_one_independently_moved_rectangle(ref_bytes, ref_fingerprint):
    """Ref-01-t001 has one polyline rectangle (2AC) moved by 17.100 units.
    Strict: 97.0 (1 position deduction).
    Tolerant: 100.0 (independent placement difference suppressed; 0 issues)."""
    strict_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t001.dxf", mode="strict")
    assert strict_out.compatibility.compatibility_status == "compatible"
    assert strict_out.comparison["score"] == 97.0
    assert len(strict_out.comparison["issues"]) == 1
    assert strict_out.comparison["issues"][0]["category"] == "incorrect_position"
    assert strict_out.comparison["issues"][0]["applied_deduction"] == 3.0

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t001.dxf", mode="translation")
    assert tol_out.compatibility.compatibility_status == "compatible"
    assert not tol_out.compatibility.grading_withheld
    assert tol_out.comparison["score"] == 100.0
    assert len(tol_out.comparison["issues"]) == 0
    assert len(tol_out.comparison["suppressed_findings"]) == 1
    assert tol_out.comparison["suppressed_findings"][0]["category"] == "incorrect_position"
    assert tol_out.comparison["suppressed_findings"][0]["suppression_reason"] == "translation_tolerant_mode"


def test_ref01_t002_fatal_error_diagnosis_and_compatibility(ref_bytes, ref_fingerprint):
    """Ref-01-t002 moves all entities in 10 different displacement directions.
    Strict: Controlled compatibility rejection ('suspicious') or 78.0 with instructor override.
    Tolerant: 100.0, compatible, not withheld, 16 matches, 0 missing/extra."""
    out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t002.dxf", mode="strict", instructor_override=False)
    compat = out.compatibility
    comp = out.comparison

    assert compat.compatibility_status == "suspicious"
    assert compat.grading_withheld is True
    assert "weak_displacement_consensus_ratio" in compat.compatibility_reason_codes
    assert "very_low_coherent_student_coverage" in compat.compatibility_reason_codes
    assert comp["score"] is None

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t002.dxf", mode="translation", instructor_override=False)
    assert tol_out.compatibility.compatibility_status == "compatible"
    assert not tol_out.compatibility.grading_withheld
    assert "independent_placement_correspondence" in tol_out.compatibility.compatibility_reason_codes
    assert tol_out.comparison["score"] == 100.0
    assert len(tol_out.comparison["issues"]) == 0
    assert len(tol_out.comparison["matches"]) == 16
    assert len(tol_out.comparison["suppressed_findings"]) == 16

    override_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t002.dxf", mode="strict", instructor_override=True)
    assert override_out.compatibility.instructor_override is True
    assert not override_out.compatibility.grading_withheld
    assert override_out.comparison["score"] == 78.0
    assert len(override_out.comparison["matches"]) == 15
    assert len(override_out.comparison["issues"]) == 17
    categories = [iss["category"] for iss in override_out.comparison["issues"]]
    assert categories.count("missing_geometry") == 1
    assert categories.count("extra_geometry") == 1
    assert categories.count("incorrect_position") == 15


def test_ref01_t003_four_moved_entities(ref_bytes, ref_fingerprint):
    """Ref-01-t003 moves 4 lines forming rectangle 1 by 27.657 units.
    Strict: 4 position errors (-3 each) -> 88.0.
    Tolerant: 100.0 (independent placement differences suppressed; 0 issues)."""
    strict_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t003.dxf", mode="strict")
    assert strict_out.comparison["score"] == 88.0
    assert len(strict_out.comparison["issues"]) == 4
    for issue in strict_out.comparison["issues"]:
        assert issue["category"] == "incorrect_position"
        assert issue["applied_deduction"] == 3.0

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t003.dxf", mode="translation")
    assert tol_out.compatibility.compatibility_status == "compatible"
    assert not tol_out.compatibility.grading_withheld
    assert tol_out.comparison["score"] == 100.0
    assert len(tol_out.comparison["issues"]) == 0
    assert len(tol_out.comparison["suppressed_findings"]) == 4


def test_ref01_t004_eight_moved_entities_and_rubric_repeat_cap(ref_bytes, ref_fingerprint):
    """Ref-01-t004 moves 8 lines across 2 rectangles.
    Raw deduction would be 8 * 3 = 24.
    However, RULE-POSITION-01 defines repeat_cap = 15.0.
    Therefore, the 6th, 7th, and 8th errors receive applied_deduction = 0.0 ('rule_repeat_cap'),
    yielding 100 - 15 = 85.0 (not 76.0).
    Tolerant: 100.0 (all 8 position findings suppressed)."""
    strict_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t004.dxf", mode="strict")
    comp = strict_out.comparison
    assert comp["score"] == 85.0
    issues = comp["issues"]
    assert len(issues) == 8

    for i in range(5):
        assert issues[i]["category"] == "incorrect_position"
        assert issues[i]["applied_deduction"] == 3.0
        assert issues[i]["deduction_status"] == "applied"

    for i in range(5, 8):
        assert issues[i]["category"] == "incorrect_position"
        assert issues[i]["applied_deduction"] == 0.0
        assert issues[i]["deduction_status"] == "capped"
        assert issues[i]["cap_reason"] == "rule_repeat_cap"

    assert sum(iss["applied_deduction"] for iss in issues) == 15.0

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t004.dxf", mode="translation")
    assert tol_out.compatibility.compatibility_status == "compatible"
    assert not tol_out.compatibility.grading_withheld
    assert tol_out.comparison["score"] == 100.0
    assert len(tol_out.comparison["issues"]) == 0
    assert len(tol_out.comparison["suppressed_findings"]) == 8


def test_ref01_t005_rotated_line(ref_bytes, ref_fingerprint):
    """Ref-01-t005 rotates 1 line (2AE) from 157.411 to 23.899 deg.
    Scores 97.0 in both strict and tolerant modes (1 angle deduction)."""
    for mode in ("strict", "translation"):
        out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t005.dxf", mode=mode)
        assert out.comparison["score"] == 97.0
        assert len(out.comparison["issues"]) == 1
        assert out.comparison["issues"][0]["category"] == "incorrect_angle"
        assert out.comparison["issues"][0]["applied_deduction"] == 3.0


def test_ref01_t006_rotated_and_moved_line(ref_bytes, ref_fingerprint):
    """Ref-01-t006 rotates and moves 1 line (2AE).
    Strict: 94.0 (-3 position, -3 angle).
    Tolerant: 97.0 (movement ignored, wrong angle remains and is deducted)."""
    strict_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t006.dxf", mode="strict")
    assert strict_out.comparison["score"] == 94.0
    cats = {iss["category"] for iss in strict_out.comparison["issues"]}
    assert cats == {"incorrect_position", "incorrect_angle"}

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t006.dxf", mode="translation")
    assert tol_out.comparison["score"] == 97.0
    assert len(tol_out.comparison["issues"]) == 1
    assert tol_out.comparison["issues"][0]["category"] == "incorrect_angle"
    assert tol_out.comparison["issues"][0]["applied_deduction"] == 3.0
    assert len(tol_out.comparison["suppressed_findings"]) == 1
    assert tol_out.comparison["suppressed_findings"][0]["category"] == "incorrect_position"


def test_ref01_t007_rotated_moved_and_resized_line(ref_bytes, ref_fingerprint):
    """Ref-01-t007 rotates, moves, and resizes 1 line (2AE: len 25 -> 35).
    Strict: 91.0 (-3 position, -3 length, -3 angle).
    Tolerant: 94.0 (movement ignored, wrong length and angle remain and are deducted)."""
    strict_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t007.dxf", mode="strict")
    assert strict_out.comparison["score"] == 91.0
    cats = {iss["category"] for iss in strict_out.comparison["issues"]}
    assert cats == {"incorrect_position", "incorrect_length", "incorrect_angle"}

    tol_out = _grade_fixture(ref_bytes, ref_fingerprint, "Ref-01-t007.dxf", mode="translation")
    assert tol_out.comparison["score"] == 94.0
    tol_cats = {iss["category"] for iss in tol_out.comparison["issues"]}
    assert tol_cats == {"incorrect_length", "incorrect_angle"}
    assert sum(iss["applied_deduction"] for iss in tol_out.comparison["issues"]) == 6.0
    assert len(tol_out.comparison["suppressed_findings"]) == 1
    assert tol_out.comparison["suppressed_findings"][0]["category"] == "incorrect_position"


def test_ref01_synthetic_uniform_whole_drawing_translation(ref_bytes, ref_fingerprint):
    """Proves that DraftLens EDU's translation-tolerant mode DOES work 100% as designed
    when a drawing is ACTUALLY uniformly translated as a whole."""
    import ezdxf
    import io

    doc = ezdxf.read(io.StringIO(ref_bytes.decode("cp1252"), newline=None))
    msp = doc.modelspace()
    for entity in msp:
        entity.translate(50.0, 50.0, 0.0)

    out_stream = io.StringIO()
    doc.write(out_stream)
    translated_bytes = out_stream.getvalue().encode("cp1252")

    rubric_strict = default_rubric("Strict").model_copy(update={"approved": True})
    rubric_strict.normalization_mode = "strict"
    strict_out = run_grading_pipeline(
        ref_bytes, translated_bytes, rubric_id="r-strict-uni", allow_fallback=True,
        position_tolerance=2.0, length_tolerance=1.0, angle_tolerance=3.0,
        dimension_tolerance=1.0, radius_tolerance=1.0,
        rubrics={"r-strict-uni": rubric_strict},
        reference_rubrics={ref_fingerprint: "r-strict-uni"},
        rubric_references={"r-strict-uni": ref_fingerprint},
    )
    assert strict_out.comparison["score"] == 50.0
    assert any(iss["category"] == "global_drawing_displacement" for iss in strict_out.comparison["issues"])

    rubric_tol = default_rubric("Translation").model_copy(update={"approved": True})
    rubric_tol.normalization_mode = "translation"
    tol_out = run_grading_pipeline(
        ref_bytes, translated_bytes, rubric_id="r-tol-uni", allow_fallback=True,
        position_tolerance=2.0, length_tolerance=1.0, angle_tolerance=3.0,
        dimension_tolerance=1.0, radius_tolerance=1.0,
        rubrics={"r-tol-uni": rubric_tol},
        reference_rubrics={ref_fingerprint: "r-tol-uni"},
        rubric_references={"r-tol-uni": ref_fingerprint},
    )
    assert tol_out.comparison["score"] == 100.0
    assert len(tol_out.comparison["issues"]) == 0
    norm = tol_out.comparison["normalization"]["student"]
    assert norm["support_count"] == 16
    assert norm["support_ratio"] == 1.0
    assert math.dist(norm["translation"], (-50.0, -50.0)) < 1e-4
