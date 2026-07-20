from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"
ARCS = FIXTURES / "simple_audit-II"
AUDIT = FIXTURES / "simple_audit"


def suggest(reference_path: Path) -> dict:
    with reference_path.open("rb") as reference:
        response = client.post(
            "/api/rubric/suggest",
            files={"reference": (reference_path.name, reference, "application/dxf")},
        )
    assert response.status_code == 200
    return response.json()


def approve(reference_path: Path, mode: str) -> dict:
    suggestion = suggest(reference_path)
    suggestion["rubric"]["normalization_mode"] = mode
    suggestion["rubric"]["assignment_type"] = suggestion["suggested_assignment_type"]
    response = client.post(
        "/api/rubric/approve",
        json={
            "reference_id": suggestion["reference_id"],
            "rubric": suggestion["rubric"],
        },
    )
    assert response.status_code == 200
    return response.json()


def review(reference_path: Path, student_path: Path) -> dict:
    with reference_path.open("rb") as reference, student_path.open("rb") as student:
        response = client.post(
            "/api/review",
            files={
                "reference": (reference_path.name, reference, "application/dxf"),
                "student": (student_path.name, student, "application/dxf"),
            },
        )
    assert response.status_code == 200
    return response.json()


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def test_suggested_rubric_defaults_to_strict_and_requires_approval():
    body = suggest(ARCS / "01-ARC-Reference.dxf")

    assert body["normalization_mode"] == "strict"
    assert body["rubric"]["normalization_mode"] == "strict"
    assert body["rubric"]["approved"] is False
    assert body["requires_instructor_approval"] is True


def test_translation_mode_is_selectable_and_approval_returns_selected_mode():
    approval = approve(ARCS / "01-ARC-Reference.dxf", "translation")

    assert approval["normalization_mode"] == "translation"
    assert approval["rubric"]["normalization_mode"] == "translation"
    assert approval["rubric"]["approved"] is True


def test_strict_exact_arc_exposes_no_permitted_transform_or_estimation_rejection():
    reference = ARCS / "01-ARC-Reference.dxf"
    approve(reference, "strict")
    body = review(reference, ARCS / "01-ARC-Student-OK.dxf")
    decision = body["normalization_decision"]

    assert body["score"] == 100
    assert body["issues"] == []
    assert body["normalization_mode"] == "strict"
    assert decision == {
        "requested_mode": "strict",
        "applied_mode": "strict",
        "transform_applied": False,
        "selected_translation": [0.0, 0.0],
        "candidate_translation": None,
        "support_count": 0,
        "evidence_count": 0,
        "support_ratio": 0.0,
        "confidence": "not_applicable",
        "error_before": None,
        "error_after": None,
        "total_error_reduction": None,
        "error_reduction_ratio": None,
        "rejection_reason": None,
    }


def test_all_moved_arcs_expose_accepted_translation_evidence():
    reference = ARCS / "01-ARC-Reference.dxf"
    approve(reference, "translation")
    body = review(reference, ARCS / "01-ARC-All-Moved.dxf")
    decision = body["normalization_decision"]

    assert body["score"] == 100
    assert body["issues"] == []
    assert body["normalization_mode"] == "translation"
    assert decision["requested_mode"] == decision["applied_mode"] == "translation"
    assert decision["transform_applied"] is True
    assert decision["selected_translation"] == pytest.approx([-34.555427, 0])
    assert decision["candidate_translation"] == pytest.approx([-34.555427, 0])
    assert decision["support_count"] == decision["evidence_count"] == 3
    assert decision["support_ratio"] == 1
    assert decision["confidence"] == "high"
    assert decision["total_error_reduction"] == pytest.approx(103.666279)
    assert decision["error_reduction_ratio"] == 1
    assert decision["rejection_reason"] is None


@pytest.mark.parametrize(
    ("mode", "expected_score"),
    (("translation", 100), ("strict", 91)),
)
def test_all_moved_arc_scores_are_controlled_by_approved_mode(mode, expected_score):
    reference = ARCS / "01-ARC-Reference.dxf"
    approve(reference, mode)
    body = review(reference, ARCS / "01-ARC-All-Moved.dxf")

    assert body["score"] == expected_score
    assert len([item for item in body["issues"] if item["category"] == "incorrect_position"]) == (0 if mode == "translation" else 3)
    assert body["normalization_decision"]["transform_applied"] is (mode == "translation")


@pytest.mark.parametrize("mode", ("translation", "strict"))
def test_two_moved_arcs_remain_two_local_position_errors(mode):
    reference = ARCS / "01-ARC-Reference.dxf"
    approve(reference, mode)
    body = review(reference, ARCS / "01-ARC-TwoOnly-Moved.dxf")
    positions = [item for item in body["issues"] if item["category"] == "incorrect_position"]

    assert body["score"] == 94
    assert len(positions) == 2
    assert all(item["recommended_commands"] == ["MOVE", "OSNAP"] for item in positions)
    assert body["normalization_decision"]["transform_applied"] is False
    if mode == "translation":
        decision = body["normalization_decision"]
        assert decision["candidate_translation"] == pytest.approx([-31.349252, 0.356078])
        assert decision["support_count"] == 2
        assert decision["evidence_count"] == 3
        assert decision["rejection_reason"] == "insufficient_support"
    else:
        assert body["normalization_decision"]["rejection_reason"] is None


def test_locally_moved_circle_does_not_shift_the_drawing():
    reference = AUDIT / "00_reference_000-Simple.dxf"
    approve(reference, "translation")
    body = review(reference, AUDIT / "06_moved_circle_722_plus20X.dxf")
    decision = body["normalization_decision"]

    assert body["score"] == 97
    assert [item["category"] for item in body["issues"]] == ["incorrect_position"]
    assert decision["transform_applied"] is False
    assert decision["selected_translation"] == [0.0, 0.0]
    assert decision["support_count"] == 18
    assert decision["evidence_count"] == 19
    assert decision["rejection_reason"] == "consensus_translation_within_position_tolerance"


@pytest.mark.parametrize(
    ("reference_name", "student_name"),
    (
        ("02-SQUARE-Reference.dxf", "02-SQUARE-Student-OK.dxf"),
        ("03-T-Junction-Reference.dxf", "03-T-Junction-Student-OK.dxf"),
    ),
)
def test_exact_square_and_t_junction_remain_clean_in_strict_mode(
    reference_name, student_name
):
    reference = ARCS / reference_name
    approve(reference, "strict")
    body = review(reference, ARCS / student_name)

    assert body["score"] == 100
    assert body["issues"] == []
    assert body["normalization_mode"] == "strict"
    assert body["normalization_decision"]["transform_applied"] is False


def test_transform_evidence_is_deterministic_and_contains_no_machine_paths():
    reference = ARCS / "01-ARC-Reference.dxf"
    approve(reference, "translation")
    first = review(reference, ARCS / "01-ARC-TwoOnly-Moved.dxf")
    repeated = review(reference, ARCS / "01-ARC-TwoOnly-Moved.dxf")

    assert first["normalization_decision"] == repeated["normalization_decision"]
    for value in strings(first["normalization_decision"]):
        assert ":\\" not in value
        assert "Traceback" not in value
        assert "__file__" not in value
