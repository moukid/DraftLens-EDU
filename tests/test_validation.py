from app.analysis import analyze_assignment
from app.models import Drawing, Entity
from app.validator import validate_reference

def _line(entity_id, start, end):
    return Entity(id=entity_id, kind="line", layer="0", points=[start, end], bbox=(min(start[0],end[0]),min(start[1],end[1]),max(start[0],end[0]),max(start[1],end[1])), centroid=((start[0]+end[0])/2,(start[1]+end[1])/2))

def _circle(entity_id, center, radius=5):
    x, y = center
    return Entity(id=entity_id, kind="circle", layer="0", points=[center], radius=radius, bbox=(x-radius,y-radius,x+radius,y+radius), centroid=center)

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
