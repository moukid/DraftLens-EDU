from __future__ import annotations

import io
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import REVIEW_SNAPSHOTS, app


client = TestClient(app)
AUDIT_II = Path(__file__).parent / "fixtures" / "simple_audit-II"
AUDIT = Path(__file__).parent / "fixtures" / "simple_audit"


def _plan_bytes(scale: float = 1.0, count: int = 4) -> bytes:
    document = ezdxf.new("R2010")
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    rectangle = (
        ((0, 0), (10, 0)),
        ((10, 0), (10, 6)),
        ((10, 6), (0, 6)),
        ((0, 6), (0, 0)),
    )
    for start, end in rectangle:
        modelspace.add_line(
            (start[0] * scale, start[1] * scale),
            (end[0] * scale, end[1] * scale),
        )
    for index in range(4, count):
        modelspace.add_line(
            (index * 2 * scale, 10 * scale),
            ((index * 2 + 1 + index / 10) * scale, 10 * scale),
        )
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def _approve(reference: bytes) -> dict:
    suggestion = client.post(
        "/api/rubric/suggest",
        files={"reference": ("reference.dxf", reference, "application/dxf")},
    ).json()
    suggestion["rubric"]["assignment_type"] = "Technical Drawing"
    response = client.post(
        "/api/rubric/approve",
        json={
            "reference_id": suggestion["reference_id"],
            "rubric": suggestion["rubric"],
        },
    )
    assert response.status_code == 200
    return response.json()


def _files(reference: bytes, student: bytes) -> dict:
    return {
        "reference": ("reference.dxf", reference, "application/dxf"),
        "student": ("student.dxf", student, "application/dxf"),
    }


def test_scaled_copy_is_withheld_then_override_is_authoritative_and_reported():
    reference = _plan_bytes()
    student = _plan_bytes(scale=50)
    _approve(reference)

    withheld = client.post("/api/review", files=_files(reference, student)).json()
    assert withheld["compatibility_status"] == "suspicious"
    assert withheld["grading_status"] == "withheld"
    assert withheld["score"] is None
    assert withheld["issues"] == []
    assert withheld["report_available"] is False
    assert withheld["review_id"] is None
    assert withheld["estimated_scale_factor"] == pytest.approx(50)
    assert withheld["compatibility_message"] == (
        "Likely global scale or drawing-unit mismatch. The submitted geometry "
        "appears uniformly scaled by approximately 50×."
    )

    overridden = client.post(
        "/api/review",
        data={"grade_anyway": "true"},
        files=_files(reference, student),
    ).json()
    assert overridden["grading_status"] == "graded"
    assert overridden["score"] is not None and overridden["score"] < 100
    assert overridden["instructor_override"] is True
    assert overridden["report_available"] is True
    pdf = client.get(f"/api/reviews/{overridden['review_id']}/report.pdf")
    assert pdf.status_code == 200
    text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf.content)).pages
    )
    assert "Instructor compatibility override" in text
    assert "Grade anyway" in text

    subsequent = client.post(
        "/api/review",
        files=_files(reference, reference),
    ).json()
    assert subsequent["compatibility_status"] == "compatible"
    assert subsequent["instructor_override"] is False
    assert "compatibility_override" not in subsequent



def test_unrelated_t_crossing_is_withheld_without_issue_flood():
    reference = _plan_bytes(count=40)
    student = (AUDIT_II / "04-T-Crossing-Student-OK.dxf").read_bytes()
    _approve(reference)

    withheld = client.post("/api/review", files=_files(reference, student)).json()
    assert withheld["compatibility_status"] == "incompatible"
    assert withheld["score"] is None
    assert not [issue for issue in withheld["issues"] if issue["provenance"] == "comparison"]
    assert withheld["report_available"] is False

    overridden = client.post(
        "/api/review",
        data={"grade_anyway": "true"},
        files=_files(reference, student),
    ).json()
    assert overridden["score"] is not None
    assert overridden["instructor_override"] is True


def test_unrelated_line_heavy_submission_is_withheld_until_explicit_override():
    reference = _plan_bytes(count=108)
    student = (AUDIT / "03_wrong_length_73C_80_units.dxf").read_bytes()
    _approve(reference)

    grade = client.post("/api/grade", files=_files(reference, student)).json()
    assert grade["compatibility_status"] == "incompatible"
    assert grade["grading_status"] == "withheld"
    assert grade["score"] is None
    assert grade["issues"] == []

    withheld = client.post("/api/review", files=_files(reference, student)).json()
    assert withheld["compatibility_status"] == "incompatible"
    assert withheld["grading_status"] == "withheld"
    assert withheld["score"] is None
    assert withheld["review_id"] is None
    assert withheld["report_available"] is False
    assert len(REVIEW_SNAPSHOTS) == 0
    assert withheld["reference_supported_entity_count"] == 108
    assert withheld["student_supported_entity_count"] == 19
    assert withheld["confident_match_count"] > 0
    assert withheld["coherent_reference_coverage"] < 0.05
    assert withheld["coherent_student_coverage"] < 0.35
    assert "raw_intrinsic_matches_lack_spatial_coherence" in (
        withheld["compatibility_reason_codes"]
    )
    assert withheld["compatibility_message"].startswith(
        "Likely wrong assignment file."
    )
    assert withheld["available_actions"] == [
        "choose_another_file",
        "grade_anyway",
    ]
    assert not [
        issue
        for issue in withheld["issues"]
        if issue["provenance"] == "comparison"
    ]

    overridden = client.post(
        "/api/review",
        data={"grade_anyway": "true"},
        files=_files(reference, student),
    ).json()
    assert overridden["grading_status"] == "graded"
    assert overridden["instructor_override"] is True
    assert overridden["report_available"] is True
    assert len(REVIEW_SNAPSHOTS) == 1
    pdf = client.get(f"/api/reviews/{overridden['review_id']}/report.pdf")
    assert pdf.status_code == 200
    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf.content)).pages
    )
    assert "Instructor compatibility override" in text
    assert "Compatibility warning" in text
    assert "Likely wrong assignment file" in text

    exact = client.post("/api/review", files=_files(reference, reference)).json()
    assert exact["compatibility_status"] == "compatible"
    assert exact["instructor_override"] is False
    assert "compatibility_override" not in exact



def test_empty_student_is_not_graded():
    reference = _plan_bytes()
    empty = ezdxf.new("R2010")
    stream = io.StringIO()
    empty.write(stream)
    _approve(reference)
    body = client.post(
        "/api/review",
        files=_files(reference, stream.getvalue().encode("utf-8")),
    ).json()
    assert body["compatibility_status"] == "empty_or_ungradable"
    assert body["score"] is None
    assert body["report_available"] is False
    assert body["available_actions"] == ["choose_another_file"]
    assert body["instructor_override"] is False


def test_rubric_source_changes_when_instructor_changes_weight():
    reference = _plan_bytes()
    suggestion = client.post(
        "/api/rubric/suggest",
        files={"reference": ("reference.dxf", reference, "application/dxf")},
    ).json()
    suggestion["rubric"]["assignment_type"] = "Technical Drawing"
    suggestion["rubric"]["categories"][0].update(weight=60, max_deduction=60)
    suggestion["rubric"]["categories"][1].update(weight=30, max_deduction=25)
    response = client.post(
        "/api/rubric/approve",
        json={
            "reference_id": suggestion["reference_id"],
            "rubric": suggestion["rubric"],
        },
    )
    assert response.status_code == 200
    rubric = response.json()["rubric"]
    assert rubric["rubric_source"] == "instructor_modified"
    assert rubric["rubric_modified_by_instructor"] is True
    assert rubric["rubric_template_name"] == "DraftLens Baseline Rubric"


def test_compatible_review_never_records_override_even_if_requested():
    reference = _plan_bytes(count=12)
    approval = _approve(reference)
    review = client.post(
        "/api/review",
        data={"grade_anyway": "true"},
        files=_files(reference, reference),
    ).json()
    assert review["compatibility_status"] == "compatible"
    assert review["instructor_override"] is False
    assert "compatibility_override" not in review
    assert review["score"] == 100
    assert review["rubric_template_name"] == "DraftLens Baseline Rubric"
    assert review["rubric"]["assignment_title"] == "Reference"
    pdf = client.get(f"/api/reviews/{review['review_id']}/report.pdf")
    assert pdf.status_code == 200
    text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf.content)).pages
    )
    assert "Instructor compatibility override" not in text
    assert approval["rubric_id"] == review["rubric_selection"]["rubric_id"]
