from __future__ import annotations

import io

import ezdxf
from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from app.main import REVIEW_SNAPSHOTS, app
from app.compare import compare_drawings
from app.compatibility import assess_compatibility
from app.correction_guidance import correction_guidance
from app.finding_presentation import compact_finding_presentation
from app.grading_adjustments import apply_acceptance_scoring
from app.models import Drawing, Entity, Issue
from app.rubric import default_rubric
from app.scale_diagnostics import diagnose_uniform_scale


def _line(index: int, *, source: str, dx: float = 0, dy: float = 0) -> Entity:
    length = 10.0 + index * 0.5
    start = (dx, index * 3.0 + dy)
    end = (length + dx, index * 3.0 + dy)
    return Entity(
        id=("R" if source == "reference" else "S") + f"-{index:03d}",
        kind="line",
        layer=f"geometry-{index:03d}",
        source=source,
        points=[start, end],
        bbox=(start[0], start[1], end[0], end[1]),
        centroid=((start[0] + end[0]) / 2.0, start[1]),
    )


def _drawing(entities: list[Entity]) -> Drawing:
    boxes = [entity.bbox for entity in entities if entity.bbox is not None]
    return Drawing(
        entities=entities,
        bbox=(
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ),
        units="millimeters",
        units_code=4,
    )


def _rubric(mode: str = "strict"):
    return default_rubric().model_copy(
        update={
            "approved": True,
            "assignment_title": "Interior Plan",
            "assignment_type": "Interior Plan",
            "normalization_mode": mode,
        }
    )


def _category(result: dict, category_id: str) -> dict:
    return next(
        category
        for category in result["score_breakdown"]["category_subtotals"]
        if category["id"] == category_id
    )


def test_strict_complete_translation_is_one_global_finding_and_scores_50():
    reference = _drawing([_line(index, source="reference") for index in range(12)])
    student = _drawing([
        _line(index, source="student", dx=100, dy=-50)
        for index in range(12)
    ])
    original_points = [list(entity.points) for entity in student.entities]

    result = compare_drawings(reference, student, rubric=_rubric("strict"))

    primary = [
        issue for issue in result["issues"]
        if issue["classification"] == "primary"
    ]
    assert result["score"] == 50
    assert [issue["category"] for issue in primary] == [
        "global_drawing_displacement"
    ]
    assert not {
        issue["category"] for issue in primary
    } & {"missing_geometry", "extra_geometry", "incorrect_position"}
    measurement = primary[0]["measurement"]
    assert measurement["displacement_x"] == 100
    assert measurement["displacement_y"] == -50
    assert measurement["magnitude"] == 111.803399
    assert measurement["support_count"] == 12
    assert measurement["support_ratio"] == 1
    assert _category(result, "geometry")["score"] == 15
    assert _category(result, "completion")["score"] == 25
    assert _category(result, "quality")["score"] == 10
    assert [entity.points for entity in student.entities] == original_points


def test_translation_tolerant_complete_translation_remains_100():
    reference = _drawing([_line(index, source="reference") for index in range(12)])
    student = _drawing([
        _line(index, source="student", dx=100, dy=-50)
        for index in range(12)
    ])
    result = compare_drawings(reference, student, rubric=_rubric("translation"))
    assert result["score"] == 100
    assert result["normalization"]["student"]["translation"] == [-100.0, 50.0]
    assert result["issues"] == []


def test_partial_work_geometry_evidence_and_completion_credit_total_about_20():
    reference = _drawing([_line(index, source="reference") for index in range(140)])
    student = _drawing([_line(index, source="student") for index in range(8)])
    rubric = _rubric("strict")
    result = compare_drawings(reference, student, rubric=rubric)
    compatibility = assess_compatibility(
        reference,
        student,
        result,
        diagnose_uniform_scale(reference, student),
    )

    apply_acceptance_scoring(result, rubric, compatibility)

    assert compatibility.compatibility_status == "compatible"
    assert compatibility.confident_match_count == 8
    assert result["geometry_evidence_coverage"] == 0.057143
    assert result["geometry_evidence_factor"] == 0.076191
    assert _category(result, "geometry")["score"] <= 5
    assert _category(result, "completion")["score"] == 5
    assert _category(result, "quality")["score"] == 10
    assert result["partial_completion_credit"] == 5
    assert result["score"] == 20


def test_compatible_result_cannot_become_override():
    drawing = _drawing([_line(index, source="reference") for index in range(12)])
    student = _drawing([_line(index, source="student") for index in range(12)])
    comparison = compare_drawings(drawing, student, rubric=_rubric())
    compatibility = assess_compatibility(
        drawing,
        student,
        comparison,
        diagnose_uniform_scale(drawing, student),
        instructor_override=True,
    )
    assert compatibility.compatibility_status == "compatible"
    assert compatibility.instructor_override is False
    assert compatibility.grading_withheld is False


def test_ordinary_extra_guidance_is_erase_only_and_duplicate_remains_overkill():
    entity = _line(1, source="student")
    extra = Issue(
        id="E-EXTRA",
        category="extra_geometry",
        severity="minor",
        message="extra",
        deduction=2,
    )
    duplicate = Issue(
        id="E-DUP",
        category="duplicate_geometry",
        severity="minor",
        message="duplicate",
        deduction=1,
    )
    extra_guidance = correction_guidance(extra, None, entity)
    duplicate_guidance = correction_guidance(duplicate, None, entity)
    assert extra_guidance is not None
    assert extra_guidance.primary_command == "ERASE"
    assert extra_guidance.alternative_commands == ()
    assert "SELECTSIMILAR" not in extra_guidance.flattened_commands()
    assert duplicate_guidance is not None
    assert duplicate_guidance.primary_command == "OVERKILL"
    assert duplicate_guidance.alternative_commands == ("ERASE",)


def test_large_finding_compaction_is_deterministic_and_preserves_raw_data():
    issues = []
    for index in range(131):
        contribution = 5.0 if index < 5 else 0.0
        issues.append({
            "issue_id": f"E-{index:03d}",
            "finding_role": "primary",
            "category": "missing_geometry",
            "severity": "major",
            "score_category": "completion",
            "deduction_status": "applied" if contribution else "capped",
            "cap_reason": None if contribution else "rule_repeat_cap",
            "final_applied_contribution": contribution,
            "technical_feedback": "Required geometry is missing.",
        })
    original = [dict(issue) for issue in issues]
    first = compact_finding_presentation(issues)
    repeated = compact_finding_presentation(issues)

    assert first == repeated
    assert first["compacted"] is True
    assert first["total_raw_count"] == 131
    assert first["total_displayed_count"] == 8
    assert first["total_summarized_count"] == 123
    assert len(issues) == 131
    assert issues == original
    assert sum(group["summarized_count"] for group in first["summary_groups"]) == 123
    summary = first["summary_groups"][0]
    assert summary["total_count"] == 131
    assert summary["contributed_count"] == 5
    assert summary["displayed_count"] == 8
    assert len(summary["deduction_groups"]) == 2


client = TestClient(app)


def _dxf_lines(
    count: int,
    *,
    dx: float = 0,
    dy: float = 0,
    scale: float = 1,
    circles: bool = False,
) -> bytes:
    document = ezdxf.new("R2010")
    document.units = ezdxf.units.MM
    modelspace = document.modelspace()
    for index in range(count):
        if circles:
            modelspace.add_circle(
                ((index * 4 + dx) * scale, (index * 2 + dy) * scale),
                (3 + index * .1) * scale,
            )
        else:
            start = ((dx) * scale, (index * 3 + dy) * scale)
            end = ((10 + index * .5 + dx) * scale, (index * 3 + dy) * scale)
            modelspace.add_line(start, end)
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def _approve_api(
    reference: bytes,
    *,
    filename: str,
    assignment_title: str,
    assignment_type: str,
    normalization_mode: str = "strict",
) -> dict:
    suggested_response = client.post(
        "/api/rubric/suggest",
        files={"reference": (filename, reference, "application/dxf")},
    )
    assert suggested_response.status_code == 200
    suggested = suggested_response.json()
    suggested["rubric"].update(
        {
            "assignment_title": assignment_title,
            "assignment_type": assignment_type,
            "normalization_mode": normalization_mode,
        }
    )
    approved = client.post(
        "/api/rubric/approve",
        json={
            "reference_id": suggested["reference_id"],
            "rubric": suggested["rubric"],
        },
    )
    assert approved.status_code == 200
    return approved.json()


def _review_api(
    reference: bytes,
    student: bytes,
    *,
    grade_anyway: bool = False,
) -> dict:
    response = client.post(
        "/api/review",
        data={"grade_anyway": str(grade_anyway).lower()},
        files={
            "reference": ("reference.dxf", reference, "application/dxf"),
            "student": ("student.dxf", student, "application/dxf"),
        },
    )
    assert response.status_code == 200
    return response.json()


def _pdf_reader(review: dict) -> tuple[bytes, PdfReader]:
    first = client.get(f"/api/reviews/{review['review_id']}/report.pdf")
    repeated = client.get(f"/api/reviews/{review['review_id']}/report.pdf")
    assert first.status_code == repeated.status_code == 200
    assert first.content == repeated.content
    return first.content, PdfReader(io.BytesIO(first.content))


def _pdf_text(reader: PdfReader) -> str:
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _pdf_image_xobjects(reader: PdfReader) -> list[str]:
    images = []
    for page in reader.pages:
        resources_reference = page.get("/Resources")
        if resources_reference is None:
            continue
        resources = resources_reference.get_object()
        xobjects_reference = resources.get("/XObject")
        if xobjects_reference is None:
            continue
        for name, reference in xobjects_reference.get_object().items():
            if reference.get_object().get("/Subtype") == "/Image":
                images.append(str(name))
    return images


@pytest.mark.parametrize(
    "filename,assignment_title,assignment_type",
    (
        (
            "00_REFERENCE_Interior_Plan_Supported_Geometry.dxf",
            "Interior Plan",
            "Interior Plan",
        ),
        (
            "00_REFERENCE_Complex_Pattern_Supported_Geometry.dxf",
            "Complex Pattern",
            "Complex Geometric Pattern",
        ),
    ),
)
def test_instructor_assignment_metadata_persists_through_review_and_pdf(
    filename,
    assignment_title,
    assignment_type,
):
    reference = _dxf_lines(12)
    _approve_api(
        reference,
        filename=filename,
        assignment_title=assignment_title,
        assignment_type=assignment_type,
    )
    review = _review_api(reference, reference)
    _content, reader = _pdf_reader(review)
    text = _pdf_text(reader)
    assert review["assignment_title"] == assignment_title
    assert review["assignment_type"] == assignment_type
    assert review["rubric_template_name"] == "DraftLens Baseline Rubric"
    assert "Assignment title" in text
    assert assignment_title in text
    assert "Assignment type" in text
    assert assignment_type in text
    assert "Rubric template" in text
    assert "DraftLens Baseline Rubric" in text
    assert "Instructor compatibility override" not in text
    assert _pdf_image_xobjects(reader) == []


def test_partial_work_api_score_and_report_are_compact_deterministic_and_vector():
    reference = _dxf_lines(140)
    student = _dxf_lines(8)
    _approve_api(
        reference,
        filename="00_REFERENCE_Interior_Plan_Supported_Geometry.dxf",
        assignment_title="Interior Plan",
        assignment_type="Interior Plan",
    )
    review = _review_api(reference, student)
    assert review["score"] == 20
    assert review["geometry_points_after_evidence_limit"] <= 5
    assert review["partial_completion_credit"] == 5
    assert review["finding_presentation"]["compacted"] is True
    _content, reader = _pdf_reader(review)
    assert len(reader.pages) <= 10
    assert "Compact finding summary" in _pdf_text(reader)
    assert _pdf_image_xobjects(reader) == []


def test_strict_global_translation_api_report_is_consolidated_and_preserves_input():
    reference = _dxf_lines(12)
    student = _dxf_lines(12, dx=100, dy=-50)
    _approve_api(
        reference,
        filename="00_REFERENCE_Interior_Plan_Supported_Geometry.dxf",
        assignment_title="Interior Plan",
        assignment_type="Interior Plan",
    )
    review = _review_api(reference, student)
    primary = [
        issue for issue in review["issues"]
        if issue["finding_role"] == "primary"
    ]
    assert review["score"] == 50
    assert [issue["category"] for issue in primary] == [
        "global_drawing_displacement"
    ]
    assert not {
        issue["category"] for issue in primary
    } & {"missing_geometry", "extra_geometry", "incorrect_position"}
    snapshot = REVIEW_SNAPSHOTS.get(review["review_id"])
    assert min(
        point[0]
        for entity in snapshot.reviewed_drawing.student_entities
        for point in entity.points
    ) == 100
    _content, reader = _pdf_reader(review)
    assert len(reader.pages) <= 5
    pdf_text = _pdf_text(reader)
    assert "Global Drawing Displacement" in pdf_text
    assert "displacement X=100, Y=-50" in pdf_text
    assert "displacement-to-tolerance ratio 55.902" in pdf_text
    assert _pdf_image_xobjects(reader) == []


@pytest.mark.parametrize(
    "student,status,page_limit",
    (
        (_dxf_lines(60, scale=50), "suspicious", 12),
        (_dxf_lines(60, circles=True), "incompatible", 10),
    ),
)
def test_overridden_large_reports_are_compact_and_disclosed(
    student,
    status,
    page_limit,
):
    reference = _dxf_lines(60)
    _approve_api(
        reference,
        filename="00_REFERENCE_Interior_Plan_Supported_Geometry.dxf",
        assignment_title="Interior Plan",
        assignment_type="Interior Plan",
    )
    withheld = _review_api(reference, student)
    assert withheld["compatibility_status"] == status
    assert withheld["grading_status"] == "withheld"
    assert withheld["report_available"] is False
    overridden = _review_api(reference, student, grade_anyway=True)
    assert overridden["instructor_override"] is True
    assert overridden["finding_presentation"]["compacted"] is True
    _content, reader = _pdf_reader(overridden)
    assert len(reader.pages) <= page_limit
    assert "Instructor compatibility override" in _pdf_text(reader)
    assert _pdf_image_xobjects(reader) == []
