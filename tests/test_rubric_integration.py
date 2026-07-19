from pathlib import Path
from fastapi.testclient import TestClient
from app.main import RUBRIC_REFERENCES, RUBRICS, app
from app.rubric import default_rubric

SAMPLES = Path(__file__).parents[1] / "samples"
client = TestClient(app)

def suggest():
    with open(SAMPLES / "reference.dxf", "rb") as source:
        response = client.post("/api/rubric/suggest", files={"reference": ("reference.dxf", source, "application/dxf")})
    assert response.status_code == 200
    return response.json()

def approve(suggestion):
    return client.post("/api/rubric/approve", json={"reference_id": suggestion["reference_id"], "rubric": suggestion["rubric"]})

def grade(*, data=None):
    with open(SAMPLES / "reference.dxf", "rb") as reference, open(SAMPLES / "student_missing_wall.dxf", "rb") as student:
        return client.post("/api/grade", data=data or {}, files={
            "reference": ("reference.dxf", reference, "application/dxf"),
            "student": ("student.dxf", student, "application/dxf"),
        })

def test_grading_requires_approval_unless_fallback_is_explicit():
    rejected = grade()
    assert rejected.status_code == 409
    assert "No approved rubric" in rejected.json()["detail"]
    fallback = grade(data={"allow_fallback": "true"})
    assert fallback.status_code == 200
    assert fallback.json()["rubric_selection"]["source"] == "explicit_fallback"
    assert [category["weight"] for category in fallback.json()["rubric"]["categories"]] == [65.0, 25.0, 10.0]

def test_grading_uses_associated_approved_rubric_and_its_tolerances():
    suggestion = suggest()
    suggestion["rubric"]["tolerances"]["position"] = 0.25
    approval = approve(suggestion)
    assert approval.status_code == 200
    result = grade()
    assert result.status_code == 200
    payload = result.json()
    assert payload["rubric_selection"] == {"rubric_id": approval.json()["rubric_id"], "source": "associated_approved"}
    assert payload["tolerances"]["position"] == 0.25
    assert payload["rubric_application"]["approved"] is True

def test_different_approved_weights_change_the_score():
    first = suggest()
    first["rubric"]["completion_scoring_mode"] = "proportional"
    first_approval = approve(first)
    assert first_approval.status_code == 200
    first_score = grade().json()["score"]

    second = suggest()
    second["rubric"]["completion_scoring_mode"] = "proportional"
    weights = {"geometry": 30, "completion": 60, "quality": 10}
    for category in second["rubric"]["categories"]:
        category["weight"] = weights[category["id"]]
        category["max_deduction"] = weights[category["id"]]
    second_approval = approve(second)
    assert second_approval.status_code == 200
    second_result = grade().json()
    assert second_result["score"] != first_score
    assert second_result["rubric_application"]["category_weights"]["completion"] == 60.0

def test_invalid_and_unapproved_rubrics_are_rejected():
    suggestion = suggest()
    suggestion["rubric"]["categories"][0]["weight"] = 80
    invalid = approve(suggestion)
    assert invalid.status_code == 422

    clean = suggest()
    rubric_id = "unapproved"
    RUBRICS[rubric_id] = default_rubric()
    RUBRIC_REFERENCES[rubric_id] = clean["reference_id"]
    rejected = grade(data={"rubric_id": rubric_id})
    assert rejected.status_code == 409
    assert "not approved" in rejected.json()["detail"]

def test_inline_rubric_upload_is_not_a_approval_bypass():
    with open(SAMPLES / "reference.dxf", "rb") as reference, open(SAMPLES / "student_good.dxf", "rb") as student:
        response = client.post("/api/grade", files={
            "reference": ("reference.dxf", reference, "application/dxf"),
            "student": ("student.dxf", student, "application/dxf"),
            "rubric": ("rubric.json", b"{}", "application/json"),
        })
    assert response.status_code == 409
    assert "Inline rubric uploads" in response.json()["detail"]
