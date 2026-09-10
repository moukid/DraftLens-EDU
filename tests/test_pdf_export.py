from tests.synthetic_data import fixture_root, samples_root
from datetime import datetime, timedelta, timezone
import hashlib
import io
from pathlib import Path
import re

import ezdxf
from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

import app.main as main_module
from app.main import REVIEW_SNAPSHOTS, app


ROOT = Path(__file__).parents[1]
SAMPLES = samples_root()
AUDIT = fixture_root() / "simple_audit"
AUDIT_II = fixture_root() / "simple_audit-II"
client = TestClient(app)


def _source_bytes(source):
    return source.read_bytes() if isinstance(source, Path) else bytes(source)


def _approve(reference, *, filename="reference.dxf", normalization_mode="strict"):
    reference_bytes = _source_bytes(reference)
    suggestion_response = client.post(
        "/api/rubric/suggest",
        files={"reference": (filename, reference_bytes, "application/dxf")},
    )
    assert suggestion_response.status_code == 200
    suggestion = suggestion_response.json()
    suggestion["rubric"]["assignment_type"] = suggestion["suggested_assignment_type"]
    suggestion["rubric"]["normalization_mode"] = normalization_mode
    approval = client.post(
        "/api/rubric/approve",
        json={"reference_id": suggestion["reference_id"], "rubric": suggestion["rubric"]},
    )
    assert approval.status_code == 200
    return suggestion, approval.json()


def _review(
    reference,
    student,
    *,
    data=None,
    reference_filename="reference.dxf",
    student_filename="student.dxf",
):
    return client.post(
        "/api/review",
        data=data or {},
        files={
            "reference": (reference_filename, _source_bytes(reference), "application/dxf"),
            "student": (student_filename, _source_bytes(student), "application/dxf"),
        },
    )


def _pdf(review):
    return client.get(f"/api/reviews/{review['review_id']}/report.pdf")


def _reader(response):
    return PdfReader(io.BytesIO(response.content))


def _text(reader):
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _image_xobjects(reader):
    images = []
    for page in reader.pages:
        resource_reference = page.get("/Resources")
        if resource_reference is None:
            continue
        resources = resource_reference.get_object()
        xobject_reference = resources.get("/XObject")
        if xobject_reference is None:
            continue
        for name, reference in xobject_reference.get_object().items():
            if reference.get_object().get("/Subtype") == "/Image":
                images.append(name)
    return images


def _unitless_document_bytes():
    document = ezdxf.new("R2010")
    document.units = 0
    document.modelspace().add_line((0, 0), (10, 0))
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def test_review_creates_authoritative_immutable_snapshot_with_optional_metadata():
    reference = SAMPLES / "reference.dxf"
    _, approval = _approve(reference)
    response = _review(
        reference,
        SAMPLES / "student_missing_wall.dxf",
        data={
            "student_name": "  Zoe\u0308  ",
            "student_id": " ST-42 ",
            "course_section": " CAD 101 ",
        },
    )
    assert response.status_code == 200
    review = response.json()
    assert review["report_available"] is True
    assert review["student_metadata"] == {
        "student_name": "Zo\u00eb",
        "student_id": "ST-42",
        "course_section": "CAD 101",
    }
    assert review["review_id"]
    datetime.fromisoformat(review["report_timestamp"].replace("Z", "+00:00"))

    snapshot = REVIEW_SNAPSHOTS.get(review["review_id"])
    assert snapshot.review_response == review
    assert snapshot.approved_rubric_id == approval["rubric_id"]
    assert snapshot.reference_sha256 == hashlib.sha256(reference.read_bytes()).hexdigest()
    assert snapshot.student_sha256 == hashlib.sha256((SAMPLES / "student_missing_wall.dxf").read_bytes()).hexdigest()
    assert snapshot.reviewed_svg == review["svg"]
    assert snapshot.score_breakdown == review["score_breakdown"]
    assert snapshot.normalization_decision == review["normalization_decision"]

    mutable_copy = snapshot.review_response
    mutable_copy["score"] = 0
    mutable_copy["rubric"]["title"] = "Browser-provided replacement"
    assert snapshot.review_response["score"] == review["score"]
    assert snapshot.approved_rubric["title"] == approval["rubric"]["title"]


@pytest.mark.parametrize(
    "field,value",
    (
        ("student_name", "bad\nname"),
        ("student_id", "x" * 65),
        ("course_section", "bad\u2028section"),
    ),
)
def test_review_rejects_unsafe_or_oversized_student_metadata(field, value):
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    response = _review(reference, SAMPLES / "student_good.dxf", data={field: value})
    assert response.status_code == 422
    assert "Student" in response.json()["detail"] or "Course / section" in response.json()["detail"]


def test_report_endpoint_distinguishes_unknown_and_expired_review_ids():
    assert client.get("/api/reviews/not-a-review/report.pdf").status_code == 404

    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review = _review(reference, SAMPLES / "student_good.dxf").json()
    snapshot = REVIEW_SNAPSHOTS.get(review["review_id"])
    object.__setattr__(snapshot, "expires_at", datetime.now(timezone.utc) - timedelta(seconds=1))
    expired = client.get(f"/api/reviews/{review['review_id']}/report.pdf")
    assert expired.status_code == 410
    assert "expired" in expired.json()["detail"].lower()


def test_pdf_reopens_and_contains_authoritative_score_assignment_evidence_and_pages():
    reference = AUDIT / "00_reference_000-Simple.dxf"
    student = AUDIT / "02_missing_line_73B.dxf"
    suggestion, approval = _approve(reference)
    review_response = _review(
        reference,
        student,
        data={"student_name": "Ada Student", "student_id": "S-100", "course_section": "CAD-A"},
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["score"] == 95

    response = _pdf(review)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    reader = _reader(response)
    assert len(reader.pages) >= 2
    assert reader.metadata.title == "DraftLens EDU Drawing Assessment Report"
    text = _text(reader)
    missing = next(issue for issue in review["issues"] if issue["category"] == "missing_geometry")
    for expected in (
        "95 / 100",
        "Ada Student",
        "S-100",
        "CAD-A",
        approval["assignment_type"],
        suggestion["detected_features"][0],
        missing["issue_id"],
        "Raw deduction",
        "Applied deduction",
        "Primary command",
        "Strict placement",
    ):
        assert expected in text
    for page_number, page in enumerate(reader.pages, start=1):
        assert f"Page {page_number}" in (page.extract_text() or "")
    assert str(ROOT.resolve()) not in text


def test_pdf_is_deterministic_authoritative_vector_content_without_regrading(monkeypatch):
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review = _review(reference, SAMPLES / "student_door_window_errors.dxf").json()
    authoritative_score = review["score"]
    browser_copy = dict(review)
    browser_copy["score"] = 0

    def fail_if_regraded(*_args, **_kwargs):
        raise AssertionError("PDF export must not invoke grading")

    monkeypatch.setattr(main_module, "run_grading_pipeline", fail_if_regraded)
    first = _pdf(review)
    second = _pdf(review)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    reader = _reader(first)
    assert f"{float(authoritative_score):g} / 100" in _text(reader)
    assert f"{browser_copy['score']} / 100" not in _text(reader) or authoritative_score == 0
    assert _image_xobjects(reader) == []
    content_streams = b"\n".join(
        page.get_contents().get_data() for page in reader.pages if page.get_contents() is not None
    )
    assert re.search(rb"(?:^|\s)-?[0-9.]+ -?[0-9.]+ m(?:\s|$)", content_streams)
    assert re.search(rb"(?:^|\s)-?[0-9.]+ -?[0-9.]+ l(?:\s|$)", content_streams)


def test_pdf_filename_is_sanitized_and_unicode_metadata_remains_exact_in_snapshot():
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review_response = _review(
        reference,
        SAMPLES / "student_good.dxf",
        data={"student_name": "Zo\u00eb", "student_id": "ID/42", "course_section": "Section A"},
        reference_filename="..\\CON?.dxf",
        student_filename="..\\unsafe student.dxf",
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["student_metadata"]["student_name"] == "Zo\u00eb"
    response = _pdf(review)
    disposition = response.headers["content-disposition"]
    match = re.search(r'filename="([^"]+)"', disposition)
    assert match
    ascii_filename = match.group(1)
    assert ascii_filename.startswith("ID_42_")
    assert ascii_filename.endswith("_DraftLens_Report.pdf")
    assert not any(character in ascii_filename for character in '<>:"/\\|?*')
    assert ".." not in ascii_filename
    assert "filename*=UTF-8''" in disposition
    assert "\r" not in disposition and "\n" not in disposition


def test_unicode_outside_bundled_font_is_stored_exactly_and_rendered_as_codepoints():
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    arabic_name = "\u0645\u062d\u0645\u062f"
    review_response = _review(
        reference,
        SAMPLES / "student_good.dxf",
        data={"student_name": arabic_name},
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["student_metadata"]["student_name"] == arabic_name
    response = _pdf(review)
    assert response.status_code == 200
    reader = _reader(response)
    assert "U+0645" in _text(reader)


def test_rule_based_missing_report_preserves_score_and_deduction_evidence():
    reference = AUDIT / "00_reference_000-Simple.dxf"
    _approve(reference)
    review = _review(reference, AUDIT / "02_missing_line_73B.dxf").json()
    missing = next(issue for issue in review["issues"] if issue["category"] == "missing_geometry")
    assert review["score"] == 95
    assert missing["raw_deduction"] == missing["applied_deduction"] == 5
    text = _text(_reader(_pdf(review)))
    assert "95 / 100" in text
    assert missing["issue_id"] in text
    assert "Rule-based" in text or "rule based" in text


def test_translation_report_records_accepted_transform_and_support_evidence():
    reference = AUDIT_II / "01-ARC-Reference.dxf"
    student = AUDIT_II / "01-ARC-All-Moved.dxf"
    _approve(reference, normalization_mode="translation")
    review = _review(reference, student).json()
    assert review["score"] == 100
    assert review["normalization_decision"]["transform_applied"] is True
    assert review["normalization_decision"]["support_count"] == 3
    assert review["normalization_decision"]["evidence_count"] == 3
    text = _text(_reader(_pdf(review)))
    assert "100 / 100" in text
    assert "transform accepted" in text
    assert "support 3/3" in text


def test_exact_copy_and_supporting_findings_remain_distinct_in_reports():
    reference = AUDIT_II / "02-SQUARE-Reference.dxf"
    _approve(reference)
    exact = _review(reference, AUDIT_II / "02-SQUARE-Student-OK.dxf").json()
    assert exact["score"] == 100
    assert exact["issues"] == []
    exact_text = _text(_reader(_pdf(exact)))
    assert "100 / 100" in exact_text
    assert "No student issues detected." in exact_text

    displaced = _review(reference, AUDIT_II / "02-SQUARE-Gap-3Unit.dxf").json()
    assert displaced["score"] == 97
    assert displaced["finding_counts"]["primary_student_issues"] == 1
    assert displaced["finding_counts"]["supporting_findings"] == 2
    supporting = [issue for issue in displaced["issues"] if issue["finding_role"] == "supporting"]
    assert all(issue["applied_deduction"] == 0 for issue in supporting)
    displaced_text = _text(_reader(_pdf(displaced)))
    assert "Supporting topology findings" in displaced_text
    assert all(issue["issue_id"] in displaced_text for issue in supporting)


def test_reference_notes_are_reported_separately_with_zero_deduction():
    document = _unitless_document_bytes()
    _approve(document, filename="unitless-reference.dxf")
    review = _review(
        document,
        document,
        reference_filename="unitless-reference.dxf",
        student_filename="unitless-student.dxf",
    ).json()
    note = next(issue for issue in review["issues"] if issue["finding_role"] == "reference")
    assert review["score"] == 100
    assert note["applied_deduction"] == 0
    text = _text(_reader(_pdf(review)))
    assert "Reference notes" in text
    assert note["issue_id"] in text


def test_production_modules_do_not_import_pil_or_pillow_and_dependencies_are_pinned():
    forbidden = re.compile(
        r"^\s*(?:from\s+(?:PIL|Pillow)\b|import\s+(?:PIL|Pillow)\b)",
        re.MULTILINE,
    )
    for source in sorted((ROOT / "app").rglob("*.py")):
        assert not forbidden.search(source.read_text(encoding="utf-8")), source
    assert "reportlab==4.5.1" in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "pillow==12.3.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "pypdf==6.14.2" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()


def test_metadata_regeneration_preserves_approved_rubric_and_score():
    reference = SAMPLES / "reference.dxf"
    _, approval = _approve(reference)
    first = _review(
        reference,
        SAMPLES / "student_good.dxf",
        data={"student_name": "First Name"},
    ).json()
    second = _review(
        reference,
        SAMPLES / "student_good.dxf",
        data={"student_name": "Second Name"},
    ).json()
    assert first["review_id"] != second["review_id"]
    assert first["rubric_selection"] == second["rubric_selection"] == {
        "rubric_id": approval["rubric_id"],
        "source": "associated_approved",
    }
    assert first["score"] == second["score"] == 100
    assert first["student_metadata"]["student_name"] == "First Name"
    assert second["student_metadata"]["student_name"] == "Second Name"


def test_all_arcs_moved_strict_report_preserves_91_and_three_position_issues():
    reference = AUDIT_II / "01-ARC-Reference.dxf"
    student = AUDIT_II / "01-ARC-All-Moved.dxf"
    _approve(reference, normalization_mode="strict")
    review = _review(reference, student).json()
    primary = [issue for issue in review["issues"] if issue["finding_role"] == "primary"]
    assert review["score"] == 91
    assert len(primary) == 3
    assert {issue["category"] for issue in primary} == {"incorrect_position"}
    assert review["normalization_decision"]["transform_applied"] is False
    text = _text(_reader(_pdf(review)))
    assert "91 / 100" in text
    assert "Strict placement. No transform is permitted or applied." in text
    assert all(issue["issue_id"] in text for issue in primary)


def test_multi_page_issue_report_preserves_every_finding_and_page_number():
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review = _review(reference, SAMPLES / "student_door_window_errors.dxf").json()
    response = _pdf(review)
    reader = _reader(response)
    text = _text(reader)
    assert len(reader.pages) >= 3
    assert review["finding_counts"]["primary_student_issues"] == 4
    assert all(issue["issue_id"] in text for issue in review["issues"])
    for page_number, page in enumerate(reader.pages, start=1):
        assert f"Page {page_number}" in (page.extract_text() or "")
    assert f"{float(review['score']):g} / 100" in text


LEGEND_TITLE = "Drawing overlay legend"
LEGEND_NOTE = "Drawing issue IDs correspond to the detailed findings on the following pages."
LEGEND_EXPLANATIONS = {
    "Reference": "Approved instructor geometry",
    "Student": "Submitted student geometry",
    "Missing": "Required reference geometry absent from the submission",
    "Extra": "Unmatched geometry found only in the submission",
    "Inaccurate": "Matched geometry outside the approved tolerance",
    "Connectivity": "Junction, closure, or topology evidence",
    "Warning": "Non-critical advisory or validation note",
    "Critical": "Severe validation or assessment condition",
}


def _normalized_page_text(page):
    return " ".join((page.extract_text() or "").split())


def _assert_full_pdf_legend(reader):
    page_one = _normalized_page_text(reader.pages[0])
    assert LEGEND_TITLE in page_one
    assert LEGEND_NOTE in page_one
    assert page_one.index("Reviewed drawing") < page_one.index(LEGEND_TITLE)
    legend = page_one[page_one.index(LEGEND_TITLE):page_one.index(LEGEND_NOTE) + len(LEGEND_NOTE)]
    positions = []
    for label, explanation in LEGEND_EXPLANATIONS.items():
        assert legend.count(label) == 1
        assert explanation in legend
        positions.append(legend.index(label))
    assert positions == sorted(positions)
    assert _image_xobjects(reader) == []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = _normalized_page_text(page)
        assert "DraftLens EDU - Report" in page_text
        assert f"Page {page_number}" in page_text
    return legend


@pytest.mark.parametrize(
    "reference,student,mode,score,primary,page_count,normalization_text",
    (
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-Student-OK.dxf", "strict", 100, 0, 2, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-TwoOnly-Moved.dxf", "strict", 94, 2, 2, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-All-Moved.dxf", "strict", 91, 3, 3, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-All-Moved.dxf", "translation", 100, 0, 2, "transform accepted"),
        (AUDIT_II / "02-SQUARE-Reference.dxf", AUDIT_II / "02-SQUARE-Student-OK.dxf", "strict", 100, 0, 2, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "02-SQUARE-Reference.dxf", AUDIT_II / "02-SQUARE-Gap-3Unit.dxf", "strict", 97, 1, 2, "Strict placement. No transform is permitted or applied."),
        (SAMPLES / "reference.dxf", SAMPLES / "student_door_window_errors.dxf", "strict", 88, 4, 3, "Strict placement. No transform is permitted or applied."),
    ),
)
def test_full_overlay_legend_is_unconditional_and_preserves_controlled_reports(
    reference,
    student,
    mode,
    score,
    primary,
    page_count,
    normalization_text,
):
    _approve(reference, normalization_mode=mode)
    review = _review(reference, student).json()
    response = _pdf(review)
    reader = _reader(response)
    assert review["score"] == score
    assert review["finding_counts"]["primary_student_issues"] == primary
    assert len(reader.pages) == page_count
    report_text = _text(reader)
    assert f"{float(score):g} / 100" in report_text
    assert normalization_text in report_text
    assert all(issue["issue_id"] in report_text for issue in review["issues"])
    _assert_full_pdf_legend(reader)


def test_reference_note_report_contains_the_same_complete_legend():
    document = _unitless_document_bytes()
    _approve(document, filename="unitless-reference.dxf")
    review = _review(
        document,
        document,
        reference_filename="unitless-reference.dxf",
        student_filename="unitless-student.dxf",
    ).json()
    assert review["finding_counts"]["reference_validation_notes"] == 1
    reader = _reader(_pdf(review))
    assert len(reader.pages) == 2
    _assert_full_pdf_legend(reader)


def test_score_93_presentation_snapshot_has_complete_deterministic_vector_legend():
    from dataclasses import replace
    import json

    from app.pdf_report import generate_pdf

    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review = _review(reference, SAMPLES / "student_door_window_errors.dxf").json()
    snapshot = REVIEW_SNAPSHOTS.get(review["review_id"])
    response = snapshot.review_response
    breakdown = snapshot.score_breakdown
    response["score"] = 93
    response["score_breakdown"]["final_score"] = 93
    breakdown["final_score"] = 93
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    combined_snapshot = replace(
        snapshot,
        review_id="controlled-combined-score-93",
        review_response_json=encode(response),
        score_breakdown_json=encode(breakdown),
    )

    first = generate_pdf(combined_snapshot)
    second = generate_pdf(combined_snapshot)
    assert first == second
    reader = PdfReader(io.BytesIO(first))
    assert len(reader.pages) == 3
    report_text = _text(reader)
    assert "93 / 100" in report_text
    assert all(issue["issue_id"] in report_text for issue in review["issues"])
    _assert_full_pdf_legend(reader)


def test_legend_samples_reuse_exact_reviewed_drawing_role_styles():
    from reportlab.lib import colors

    from app.pdf_report import LegendSampleFlowable, _LEGEND_ENTRIES, _ROLE_STYLE

    class RecordingCanvas:
        def __init__(self):
            self.color = None
            self.width = None
            self.dash = ()
            self.marks = []

        def saveState(self):
            pass

        def restoreState(self):
            pass

        def setStrokeColor(self, color):
            self.color = color.hexval()

        def setFillColor(self, _color):
            pass

        def setLineWidth(self, width):
            self.width = width

        def setDash(self, dash):
            self.dash = tuple(dash)

        def line(self, *_coordinates):
            self.marks.append(("line", self.color, self.width, self.dash))

        def rect(self, *_coordinates, **_options):
            self.marks.append(("rect", self.color, self.width, self.dash))

    assert tuple(label for _role, label, _explanation in _LEGEND_ENTRIES) == tuple(LEGEND_EXPLANATIONS)

    def expected(role, marker):
        color, width, dash = _ROLE_STYLE[role]
        return marker, colors.HexColor(color).hexval(), width, tuple(dash or ())

    for role, _label, _explanation in _LEGEND_ENTRIES:
        recorder = RecordingCanvas()
        sample = LegendSampleFlowable(role)
        sample.canv = recorder
        sample.draw()
        if role == "inaccurate":
            assert recorder.marks == [
                expected("inaccurate-expected", "line"),
                expected("inaccurate-actual", "line"),
            ]
        else:
            marker = "rect" if role in {"connectivity", "warning", "critical"} else "line"
            assert recorder.marks == [expected(role, marker)]
