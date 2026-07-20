from datetime import datetime, timedelta, timezone

import pytest

from app.review_snapshot import (
    ReviewSnapshotStore,
    SnapshotCapacityError,
    SnapshotExpired,
    SnapshotNotFound,
    StudentMetadataError,
    normalize_student_metadata,
)
from app.reviewed_dxf import ReviewedDrawing


def reviewed(score=100):
    return ReviewedDrawing((), (), (), (), (), (0.0, 0.0, 0.0, 0.0), "mm", score)


def response(score=100):
    return {
        "score": score,
        "rubric": {"title": "Test rubric", "approved": True},
        "assignment_type": "Technical Drawing",
        "suggested_assignment_type": "Technical Drawing",
        "detected_features": ["mixed geometric primitives"],
        "issues": [],
        "finding_counts": {"primary_student_issues": 0, "supporting_findings": 0, "reference_validation_notes": 0, "unsupported_entities": 0},
        "score_breakdown": {"category_subtotals": [], "total_applied_deduction": 0, "final_score": score},
        "normalization_decision": {"requested_mode": "strict", "transform_applied": False},
        "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>",
    }


def create(store, token="R1", *, reference=b"ref", student=b"student", payload=None, metadata=None):
    return store.create(
        reference_filename="reference.dxf",
        reference_bytes=reference,
        student_filename="student.dxf",
        student_bytes=student,
        student_metadata=metadata or normalize_student_metadata(),
        approved_rubric_id="rubric-1",
        approved_rubric={"title": "Test rubric", "approved": True},
        assignment_type="Technical Drawing",
        suggested_assignment_type="Technical Drawing",
        detected_features=["mixed geometric primitives"],
        reviewed_drawing=reviewed(),
        review_response=payload or response(),
    )


def test_metadata_is_nfc_normalized_trimmed_and_optional():
    metadata = normalize_student_metadata("  Zoe\u0308  ", " ID-7 ", " CAD 101 ")
    assert metadata.student_name == "Zo\u00eb"
    assert metadata.student_id == "ID-7"
    assert metadata.course_section == "CAD 101"
    assert normalize_student_metadata(" ", None, "").to_dict() == {"student_name": None, "student_id": None, "course_section": None}


@pytest.mark.parametrize("value", ["bad\nvalue", "bad\rvalue", "bad\x00value", "bad\tvalue", "bad\u2028value"])
def test_metadata_rejects_control_and_header_breaking_characters(value):
    with pytest.raises(StudentMetadataError):
        normalize_student_metadata(value, None, None)


@pytest.mark.parametrize("field,maximum", [("student_name",120),("student_id",64),("course_section",120)])
def test_metadata_length_limits(field, maximum):
    values = {"student_name": None, "student_id": None, "course_section": None}
    values[field] = "x" * maximum
    assert getattr(normalize_student_metadata(**values), field) == values[field]
    values[field] += "x"
    with pytest.raises(StudentMetadataError):
        normalize_student_metadata(**values)


def test_snapshot_is_authoritative_immutable_and_hashes_raw_uploads():
    source = response(95)
    rubric = {"title": "Approved", "approved": True}
    store = ReviewSnapshotStore(token_factory=lambda: "fixed-review")
    snapshot = store.create(
        reference_filename="reference.dxf", reference_bytes=b"reference", student_filename="student.dxf", student_bytes=b"student",
        student_metadata=normalize_student_metadata("Zo?"), approved_rubric_id="rubric-1", approved_rubric=rubric,
        assignment_type="Technical Drawing", suggested_assignment_type="Technical Drawing", detected_features=["feature"],
        reviewed_drawing=reviewed(95), review_response=source,
    )
    source["score"] = 0; rubric["title"] = "Changed"
    assert snapshot.review_id == "fixed-review"
    assert snapshot.review_response["score"] == 95
    assert snapshot.approved_rubric["title"] == "Approved"
    assert snapshot.review_response["review_id"] == snapshot.review_id
    assert snapshot.review_response["report_available"] is True
    assert snapshot.raw_reference_bytes == b"reference"
    assert len(snapshot.reference_sha256) == len(snapshot.student_sha256) == 64


def test_expired_and_unknown_review_ids_are_distinct():
    now = [datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)]
    store = ReviewSnapshotStore(ttl_seconds=10, clock=lambda: now[0], token_factory=lambda: "expiring")
    create(store)
    with pytest.raises(SnapshotNotFound): store.get("unknown")
    now[0] += timedelta(seconds=11)
    with pytest.raises(SnapshotExpired): store.get("expiring")


def test_lru_eviction_respects_recent_access_and_count_limit():
    tokens = iter(("one", "two", "three"))
    store = ReviewSnapshotStore(max_snapshots=2, token_factory=lambda: next(tokens))
    create(store); create(store)
    store.get("one")
    create(store)
    assert store.get("one").review_id == "one"
    assert store.get("three").review_id == "three"
    with pytest.raises(SnapshotNotFound): store.get("two")


def test_memory_limit_evicts_oldest_and_rejects_single_oversized_pair():
    tokens = iter(("one", "two", "too-large"))
    store = ReviewSnapshotStore(max_raw_bytes=10, token_factory=lambda: next(tokens))
    create(store, reference=b"123", student=b"456")
    create(store, reference=b"abcd", student=b"efgh")
    assert store.total_raw_bytes == 8
    with pytest.raises(SnapshotNotFound): store.get("one")
    with pytest.raises(SnapshotCapacityError): create(store, reference=b"123456", student=b"12345")
