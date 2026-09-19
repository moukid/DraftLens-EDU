import io
import base64
import ezdxf
import pytest
from app.dxf import parse_dxf_bytes
from app.models import Entity
from app.reference_objects import (
    DEFAULT_CODE_MAPPINGS,
    ReferenceMarker,
    ReferenceObject,
    build_proposed_reference_objects,
    evaluate_student_object_correspondence,
    extract_reference_markers_and_legend,
    is_info_layer,
)
from app.review_service import run_grading_pipeline
from fastapi.testclient import TestClient
from app.main import app, REFERENCE_OBJECTS, REFERENCE_RUBRICS, RUBRICS


def _dxf_bytes(doc: ezdxf.document.Drawing) -> bytes:
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def test_is_info_layer():
    assert is_info_layer("DL-Info") is True
    assert is_info_layer("dl-info") is True
    assert is_info_layer("DL-INFO-TAGS") is True
    assert is_info_layer("dl-info-legend") is True
    assert is_info_layer("DL-INFO-REGIONS") is True
    assert is_info_layer("DL-Info-Doors") is True
    assert is_info_layer("dl-info-notes") is True
    assert is_info_layer("  DL-INFO-TAGS  ") is True

    assert is_info_layer("0") is False
    assert is_info_layer("WALLS") is False
    assert is_info_layer("DOORS") is False
    assert is_info_layer("DL-EXTRA-INFO") is False
    assert is_info_layer("FLOOR-DL-Info") is False
    assert is_info_layer("") is False

    assert is_info_layer("CUSTOM_TAGS", custom_layers={"CUSTOM_TAGS"}) is True
    assert is_info_layer("custom_tags", custom_layers={"CUSTOM_TAGS"}) is True


def test_extract_reference_markers_and_legend_separation():
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    # Plan markers
    t1 = msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (100.0, 200.0)})
    t2 = msp.add_text("W1", dxfattribs={"layer": "DL-INFO-TAGS", "insert": (150.0, 200.0)})
    t3 = msp.add_text("C1", dxfattribs={"layer": "DL-Info", "insert": (50.0, 100.0)})

    # Marker outline for D1
    msp.add_lwpolyline([(95.0, 195.0), (105.0, 195.0), (105.0, 205.0), (95.0, 205.0)], dxfattribs={"layer": "DL-Info"})

    # Legend marker on explicit DL-INFO-LEGEND layer
    msp.add_text("D1", dxfattribs={"layer": "DL-INFO-LEGEND", "insert": (500.0, 50.0)})

    # Legend marker inside legend bounding box
    msp.add_text("W1", dxfattribs={"layer": "DL-Info", "insert": (510.0, 60.0)})

    drawing = parse_dxf_bytes(_dxf_bytes(doc), exclude_info_layers=False)

    unsupported = [
        {"entity_type": "ACAD_TABLE", "layer": "0", "handle": "TBL1", "insert": (500.0, 40.0)}
    ]

    legend_bbox = (490.0, 30.0, 550.0, 80.0)
    plan_markers, legend_markers, meta = extract_reference_markers_and_legend(
        drawing.entities,
        unsupported,
        legend_region_bbox=legend_bbox,
    )

    assert meta["total_markers_detected"] == 5
    assert meta["plan_markers_count"] == 3
    assert meta["legend_samples_count"] == 2
    assert meta["legend_tables_detected"] == 1

    # Plan markers must be sorted: y descending (200, 200, 100), then x ascending
    assert [m.code for m in plan_markers] == ["D1", "W1", "C1"]
    assert plan_markers[0].location == (100.0, 200.0)
    assert plan_markers[0].meaning == "Door"
    assert len(plan_markers[0].outline_points) == 4

    # Legend markers have exclusion reasons
    assert any("DL-INFO-LEGEND" in (m.exclusion_reason or "") for m in legend_markers)
    assert any("legend region" in (m.exclusion_reason or "") for m in legend_markers)


def test_build_proposed_reference_objects_and_deterministic_ids():
    markers = [
        ReferenceMarker(code="D1", meaning="Door", location=(100.0, 200.0), layer="DL-Info"),
        ReferenceMarker(code="D1", meaning="Door", location=(150.0, 200.0), layer="DL-Info"),
        ReferenceMarker(code="W1", meaning="Window", location=(50.0, 100.0), layer="DL-Info"),
        ReferenceMarker(code="X9", meaning=None, location=(10.0, 10.0), layer="DL-Info"),
    ]

    # Reference entities near markers
    e1 = Entity(id="R1", kind="line", layer="DOORS", points=[(98.0, 198.0), (102.0, 202.0)], centroid=(100.0, 200.0))
    e2 = Entity(id="R2", kind="line", layer="DOORS", points=[(148.0, 198.0), (152.0, 202.0)], centroid=(150.0, 200.0))
    e3 = Entity(id="R3", kind="line", layer="WALLS", points=[(49.0, 99.0), (51.0, 101.0)], centroid=(50.0, 100.0))
    e_far = Entity(id="R_FAR", kind="line", layer="WALLS", points=[(900.0, 900.0), (910.0, 910.0)], centroid=(905.0, 905.0))

    objects, summary = build_proposed_reference_objects(markers, [e1, e2, e3, e_far], search_radius=30.0)

    assert len(objects) == 4
    assert objects[0].occurrence_id == "D1-001"
    assert objects[0].meaning == "Door"
    assert objects[0].member_entity_ids == ["R1"]
    assert objects[0].status == "proposed"

    assert objects[1].occurrence_id == "D1-002"
    assert objects[1].member_entity_ids == ["R2"]

    assert objects[2].occurrence_id == "W1-001"
    assert objects[2].meaning == "Window"
    assert objects[2].member_entity_ids == ["R3"]

    # Unknown code X9
    assert objects[3].occurrence_id == "X9-001"
    assert objects[3].meaning == "Unmapped (X9)"
    assert objects[3].status == "unresolved"
    assert "X9" in summary["unknown_codes"]

    assert summary["counts_by_type"] == {"D1": 2, "W1": 1, "X9": 1}
    assert summary["counts_by_status"]["proposed"] == 3
    assert summary["counts_by_status"]["unresolved"] == 1
    assert "R_FAR" not in objects[0].member_entity_ids


def test_overlapping_memberships_detection():
    # Two markers close together claiming the same entity
    markers = [
        ReferenceMarker(code="D1", meaning="Door", location=(100.0, 100.0), layer="DL-Info"),
        ReferenceMarker(code="DD1", meaning="Double Door", location=(105.0, 102.0), layer="DL-Info"),
    ]
    shared_entity = Entity(id="R_SHARED", kind="line", layer="DOORS", points=[(100.0, 100.0), (105.0, 102.0)], centroid=(102.5, 101.0))

    objects, summary = build_proposed_reference_objects(markers, [shared_entity], search_radius=20.0)

    assert summary["has_overlapping_memberships"] is True
    assert len(summary["overlapping_memberships"]) == 1
    assert summary["overlapping_memberships"][0]["entity_id"] == "R_SHARED"
    assert set(summary["overlapping_memberships"][0]["shared_between_objects"]) == {"D1-001", "DD1-001"}

    assert objects[0].shared_entity_ids == ["R_SHARED"]
    assert objects[1].shared_entity_ids == ["R_SHARED"]


def test_evaluate_student_object_correspondence():
    confirmed = [
        ReferenceObject(
            occurrence_id="D1-001",
            type_code="D1",
            meaning="Door",
            marker_location=(100.0, 200.0),
            member_entity_ids=["R1", "R2"],
            status="confirmed",
        ),
        ReferenceObject(
            occurrence_id="W1-001",
            type_code="W1",
            meaning="Window",
            marker_location=(50.0, 100.0),
            member_entity_ids=["R3", "R4"],
            status="confirmed",
        ),
        ReferenceObject(
            occurrence_id="C1-001",
            type_code="C1",
            meaning="Column",
            marker_location=(10.0, 10.0),
            member_entity_ids=["R5"],
            status="confirmed",
        ),
        ReferenceObject(
            occurrence_id="S1-001",
            type_code="S1",
            meaning="Stairs",
            marker_location=(300.0, 300.0),
            member_entity_ids=[],
            status="confirmed",
        ),
        ReferenceObject(
            occurrence_id="EXCLUDED-001",
            type_code="D1",
            meaning="Door",
            marker_location=(0.0, 0.0),
            member_entity_ids=["R99"],
            status="excluded",
        ),
    ]

    matches = [
        {"reference_entity_id": "R1", "student_entity_id": "S1"},
        {"reference_entity_id": "R2", "student_entity_id": "S2"},
        {"reference_entity_id": "R3", "student_entity_id": "S3"},
    ]

    corr = evaluate_student_object_correspondence(confirmed, matches)

    assert len(corr) == 4
    c_map = {c.occurrence_id: c for c in corr}

    assert c_map["D1-001"].status == "present"
    assert c_map["D1-001"].matched_members == 2
    assert c_map["D1-001"].total_members == 2

    assert c_map["W1-001"].status == "partial"
    assert c_map["W1-001"].matched_members == 1
    assert c_map["W1-001"].total_members == 2

    assert c_map["C1-001"].status == "missing"
    assert c_map["C1-001"].matched_members == 0
    assert c_map["C1-001"].total_members == 1

    assert c_map["S1-001"].status == "uncertain"
    assert "No confirmed member entities" in c_map["S1-001"].explanation


def test_grading_invariance_with_info_layers():
    """Identical base geometry with vs without info layers must produce identical scores."""
    base_doc = ezdxf.new("R2010")
    base_doc.units = ezdxf.units.MM
    msp_base = base_doc.modelspace()
    msp_base.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
    msp_base.add_line((100, 0), (100, 100), dxfattribs={"layer": "WALLS"})
    msp_base.add_line((100, 100), (0, 100), dxfattribs={"layer": "WALLS"})
    msp_base.add_line((0, 100), (0, 0), dxfattribs={"layer": "WALLS"})
    base_ref_bytes = _dxf_bytes(base_doc)

    tagged_doc = ezdxf.new("R2010")
    tagged_doc.units = ezdxf.units.MM
    msp_tagged = tagged_doc.modelspace()
    msp_tagged.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
    msp_tagged.add_line((100, 0), (100, 100), dxfattribs={"layer": "WALLS"})
    msp_tagged.add_line((100, 100), (0, 100), dxfattribs={"layer": "WALLS"})
    msp_tagged.add_line((0, 100), (0, 0), dxfattribs={"layer": "WALLS"})
    # Add info layer content
    msp_tagged.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (50, 0)})
    msp_tagged.add_text("W1", dxfattribs={"layer": "DL-INFO-TAGS", "insert": (100, 50)})
    msp_tagged.add_lwpolyline([(45, -5), (55, -5), (55, 5), (45, 5)], dxfattribs={"layer": "DL-Info"})
    msp_tagged.add_text("D1", dxfattribs={"layer": "DL-INFO-LEGEND", "insert": (300, 300)})
    tagged_ref_bytes = _dxf_bytes(tagged_doc)

    stu_doc = ezdxf.new("R2010")
    stu_doc.units = ezdxf.units.MM
    msp_stu = stu_doc.modelspace()
    msp_stu.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((100, 0), (100, 100), dxfattribs={"layer": "WALLS"})
    msp_stu.add_line((100, 100), (0, 100), dxfattribs={"layer": "WALLS"})
    stu_bytes = _dxf_bytes(stu_doc)

    base_ref_drawing = parse_dxf_bytes(base_ref_bytes, exclude_info_layers=True)
    tagged_ref_drawing = parse_dxf_bytes(tagged_ref_bytes, exclude_info_layers=True)

    assert len(base_ref_drawing.entities) == len(tagged_ref_drawing.entities) == 4
    assert len(tagged_ref_drawing.info_entities) > 0
    assert len(base_ref_drawing.info_entities) == 0

    pipeline_kwargs = dict(
        rubric_id=None,
        allow_fallback=True,
        position_tolerance=1.0,
        length_tolerance=1.0,
        angle_tolerance=1.0,
        dimension_tolerance=1.0,
        radius_tolerance=1.0,
        rubrics={},
        reference_rubrics={},
        rubric_references={},
    )
    out_base = run_grading_pipeline(base_ref_bytes, stu_bytes, **pipeline_kwargs)
    out_tagged = run_grading_pipeline(tagged_ref_bytes, stu_bytes, **pipeline_kwargs)

    assert out_base.comparison["score"] == out_tagged.comparison["score"]
    assert len(out_base.comparison["issues"]) == len(out_tagged.comparison["issues"])


def test_api_reference_objects_inspect_and_confirm():
    client = TestClient(app)

    # Build reference DXF with DL-Info tags
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (50.0, 0.0)})
    ref_bytes = _dxf_bytes(doc)

    # 1. Inspect
    resp = client.post(
        "/api/reference/objects/inspect",
        files={"reference": ("reference.dxf", ref_bytes, "application/dxf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["plan_markers"]) == 1
    assert len(data["objects"]) == 1
    obj = data["objects"][0]
    assert obj["occurrence_id"] == "D1-001"
    assert obj["type_code"] == "D1"
    ref_id = data["reference_id"]

    # 2. Confirm
    confirm_resp = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": ref_id,
            "inspection_token": data["inspection_token"],
            "objects": [
                {
                    "occurrence_id": "D1-001",
                    "type_code": "D1",
                    "meaning": "Door",
                    "marker_location": [50.0, 0.0],
                    "member_entity_ids": obj["member_entity_ids"],
                    "status": "confirmed",
                }
            ],
        },
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["confirmed_count"] == 1

    # Check store
    assert ref_id in REFERENCE_OBJECTS
    assert len(REFERENCE_OBJECTS[ref_id]["objects"]) == 1
    assert REFERENCE_OBJECTS[ref_id]["objects"][0]["status"] == "confirmed"


def test_descriptive_and_malformed_info_text_is_not_promoted_to_marker():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (5, 0)})
    msp.add_text("Door type one", dxfattribs={"layer": "DL-Info", "insert": (20, 0)})
    msp.add_text("D-1", dxfattribs={"layer": "DL-Info", "insert": (30, 0)})
    msp.add_text("X9", dxfattribs={"layer": "DL-Info", "insert": (40, 0)})
    drawing = parse_dxf_bytes(_dxf_bytes(doc), exclude_info_layers=False)

    plan, legend, metadata = extract_reference_markers_and_legend(
        drawing.entities,
        drawing.unsupported_entities,
    )

    assert [marker.code for marker in plan] == ["D1", "X9"]
    assert legend == []
    assert {entry["text"] for entry in metadata["ignored_information_text"]} == {
        "Door type one",
        "D-1",
    }
    objects, summary = build_proposed_reference_objects(plan, drawing.entities)
    assert objects[1].status == "unresolved"
    assert summary["unknown_codes"] == ["X9"]


def test_student_geometry_on_reserved_layer_is_not_hidden_from_grading():
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "DL-Info"})
    drawing = parse_dxf_bytes(
        _dxf_bytes(doc),
        source="student",
        exclude_info_layers=True,
    )
    assert len(drawing.entities) == 1
    assert drawing.entities[0].layer == "DL-Info"
    assert drawing.info_entities == []


def test_confirmation_rejects_stale_foreign_and_empty_groups():
    client = TestClient(app)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (5, 0)})
    ref_bytes = _dxf_bytes(doc)
    inspected = client.post(
        "/api/reference/objects/inspect",
        files={"reference": ("reference.dxf", ref_bytes, "application/dxf")},
    ).json()
    obj = inspected["objects"][0]

    stale = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": "0" * 64,
            "objects": [{**obj, "status": "confirmed"}],
        },
    )
    assert stale.status_code == 409

    foreign = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "objects": [{
                **obj,
                "member_entity_ids": ["R-99999"],
                "status": "confirmed",
            }],
        },
    )
    assert foreign.status_code == 422
    assert "outside this reference" in foreign.json()["detail"]

    empty = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "objects": [{
                **obj,
                "member_entity_ids": [],
                "status": "confirmed",
            }],
        },
    )
    assert empty.status_code == 422
    assert "without reference geometry" in empty.json()["detail"]


def test_overlapping_confirmed_memberships_require_explicit_acknowledgment():
    client = TestClient(app)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (4, 0)})
    msp.add_text("W1", dxfattribs={"layer": "DL-Info", "insert": (6, 0)})
    inspected = client.post(
        "/api/reference/objects/inspect",
        files={"reference": ("reference.dxf", _dxf_bytes(doc), "application/dxf")},
    ).json()
    objects = [{**obj, "status": "confirmed"} for obj in inspected["objects"]]

    rejected = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "objects": objects,
        },
    )
    assert rejected.status_code == 409

    accepted = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "overlap_acknowledged": True,
            "objects": objects,
        },
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["overlap_acknowledged"] is True
    assert all(obj["shared_entity_ids"] for obj in body["objects"])


def test_object_change_invalidates_assignment_approval_and_reopens_saved_members():
    client = TestClient(app)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "WALLS"})
    msp.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (5, 2.5)})
    ref_bytes = _dxf_bytes(doc)
    inspected = client.post(
        "/api/reference/objects/inspect",
        files={"reference": ("reference.dxf", ref_bytes, "application/dxf")},
    ).json()
    obj = {**inspected["objects"][0], "status": "confirmed"}
    first_confirmation = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "objects": [obj],
        },
    )
    assert first_confirmation.status_code == 200

    suggestion = client.post(
        "/api/rubric/suggest",
        files={"reference": ("reference.dxf", ref_bytes, "application/dxf")},
    ).json()
    suggestion["rubric"]["assignment_type"] = suggestion["suggested_assignment_type"]
    approval = client.post(
        "/api/rubric/approve",
        json={"reference_id": suggestion["reference_id"], "rubric": suggestion["rubric"]},
    )
    assert approval.status_code == 200
    rubric_id = approval.json()["rubric_id"]
    assert REFERENCE_OBJECTS[inspected["reference_id"]]["rubric_id"] == rubric_id

    changed = {**obj, "member_entity_ids": obj["member_entity_ids"][:1]}
    reconfirmed = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "rubric_id": rubric_id,
            "objects": [changed],
        },
    )
    assert reconfirmed.status_code == 200
    assert reconfirmed.json()["approval_invalidated"] is True
    assert inspected["reference_id"] not in REFERENCE_RUBRICS
    assert RUBRICS[rubric_id].approved is False

    stale_assignment = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": inspected["reference_id"],
            "inspection_token": inspected["inspection_token"],
            "rubric_id": rubric_id,
            "objects": [changed],
        },
    )
    assert stale_assignment.status_code == 409

    reopened = client.post(
        "/api/reference/objects/inspect",
        files={"reference": ("reference.dxf", ref_bytes, "application/dxf")},
    )
    assert reopened.status_code == 200
    assert reopened.json()["objects"][0]["member_entity_ids"] == changed["member_entity_ids"]
    assert reopened.json()["objects"][0]["status"] == "confirmed"

def test_synthetic_t3_marker_counts_exclude_six_legacy_legend_samples():
    client = TestClient(app)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (2000, 0), dxfattribs={"layer": "WALLS"})
    expected = {"D1": 7, "W1": 9, "C1": 7, "DD1": 1, "SD1": 1, "S1": 2}
    index = 0
    for code, count in expected.items():
        for _ in range(count):
            msp.add_text(
                code,
                dxfattribs={
                    "layer": "DL-Info",
                    "insert": (50 + (index % 10) * 100, 500 - (index // 10) * 100),
                },
            )
            index += 1
    for legend_index, code in enumerate(expected):
        msp.add_text(
            code,
            dxfattribs={"layer": "DL-Info", "insert": (1500, 50 + legend_index * 20)},
        )
    msp.add_text(
        "LEGEND DESCRIPTIONS",
        dxfattribs={"layer": "DL-Info", "insert": (1600, 50)},
    )

    response = client.post(
        "/api/reference/objects/inspect",
        data={"legend_bbox": "1450, 0, 1700, 200"},
        files={"reference": ("t3-synthetic.dxf", _dxf_bytes(doc), "application/dxf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["counts_by_type"] == expected
    assert body["metadata"]["plan_markers_count"] == 27
    assert body["metadata"]["legend_samples_count"] == 6
    assert len(body["metadata"]["ignored_information_text"]) == 1


def test_custom_information_layer_and_mapping_are_applied_and_confirmable():
    client = TestClient(app)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (20, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text("X9", dxfattribs={"layer": "COURSE-TAGS", "insert": (10, 0)})
    response = client.post(
        "/api/reference/objects/inspect",
        data={
            "custom_info_layers": "COURSE-TAGS",
            "code_mappings": '{"X9":"Instructor-defined object"}',
        },
        files={"reference": ("custom.dxf", _dxf_bytes(doc), "application/dxf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["objects"][0]["meaning"] == "Instructor-defined object"
    assert body["objects"][0]["status"] == "proposed"
    assert len(body["available_entities"]) == 1
    confirmation = client.post(
        "/api/reference/objects/confirm",
        json={
            "reference_id": body["reference_id"],
            "inspection_token": body["inspection_token"],
            "objects": [{**body["objects"][0], "status": "confirmed"}],
        },
    )
    assert confirmation.status_code == 200
    assert confirmation.json()["confirmed_count"] == 1