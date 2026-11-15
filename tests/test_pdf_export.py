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
    drawing_page = next((page for page in reader.pages if LEGEND_TITLE in (page.extract_text() or "")), reader.pages[0])
    page_text = _normalized_page_text(drawing_page)
    assert LEGEND_TITLE in page_text
    assert LEGEND_NOTE in page_text
    assert page_text.index("Reviewed drawing") < page_text.index(LEGEND_TITLE)
    legend = page_text[page_text.index(LEGEND_TITLE):page_text.index(LEGEND_NOTE) + len(LEGEND_NOTE)]
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
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-Student-OK.dxf", "strict", 100, 0, 9, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-TwoOnly-Moved.dxf", "strict", 94, 2, 9, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-All-Moved.dxf", "strict", 91, 3, 10, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "01-ARC-Reference.dxf", AUDIT_II / "01-ARC-All-Moved.dxf", "translation", 100, 0, 9, "transform accepted"),
        (AUDIT_II / "02-SQUARE-Reference.dxf", AUDIT_II / "02-SQUARE-Student-OK.dxf", "strict", 100, 0, 9, "Strict placement. No transform is permitted or applied."),
        (AUDIT_II / "02-SQUARE-Reference.dxf", AUDIT_II / "02-SQUARE-Gap-3Unit.dxf", "strict", 97, 1, 9, "Strict placement. No transform is permitted or applied."),
        (SAMPLES / "reference.dxf", SAMPLES / "student_door_window_errors.dxf", "strict", 88, 4, 10, "Strict placement. No transform is permitted or applied."),
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
    assert len(reader.pages) == 9
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
    assert len(reader.pages) == 10
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


def test_compact_unique_badge_assignment():
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing, assign_badge_labels

    lines = [
        Entity(id=f"R-{i:03d}", kind="line", layer="0", points=[(float(i * 10), 0.0), (float(i * 10 + 5), 0.0)])
        for i in range(5)
    ]
    ref = Drawing(lines, (0.0, 0.0, 50.0, 10.0))
    stu = Drawing([], (0.0, 0.0, 50.0, 10.0))

    raw_issues = [
        {"error_id": "ISSUE-001", "category": "missing_geometry", "severity": "warning", "reference_entity_id": "R-001"},
        {"error_id": "ISSUE-002", "category": "missing_geometry", "severity": "warning", "reference_entity_id": "R-002"},
        {"error_id": "ISSUE-003", "category": "extra_geometry", "severity": "warning"},
        {"error_id": "ISSUE-004", "category": "endpoint_gap", "severity": "warning"},
    ]
    reviewed = build_reviewed_drawing(ref, stu, {"score": 80.0, "issues": raw_issues})
    assert len(reviewed.issues) == 4
    badges = {iss.issue_id: iss.badge_label for iss in reviewed.issues}
    assert badges["ISSUE-001"] == "M1"
    assert badges["ISSUE-002"] == "M2"
    assert badges["ISSUE-003"] == "E1"
    assert badges["ISSUE-004"] == "C1"

    # Verify dict serialization preserves badge_label
    d = reviewed.issues[0].to_dict()
    assert d["badge_label"] == "M1"
    assert d["issue_id"] == "ISSUE-001"

    # Verify mixing pre-labelled and unlabelled issues never produces duplicate badges
    from dataclasses import replace as dc_replace
    mixed = [
        dc_replace(reviewed.issues[0], issue_id="ISSUE-001", badge_label="M1"),
        dc_replace(reviewed.issues[1], issue_id="ISSUE-002", badge_label=None),
        dc_replace(reviewed.issues[0], issue_id="ISSUE-003", badge_label="M1"),  # duplicate pre-label
    ]
    reassigned = assign_badge_labels(mixed)
    reassigned_badges = [iss.badge_label for iss in reassigned]
    assert len(set(reassigned_badges)) == 3
    assert reassigned_badges == ["M1", "M2", "M3"]


def test_pdf_mapping_table_has_badge_column_and_no_badge_collisions():
    import io
    from pypdf import PdfReader
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import generate_pdf, ReviewedDrawingFlowable, CoordinateTransform
    from dataclasses import replace

    # Build reference and student with 3 adjacent missing squares
    ref_entities = []
    for sq in range(3):
        ox = sq * 30.0
        for i, (p1, p2) in enumerate([
            ((ox, 0.0), (ox + 20.0, 0.0)),
            ((ox + 20.0, 0.0), (ox + 20.0, 20.0)),
            ((ox + 20.0, 20.0), (ox, 20.0)),
            ((ox, 20.0), (ox, 0.0)),
        ]):
            ref_entities.append(Entity(id=f"R-SQ{sq}-E{i}", kind="line", layer="0", points=[p1, p2]))

    ref = Drawing(ref_entities, (0.0, 0.0, 100.0, 30.0))
    stu = Drawing([], (0.0, 0.0, 100.0, 30.0))

    raw_issues = [
        {"error_id": "ISSUE-OBJ-001", "code": "MISSING_OBJECT", "category": "missing_geometry", "severity": "warning", "parent_object_id": "OBJ-001", "measurement": {"source_entity_ids": ["R-SQ0-E0", "R-SQ0-E1", "R-SQ0-E2", "R-SQ0-E3"], "missing_part_count": 4, "total_part_count": 4}},
        {"error_id": "ISSUE-OBJ-002", "code": "MISSING_OBJECT", "category": "missing_geometry", "severity": "warning", "parent_object_id": "OBJ-002", "measurement": {"source_entity_ids": ["R-SQ1-E0", "R-SQ1-E1", "R-SQ1-E2", "R-SQ1-E3"], "missing_part_count": 4, "total_part_count": 4}},
        {"error_id": "ISSUE-OBJ-003", "code": "MISSING_OBJECT", "category": "missing_geometry", "severity": "warning", "parent_object_id": "OBJ-003", "measurement": {"source_entity_ids": ["R-SQ2-E0", "R-SQ2-E1", "R-SQ2-E2", "R-SQ2-E3"], "missing_part_count": 4, "total_part_count": 4}},
    ]
    comparison = {
        "score": 70.0,
        "issues": raw_issues,
        "assessment_objects": [
            {"object_id": "OBJ-001", "source_entity_ids": ["R-SQ0-E0", "R-SQ0-E1", "R-SQ0-E2", "R-SQ0-E3"], "bbox": (0.0, 0.0, 20.0, 20.0)},
            {"object_id": "OBJ-002", "source_entity_ids": ["R-SQ1-E0", "R-SQ1-E1", "R-SQ1-E2", "R-SQ1-E3"], "bbox": (30.0, 0.0, 50.0, 20.0)},
            {"object_id": "OBJ-003", "source_entity_ids": ["R-SQ2-E0", "R-SQ2-E1", "R-SQ2-E2", "R-SQ2-E3"], "bbox": (60.0, 0.0, 80.0, 20.0)},
        ],
    }
    reviewed = build_reviewed_drawing(ref, stu, comparison)
    assert [iss.badge_label for iss in reviewed.issues] == ["M1", "M2", "M3"]

    # Verify flowable collision avoidance
    flowable = ReviewedDrawingFlowable(reviewed, width=540.0)

    # Simulate canvas recording to check placed badges
    class BoxRecorder:
        def __init__(self):
            self.round_rects = []
            self.lines = []
            self.strings = []

        def saveState(self): pass
        def restoreState(self): pass
        def setStrokeColor(self, c): pass
        def setFillColor(self, c): pass
        def setLineWidth(self, w): pass
        def setDash(self, d): pass
        def setFont(self, f, s): pass
        def rect(self, *a, **k): pass
        def circle(self, *a, **k): pass
        def line(self, x1, y1, x2, y2): self.lines.append((x1, y1, x2, y2))
        def drawString(self, x, y, text): self.strings.append((x, y, text))
        def drawCentredString(self, *a): pass
        def roundRect(self, x, y, w, h, r, stroke=1, fill=1):
            if w < 500:  # exclude background canvas box
                self.round_rects.append((x, y, w, h))

    recorder = BoxRecorder()
    flowable.canv = recorder
    flowable.draw()

    # Verify 3 badge pills were drawn
    assert len(recorder.round_rects) == 3
    # Check that no two badge boxes collide (overlap)
    for i in range(len(recorder.round_rects)):
        x1, y1, w1, h1 = recorder.round_rects[i]
        assert 4.0 <= x1 <= flowable.width - w1 - 4.0
        assert 4.0 <= y1 <= flowable.height - h1 - 4.0
        for j in range(i + 1, len(recorder.round_rects)):
            x2, y2, w2, h2 = recorder.round_rects[j]
            # No overlap with 2.0 margin
            assert (x1 + w1 + 2.0 <= x2) or (x2 + w2 + 2.0 <= x1) or (y1 + h1 + 2.0 <= y2) or (y2 + h2 + 2.0 <= y1)

    # Verify strings include M1, M2, M3
    texts = [s[2] for s in recorder.strings]
    assert "M1" in texts
    assert "M2" in texts
    assert "M3" in texts

    # Verify PDF report generation contains mapping table with Badge column
    reference = SAMPLES / "reference.dxf"
    _approve(reference)
    review = _review(reference, SAMPLES / "student_door_window_errors.dxf").json()
    snapshot = REVIEW_SNAPSHOTS.get(review["review_id"])
    combined_snapshot = replace(snapshot, reviewed_drawing=reviewed)
    pdf_bytes = generate_pdf(combined_snapshot)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    drawing_pages_text = "\n".join(page.extract_text() or "" for page in reader.pages[1:8])
    assert "Badge" in drawing_pages_text
    assert "Issue ID" in drawing_pages_text
    assert "Issue-to-drawing mapping" in drawing_pages_text
    assert "M1" in drawing_pages_text
    assert "M2" in drawing_pages_text
    assert "M3" in drawing_pages_text
    assert "<b>" not in drawing_pages_text
    assert "</b>" not in drawing_pages_text


def test_pdf_mapping_table_badge_column_clean_labels_without_literal_markup():
    """Focused regression check: mapping table displays clean badge labels (M1, M2, W1) without literal markup."""
    import io
    import json
    from datetime import datetime, timezone
    from pypdf import PdfReader
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.review_snapshot import ReviewSnapshot, StudentMetadata
    from app.pdf_report import generate_pdf

    ref_entities = [
        Entity(id="R1", kind="line", layer="0", points=[(0.0, 0.0), (10.0, 0.0)]),
        Entity(id="R2", kind="line", layer="0", points=[(0.0, 20.0), (10.0, 20.0)]),
    ]
    ref = Drawing(ref_entities, (0.0, 0.0, 30.0, 30.0))
    stu = Drawing([], (0.0, 0.0, 30.0, 30.0))

    raw_issues = [
        {
            "issue_id": "ISSUE-M01",
            "error_id": "ISSUE-M01",
            "code": "MISSING_OBJECT",
            "category": "missing_geometry",
            "severity": "warning",
            "parent_object_id": "OBJ-1",
            "measurement": {"missing_part_count": 1, "total_part_count": 1},
        },
        {
            "issue_id": "ISSUE-M02",
            "error_id": "ISSUE-M02",
            "code": "MISSING_OBJECT",
            "category": "missing_geometry",
            "severity": "warning",
            "parent_object_id": "OBJ-2",
            "measurement": {"missing_part_count": 1, "total_part_count": 1},
        },
        {
            "issue_id": "ISSUE-W01",
            "error_id": "ISSUE-W01",
            "code": "LAYER_WARNING",
            "category": "drawing_scale",
            "severity": "warning",
            "visual_role": "warning",
            "measurement": {},
        },
    ]
    comp = {
        "score": 75.0,
        "issues": raw_issues,
        "assessment_objects": [
            {"object_id": "OBJ-1", "source_entity_ids": ["R1"], "bbox": (0.0, 0.0, 10.0, 10.0)},
            {"object_id": "OBJ-2", "source_entity_ids": ["R2"], "bbox": (0.0, 20.0, 10.0, 30.0)},
        ],
    }
    reviewed = build_reviewed_drawing(ref, stu, comp)

    snap = ReviewSnapshot(
        review_id="rev-regression-clean-badges-001",
        report_timestamp=datetime.now(timezone.utc).isoformat(),
        expires_at=datetime.now(timezone.utc),
        reference_filename="ref.dxf",
        reference_sha256="0" * 64,
        raw_reference_bytes=b"",
        student_filename="stu.dxf",
        student_sha256="0" * 64,
        raw_student_bytes=b"",
        student_metadata=StudentMetadata(student_name="Jane Doe", student_id="STU-01", course_section="CAD-101"),
        approved_rubric_id=None,
        approved_rubric_json="{}",
        assignment_title="Badge Regression Test",
        assignment_type="geometric",
        suggested_assignment_type="geometric",
        detected_features=(),
        reviewed_drawing=reviewed,
        review_response_json=json.dumps({"score": 75.0, "issues": raw_issues}),
        reviewed_svg="<svg></svg>",
        score_breakdown_json=json.dumps({"overall": 75.0}),
        normalization_decision_json=json.dumps({"accepted": False, "mode": "strict"}),
    )

    pdf_bytes = generate_pdf(snap)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    drawing_pages_text = "\n".join(page.extract_text() or "" for page in reader.pages[1:8])

    # Must contain clean labels
    assert "M1" in drawing_pages_text
    assert "M2" in drawing_pages_text
    assert "W1" in drawing_pages_text

    # Must NOT contain literal HTML markup or escaped entities
    assert "<b>" not in drawing_pages_text
    assert "</b>" not in drawing_pages_text
    assert "&lt;" not in drawing_pages_text
    assert "&gt;" not in drawing_pages_text
    assert "<font" not in drawing_pages_text

    # Preserves badge-to-issue mappings
    lines = [line.strip() for line in drawing_pages_text.splitlines() if line.strip()]
    assert "M1" in lines
    assert "M2" in lines
    assert "W1" in lines
    assert "ISSUE-M01" in drawing_pages_text
    assert "ISSUE-M02" in drawing_pages_text
    assert "ISSUE-W01" in drawing_pages_text


def test_pdf_arc_circle_anchors_on_geometry_and_overflow_notice():
    """Verify arc/circle leader lines anchor strictly to curves and overflow notice text never overflows page."""
    import math
    import io
    import pymupdf
    from reportlab.pdfgen import canvas
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import ReviewedDrawingFlowable, CoordinateTransform

    # 1. Test arc and circle anchor points
    arc_center = (50.0, 50.0)
    arc_radius = 20.0
    circ_center = (80.0, 80.0)
    circ_radius = 15.0
    ref_entities = [
        Entity(id="R-ARC", kind="arc", layer="0", points=[arc_center], radius=arc_radius, start_angle=0.0, end_angle=180.0),
        Entity(id="R-CIRC", kind="circle", layer="0", points=[circ_center], radius=circ_radius),
    ]
    ref = Drawing(ref_entities, (0.0, 0.0, 100.0, 100.0))
    stu = Drawing([], (0.0, 0.0, 100.0, 100.0))

    raw_issues = [
        {"error_id": "ISSUE-ARC", "code": "MISSING_ENTITY", "category": "missing_geometry", "severity": "warning", "visual_role": "missing", "reference_entity_id": "R-ARC", "measurement": {}},
        {"error_id": "ISSUE-CIRC", "code": "MISSING_ENTITY", "category": "missing_geometry", "severity": "warning", "visual_role": "missing", "reference_entity_id": "R-CIRC", "measurement": {}},
    ]
    comparison = {"score": 80.0, "issues": raw_issues, "assessment_objects": []}
    reviewed = build_reviewed_drawing(ref, stu, comparison)
    flowable = ReviewedDrawingFlowable(reviewed, width=500.0)

    class LeaderRecorder:
        def __init__(self):
            self.lines = []
            self.circles = []
            self.round_rects = []
            self.strings = []
        def saveState(self): pass
        def restoreState(self): pass
        def setStrokeColor(self, c): pass
        def setFillColor(self, c): pass
        def setLineWidth(self, w): pass
        def setDash(self, d): pass
        def setFont(self, f, s): pass
        def rect(self, *a, **k): pass
        def circle(self, x, y, r, stroke=1, fill=1): self.circles.append((x, y, r))
        def arc(self, *a, **k): pass
        def beginPath(self, *a, **k): pass
        def drawPath(self, *a, **k): pass
        def line(self, x1, y1, x2, y2): self.lines.append((x1, y1, x2, y2))
        def drawString(self, x, y, text): self.strings.append((x, y, text))
        def roundRect(self, x, y, w, h, r, stroke=1, fill=1):
            if w < 480:
                self.round_rects.append((x, y, w, h))

    rec = LeaderRecorder()
    flowable.canv = rec
    flowable.draw()

    # Must have drawn 2 leader lines
    assert len(rec.lines) == 2
    transform = CoordinateTransform(reviewed.extents, flowable.width, flowable.height, 36.0)
    arc_cp = flowable._point(transform, arc_center)
    arc_r = transform.length(arc_radius)
    circ_cp = flowable._point(transform, circ_center)
    circ_r = transform.length(circ_radius)

    found_arc = False
    found_circ = False
    for ax, ay, cx, cy in rec.lines:
        dist_arc = math.hypot(ax - arc_cp[0], ay - arc_cp[1])
        dist_circ = math.hypot(ax - circ_cp[0], ay - circ_cp[1])
        if math.isclose(dist_arc, arc_r, abs_tol=0.5):
            assert dist_arc > 5.0, "Arc anchor must not be at center point"
            found_arc = True
        elif math.isclose(dist_circ, circ_r, abs_tol=0.5):
            assert dist_circ > 5.0, "Circle anchor must not be at center point"
            found_circ = True
    assert found_arc, "Arc leader line did not anchor to arc curve"
    assert found_circ, "Circle leader line did not anchor to circle circumference"

    # 2. Test badge overflow notice wrapping, non-collision, and PyMuPDF full text extraction
    many_issues = []
    for i in range(100):
        many_issues.append({
            "error_id": f"ISSUE-{i:03d}",
            "code": "MISSING_ENTITY",
            "category": "missing_geometry",
            "severity": "warning",
            "visual_role": "missing",
            "reference_entity_id": "R-ARC",
            "location": [50.0, 50.0],
            "measurement": {},
        })
    comp_overflow = {"score": 50.0, "issues": many_issues, "assessment_objects": []}
    reviewed_overflow = build_reviewed_drawing(ref, stu, comp_overflow)
    flowable_overflow = ReviewedDrawingFlowable(reviewed_overflow, width=300.0)

    # Render actual PDF bytes and inspect with PyMuPDF
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300.0, flowable_overflow.height + 20.0))
    flowable_overflow.canv = c
    flowable_overflow.draw()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    page_text = doc[0].get_text()
    # Must contain full promised table guidance intact without being clipped
    assert "findings" in page_text
    assert ("listed in findings table below" in page_text or "see findings table below" in page_text or "see table below" in page_text)
    # The text must not contain cut off fragments
    assert "space co" not in page_text

    # 3. Test location-only and region-only findings (no resolvable feature):
    # Must NEVER anchor a leader line or dot to an empty circle center or centroid,
    # and must explicitly report the unanchored limitation in the notice strip.
    probe_ref = Drawing(
        [Entity(id="R-PROBE-CIRC", kind="circle", layer="0", points=[(50.0, 50.0)], radius=35.0)],
        (0.0, 0.0, 100.0, 100.0),
    )
    probe_stu = Drawing([], (0.0, 0.0, 100.0, 100.0))
    for unanchored_issue in (
        {"error_id": "E-LOC-ONLY", "category": "missing_geometry", "severity": "major", "location": (50.0, 50.0)},
        {"error_id": "E-REG-ONLY", "category": "missing_geometry", "severity": "major", "region": (15.0, 15.0, 85.0, 85.0)},
    ):
        probe_reviewed = build_reviewed_drawing(probe_ref, probe_stu, {"score": 90.0, "issues": [unanchored_issue]})
        probe_flowable = ReviewedDrawingFlowable(probe_reviewed, width=300.0)
        probe_rec = LeaderRecorder()
        probe_flowable.canv = probe_rec
        probe_flowable.draw()

        # Zero leader lines and zero anchor dots (only the reference circle itself is drawn)
        assert probe_rec.lines == [], f"Unanchored finding must not draw an off-feature leader line: {probe_rec.lines}"
        anchor_dots = [c_item for c_item in probe_rec.circles if c_item[2] <= 2.0]
        assert anchor_dots == [], f"Unanchored finding must not draw an off-feature anchor dot: {anchor_dots}"

        # Render to PDF and verify explicit unanchored notice via PyMuPDF
        probe_buf = io.BytesIO()
        probe_canv = canvas.Canvas(probe_buf, pagesize=(300.0, probe_flowable.height + 20.0))
        probe_flowable.canv = probe_canv
        probe_flowable.draw()
        probe_canv.save()
        probe_doc = pymupdf.open(stream=probe_buf.getvalue(), filetype="pdf")
        probe_text = probe_doc[0].get_text()
        assert "M1" in probe_text
        assert "unanchored" in probe_text
        assert "see findings table below" in probe_text


def test_dense_overview_badges_have_zero_crossing_leaders():
    """Verify that a dense drawing with 60 badges has ZERO crossing leader lines."""
    import math
    import io
    import pymupdf
    from reportlab.pdfgen import canvas
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import ReviewedDrawingFlowable, _segments_cross

    ref_entities = []
    stu_entities = []
    issues = []

    # Create 30 upper features and 30 lower features
    for i in range(30):
        x1 = 20.0 + i * 15.0
        y1_up = 65.0 + (i % 5) * 5.0
        x2 = x1 + 10.0
        y2_up = y1_up + 3.0
        ref_entities.append(Entity(id=f"R-UP-{i}", kind="line", layer="0", points=[(x1, y1_up), (x2, y2_up)]))
        stu_entities.append(Entity(id=f"S-UP-{i}", kind="line", layer="0", points=[(x1 + 1.0, y1_up + 1.0), (x2 + 1.0, y2_up + 1.0)]))
        issues.append({
            "error_id": f"ISSUE-UP-{i}",
            "code": "INCORRECT_POSITION",
            "category": "incorrect_position",
            "severity": "major",
            "reference_entity_id": f"R-UP-{i}",
            "student_entity_id": f"S-UP-{i}",
            "measurement": {},
        })

        y1_dn = 15.0 + (i % 5) * 5.0
        y2_dn = y1_dn + 3.0
        ref_entities.append(Entity(id=f"R-DN-{i}", kind="line", layer="0", points=[(x1, y1_dn), (x2, y2_dn)]))
        stu_entities.append(Entity(id=f"S-DN-{i}", kind="line", layer="0", points=[(x1 + 1.0, y1_dn + 1.0), (x2 + 1.0, y2_dn + 1.0)]))
        issues.append({
            "error_id": f"ISSUE-DN-{i}",
            "code": "INCORRECT_POSITION",
            "category": "incorrect_position",
            "severity": "major",
            "reference_entity_id": f"R-DN-{i}",
            "student_entity_id": f"S-DN-{i}",
            "measurement": {},
        })

    ref = Drawing(ref_entities, (0.0, 0.0, 500.0, 100.0))
    stu = Drawing(stu_entities, (0.0, 0.0, 500.0, 100.0))
    comp = {"score": 37.5, "issues": issues, "assessment_objects": []}
    reviewed = build_reviewed_drawing(ref, stu, comp)

    flowable = ReviewedDrawingFlowable(reviewed, width=500.0, height=240.0, role_filter="inaccurate")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(500.0, 240.0))
    flowable.canv = c
    flowable.draw()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    page = doc[0]
    paths = page.get_drawings()
    leaders = []
    for p in paths:
        if abs((p.get("width") or 0) - 0.65) < 1e-4 and p.get("type") == "s" and len(p.get("items", [])) == 1 and p["items"][0][0] == "l":
            a, b = p["items"][0][1:]
            leaders.append(((a.x, a.y), (b.x, b.y)))

    assert len(leaders) >= 50, f"Expected dense leader count >= 50, got {len(leaders)}"

    # Check for any crossing leader lines
    crossings = []
    for i in range(len(leaders)):
        for j in range(i + 1, len(leaders)):
            if _segments_cross(leaders[i][0], leaders[i][1], leaders[j][0], leaders[j][1]):
                crossings.append((i, j))

    assert crossings == [], f"Expected 0 leader crossings on dense overview, got {len(crossings)} crossings: {crossings}"


def test_dense_inaccurate_upper_right_and_edge_clusters_have_zero_badge_collisions():
    """Regression for Page 5 upper-right badge collision (I19/I30/I233/I167/I8/I203) and Page 8 empty-role notice."""
    import io
    import re
    import pymupdf
    from reportlab.pdfgen import canvas
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import ReviewedDrawingFlowable

    def _boxes_collide(
        b1: tuple[float, float, float, float],
        b2: tuple[float, float, float, float],
        pad: float = 0.0,
    ) -> bool:
        x1, y1, w1, h1 = b1
        x2, y2, w2, h2 = b2
        return not (
            x1 + w1 + pad <= x2
            or x2 + w2 + pad <= x1
            or y1 + h1 + pad <= y2
            or y2 + h2 + pad <= y1
        )

    ref_entities = []
    stu_entities = []
    issues = []

    # 120 inaccurate findings clustered heavily near the right and left edges in both half-planes,
    # producing 1-, 2-, and 3-digit I-badges (I1..I120) that fill all 4 horizontal rows and overflow
    # into the bottom Notice strip.
    idx = 0
    for half in ("top", "bot"):
        for k in range(60):
            idx += 1
            # Cluster heavily toward the right edge (x in 340..488) and left edge (x in 5..66)
            if k < 12:
                x1 = 5.0 + k * 5.5
            else:
                x1 = 340.0 + (k - 12) * 3.1
            y_base = (72.0 + (k % 7) * 3.2) if half == "top" else (12.0 + (k % 7) * 3.2)
            x2 = x1 + 4.0
            y2 = y_base + 2.0
            rid = f"R-CLUST-{idx:03d}"
            sid = f"S-CLUST-{idx:03d}"
            ref_entities.append(Entity(id=rid, kind="line", layer="0", points=[(x1, y_base), (x2, y2)]))
            stu_entities.append(Entity(id=sid, kind="line", layer="0", points=[(x1 + 0.8, y_base + 0.6), (x2 + 0.8, y2 + 0.6)]))
            issues.append({
                "error_id": f"ERR-CLUST-{idx:03d}",
                "code": "INCORRECT_POSITION",
                "category": "incorrect_position",
                "severity": "major",
                "reference_entity_id": rid,
                "student_entity_id": sid,
                "measurement": {},
            })

    ref = Drawing(ref_entities, (0.0, 0.0, 500.0, 100.0))
    stu = Drawing(stu_entities, (0.0, 0.0, 500.0, 100.0))
    comp = {"score": 27.75, "issues": issues, "assessment_objects": []}
    reviewed = build_reviewed_drawing(ref, stu, comp)

    w_pt, h_pt = 492.567, 240.0
    flowable = ReviewedDrawingFlowable(reviewed, width=w_pt, height=h_pt, role_filter="inaccurate")

    class PillRecorder:
        def __init__(self):
            self.pills = []
            self.notices = []
            self.centred = []

        def saveState(self): pass
        def restoreState(self): pass
        def setStrokeColor(self, c): pass
        def setFillColor(self, c): pass
        def setLineWidth(self, w): pass
        def setDash(self, d): pass
        def setFont(self, f, s): pass
        def rect(self, *a, **k): pass
        def circle(self, *a, **k): pass
        def arc(self, *a, **k): pass
        def beginPath(self, *a, **k): pass
        def drawPath(self, *a, **k): pass
        def line(self, *a, **k): pass
        def drawString(self, *a, **k): pass
        def drawCentredString(self, x, y, text):
            self.centred.append((x, y, text))
        def roundRect(self, x, y, w, h, r, stroke=1, fill=1):
            if w >= w_pt - 1.0:
                return
            if abs(h - 11.5) < 0.2:
                self.pills.append((x, y, w, h))
            else:
                self.notices.append((x, y, w, h))

    rec = PillRecorder()
    flowable.canv = rec
    flowable.draw()

    assert len(rec.pills) >= 60, f"Expected at least 60 placed badges across 4 rows, got {len(rec.pills)}"
    assert len(rec.notices) == 1, f"Expected 1 bottom overflow notice strip, got {rec.notices}"

    valid_row_ys = {11.0, 24.5, h_pt - 29.0, h_pt - 15.5}
    for idx_a, box_a in enumerate(rec.pills):
        bx, by, bw, bh = box_a
        assert any(abs(by - ry) < 1e-4 for ry in valid_row_ys), f"Badge hijacked outside horizontal gutters: {box_a}"
        assert 4.0 - 1e-4 <= bx and bx + bw <= w_pt - 4.0 + 1e-4, f"Badge out of horizontal bounds: {box_a}"
        for box_b in rec.pills[idx_a + 1:]:
            assert not _boxes_collide(box_a, box_b, pad=0.8), f"Badge pills collide: {box_a} vs {box_b}"
        for nbox in rec.notices:
            assert not _boxes_collide(box_a, nbox, pad=0.5), f"Badge pill collides with notice strip: {box_a} vs {nbox}"

    # Render to actual PDF and verify PyMuPDF text spans and vector pill rectangles have zero overlap
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))
    flowable.canv = c
    flowable.draw()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    page = doc[0]
    spans = [
        (s["text"], s["bbox"])
        for b in page.get_text("dict")["blocks"]
        if "lines" in b
        for ln in b["lines"]
        for s in ln["spans"]
        if re.fullmatch(r"I\d+", s["text"])
    ]
    assert len(spans) == len(rec.pills)
    for i in range(len(spans)):
        t1, b1 = spans[i]
        r1 = pymupdf.Rect(b1)
        for j in range(i + 1, len(spans)):
            t2, b2 = spans[j]
            inter = r1 & pymupdf.Rect(b2)
            assert not (inter.width > 0.5 and inter.height > 0.5), (
                f"Badge text spans overlap: {t1} {b1} vs {t2} {b2}"
            )

    # Verify empty-role flowable (e.g. Page 8 "No critical findings.") places text in top gutter above geom_box
    crit_flowable = ReviewedDrawingFlowable(reviewed, width=w_pt, height=h_pt, role_filter="critical")
    crit_rec = PillRecorder()
    crit_flowable.canv = crit_rec
    crit_flowable.draw()
    assert len(crit_rec.centred) == 1
    _cx, cy, ctext = crit_rec.centred[0]
    assert ctext == "No critical findings."
    assert cy >= h_pt - 36.0, f"Expected empty-role notice in top gutter above geometry box, got y={cy}"


def _snapshot_proxy(base_snapshot, *, reviewed, response_patch):
    """Lightweight read-only proxy delegating unchanged ReviewSnapshot attributes for PDF tests."""
    from copy import deepcopy

    merged_response = deepcopy(base_snapshot.review_response)
    merged_response.update(response_patch)

    class _Proxy:
        review_id = "synthetic-pdf-regression"
        reviewed_drawing = reviewed
        review_response = merged_response

        def __getattr__(self, name):
            return getattr(base_snapshot, name)

    return _Proxy()


def test_detached_object_position_uses_student_frame_and_isolates_final_sheet():
    """Detached object-level position issues must omit raw expected dashes and keep local student zoom."""
    from dataclasses import replace
    import pymupdf
    from reportlab.lib import colors
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import _ROLE_STYLE, _is_detached_placement_issue, generate_pdf

    doc_bytes = _unitless_document_bytes()
    _approve(doc_bytes, filename="base-ref.dxf")
    base_review = _review(doc_bytes, doc_bytes).json()
    base_snapshot = REVIEW_SNAPSHOTS.get(base_review["review_id"])

    ref_entities = [
        Entity(id="R-OBJ1-0", kind="line", layer="0", points=[(0.0, 0.0), (20.0, 0.0)]),
        Entity(id="R-OBJ1-1", kind="line", layer="0", points=[(20.0, 0.0), (20.0, 10.0)]),
        Entity(id="R-OBJ1-2", kind="line", layer="0", points=[(20.0, 10.0), (0.0, 10.0)]),
        Entity(id="R-OBJ1-3", kind="line", layer="0", points=[(0.0, 10.0), (0.0, 0.0)]),
    ]
    stu_entities = [
        Entity(id="S-OBJ1-0", kind="line", layer="0", points=[(500.0, 500.0), (520.0, 500.0)]),
        Entity(id="S-OBJ1-1", kind="line", layer="0", points=[(520.0, 500.0), (520.0, 510.0)]),
        Entity(id="S-OBJ1-2", kind="line", layer="0", points=[(520.0, 510.0), (500.0, 510.0)]),
        Entity(id="S-OBJ1-3", kind="line", layer="0", points=[(500.0, 510.0), (500.0, 500.0)]),
    ]
    comp_issues = []
    for idx in range(13):
        rid = f"R-SM-{idx}"
        ref_entities.append(Entity(id=rid, kind="line", layer="0", points=[(idx * 0.1, 0.0), (idx * 0.1 + 1.0, 1.0)]))
        comp_issues.append({
            "error_id": f"ERR-SM-{idx}",
            "code": "MISSING_ENTITY",
            "category": "missing_geometry",
            "severity": "major",
            "reference_entity_id": rid,
            "parent_object_id": "OBJ-001",
            "component_id": rid,
            "measurement": {},
        })

    pos_raw = {
        "error_id": "ISSUE-OBJ-001-POS",
        "code": "INCORRECT_POSITION",
        "category": "incorrect_position",
        "severity": "major",
        "reference_entity_id": "R-OBJ1-0",
        "student_entity_id": "S-OBJ1-0",
        "parent_object_id": "OBJ-001",
        "measurement": {"dx": 500.0, "dy": 500.0},
    }
    raw_by_id = {item["error_id"]: item for item in [pos_raw, *comp_issues]}
    comp = {
        "score": 80.0,
        "issues": [pos_raw, *comp_issues],
        "assessment_objects": [
            {
                "object_id": "OBJ-001",
                "component_count": 14,
                "bounds": [0.0, 0.0, 20.0, 10.0],
            }
        ],
    }
    reviewed = build_reviewed_drawing(
        Drawing(ref_entities, (0.0, 0.0, 20.0, 10.0)),
        Drawing(stu_entities, (500.0, 500.0, 520.0, 510.0)),
        comp,
    )
    # Populate full student perimeter on ISSUE-OBJ-001-POS and align component issues to student frame
    pos_orig = next(i for i in reviewed.issues if i.issue_id == "ISSUE-OBJ-001-POS")
    stu_reviewed_geoms = tuple(
        replace(
            pos_orig.actual_geometries[0],
            entity_id=e.entity_id,
            points=e.points,
            bbox=e.bbox,
        )
        for e in reviewed.student_entities
    )
    patched_issues = []
    for iss in reviewed.issues:
        if iss.issue_id == "ISSUE-OBJ-001-POS":
            patched_issues.append(replace(
                iss,
                parent_object_id="OBJ-001",
                component_id=None,
                actual_geometries=stu_reviewed_geoms,
                region=(0.0, 0.0, 520.0, 510.0),
            ))
        else:
            # Local tiny missing mark at (500..502, 500..502) — spans 2x2 (<70% of 20x10 object)
            patched_issues.append(replace(
                iss,
                parent_object_id="OBJ-001",
                component_id=iss.issue_id,
                expected_geometries=(replace(
                    iss.expected_geometries[0],
                    points=((500.0, 500.0), (502.0, 502.0)),
                    bbox=(500.0, 500.0, 502.0, 502.0),
                ),),
                region=(500.0, 500.0, 502.0, 502.0),
            ))
    reviewed = replace(reviewed, issues=tuple(patched_issues))

    pos_iss = next(i for i in reviewed.issues if i.issue_id == "ISSUE-OBJ-001-POS")
    comp_iss = next(i for i in reviewed.issues if i.issue_id != "ISSUE-OBJ-001-POS")
    assert _is_detached_placement_issue(pos_iss)
    assert not _is_detached_placement_issue(comp_iss)

    resp_issues = [
        {
            "issue_id": iss.issue_id,
            "code": raw_by_id[iss.issue_id]["code"],
            "category": iss.category,
            "badge_label": iss.badge_label,
            "visual_role": iss.visual_role,
            "severity": "major",
            "classification": "primary",
            "provenance": "comparison",
            "deduction": 1.0,
            "applied_deduction": 1.0,
            "deduction_status": "applied",
            "reference_entity_id": iss.expected_entity_id,
            "student_entity_id": iss.source_entity_id,
            "description": f"Synthetic {iss.issue_id}",
            "confidence": "verified",
        }
        for iss in reviewed.issues
    ]
    proxy = _snapshot_proxy(
        base_snapshot,
        reviewed=reviewed,
        response_patch={
            "score": 80.0,
            "rubric_version": "2.1",
            "assessment_objects": comp["assessment_objects"],
            "object_translations": {"OBJ-001": [500.0, 500.0]},
            "issues": resp_issues,
            "score_breakdown": {"final_score": 80.0, "deduction_items": []},
        },
    )
    pdf_bytes = generate_pdf(proxy)
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    part3_pages = [
        p for p in doc
        if "Sheet D-1c - Object Detail (OBJ-001 — Part 3 of 3)" in (p.get_text() or "")
    ]
    assert len(part3_pages) == 1, f"Expected dedicated final sheet Sheet D-1c for ISSUE-OBJ-001-POS, pages={[p.get_text()[:120] for p in doc]}"
    target_page = part3_pages[0]
    assert "ISSUE-OBJ-001-POS" in (target_page.get_text() or "")

    inacc_rgb = colors.HexColor(_ROLE_STYLE["inaccurate-actual"][0]).rgb()

    def _is_red(c):
        return c and abs(c[0] - inacc_rgb[0]) < 0.04 and abs(c[1] - inacc_rgb[1]) < 0.04 and abs(c[2] - inacc_rgb[2]) < 0.04

    # Exclude the small legend sample swatch (~24pt wide below the main 205pt drawing box)
    drawing_strokes = [
        d for d in target_page.get_drawings()
        if _is_red(d.get("color")) and d["rect"].y0 < 400.0
    ]
    dashed_red = [d for d in drawing_strokes if d.get("dashes") and "[]" not in d["dashes"]]
    assert dashed_red == [], f"Detached placement sheet must omit raw dashed expected strokes: {dashed_red}"

    solid_red = [d for d in drawing_strokes if not d.get("dashes") or "[]" in d["dashes"]]
    assert solid_red, "Expected solid red student stroke for ISSUE-OBJ-001-POS"
    max_red_span_x = max(d["rect"].width for d in solid_red)
    assert max_red_span_x >= 70.0, f"Expected zoomed local student geometry width >= 70pt, got {max_red_span_x}"


def test_short_missing_strokes_render_on_top_with_tighter_dash_and_separated_anchors():
    """Short missing chamfers must draw after inaccurate overlays with shorter dashes and distinct dots."""
    import math
    import pymupdf
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import ReviewedDrawingFlowable, _ROLE_STYLE

    ref_entities = [
        Entity(id="R-WALL", kind="line", layer="0", points=[(0.0, 0.0), (100.0, 0.0)]),
        Entity(id="R-CHAMF", kind="line", layer="0", points=[(48.0, 0.0), (50.0, 2.0)]),
        Entity(id="R-SQ-0", kind="line", layer="0", points=[(10.0, 10.0), (40.0, 10.0)]),
        Entity(id="R-SQ-1", kind="line", layer="0", points=[(40.0, 10.0), (40.0, 40.0)]),
        Entity(id="R-SQ-2", kind="line", layer="0", points=[(40.0, 40.0), (10.0, 40.0)]),
    ]
    stu_entities = [
        Entity(id="S-WALL", kind="line", layer="0", points=[(0.0, 0.2), (100.0, 0.2)]),
        Entity(id="S-SQ-0", kind="line", layer="0", points=[(10.5, 10.0), (40.5, 10.0)]),
        Entity(id="S-SQ-1", kind="line", layer="0", points=[(40.5, 10.0), (40.5, 40.0)]),
        Entity(id="S-SQ-2", kind="line", layer="0", points=[(40.5, 40.0), (10.5, 40.0)]),
    ]
    issues = [
        {
            "error_id": "ERR-CHAMF-MISS",
            "code": "MISSING_ENTITY",
            "category": "missing_geometry",
            "severity": "major",
            "reference_entity_id": "R-CHAMF",
            "measurement": {},
        },
        {
            "error_id": "ERR-WALL-INACC",
            "code": "INCORRECT_POSITION",
            "category": "incorrect_position",
            "severity": "minor",
            "reference_entity_id": "R-WALL",
            "student_entity_id": "S-WALL",
            "measurement": {},
        },
        {
            "error_id": "ERR-CO-1",
            "code": "INCORRECT_ANGLE",
            "category": "incorrect_angle",
            "severity": "minor",
            "reference_entity_id": "R-SQ-0",
            "student_entity_id": "S-SQ-0",
            "measurement": {},
        },
        {
            "error_id": "ERR-CO-2",
            "code": "INCORRECT_LENGTH",
            "category": "incorrect_length",
            "severity": "minor",
            "reference_entity_id": "R-SQ-0",
            "student_entity_id": "S-SQ-0",
            "measurement": {},
        },
        {
            "error_id": "ERR-CO-3",
            "code": "INCORRECT_POSITION",
            "category": "incorrect_position",
            "severity": "minor",
            "reference_entity_id": "R-SQ-0",
            "student_entity_id": "S-SQ-0",
            "measurement": {},
        },
    ]
    reviewed = build_reviewed_drawing(
        Drawing(ref_entities, (0.0, 0.0, 100.0, 50.0)),
        Drawing(stu_entities, (0.0, 0.0, 100.5, 50.0)),
        {"score": 85.0, "issues": issues, "assessment_objects": []},
    )

    w_pt, h_pt = 492.567, 240.0
    flowable = ReviewedDrawingFlowable(reviewed, width=w_pt, height=h_pt)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))
    flowable.canv = c
    flowable.draw()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    drawings = doc[0].get_drawings()

    inacc_rgb = colors.HexColor(_ROLE_STYLE["inaccurate-actual"][0]).rgb()
    miss_rgb = colors.HexColor(_ROLE_STYLE["missing"][0]).rgb()

    def _matches(c, target):
        return c and abs(c[0] - target[0]) < 0.04 and abs(c[1] - target[1]) < 0.04 and abs(c[2] - target[2]) < 0.04

    red_indices = [idx for idx, d in enumerate(drawings) if _matches(d.get("color"), inacc_rgb)]
    missing_strokes = [(idx, d) for idx, d in enumerate(drawings) if _matches(d.get("color"), miss_rgb)]
    assert red_indices and missing_strokes
    assert min(idx for idx, _ in missing_strokes) > max(red_indices), (
        "Missing strokes must render after inaccurate overlays so chamfers remain visible on top"
    )

    _idx, chamfer_drawing = missing_strokes[0]
    assert (chamfer_drawing.get("width") or 0) >= 2.3, f"Expected widened short chamfer stroke, got {chamfer_drawing}"
    dashes_str = chamfer_drawing.get("dashes") or ""
    assert dashes_str and "[6" not in dashes_str, f"Expected tightened dash pattern for short chamfer, got {dashes_str}"

    dot_centers = []
    for d in drawings:
        rect = d.get("rect")
        if d.get("type") == "f" and rect is not None and 1.8 <= rect.width <= 3.0 and 1.8 <= rect.height <= 3.0:
            dot_centers.append(((rect.x0 + rect.x1) * 0.5, (rect.y0 + rect.y1) * 0.5))
    assert len(dot_centers) == 5, f"Expected 5 badge anchor dots, got {len(dot_centers)}"
    for i in range(len(dot_centers)):
        for j in range(i + 1, len(dot_centers)):
            dist = math.hypot(dot_centers[i][0] - dot_centers[j][0], dot_centers[i][1] - dot_centers[j][1])
            assert dist >= 2.0, f"Coincident badge anchor dots at {dot_centers[i]} and {dot_centers[j]}"


def test_object_detail_spatial_clustering_groups_nearby_components():
    """Multi-sheet objects cluster nearby defects spatially so zoomed sheets stay readable."""
    from dataclasses import replace
    import pymupdf
    from reportlab.lib import colors
    from app.models import Drawing, Entity
    from app.reviewed_dxf import build_reviewed_drawing
    from app.pdf_report import _ROLE_STYLE, generate_pdf

    doc_bytes = _unitless_document_bytes()
    _approve(doc_bytes, filename="cluster-ref.dxf")
    base_review = _review(doc_bytes, doc_bytes).json()
    base_snapshot = REVIEW_SNAPSHOTS.get(base_review["review_id"])

    ref_entities = []
    issues = []
    for item_idx in range(12):
        for cluster_idx, base_x in enumerate((0.0, 400.0)):
            rid = f"R-I{item_idx:02d}-C{cluster_idx}"
            x = base_x + item_idx * 1.0
            ref_entities.append(Entity(id=rid, kind="line", layer="0", points=[(x, 0.0), (x + 1.0, 2.0)]))
            issues.append({
                "error_id": f"ERR-I{item_idx:02d}-C{cluster_idx}",
                "code": "MISSING_ENTITY",
                "category": "missing_geometry",
                "severity": "major",
                "reference_entity_id": rid,
                "parent_object_id": "OBJ-CLUSTER",
                "component_id": rid,
                "measurement": {},
            })

    reviewed = build_reviewed_drawing(
        Drawing(ref_entities, (0.0, 0.0, 412.0, 10.0)),
        Drawing([], (0.0, 0.0, 412.0, 10.0)),
        {
            "score": 50.0,
            "issues": issues,
            "assessment_objects": [{"object_id": "OBJ-CLUSTER", "component_count": 24, "bounds": [0.0, 0.0, 412.0, 10.0]}],
        },
    )
    reviewed = replace(
        reviewed,
        issues=tuple(replace(iss, parent_object_id="OBJ-CLUSTER", component_id=iss.issue_id) for iss in reviewed.issues),
    )
    resp_issues = [
        {
            "issue_id": iss.issue_id,
            "code": "MISSING_ENTITY",
            "category": iss.category,
            "badge_label": iss.badge_label,
            "visual_role": iss.visual_role,
            "severity": "major",
            "classification": "primary",
            "provenance": "comparison",
            "deduction": 1.0,
            "applied_deduction": 1.0,
            "deduction_status": "applied",
            "reference_entity_id": iss.expected_entity_id,
            "student_entity_id": iss.source_entity_id,
            "description": f"Synthetic {iss.issue_id}",
            "confidence": "verified",
        }
        for iss in reviewed.issues
    ]
    proxy = _snapshot_proxy(
        base_snapshot,
        reviewed=reviewed,
        response_patch={
            "score": 50.0,
            "rubric_version": "2.1",
            "assessment_objects": [{"object_id": "OBJ-CLUSTER", "component_count": 24, "bounds": [0.0, 0.0, 412.0, 10.0]}],
            "object_translations": {},
            "issues": resp_issues,
            "score_breakdown": {"final_score": 50.0, "deduction_items": []},
        },
    )
    pdf_bytes = generate_pdf(proxy)
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    part_a = next((p for p in doc if "Sheet D-1a - Object Detail (OBJ-CLUSTER — Part 1 of 2)" in (p.get_text() or "")), None)
    part_b = next((p for p in doc if "Sheet D-1b - Object Detail (OBJ-CLUSTER — Part 2 of 2)" in (p.get_text() or "")), None)
    assert part_a is not None and part_b is not None
    assert "12 missing, 0 inaccurate on this sheet" in (part_a.get_text() or "")
    assert "12 missing, 0 inaccurate on this sheet" in (part_b.get_text() or "")
    assert "-C1" not in (part_a.get_text() or "")
    assert "-C0" not in (part_b.get_text() or "")

    # Verify Sheet D-1a zoomed tightly onto the 12-unit cluster rather than full 412-unit object width
    miss_rgb = colors.HexColor(_ROLE_STYLE["missing"][0]).rgb()
    drawing_miss = [
        d for d in part_a.get_drawings()
        if d.get("color")
        and abs(d["color"][0] - miss_rgb[0]) < 0.04
        and abs(d["color"][1] - miss_rgb[1]) < 0.04
        and abs(d["color"][2] - miss_rgb[2]) < 0.04
        and d["rect"].y0 < 400.0
    ]
    assert drawing_miss
    cluster_xs = [x for d in drawing_miss for x in (d["rect"].x0, d["rect"].x1)]
    assert (max(cluster_xs) - min(cluster_xs)) >= 180.0, (
        f"Expected tight spatial zoom on Sheet D-1a cluster, got width {max(cluster_xs) - min(cluster_xs)}"
    )


def test_compact_dense_overview_uses_4side_perimeter_with_zero_crossings_or_pill_hits():
    """Verify compact ~1:1 dense overview layouts route badges onto 4 perimeter sides with 0 crossings and 0 pill hits."""
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    import pymupdf
    from app.models import Drawing, Entity
    from app.pdf_report import ReviewedDrawingFlowable, _segments_cross
    from app.reviewed_dxf import build_reviewed_drawing

    # 1:1 compact geometry (200x200) inside a 17.4cm x 240pt overview canvas leaves generous left/right margins.
    ref_entities = []
    stu_entities = []
    issues = []
    for i in range(60):
        # Distribute 60 features across 4 clusters (top, bottom, left, right) inside [0..200] x [0..200]
        if i < 16:
            k = i
            x1 = 22.0 + (k % 8) * 18.0
            y1 = 155.0 + (k // 8) * 14.0
        elif i < 32:
            k = i - 16
            x1 = 22.0 + (k % 8) * 18.0
            y1 = 20.0 + (k // 8) * 14.0
        elif i < 46:
            k = i - 32
            x1 = 18.0 + (k % 2) * 20.0
            y1 = 52.0 + (k // 2) * 13.0
        else:
            k = i - 46
            x1 = 148.0 + (k % 2) * 20.0
            y1 = 52.0 + (k // 2) * 13.0
        x2 = x1 + 12.0
        y2 = y1 + 6.0
        ref_entities.append(Entity(id=f"R-C-{i}", kind="line", layer="0", points=[(x1, y1), (x2, y2)]))
        stu_entities.append(
            Entity(id=f"S-C-{i}", kind="line", layer="0", points=[(x1 + 1.5, y1 + 1.5), (x2 + 1.5, y2 + 1.5)])
        )
        issues.append({
            "error_id": f"ISSUE-C-{i}",
            "code": "INCORRECT_POSITION",
            "category": "incorrect_position",
            "severity": "major",
            "reference_entity_id": f"R-C-{i}",
            "student_entity_id": f"S-C-{i}",
            "measurement": {},
        })

    ref = Drawing(ref_entities, (0.0, 0.0, 200.0, 200.0))
    stu = Drawing(stu_entities, (0.0, 0.0, 200.0, 200.0))
    comp = {"score": 40.0, "issues": issues, "assessment_objects": []}
    reviewed = build_reviewed_drawing(ref, stu, comp)

    w_pt, h_pt = 17.4 * cm, 240.0
    flowable = ReviewedDrawingFlowable(reviewed, width=w_pt, height=h_pt, role_filter="inaccurate")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))
    flowable.canv = c
    flowable.draw()
    c.save()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    page = doc[0]
    leaders = []
    pills = []
    notices = []
    for path in page.get_drawings():
        pw = path.get("width") or 0.0
        items = path.get("items", [])
        rect = path.get("rect")
        if abs(pw - 0.65) < 1e-4 and path.get("type") == "s" and len(items) == 1 and items[0][0] == "l":
            a, b = items[0][1:]
            leaders.append(((a.x, a.y), (b.x, b.y)))
        elif abs(pw - 0.7) < 1e-4 and rect is not None and 9.0 <= rect.height <= 14.0:
            if rect.width > 120.0:
                notices.append(rect)
            else:
                pills.append(rect)

    assert len(leaders) >= 48, f"Expected >= 48 perimeter leaders on 4 sides, got {len(leaders)}"
    assert len(pills) >= len(leaders)

    # Confirm badges span horizontal rows and vertical side rails (4-side layout active)
    top_pills = [r for r in pills if r.y0 < 40.0]
    bot_pills = [r for r in pills if r.y1 > h_pt - 40.0]
    left_pills = [r for r in pills if 40.0 <= r.y0 and r.y1 <= h_pt - 40.0 and r.x1 < w_pt * 0.4]
    right_pills = [r for r in pills if 40.0 <= r.y0 and r.y1 <= h_pt - 40.0 and r.x0 > w_pt * 0.6]
    assert top_pills and bot_pills and left_pills and right_pills, (
        f"Expected 4-side badge distribution, got top={len(top_pills)} bot={len(bot_pills)} "
        f"left={len(left_pills)} right={len(right_pills)}"
    )

    crossings = [
        (i, j)
        for i in range(len(leaders))
        for j in range(i + 1, len(leaders))
        if _segments_cross(leaders[i][0], leaders[i][1], leaders[j][0], leaders[j][1])
    ]
    assert crossings == [], f"Found {len(crossings)} crossing leaders in 4-side overview: {crossings[:5]}"

    pill_hits = []
    for li, (p1, p2) in enumerate(leaders):
        for pi, pr in enumerate(pills):
            x0, y0, x1, y1 = pr.x0 + 0.5, pr.y0 + 0.5, pr.x1 - 0.5, pr.y1 - 0.5
            edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
            if any(_segments_cross(p1, p2, e1, e2) for e1, e2 in edges):
                pill_hits.append((li, pi))
    assert pill_hits == [], f"Found {len(pill_hits)} leader-to-pill intersections: {pill_hits[:5]}"

    for nrect in notices:
        for pr in pills:
            inter = nrect & pr
            assert not (inter.width > 0.2 and inter.height > 0.2), f"Pill overlaps notice strip: {pr} vs {nrect}"
