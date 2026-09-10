from time import perf_counter

from app.analysis import analyze_assignment
from app.models import Drawing, Entity
from app.validator import validate_reference

def _line(entity_id, start, end):
    return Entity(id=entity_id, kind="line", layer="0", points=[start, end], bbox=(min(start[0],end[0]),min(start[1],end[1]),max(start[0],end[0]),max(start[1],end[1])), centroid=((start[0]+end[0])/2,(start[1]+end[1])/2))

def _circle(entity_id, center, radius=5):
    x, y = center
    return Entity(id=entity_id, kind="circle", layer="0", points=[center], radius=radius, bbox=(x-radius,y-radius,x+radius,y+radius), centroid=center)

def _polyline(entity_id, points, *, closed=False, layer="0"):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return Entity(
        id=entity_id,
        kind="polyline",
        layer=layer,
        points=list(points),
        closed=closed,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        centroid=(sum(xs) / len(xs), sum(ys) / len(ys)),
    )

def _drawing(*entities, units="mm", units_code=4):
    boxes = [entity.bbox for entity in entities]
    return Drawing(
        list(entities),
        (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
        units=units,
        units_code=units_code,
    )

def _open_polyline_findings(result):
    return [finding for finding in result["findings"] if finding["code"] == "open_polyline"]

def test_reference_validation_reports_units_and_duplicates_but_accepts_terminals():
    first = _line("R-1", (0,0), (10,0))
    duplicate = _line("R-2", (0,0), (10,0))
    disconnected = _line("R-3", (20,0), (30,0))
    drawing = Drawing([first, duplicate, disconnected], (0,0,30,0))
    result = validate_reference(drawing)
    codes = {finding["code"] for finding in result["findings"]}
    assert {"missing_units", "duplicate_geometry"} <= codes
    assert "disconnected_boundary" not in codes
    assert result["can_continue"] is True
    assert result["requires_acknowledgement"] is True

def test_standalone_arc_endpoints_do_not_create_connectivity_warning():
    entity = Entity(
        id="R-A", kind="arc", layer="0", points=[(0,0)], radius=5,
        start_angle=0, end_angle=90, bbox=(-5,-5,5,5), centroid=(0,0),
    )
    result = validate_reference(
        Drawing([entity], (-5,-5,5,5), units="mm", units_code=4)
    )
    assert result["findings"] == []
    assert len(result["topology"]["endpoints"]) == 2

def test_zero_length_reference_geometry_is_critical():
    entity = _line("R-1", (2,2), (2,2))
    result = validate_reference(Drawing([entity], (2,2,2,2), units="mm", units_code=4))
    assert result["can_continue"] is False
    assert result["summary"]["critical"] == 1

def test_closed_square_polyline_has_no_open_boundary_warning():
    square = _polyline("R-P", [(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    assert _open_polyline_findings(validate_reference(_drawing(square))) == []

def test_open_two_point_polyline_is_not_treated_as_an_incomplete_boundary():
    wall_run = _polyline("R-P", [(0, 0), (10, 0)])
    assert _open_polyline_findings(validate_reference(_drawing(wall_run))) == []

def test_open_three_point_motif_is_not_treated_as_an_incomplete_boundary():
    motif = _polyline("R-P", [(0, 0), (10, 0), (5, 8)])
    assert _open_polyline_findings(validate_reference(_drawing(motif))) == []

def test_open_u_shape_is_not_treated_as_an_incomplete_boundary():
    u_shape = _polyline("R-P", [(0, 10), (0, 0), (10, 0), (10, 10)])
    assert _open_polyline_findings(validate_reference(_drawing(u_shape))) == []

def test_near_closed_polyline_emits_exactly_one_targeted_warning():
    near_closed = _polyline(
        "R-P",
        [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0.5)],
    )
    warnings = _open_polyline_findings(validate_reference(_drawing(near_closed)))
    assert len(warnings) == 1
    finding = warnings[0]
    assert finding["code"] == "open_polyline"
    assert finding["severity"] == "warning"
    assert finding["message"] == "Polyline endpoints are nearly coincident but the polyline is not marked closed; verify the intended boundary."
    assert finding["entity_id"] == "R-P"
    assert finding["location"] == near_closed.centroid
    assert finding["entity_type"] == "LWPOLYLINE"
    assert finding["blocks_reference"] is False
    assert "nearly coincident" in finding["explanation"]
    assert "PEDIT" in finding["suggested_correction"]

def test_near_closure_classification_is_scale_consistent_for_mm_and_cm():
    millimeters = _polyline(
        "R-MM",
        [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0.5)],
    )
    centimeters = _polyline(
        "R-CM",
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.05)],
    )
    mm_findings = _open_polyline_findings(validate_reference(_drawing(millimeters)))
    cm_findings = _open_polyline_findings(
        validate_reference(_drawing(centimeters, units="cm", units_code=5))
    )
    assert len(mm_findings) == len(cm_findings) == 1

def test_many_intentional_open_polylines_do_not_create_a_warning_flood():
    entities = [
        _polyline(
            f"R-P{index:03d}",
            [(0, index * 20), (4, index * 20)],
            layer=f"PATH-{index:03d}",
        )
        for index in range(268)
    ]
    result = validate_reference(_drawing(*entities))
    assert _open_polyline_findings(result) == []
    assert result["summary"] == {
        "critical": 0,
        "warnings": 0,
        "supported_entities": 268,
        "unsupported_entities": 0,
    }

def test_complex_reference_profile_has_no_false_open_polyline_notes_and_is_bounded():
    open_polylines = [
        _polyline(
            f"R-OPEN-{index:03d}",
            [(0, index * 20), (4, index * 20)],
            layer=f"OPEN-{index:03d}",
        )
        for index in range(268)
    ]
    closed_polylines = [
        _polyline(
            f"R-CLOSED-{index:03d}",
            [
                (20, index * 20),
                (24, index * 20),
                (24, index * 20 + 4),
                (20, index * 20 + 4),
            ],
            closed=True,
            layer=f"CLOSED-{index:03d}",
        )
        for index in range(37)
    ]
    lines = [
        _line(f"R-LINE-{index:04d}", (40, index * 20), (44, index * 20))
        for index in range(1637)
    ]
    for index, line in enumerate(lines):
        line.layer = f"LINE-{index:04d}"
    drawing = _drawing(*open_polylines, *closed_polylines, *lines)

    started = perf_counter()
    validation = validate_reference(drawing)
    analysis = analyze_assignment(drawing)
    elapsed = perf_counter() - started

    assert len(drawing.entities) == 1942
    assert analysis["entity_counts"]["LWPOLYLINE"] == 305
    assert sum(entity.closed for entity in open_polylines + closed_polylines) == 37
    assert _open_polyline_findings(validation) == []
    assert validation["summary"]["critical"] == 0
    assert validation["summary"]["warnings"] == 0
    assert validation["can_continue"] is True
    assert elapsed < 5

def test_interior_plan_open_runs_remain_valid_reference_geometry():
    entities = [
        _polyline("R-WALL-1", [(0, 0), (50, 0), (50, 30)], layer="WALLS"),
        _polyline("R-WALL-2", [(60, 30), (60, 0), (110, 0)], layer="WALLS"),
        _polyline("R-OPENING", [(45, 30), (55, 30)], layer="OPENINGS"),
    ]
    result = validate_reference(_drawing(*entities))
    assert result["valid"] is True
    assert result["can_continue"] is True
    assert _open_polyline_findings(result) == []

def test_assignment_analysis_is_structured_and_deterministic():
    drawing = Drawing([_line("R-1",(0,0),(10,0)),_line("R-2",(0,5),(10,5)),_line("R-3",(0,10),(10,10))],(0,0,10,10),units="mm",units_code=4)
    result = analyze_assignment(drawing)
    assert result["entity_counts"] == {"LINE": 3}
    assert result["repeated_angles"] == [0.0]
    assert "incorrect_length" in result["suggested_checks"]

def test_abstract_geometry_profile_is_neutral_structural_and_deterministic():
    entities = [
        _line(f"R-L{index}", (0,index), (20,index)) for index in range(32)
    ] + [
        _circle(f"R-C{index}", (index * 15, 50), 5 + index % 2) for index in range(8)
    ]
    drawing = Drawing(entities, (0,0,110,55), units="cm", units_code=5)

    first = analyze_assignment(drawing)
    second = analyze_assignment(drawing)

    assert first == second
    assert first["suggested_assignment_type"] == "Mixed Geometric Composition"
    assert first["assignment_type"] is None
    assert first["likely_assignment_type"] == first["suggested_assignment_type"]
    assert first["suggested_assignment_type"] != "Islamic Geometric Pattern"
    assert {
        "radial structure",
        "repeated angles",
        "closed boundaries",
        "possible repeated or symmetric structure",
        "mixed geometric primitives",
    } <= set(first["detected_features"])


def test_duplicate_geometry_hash_grouping_is_deterministic():
    drawing = Drawing(
        [
            _line("R-1", (0, 0), (10, 0)),
            _line("R-2", (0, 0), (10, 0)),
            _line("R-3", (20, 0), (30, 0)),
        ],
        (0, 0, 30, 0),
        units="mm",
        units_code=4,
    )

    first = validate_reference(drawing)
    repeated = validate_reference(drawing)
    duplicates = [
        finding
        for finding in first["findings"]
        if finding["code"] == "duplicate_geometry"
    ]

    assert first == repeated
    assert [finding["entity_id"] for finding in duplicates] == ["R-2"]


def test_large_synthetic_reference_analysis_is_bounded_and_warning_free():
    entities = [
        _line(f"R-{index:04d}", (0, index * 20), (4, index * 20))
        for index in range(600)
    ]
    for index, entity in enumerate(entities):
        entity.layer = f"LAYER-{index:04d}"
    drawing = Drawing(
        entities,
        (0, 0, 4, (len(entities) - 1) * 20),
        units="mm",
        units_code=4,
    )

    started = perf_counter()
    validation = validate_reference(drawing)
    analysis = analyze_assignment(drawing)
    elapsed = perf_counter() - started

    assert validation["findings"] == []
    assert validation == validate_reference(drawing)
    assert analysis == analyze_assignment(drawing)
    assert validation["summary"]["supported_entities"] == len(entities)
    assert elapsed < 5


def test_critical_finding_schema_with_complete_and_missing_metadata():
    line_complete = _line("R-LINE-1", (5, 5), (5, 5))
    line_complete.source_handle = "4F"
    line_complete.layer = "WALLS"

    drawing = Drawing([line_complete], (5, 5, 5, 5), units="mm", units_code=4)
    result = validate_reference(drawing)

    assert result["can_continue"] is False
    assert result["valid"] is False
    assert result["summary"]["critical"] == 1

    findings = [f for f in result["findings"] if f["code"] == "zero_length"]
    assert len(findings) == 1
    finding = findings[0]

    # Preserved existing fields
    assert finding["code"] == "zero_length"
    assert finding["severity"] == "critical"
    assert finding["message"] == "A zero-length line makes the reference invalid."
    assert finding["entity_id"] == "R-LINE-1"
    assert finding["location"] == (5.0, 5.0)

    # Added enriched fields
    assert finding["entity_type"] == "LINE"
    assert finding["source_handle"] == "4F"
    assert finding["layer"] == "WALLS"
    assert finding["blocks_reference"] is True
    assert "identical start and end points" in finding["explanation"]
    assert "Inspect the identified entity in AutoCAD" in finding["suggested_correction"]
    assert "review the result before saving" in finding["suggested_correction"]

    # Critical finding with missing optional metadata
    circle_missing = Entity(
        id="R-CIRC-1",
        kind="circle",
        layer=None,  # type: ignore[arg-type]
        points=[(0, 0)],
        radius=0,
        source_handle=None,
        centroid=None,
    )
    result_missing = validate_reference(Drawing([circle_missing], (0, 0, 0, 0), units="mm", units_code=4))
    zero_radius = [f for f in result_missing["findings"] if f["code"] == "zero_radius"][0]
    assert zero_radius["entity_type"] == "CIRCLE"
    assert zero_radius["source_handle"] is None
    assert zero_radius["layer"] is None
    assert zero_radius["location"] is None
    assert zero_radius["blocks_reference"] is True
    assert "non-positive or zero radius" in zero_radius["explanation"]
    assert "Properties" in zero_radius["suggested_correction"]


def test_warning_finding_schema_with_complete_and_missing_metadata():
    first = _line("R-1", (0, 0), (10, 0))
    first.source_handle = "H1"
    first.layer = "VISIBLE"
    dup = _line("R-2", (0, 0), (10, 0))
    dup.source_handle = "H2"
    dup.layer = "VISIBLE"

    unsupported = [{"entity_type": "HATCH", "handle": "H3", "layer": "HATCHES"}]
    drawing = Drawing([first, dup], (0, 0, 10, 0), units="mm", units_code=4, unsupported_entities=unsupported)
    result = validate_reference(drawing)

    assert result["can_continue"] is True
    assert result["valid"] is True
    assert result["summary"]["critical"] == 0

    # Duplicate geometry warning with complete metadata
    dup_finding = [f for f in result["findings"] if f["code"] == "duplicate_geometry"][0]
    assert dup_finding["code"] == "duplicate_geometry"
    assert dup_finding["severity"] == "warning"
    assert dup_finding["entity_id"] == "R-2"
    assert dup_finding["entity_type"] == "LINE"
    assert dup_finding["source_handle"] == "H2"
    assert dup_finding["layer"] == "VISIBLE"
    assert dup_finding["blocks_reference"] is False
    assert "Multiple identical entities" in dup_finding["explanation"]
    assert "OVERKILL" in dup_finding["suggested_correction"]

    # Unsupported entity warning
    unsup_finding = [f for f in result["findings"] if f["code"] == "unsupported_entity"][0]
    assert unsup_finding["code"] == "unsupported_entity"
    assert unsup_finding["severity"] == "warning"
    assert unsup_finding["entity_id"] is None
    assert unsup_finding["location"] is None
    assert unsup_finding["entity_type"] == "HATCH"
    assert unsup_finding["source_handle"] == "H3"
    assert unsup_finding["layer"] == "HATCHES"
    assert unsup_finding["blocks_reference"] is False
    assert "not supported" in unsup_finding["explanation"]

    # Missing units warning (drawing-level, missing entity metadata)
    drawing_no_units = Drawing([first], (0, 0, 10, 0), units="unitless", units_code=0)
    result_no_units = validate_reference(drawing_no_units)
    units_finding = [f for f in result_no_units["findings"] if f["code"] == "missing_units"][0]
    assert units_finding["code"] == "missing_units"
    assert units_finding["severity"] == "warning"
    assert units_finding["entity_id"] is None
    assert units_finding["location"] is None
    assert units_finding["entity_type"] is None
    assert units_finding["source_handle"] is None
    assert units_finding["layer"] is None
    assert units_finding["blocks_reference"] is False
    assert "UNITS" in units_finding["suggested_correction"]


def test_unknown_finding_code_fallback():
    from app.validator import _finding

    critical_custom = _finding("custom_error_code", "critical", "Custom failure occurred.")
    assert critical_custom["code"] == "custom_error_code"
    assert critical_custom["severity"] == "critical"
    assert critical_custom["blocks_reference"] is True
    assert critical_custom["explanation"] == "Custom failure occurred."
    assert "AutoCAD" in critical_custom["suggested_correction"]

    warning_custom = _finding("custom_warning_code", "warning", "Custom warning occurred.")
    assert warning_custom["code"] == "custom_warning_code"
    assert warning_custom["severity"] == "warning"
    assert warning_custom["blocks_reference"] is False
    assert warning_custom["explanation"] == "Custom warning occurred."
    assert "AutoCAD" in warning_custom["suggested_correction"]


def test_blocks_reference_strictly_aligns_with_critical_severity():
    from app.validator import _finding

    for code in ("zero_length", "zero_radius"):
        finding = _finding(code, "critical", "message")
        assert finding["blocks_reference"] is True

    for code in ("missing_units", "open_polyline", "duplicate_geometry", "extreme_coordinates", "inconsistent_layers"):
        finding = _finding(code, "warning", "message")
        assert finding["blocks_reference"] is False
