"""Independent regressions for reference configuration and displayed evidence."""
import io
import json

import ezdxf
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app
from app.scale_diagnostics import ScaleDiagnostic
from app.unit_scale_review import evaluate_unit_scale_review
from app.dxf import parse_dxf_bytes
from app.compare import compare_drawings
from app.reviewed_dxf import build_reviewed_drawing
from tests.test_connectivity_presentation import drawing, line, rubric


def tagged_bytes():
    doc = ezdxf.new("R2010")
    doc.units = 4
    model = doc.modelspace()
    for a, b in [((0, 0), (100, 0)), ((100, 0), (100, 80)),
                 ((100, 80), (0, 80)), ((0, 80), (0, 0))]:
        model.add_line(a, b)
    model.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (50, 0)})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


def test_changed_information_configuration_invalidates_approval_before_confirmation():
    client = TestClient(app)
    data = tagged_bytes()
    files = {"reference": ("synthetic.dxf", data, "application/dxf")}
    first = client.post("/api/reference/objects/inspect", files=files).json()
    suggestion = client.post("/api/rubric/suggest", files=files).json()
    suggestion["rubric"]["assignment_type"] = "Architectural Drawing"
    approval = client.post("/api/rubric/approve", json={
        "reference_id": first["reference_id"], "rubric": suggestion["rubric"]
    }).json()
    changed = client.post("/api/reference/objects/inspect", files=files,
                          data={"code_mappings": '{"D1":"Instructor door"}'})
    assert changed.status_code == 200
    assert changed.json().get("approval_invalidated") is True
    review = client.post("/api/review", data={"rubric_id": approval["rubric_id"]},
                         files={**files, "student": ("synthetic-student.dxf", data, "application/dxf")})
    assert review.status_code == 409


def test_information_region_rejects_nonfinite_coordinates():
    client = TestClient(app)
    for region in ("nan,0,100,100", "0,0,inf,100"):
        result = client.post("/api/reference/objects/inspect",
                             files={"reference": ("synthetic.dxf", tagged_bytes(), "application/dxf")},
                             data={"legend_bbox": region})
        assert result.status_code == 422


def test_low_support_extents_ratio_does_not_prove_physical_unit_consistency():
    reference = parse_dxf_bytes(tagged_bytes(), exclude_info_layers=True)
    student = parse_dxf_bytes(tagged_bytes(), source="student")
    student.units = "cm"
    diagnostic = ScaleDiagnostic(False, 0.1, 0, 0, "none", False)
    result = evaluate_unit_scale_review(reference, student, diagnostic,
                                       intended_unit="mm", intended_unit_confirmed=True)
    assert not result.units_scale_physically_consistent
    assert result.requires_instructor_acknowledgment
    assert "Insufficient" in result.factor_direction_explanation


def test_translated_gap_regions_and_endpoints_use_student_frame():
    ref = drawing(line("R1", (0, 0), (100, 0)), line("R2", (100, 0), (100, 80)),
                  line("R3", (100, 80), (0, 80)), line("R4", (0, 80), (0, 0)))
    stu = drawing(line("S1", (300, 400), (400, 400), source="student"),
                  line("S2", (400, 403), (400, 480), source="student"),
                  line("S3", (400, 480), (300, 480), source="student"),
                  line("S4", (300, 480), (300, 400), source="student"))
    # Three distinct intrinsic anchors make this an accepted translation case.
    for index, (a, b) in enumerate([((10, 10), (23, 15)), ((40, 20), (62, 31)), ((60, 55), (78, 61))]):
        ref.entities.append(line(f"RA{index}", a, b, layer="ANCHORS"))
        stu.entities.append(line(f"SA{index}", (a[0]+300, a[1]+400), (b[0]+300, b[1]+400), source="student", layer="ANCHORS"))
    for entity in ref.entities + stu.entities:
        entity.layer = "GEOMETRY"
        entity.points.sort()
    comparison = compare_drawings(ref, stu, rubric=rubric("translation"))
    assert comparison["normalization"]["student"]["translation"] == [-300, -400]
    reviewed = build_reviewed_drawing(ref, stu, comparison)
    gap = next(issue for issue in reviewed.issues if issue.category == "endpoint_gap")
    assert sorted(gap.measurement["actual_points"]) == [[400, 400], [400, 403]]
    assert gap.region[0] >= 299 and gap.region[1] >= 399


def test_confirmed_bounds_remain_numeric_after_membership_change():
    client = TestClient(app)
    data = tagged_bytes()
    inspected = client.post("/api/reference/objects/inspect", files={
        "reference": ("synthetic.dxf", data, "application/dxf")}).json()
    obj = inspected["objects"][0]
    obj.update(status="confirmed", member_entity_ids=[inspected["available_entities"][0]["internal_id"]])
    confirmed = client.post("/api/reference/objects/confirm", json={
        "reference_id": inspected["reference_id"], "inspection_token": inspected["inspection_token"],
        "objects": [obj]}).json()
    assert confirmed["objects"][0]["bounds"] == [0, 0, 100, 0]


def test_custom_metadata_is_excluded_before_any_object_confirmation():
    client = TestClient(app)
    clean = tagged_bytes()
    doc = ezdxf.read(io.StringIO(clean.decode()))
    doc.modelspace().add_line((10000, 10000), (20000, 20000), dxfattribs={"layer": "COURSE-META"})
    stream = io.StringIO()
    doc.write(stream)
    tagged = stream.getvalue().encode()
    files = {"reference": ("synthetic.dxf", tagged, "application/dxf")}
    inspected = client.post("/api/reference/objects/inspect", files=files,
                            data={"custom_info_layers": "COURSE-META"})
    assert inspected.status_code == 200
    suggestion = client.post("/api/rubric/suggest", files=files).json()
    suggestion["rubric"]["assignment_type"] = "Other"
    approval = client.post("/api/rubric/approve", json={"reference_id": suggestion["reference_id"], "rubric": suggestion["rubric"]}).json()
    # The clean student omits the instructor text as well as custom metadata.
    doc = ezdxf.read(io.StringIO(clean.decode()))
    for entity in list(doc.modelspace().query('TEXT')):
        doc.modelspace().delete_entity(entity)
    stream = io.StringIO()
    doc.write(stream)
    review = client.post("/api/review", data={"rubric_id": approval["rubric_id"]},
                         files={**files, "student": ("student.dxf", stream.getvalue().encode(), "application/dxf")})
    assert review.status_code == 200
    assert review.json()["score"] == 100


def test_pdf_records_intended_unit_and_keeps_optional_support_in_appendix():
    from tests.stage_audit_synthetic import document
    client = TestClient(app)
    files = {"reference": ("synthetic.dxf", document(), "application/dxf")}
    suggestion = client.post("/api/rubric/suggest", files=files).json()
    suggestion["rubric"]["assignment_type"] = "Architectural Drawing"
    approval = client.post("/api/rubric/approve", json={"reference_id": suggestion["reference_id"], "rubric": suggestion["rubric"]}).json()
    review = client.post("/api/review", data={"rubric_id": approval["rubric_id"]},
                         files={**files, "student": ("gap.dxf", document(gap=4), "application/dxf")}).json()
    uri = f"/api/reviews/{review['review_id']}/report.pdf"
    ordinary = client.get(uri).content
    appendix = client.get(uri + "?include_appendix=true").content
    text = lambda data: " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).split())
    assert "Intended assignment unit: mm (instructor confirmed)" in text(ordinary)
    assert "Architectural Drawing" in text(ordinary)
    for issue in review["issues"]:
        assert issue["issue_id"] in text(appendix)
        if issue["finding_role"] == "supporting":
            assert issue["issue_id"] not in text(ordinary)
    assert ordinary == client.get(uri).content
    changed = client.post("/api/reference/objects/inspect", files=files, data={"code_mappings": json.dumps({"D1": "Changed"})})
    assert changed.json()["approval_invalidated"] is True
    assert ordinary == client.get(uri).content, "Existing immutable snapshot retains its approval/settings"
