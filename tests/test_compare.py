from tests.synthetic_data import fixture_root, samples_root
from pathlib import Path
from app.compare import compare_drawings
from app.dxf import parse_dxf_path
from app.models import Drawing, Entity
from app.rubric import default_rubric
S=samples_root()
def test_good_scores_full(): assert compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_good.dxf"))["score"]==100
def test_missing_wall_detected(): assert "MISSING_WALL" in {i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_missing_wall.dxf"))["issues"]}
def test_door_window_detected():
 c={i["code"] for i in compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_door_window_errors.dxf"))["issues"]}; assert {"DOOR_SWING","WINDOW_GEOMETRY"}<=c


def test_missing_entity_has_nullable_measurement_and_feedback():
 result=compare_drawings(parse_dxf_path(S/"reference.dxf"),parse_dxf_path(S/"student_missing_wall.dxf",source="student"))
 issue=next(i for i in result["issues"] if i["category"]=="missing_geometry")
 assert issue["measurement"] is None
 assert issue["expected"] is None and issue["actual"] is None
 assert issue["technical_feedback"]

def _line(entity_id, start, end, *, source="reference", layer=None):
    points = [tuple(start), tuple(end)]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="line",
        layer=layer or entity_id,
        source=source,
        points=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2),
    )


def _circle(entity_id, center, radius, *, source="reference", layer=None):
    x, y = center
    return Entity(
        id=entity_id,
        kind="circle",
        layer=layer or entity_id,
        source=source,
        points=[tuple(center)],
        radius=radius,
        bbox=(x - radius, y - radius, x + radius, y + radius),
        centroid=tuple(center),
    )


def _drawing(*entities):
    boxes = [entity.bbox for entity in entities]
    return Drawing(
        entities=list(entities),
        bbox=(
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
    )


def _approved_rubric(mode="translation"):
    return default_rubric().model_copy(
        update={"approved": True, "normalization_mode": mode}
    )


def test_strict_mode_preserves_coordinates_and_applies_zero_translation():
    reference = _drawing(_line("R-1", (-10, -5), (0, -5), layer="wall"))
    student = _drawing(
        _line("S-1", (-5, -5), (5, -5), source="student", layer="wall")
    )
    original_points = list(student.entities[0].points)

    result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))

    assert result["normalization"]["reference"]["translation"] == [0.0, 0.0]
    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert result["normalization"]["student"]["rejection_reason"] == "strict_mode"
    assert [issue["category"] for issue in result["issues"]] == [
        "incorrect_position"
    ]
    assert student.entities[0].points == original_points


def test_translation_mode_uses_multi_entity_consensus():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 50), (25, 50), layer="c"),
    )
    student = _drawing(
        _line("S-1", (30, -12), (40, -12), source="student", layer="a"),
        _line("S-2", (30, 8), (45, 8), source="student", layer="b"),
        _line("S-3", (30, 38), (55, 38), source="student", layer="c"),
    )
    original_points = [list(entity.points) for entity in student.entities]

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-30.0, 12.0]
    assert normalization["support_count"] == 3
    assert normalization["support_ratio"] == 1.0
    assert normalization["rejection_reason"] is None
    assert result["score"] == 100
    assert result["issues"] == []
    assert [entity.points for entity in student.entities] == original_points


def test_translation_consensus_rejects_displacement_outlier():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _line("R-4", (0, 60), (25, 60), layer="d"),
        _circle("R-5", (80, 30), 6, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (12, 7), (22, 7), source="student", layer="a"),
        _line("S-2", (12, 27), (27, 27), source="student", layer="b"),
        _line("S-3", (12, 47), (32, 47), source="student", layer="c"),
        _line("S-4", (12, 67), (37, 67), source="student", layer="d"),
        _circle("S-5", (120, 37), 6, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-12.0, -7.0]
    assert normalization["support_count"] == 4
    assert normalization["evidence_count"] == 5
    assert normalization["support_ratio"] == 0.8


def test_one_moved_entity_does_not_create_global_transform():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _circle("R-4", (60, 20), 5, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="a"),
        _line("S-2", (0, 20), (15, 20), source="student", layer="b"),
        _line("S-3", (0, 40), (20, 40), source="student", layer="c"),
        _circle("S-4", (68, 20), 5, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric("translation"))

    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert (
        result["normalization"]["student"]["rejection_reason"]
        == "consensus_translation_within_position_tolerance"
    )
    assert result["issues"] == []
    assert len(result["suppressed_findings"]) == 1
    assert result["suppressed_findings"][0]["category"] == "incorrect_position"
    assert result["match_count"] == 4

    strict_result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))
    assert [issue["category"] for issue in strict_result["issues"]] == [
        "incorrect_position"
    ]
    assert strict_result["match_count"] == 4


def test_one_resized_extreme_entity_does_not_create_global_transform():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _circle("R-4", (-100, -100), 50, layer="circle"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="a"),
        _line("S-2", (0, 20), (15, 20), source="student", layer="b"),
        _line("S-3", (0, 40), (20, 40), source="student", layer="c"),
        _circle("S-4", (-100, -100), 40, source="student", layer="circle"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    assert result["normalization"]["student"]["translation"] == [0.0, 0.0]
    assert result["match_count"] == 4
    assert not [
        issue
        for issue in result["issues"]
        if issue["category"] == "incorrect_position"
    ]


def test_majority_rigid_translation_is_accepted():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
        _line("R-3", (0, 40), (20, 40), layer="c"),
        _line("R-4", (0, 60), (25, 60), layer="d"),
        _line("R-5", (0, 80), (30, 80), layer="e"),
    )
    student = _drawing(
        _line("S-1", (20, -6), (30, -6), source="student", layer="a"),
        _line("S-2", (20, 14), (35, 14), source="student", layer="b"),
        _line("S-3", (20, 34), (40, 34), source="student", layer="c"),
        _line("S-4", (20, 54), (45, 54), source="student", layer="d"),
        _line("S-5", (45, 74), (75, 74), source="student", layer="e"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["translation"] == [-20.0, 6.0]
    assert normalization["support_count"] == 4
    assert normalization["support_ratio"] == 0.8
    assert normalization["rejection_reason"] is None


def test_insufficient_transform_support_is_rejected():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="a"),
        _line("R-2", (0, 20), (15, 20), layer="b"),
    )
    student = _drawing(
        _line("S-1", (30, 5), (40, 5), source="student", layer="a"),
        _line("S-2", (30, 25), (45, 25), source="student", layer="b"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())

    normalization = result["normalization"]["student"]
    assert normalization["candidate_translation"] == [-30.0, -5.0]
    assert normalization["translation"] == [0.0, 0.0]
    assert normalization["support_count"] == 2
    assert normalization["rejection_reason"] == "insufficient_support"


def test_repeated_geometry_matching_is_deterministic():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="same"),
        _line("R-2", (0, 0), (10, 0), layer="same"),
        _line("R-3", (0, 20), (20, 20), layer="unique"),
    )
    first_student = _drawing(
        _line("S-2", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-1", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-3", (0, 20), (20, 20), source="student", layer="unique"),
    )
    second_student = _drawing(*reversed(first_student.entities))

    first = compare_drawings(reference, first_student, rubric=_approved_rubric())
    repeated = compare_drawings(reference, first_student, rubric=_approved_rubric())
    reordered = compare_drawings(reference, second_student, rubric=_approved_rubric())

    assert first["matches"] == repeated["matches"]
    assert first["matches"] == reordered["matches"]


def test_exact_matches_are_locked_before_approximate_matching():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="same"),
        _line("R-2", (0, 4), (10, 4), layer="same"),
    )
    student = _drawing(
        _line("S-1", (0, 0), (10, 0), source="student", layer="same"),
        _line("S-2", (0, 7), (10, 7), source="student", layer="same"),
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric())
    matches = {
        item["reference_entity_id"]: item["student_entity_id"]
        for item in result["matches"]
    }

    assert matches["R-1"] == "S-1"
    assert matches["R-2"] == "S-2"


def test_reversed_line_endpoints_are_exactly_equivalent():
    reference = _drawing(
        _line("R-1", (0, 0), (10, 0), layer="wall")
    )
    student = _drawing(
        _line("S-1", (10, 0), (0, 0), source="student", layer="wall")
    )

    result = compare_drawings(reference, student, rubric=_approved_rubric("strict"))

    assert result["score"] == 100
    assert result["issues"] == []
    assert result["matches"][0]["confidence"] == 1.0

def test_equivalent_t_junction_segmentation_across_all_policies():
    """F9 regression: Equivalent T-junction geometry (20 + 80 vs 100) must receive score 100
    with 0 issues across rule_based, proportional, and object_part_deduction policies."""
    import io, ezdxf
    from app.dxf import parse_dxf_bytes

    def make_dxf(split: bool, reverse: bool = False, breakpoint: float = 20.0) -> bytes:
        doc = ezdxf.new()
        doc.units = 4
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (200, 0), (200, 200), (0, 200)], close=True)
        segs = [((50, 40), (50, 40 + breakpoint)), ((50, 40 + breakpoint), (50, 140))] if split else [((50, 40), (50, 140))]
        segs.append(((50, 40 + breakpoint), (70, 40 + breakpoint)))
        for a, b in segs:
            msp.add_line(b if reverse else a, a if reverse else b)
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode()

    cases = [
        ("split-to-merged", True, False, False),
        ("merged-to-split", False, True, False),
        ("split-to-reversed", True, False, True),
    ]
    policies = ("rule_based", "proportional", "object_part_deduction")

    for case_name, rs, ss, rev in cases:
        ref_dwg = parse_dxf_bytes(make_dxf(rs))
        stu_dwg = parse_dxf_bytes(make_dxf(ss, reverse=rev))
        for policy in policies:
            rubric = _approved_rubric().model_copy(update={
                "assignment_type": "Geometric Construction Exercise",
                "construction_requirement": "geometry_only",
                "normalization_mode": "translation",
                "completion_scoring_mode": policy,
                "missing_part_deduction": 0.5,
            })
            result = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
            assert result["score"] == 100.0, f"{case_name} under {policy} scored {result['score']}"
            assert result["issues"] == [], f"{case_name} under {policy} produced issues: {result['issues']}"


def test_inplace_assembly_individual_moved_line_not_suppressed_as_canonical_translation():
    """Verify in-place assembly parent/child translation behavior:
    1. For a multi-component in-place assembly (e.g. square with 3 edges in-place and 1 edge moved by +20Y),
       the parent assembly is anchored at (0, 0). The displaced child line cannot claim canonical translation;
       it produces an incorrect_position issue, is NOT suppressed as canonical_object_translation, and is penalized.
    2. For a legitimately movable isolated object (e.g., line 73B in 04_moved_line_73B_plus20Y.dxf),
       its independent (0, 20) translation is recognized while the anchor square remains at (0, 0)."""
    import math

    # 1. Multi-component in-place assembly with one displaced child line
    ref_assembly = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 100), layer="A"),
        _line("R-3", (100, 100), (0, 100), layer="A"),
        _line("R-4", (0, 100), (0, 0), layer="A"),
    )
    stu_assembly = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 100), source="student", layer="A"),
        _line("S-3", (100, 100), (0, 100), source="student", layer="A"),
        _line("S-4", (0, 120), (0, 20), source="student", layer="A"),  # displaced by +20Y
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })
    res_assembly = compare_drawings(ref_assembly, stu_assembly, rubric=rubric)

    # Parent assembly translation is near (0, 0) due to 3 in-place anchor lines
    assert len(res_assembly["canonical_match"]["object_translations"]) >= 1
    for t in res_assembly["canonical_match"]["object_translations"].values():
        assert math.hypot(t[0], t[1]) <= rubric.tolerances.position

    # Displaced child line must NOT be suppressed with canonical_object_translation
    displaced_suppressions = [
        s for s in res_assembly.get("suppressed_findings", [])
        if s.get("reference_entity_id") == "R-4" and s.get("suppression_reason") == "canonical_object_translation"
    ]
    assert len(displaced_suppressions) == 0, f"Displaced child line was erroneously suppressed: {displaced_suppressions}"

    # Displaced child line must produce an incorrect_position issue and score penalty
    pos_issues = [
        i for i in res_assembly["issues"]
        if i["category"] == "incorrect_position" and i.get("reference_entity_id") == "R-4"
    ]
    assert len(pos_issues) >= 1, f"Expected incorrect_position issue for displaced child line, got: {res_assembly['issues']}"
    assert res_assembly["score"] < 100.0, f"Expected penalty for displaced child line, got {res_assembly['score']}"

    # 2. In 04_moved_line_73B_plus20Y.dxf, line 73B is an isolated, legitimately movable object:
    audit_dir = fixture_root() / "simple_audit"
    ref_dwg = parse_dxf_path(audit_dir / "00_reference_000-Simple.dxf")
    stu_dwg = parse_dxf_path(audit_dir / "04_moved_line_73B_plus20Y.dxf")
    res_fixture = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)

    # Recover target line and anchor square identities from geometry
    line_73b_ref = next(
        e for e in ref_dwg.entities
        if e.kind == "line" and any(math.dist(p, (200, 0)) < 1.0 for p in e.points)
    )
    square_lines_ref = [
        e for e in ref_dwg.entities
        if e.kind == "line" and all(0.0 <= p[0] <= 100.0 and 0.0 <= p[1] <= 100.0 for p in e.points)
    ]
    square_line_ids = {e.id for e in square_lines_ref}

    # Bind to parent assessment objects
    square_obj = next(
        obj for obj in res_fixture["assessment_objects"]
        if any(eid in square_line_ids for eid in obj["source_entity_ids"])
    )
    line_73b_obj = next(
        obj for obj in res_fixture["assessment_objects"]
        if line_73b_ref.id in obj["source_entity_ids"]
    )

    translations = res_fixture["canonical_match"]["object_translations"]
    square_t = translations[square_obj["object_id"]]
    line_t = translations[line_73b_obj["object_id"]]

    # Anchor square translation is near zero; legitimately movable line has translation near (0, 20)
    assert math.hypot(square_t[0], square_t[1]) <= rubric.tolerances.position, (
        f"Square anchor translation should be near zero, got {square_t}"
    )
    assert math.hypot(line_t[0], line_t[1] - 20.0) <= rubric.tolerances.position, (
        f"Moved line translation should be near (0, 20), got {line_t}"
    )


def test_inplace_assembly_individual_moved_circle_not_suppressed_as_canonical_translation():
    """Verify that when a circle is a child of an in-place assembly (e.g. circle inside a square),
    an individual displacement produces an incorrect_position issue and is NOT suppressed with
    canonical_object_translation under translation normalization mode.
    Also verify target circle behavior in 06_moved_circle_722_plus20X.dxf under strict placement."""
    import math

    # 1. In-place assembly with contained circle moved by +20X
    ref_assembly = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 100), layer="A"),
        _line("R-3", (100, 100), (0, 100), layer="A"),
        _line("R-4", (0, 100), (0, 0), layer="A"),
        _circle("R-C", (50, 50), 20.0, layer="A"),
    )
    stu_assembly = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 100), source="student", layer="A"),
        _line("S-3", (100, 100), (0, 100), source="student", layer="A"),
        _line("S-4", (0, 100), (0, 0), source="student", layer="A"),
        _circle("S-C", (70, 50), 20.0, source="student", layer="A"),  # displaced by +20X
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })
    res_assembly = compare_drawings(ref_assembly, stu_assembly, rubric=rubric)

    # Parent assembly translation is near (0, 0) due to 4 in-place square lines
    for t in res_assembly["canonical_match"]["object_translations"].values():
        assert math.hypot(t[0], t[1]) <= rubric.tolerances.position

    # Target circle must NOT be suppressed with canonical_object_translation
    circle_suppressions = [
        s for s in res_assembly.get("suppressed_findings", [])
        if s.get("reference_entity_id") == "R-C" and s.get("suppression_reason") == "canonical_object_translation"
    ]
    assert len(circle_suppressions) == 0, f"Target circle was erroneously suppressed: {circle_suppressions}"

    # Target circle must produce an incorrect_position issue and penalty
    circle_pos_issues = [
        i for i in res_assembly["issues"]
        if i["category"] == "incorrect_position" and i.get("reference_entity_id") == "R-C"
    ]
    assert len(circle_pos_issues) >= 1, f"Expected incorrect_position issue for target circle, got: {res_assembly['issues']}"
    assert res_assembly["score"] < 100.0, f"Expected score deduction for moved circle, got {res_assembly['score']}"

    # 2. Verify target circle in 06_moved_circle_722_plus20X.dxf under strict placement:
    audit_dir = fixture_root() / "simple_audit"
    strict_rubric = _approved_rubric("strict").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })
    ref_dwg = parse_dxf_path(audit_dir / "00_reference_000-Simple.dxf")
    stu_dwg = parse_dxf_path(audit_dir / "06_moved_circle_722_plus20X.dxf")
    res_strict = compare_drawings(ref_dwg, stu_dwg, rubric=strict_rubric)

    # Derive target circle identity directly from reference geometry at (400, 100)
    circle_722_ref = next(
        e for e in ref_dwg.entities
        if e.kind == "circle" and e.centroid and math.dist(e.centroid, (400, 100)) < 1.0
    )

    # Correspondence must exist for target circle
    circle_match = next(
        (m for m in res_strict["matches"] if m.get("reference_entity_id") == circle_722_ref.id),
        None,
    )
    assert circle_match is not None, f"Expected match for circle {circle_722_ref.id}"
    assert circle_match["confidence"] >= 0.8

    # Specific child finding: target circle must have an incorrect_position issue
    circle_issue = next(
        (
            i for i in res_strict["issues"]
            if i.get("reference_entity_id") == circle_722_ref.id and i["category"] == "incorrect_position"
        ),
        None,
    )
    assert circle_issue is not None, (
        f"Expected incorrect_position issue for target circle {circle_722_ref.id}, got: {res_strict['issues']}"
    )
    assert circle_issue["applied_deduction"] == 3.0
    assert circle_issue["deduction_status"] == "applied"
    assert res_strict["score"] == 97.0

    # Suppression ownership: target circle must NOT be erroneously suppressed as canonical translation
    circle_suppressions = [
        s for s in res_strict.get("suppressed_findings", [])
        if s.get("reference_entity_id") == circle_722_ref.id and s.get("suppression_reason") == "canonical_object_translation"
    ]
    assert len(circle_suppressions) == 0, f"Target circle was erroneously suppressed: {circle_suppressions}"

    # Genuine translation mode control: circle 722 as independent object is accepted with (20, 0) transform
    res_trans = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    assert res_trans["score"] == 100.0, f"Expected 100.0 for independent movable circle under translation mode, got {res_trans['score']}"
    circle_trans_obj = next(
        obj for obj in res_trans["assessment_objects"]
        if circle_722_ref.id in obj["source_entity_ids"]
    )
    circle_t = res_trans["canonical_match"]["object_translations"][circle_trans_obj["object_id"]]
    assert math.hypot(circle_t[0] - 20.0, circle_t[1]) <= rubric.tolerances.position


def test_genuinely_translated_assembly_suppresses_position_findings():
    """Verify that when a complete assembly is genuinely translated beyond tolerance,
    the translation is recognized, position error is suppressed as canonical_object_translation,
    and score is 100.0."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="A"),
        _line("R-2", (50, 0), (25, 40), layer="A"),
        _line("R-3", (25, 40), (0, 0), layer="A"),
        _circle("R-4", (25, 15), 10.0, layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (60, 40), (110, 40), source="student", layer="A"),
        _line("S-2", (110, 40), (85, 80), source="student", layer="A"),
        _line("S-3", (85, 80), (60, 40), source="student", layer="A"),
        _circle("S-4", (85, 55), 10.0, source="student", layer="A"),
    )

    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Geometric Construction Exercise",
        "completion_scoring_mode": "object_part_deduction",
        "missing_part_deduction": 0.5,
        "construction_requirement": "geometry_only",
    })

    result = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    assert result["score"] == 100.0, f"Expected 100.0 for translated assembly, got {result['score']}"
    assert result["issues"] == [], f"Expected 0 issues for translated assembly, got {result['issues']}"


def test_compatibility_unmatched_student_entities_exact_count():
    """Verify that assess_compatibility accurately calculates unmatched_stu using unique
    student entity IDs when multiple reference entities overlap the same student entity.
    Tested under both canonical v2 (with spatial correspondences) and noncanonical contracts."""
    import pytest
    from app.compatibility import assess_compatibility
    from app.scale_diagnostics import ScaleDiagnostic

    s1 = _line("S-1", (0, 0), (50, 0), source="student")
    s2 = _line("S-2", (0, 50), (50, 50), source="student")
    s3 = _line("S-3", (0, 100), (50, 100), source="student")
    stu_dwg = _drawing(s1, s2, s3)

    r1 = _line("R-1", (0, 0), (50, 0), source="reference")
    r2 = _line("R-2", (0, 0), (50, 0), source="reference")
    ref_dwg = _drawing(r1, r2)

    # 1. Canonical v2 contract: spatial correspondences provide canonical observation ledger
    comparison_v2 = {
        "matches": [
            {"reference_entity_id": "R-1", "student_entity_id": "S-1", "confidence": 1.0, "match_quality": 1.0},
            {"reference_entity_id": "R-2", "student_entity_id": "S-1", "confidence": 1.0, "match_quality": 1.0},
        ],
        "canonical_match": {
            "spatial_correspondences": [
                {
                    "reference_component_id": "R-1",
                    "student_component_ids": ["S-1"],
                    "displacement": [0.0, 0.0],
                    "correctness": 1.0,
                    "presence": 1.0,
                },
                {
                    "reference_component_id": "R-2",
                    "student_component_ids": ["S-1"],
                    "displacement": [0.0, 0.0],
                    "correctness": 1.0,
                    "presence": 1.0,
                },
            ],
            "object_summary": {
                "total_reference_components": 2,
                "total_student_components": 3,
            },
        },
        "normalization": {"student": {"translation": [0.0, 0.0]}},
        "rubric_application": {"normalization_mode": "strict", "rubric_version": "2.0"},
    }
    scale = ScaleDiagnostic(
        detected_scale_mismatch=False,
        estimated_scale_factor=None,
        scale_support_count=0,
        scale_support_ratio=0.0,
        scale_confidence="none",
        likely_unit_or_scale_mismatch=False,
    )

    compat_v2 = assess_compatibility(ref_dwg, stu_dwg, comparison_v2, scale)
    assert compat_v2.student_supported_entity_count == 3
    assert compat_v2.confident_match_count == 2
    # Distinct matched student ID is {'S-1'} (count 1), so unmatched student count is 3 - 1 = 2
    assert compat_v2.unmatched_student_count == 2
    assert compat_v2.student_match_coverage == pytest.approx(1.0 / 3.0, abs=1e-4)

    # 2. Noncanonical v1 contract: verify fallback matching counts
    comparison_v1 = {
        "matches": [
            {"reference_entity_id": "R-1", "student_entity_id": "S-1", "confidence": 1.0, "match_quality": 1.0},
            {"reference_entity_id": "R-2", "student_entity_id": "S-1", "confidence": 1.0, "match_quality": 1.0},
        ],
        "normalization": {"student": {"translation": [0.0, 0.0]}},
        "rubric_application": {"normalization_mode": "strict", "rubric_version": "1.0"},
    }
    compat_v1 = assess_compatibility(ref_dwg, stu_dwg, comparison_v1, scale)
    assert compat_v1.student_supported_entity_count == 3
    assert compat_v1.confident_match_count == 2
    assert compat_v1.unmatched_student_count == 2


def test_formative_mode_sanitizes_all_scoring_fields_across_all_policies():
    """Verify that under assessment_mode='formative', all numeric scoring fields
    (score, deduction, requested, raw_deduction, final_applied_contribution, applied,
    weight, etc.) across summary, rubric_breakdown, audit_trail, and score_breakdown
    are sanitized to None or 'diagnostic' across rule_based, proportional, and
    object_part_deduction policies, while fully preserving diagnostics."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 100), layer="A"),
        _line("R-3", (100, 100), (0, 100), layer="A"),
        _line("R-4", (0, 100), (0, 0), layer="A"),
    )
    # Defect: line 4 is displaced by +20Y
    stu_defect = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 100), source="student", layer="A"),
        _line("S-3", (100, 100), (0, 100), source="student", layer="A"),
        _line("S-4", (0, 120), (0, 20), source="student", layer="A"),
    )
    # Rigid: whole assembly translated by (+50, +30)
    stu_rigid = _drawing(
        _line("S-1", (50, 30), (150, 30), source="student", layer="A"),
        _line("S-2", (150, 30), (150, 130), source="student", layer="A"),
        _line("S-3", (150, 130), (50, 130), source="student", layer="A"),
        _line("S-4", (50, 130), (50, 30), source="student", layer="A"),
    )

    policies = ["rule_based", "proportional", "object_part_deduction"]
    scoring_keys = {
        "score",
        "system_score",
        "deduction",
        "applied",
        "raw_deduction",
        "requested",
        "final_applied_contribution",
        "deduction_after_rule_cap",
        "deduction_after_category_cap",
        "applied_deduction",
        "raw_rule_deduction",
        "weight",
        "total_applied_deduction",
        "final_score",
        "unrounded_final_score",
        "missing_part_deduction",
        "geometry_missing_deduction",
        "completion_missing_deduction",
    }

    def assert_no_numeric_scoring_fields(obj, path="root"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in scoring_keys or k.endswith("_deduction"):
                    assert v is None or v == "diagnostic", (
                        f"Expected None or 'diagnostic' for scoring field '{path}.{k}', got: {v!r}"
                    )
                elif k in {"object_budgets", "category_split"}:
                    assert v is None or (isinstance(v, dict) and all(val is None for val in v.values())), (
                        f"Expected None or all None values for budget/split '{path}.{k}', got: {v!r}"
                    )
                else:
                    assert_no_numeric_scoring_fields(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                assert_no_numeric_scoring_fields(item, f"{path}[{idx}]")

    for policy in policies:
        for stu, label in [(stu_defect, "defect"), (stu_rigid, "rigid")]:
            rubric = _approved_rubric("translation").model_copy(update={
                "rubric_version": "2.0",
                "assessment_mode": "formative",
                "assignment_type": "Geometric Construction Exercise",
                "completion_scoring_mode": policy,
                "missing_part_deduction": 0.5,
                "construction_requirement": "geometry_only",
            })
            result = compare_drawings(ref_dwg, stu, rubric=rubric)

            # Top-level score and deduction must be None
            assert result["score"] is None, f"{policy}/{label}: score is not None"
            assert result["system_score"] is None, f"{policy}/{label}: system_score is not None"
            assert result["deduction"] is None, f"{policy}/{label}: deduction is not None"

            # In defect case, diagnostics must be retained
            if label == "defect":
                assert len(result["issues"]) >= 1, f"{policy}: expected issues retained for defect"
                assert any(i["category"] == "incorrect_position" for i in result["issues"])

            # Verify no numeric scoring fields leaked across ledgers
            assert_no_numeric_scoring_fields(result["summary"]["by_category"], f"{policy}.summary.by_category")
            assert_no_numeric_scoring_fields(result["rubric_breakdown"], f"{policy}.rubric_breakdown")
            assert_no_numeric_scoring_fields(result["score_breakdown"], f"{policy}.score_breakdown")
            assert_no_numeric_scoring_fields(result["audit_trail"], f"{policy}.audit_trail")
            assert_no_numeric_scoring_fields(result["issues"], f"{policy}.issues")


def test_subdivided_geometry_scores_100_in_both_directions():
    """Verify that equivalent subdivided/merged geometry receives score 100 with zero
    primary issues under strict v2 geometry-only grading in both directions."""
    ref_coarse = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 80), layer="A"),
        _line("R-3", (100, 80), (0, 80), layer="A"),
        _line("R-4", (0, 80), (0, 0), layer="A"),
        _line("R-5", (20, 20), (50, 20), layer="B"),
        _circle("R-6", (200, 200), 20, layer="C"),
    )
    stu_split = _drawing(
        _line("S-1a", (0, 0), (50, 0), source="student", layer="A"),
        _line("S-1b", (50, 0), (100, 0), source="student", layer="A"),
        _line("S-2a", (100, 0), (100, 40), source="student", layer="A"),
        _line("S-2b", (100, 40), (100, 80), source="student", layer="A"),
        _line("S-3a", (100, 80), (50, 80), source="student", layer="A"),
        _line("S-3b", (50, 80), (0, 80), source="student", layer="A"),
        _line("S-4a", (0, 80), (0, 40), source="student", layer="A"),
        _line("S-4b", (0, 40), (0, 0), source="student", layer="A"),
        _line("S-5a", (20, 20), (35, 20), source="student", layer="B"),
        _line("S-5b", (35, 20), (50, 20), source="student", layer="B"),
        _circle("S-6", (200, 200), 20, source="student", layer="C"),
    )
    for policy in ["rule_based", "object_part_deduction"]:
        rubric = _approved_rubric("translation").model_copy(update={
            "rubric_version": "2.0",
            "assignment_type": "Geometric Construction Exercise",
            "completion_scoring_mode": policy,
            "construction_requirement": "geometry_only",
        })
        # Forward: coarse reference -> split student
        res_fwd = compare_drawings(ref_coarse, stu_split, rubric=rubric)
        assert res_fwd["score"] == 100.0, f"Forward {policy} score expected 100.0, got {res_fwd['score']}"
        assert len(res_fwd["issues"]) == 0, f"Forward {policy} issues expected empty, got {res_fwd['issues']}"

        # Reverse: split reference -> coarse student
        ref_split = _drawing(
            _line("R-1a", (0, 0), (50, 0), layer="A"),
            _line("R-1b", (50, 0), (100, 0), layer="A"),
            _line("R-2a", (100, 0), (100, 40), layer="A"),
            _line("R-2b", (100, 40), (100, 80), layer="A"),
            _line("R-3a", (100, 80), (50, 80), layer="A"),
            _line("R-3b", (50, 80), (0, 80), layer="A"),
            _line("R-4a", (0, 80), (0, 40), layer="A"),
            _line("R-4b", (0, 40), (0, 0), layer="A"),
            _line("R-5a", (20, 20), (35, 20), layer="B"),
            _line("R-5b", (35, 20), (50, 20), layer="B"),
            _circle("R-6", (200, 200), 20, layer="C"),
        )
        stu_coarse = _drawing(
            _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
            _line("S-2", (100, 0), (100, 80), source="student", layer="A"),
            _line("S-3", (100, 80), (0, 80), source="student", layer="A"),
            _line("S-4", (0, 80), (0, 0), source="student", layer="A"),
            _line("S-5", (20, 20), (50, 20), source="student", layer="B"),
            _circle("S-6", (200, 200), 20, source="student", layer="C"),
        )
        res_rev = compare_drawings(ref_split, stu_coarse, rubric=rubric)
        assert res_rev["score"] == 100.0, f"Reverse {policy} score expected 100.0, got {res_rev['score']}"
        assert len(res_rev["issues"]) == 0, f"Reverse {policy} issues expected empty, got {res_rev['issues']}"


def test_missing_internal_span_detected_and_deducted():
    """Verify that an 8-unit missing span inside an internal line is detected with an
    incorrect_length finding (expected=30, actual=22) and points are deducted."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 80), layer="A"),
        _line("R-3", (100, 80), (0, 80), layer="A"),
        _line("R-4", (0, 80), (0, 0), layer="A"),
        _line("R-5", (20, 20), (50, 20), layer="B"),  # length 30
        _circle("R-6", (200, 200), 20, layer="C"),
    )
    # Student has (20,20)->(32,20) and (40,20)->(50,20) (8-unit missing gap in line R-5)
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 80), source="student", layer="A"),
        _line("S-3", (100, 80), (0, 80), source="student", layer="A"),
        _line("S-4", (0, 80), (0, 0), source="student", layer="A"),
        _line("S-5a", (20, 20), (32, 20), source="student", layer="B"),
        _line("S-5b", (40, 20), (50, 20), source="student", layer="B"),
        _circle("S-6", (200, 200), 20, source="student", layer="C"),
    )
    for policy in ["rule_based", "object_part_deduction"]:
        rubric = _approved_rubric("translation").model_copy(update={
            "rubric_version": "2.0",
            "assignment_type": "Geometric Construction Exercise",
            "completion_scoring_mode": policy,
            "construction_requirement": "geometry_only",
        })
        res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
        assert res["score"] < 100.0, f"{policy}: expected deduction for 8-unit missing span, got score {res['score']}"
        length_issues = [i for i in res["issues"] if i["category"] == "incorrect_length"]
        assert len(length_issues) >= 1, f"{policy}: expected incorrect_length issue"
        assert any(
            i["expected"] == 30.0 and i["actual"] == 22.0
            for i in length_issues
        ), f"{policy}: expected 30.0 actual 22.0 in {length_issues}"


def test_collinear_wall_span_with_overhang_credits_coverage_and_preserves_overhang():
    """Collinear sub-spans that overlap an uncovered part of a reference wall must not
    be misclassified as Extra, while any genuine overhang past the wall end is preserved."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 700), layer="A"),
        _line("R-3", (100, 700), (0, 700), layer="A"),
        _line("R-4", (0, 700), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 700), source="student", layer="A"),
        _line("S-3", (100, 700), (0, 700), source="student", layer="A"),
        _line("S-4a", (0, 0), (0, 335), source="student", layer="A"),
        _line("S-4b", (0, 299), (0, 753), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    extra_ids = {i.get("student_entity_id") for i in res["issues"] if i["category"] == "extra_geometry"}
    missing_ids = {i.get("reference_entity_id") for i in res["issues"] if i["category"] == "missing_geometry"}
    assert "S-4b" not in extra_ids, f"Collinear wall span S-4b misclassified as extra: {res['issues']}"
    assert "R-4" not in missing_ids, f"Covered wall R-4 misclassified as missing: {res['issues']}"
    pos_issues = [
        i for i in res["issues"]
        if i["category"] == "incorrect_position" and i.get("student_entity_id") == "S-4b"
    ]
    assert pos_issues, f"Expected overhang finding on S-4b, got {res['issues']}"
    assert any(abs(float(i["actual"]) - 53.0) <= 0.5 for i in pos_issues)


def test_whole_axially_translated_segment_still_matches_in_phase2():
    """A same-length segment translated as a whole along its axis should still be
    skipped in Phase 1 and matched 1-to-1 in Phase 2 without incorrect_length."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 100), layer="A"),
        _line("R-3", (100, 100), (0, 100), layer="A"),
        _line("R-4", (0, 100), (0, 0), layer="A"),
        _line("R-5", (20, 20), (120, 20), layer="B"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 100), source="student", layer="A"),
        _line("S-3", (100, 100), (0, 100), source="student", layer="A"),
        _line("S-4", (0, 100), (0, 0), source="student", layer="A"),
        _line("S-5", (40, 20), (140, 20), source="student", layer="B"),
    )
    rubric = _approved_rubric("strict").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    extra_ids = {i.get("student_entity_id") for i in res["issues"] if i["category"] == "extra_geometry"}
    assert "S-5" not in extra_ids
    len_issues = [i for i in res["issues"] if i["category"] == "incorrect_length" and i.get("student_entity_id") == "S-5"]
    assert not len_issues, f"Whole axially translated segment should not emit incorrect_length: {len_issues}"
    pos_issues = [i for i in res["issues"] if i["category"] == "incorrect_position" and i.get("student_entity_id") == "S-5"]
    assert pos_issues, f"Expected incorrect_position on S-5, got {res['issues']}"


def test_phase2_prefers_overlapping_near_wall_over_more_displaced_segment():
    """In Phase 2, a near-parallel segment only 3.75 units away that overlaps 100% of
    the reference wall with an overhang must beat a segment 11.25 units away whose
    centroid happens to be closer because it is shorter."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (131.21, 0), layer="A"),
        _line("R-2", (131.21, 0), (131.21, 100), layer="A"),
        _line("R-3", (0, 100), (0, 0), layer="A"),
        _line("R-4", (0, 100), (131.21, 100), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (131.21, 0), source="student", layer="A"),
        _line("S-2", (131.21, 0), (131.21, 100), source="student", layer="A"),
        _line("S-3", (0, 100), (0, 0), source="student", layer="A"),
        _line("S-4a", (-48.79, 96.25), (131.21, 96.25), source="student", layer="A"),
        _line("S-4b", (-16.89, 88.75), (148.11, 88.75), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    extra_ids = {i.get("student_entity_id") for i in res["issues"] if i["category"] == "extra_geometry"}
    assert "S-4a" not in extra_ids, f"Closer overlapping wall S-4a should win R-4 over S-4b: {res['issues']}"
    assert "S-4b" in extra_ids, f"More displaced segment S-4b should remain extra: {res['issues']}"


def test_phase2_supersedes_tiny_stub_when_displaced_full_wall_exists():
    """A tiny accidental collinear stub (<= 15% of reference length) must not lock a
    360-unit wall out of Phase 2 when a displaced 350-unit wall is available."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 360), layer="A"),
        _line("R-3", (100, 360), (0, 360), layer="A"),
        _line("R-4", (0, 360), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (100, 0), source="student", layer="A"),
        _line("S-2-stub", (100, 290), (100, 305), source="student", layer="A"),
        _line("S-2-disp", (85, 0), (85, 350), source="student", layer="A"),
        _line("S-3", (100, 360), (0, 360), source="student", layer="A"),
        _line("S-4", (0, 360), (0, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    extra_ids = {i.get("student_entity_id") for i in res["issues"] if i["category"] == "extra_geometry"}
    assert "S-2-disp" not in extra_ids, f"Displaced wall S-2-disp should match R-2 instead of being extra: {res['issues']}"
    pos_issues = [
        i for i in res["issues"]
        if i["category"] == "incorrect_position" and i.get("student_entity_id") == "S-2-disp"
    ]
    assert pos_issues, f"Expected incorrect_position on displaced wall S-2-disp, got {res['issues']}"


def test_bridged_and_closed_corners_do_not_emit_false_endpoint_gap():
    """A corner bridged by a student chamfer segment must not emit a false endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 80), layer="A"),
        _line("R-3", (100, 80), (0, 80), layer="A"),
        _line("R-4", (0, 80), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (90, 0), source="student", layer="A"),
        _line("S-chamfer", (90, 0), (100, 10), source="student", layer="A"),
        _line("S-2", (100, 10), (100, 80), source="student", layer="A"),
        _line("S-3", (100, 80), (0, 80), source="student", layer="A"),
        _line("S-4", (0, 80), (0, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [
        i for i in res["issues"]
        if i["category"] == "endpoint_gap" and i.get("classification") != "supporting_evidence"
    ]
    assert not gap_issues, f"Bridged chamfer corner should not emit primary endpoint_gap: {gap_issues}"


def test_deliberate_broken_junction_still_emits_endpoint_gap():
    """A genuine dangling/open endpoint gap must still emit endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 80), layer="A"),
        _line("R-3", (100, 80), (0, 80), layer="A"),
        _line("R-4", (0, 80), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (85, 0), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 80), source="student", layer="A"),
        _line("S-3", (100, 80), (0, 80), source="student", layer="A"),
        _line("S-4", (0, 80), (0, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for genuine broken junction, got {res['issues']}"


def test_disconnected_open_tjunctions_still_emit_endpoint_gap():
    """Two disconnected open endpoints with degree >= 2 (not closed cycles) must still emit endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (100, 0), layer="A"),
        _line("R-2", (100, 0), (100, 80), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (85, 0), source="student", layer="A"),
        _line("S-1b", (85, 0), (85, -20), source="student", layer="A"),
        _line("S-2", (100, 0), (100, 80), source="student", layer="A"),
        _line("S-2b", (100, 0), (120, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for disconnected open deg>=2 junctions, got {res['issues']}"


def test_disconnected_closed_loops_still_emit_endpoint_gap():
    """Two disconnected closed loops separated at a shared reference corner must still emit endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (20, 0), layer="A"),
        _line("R-2", (20, 0), (20, 10), layer="A"),
        _line("R-3", (20, 10), (0, 10), layer="A"),
        _line("R-4", (0, 10), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1a", (0, 0), (10, 0), source="student", layer="A"),
        _line("S-2a", (10, 0), (10, 10), source="student", layer="A"),
        _line("S-3a", (10, 10), (0, 10), source="student", layer="A"),
        _line("S-4a", (0, 10), (0, 0), source="student", layer="A"),
        _line("S-2b", (20, 0), (20, 10), source="student", layer="A"),
        _line("S-3b", (20, 10), (30, 5), source="student", layer="A"),
        _line("S-4b", (30, 5), (20, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for disconnected closed loops, got {res['issues']}"


def test_open_corner_gap_not_suppressed_by_long_path_around_rectangle():
    """An open 5-unit corner gap on a rectangle must not be suppressed by the path around the other 3 sides."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (20, 0), layer="A"),
        _line("R-2", (20, 0), (20, 20), layer="A"),
        _line("R-3", (20, 20), (0, 20), layer="A"),
        _line("R-4", (0, 20), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (15, 0), source="student", layer="A"),
        _line("S-2", (20, 0), (20, 20), source="student", layer="A"),
        _line("S-3", (20, 20), (0, 20), source="student", layer="A"),
        _line("S-4", (0, 20), (0, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for open 5-unit corner gap, got {res['issues']}"


def test_open_junction_with_dead_end_branches_still_emits_endpoint_gap():
    """An open 5-unit junction with dead-end branches (deg>=2, not closed cycles) and a long perimeter path must emit endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="A"),
        _line("R-2", (50, 0), (50, 50), layer="A"),
        _line("R-3", (50, 50), (0, 50), layer="A"),
        _line("R-4", (0, 50), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (45, 0), source="student", layer="A"),
        _line("S-1-stub", (45, 0), (45, -10), source="student", layer="A"),
        _line("S-2", (50, 0), (50, 50), source="student", layer="A"),
        _line("S-2-stub", (50, 0), (60, 0), source="student", layer="A"),
        _line("S-3", (50, 50), (0, 50), source="student", layer="A"),
        _line("S-4", (0, 50), (0, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for open junction with dead-end branches, got {res['issues']}"


def test_open_junction_with_closed_branches_still_emits_endpoint_gap():
    """An open 5-unit junction where both endpoints belong to closed cycles and only a 195-unit detour connects them must emit endpoint_gap."""
    ref_dwg = _drawing(
        _line("R-1", (0, 0), (50, 0), layer="A"),
        _line("R-2", (50, 0), (50, 50), layer="A"),
        _line("R-3", (50, 50), (0, 50), layer="A"),
        _line("R-4", (0, 50), (0, 0), layer="A"),
    )
    stu_dwg = _drawing(
        _line("S-1", (0, 0), (45, 0), source="student", layer="A"),
        _line("S-2", (50, 0), (50, 50), source="student", layer="A"),
        _line("S-3", (50, 50), (0, 50), source="student", layer="A"),
        _line("S-4", (0, 50), (0, 0), source="student", layer="A"),
        # Closed triangle loop at (45, 0)
        _line("S-L1", (45, 0), (35, -10), source="student", layer="A"),
        _line("S-L2", (35, -10), (35, -20), source="student", layer="A"),
        _line("S-L3", (35, -20), (45, 0), source="student", layer="A"),
        # Closed triangle loop at (50, 0)
        _line("S-R1", (50, 0), (60, -10), source="student", layer="A"),
        _line("S-R2", (60, -10), (60, -20), source="student", layer="A"),
        _line("S-R3", (60, -20), (50, 0), source="student", layer="A"),
    )
    rubric = _approved_rubric("translation").model_copy(update={
        "rubric_version": "2.0",
        "assignment_type": "Mixed Geometric Composition",
        "completion_scoring_mode": "object_part_deduction",
        "construction_requirement": "geometry_only",
    })
    res = compare_drawings(ref_dwg, stu_dwg, rubric=rubric)
    gap_issues = [i for i in res["issues"] if i["category"] == "endpoint_gap"]
    assert gap_issues, f"Expected endpoint_gap for open junction with closed branches, got {res['issues']}"
