"""Synthetic fixture for browser QA of Gaps & Connections presentation."""
from dataclasses import replace
import json
import base64
import io

from app.svg_renderer import render_svg
from tests.legend_synthetic import browser_fixture, dense_uploads
from tests.test_review_usability_repairs import basic_snapshot


def connectivity_browser_fixture():
    snapshot = basic_snapshot()
    drawing = snapshot.reviewed_drawing
    template = drawing.reference_entities[0]
    references = tuple(
        replace(
            template,
            entity_id=f"R-QA-{i}",
            source="reference",
            kind="line",
            layer=["reference", "student", "issues"][i % 3],
            points=((i % 16 * 20.0, i // 16 * 20.0), (i % 16 * 20.0 + 16, i // 16 * 20.0 + 10)),
            bbox=None,
        )
        for i in range(160)
    )
    students = tuple(
        replace(
            e,
            entity_id=e.entity_id.replace("R-", "S-"),
            source="student",
            points=tuple((x, y + 3) for x, y in e.points),
        )
        for e in references
    )

    review = browser_fixture()
    visuals = []
    roles = ["missing", "extra", "inaccurate", "connectivity", "warning", "critical"]
    for index, role in enumerate(roles):
        identity = f"QA-{role}"
        meas = None
        if role == "connectivity":
            meas = {
                "actual_points": [(index * 35.0, 40.0), (index * 35.0 + 2.0, 40.0)],
                "expected_point": (index * 35.0, 40.0),
                "distance": 2.0,
                "tolerance": 0.5,
                "unit": "mm",
            }
        visuals.append(
            replace(
                drawing.issues[0],
                issue_id=identity,
                visual_role=role,
                expected_geometry=references[index],
                actual_geometry=students[index],
                region=(index * 35.0, 40.0, index * 35.0 + 22, 65.0),
                measurement_json=json.dumps(meas) if meas else None,
            )
        )

    visuals.append(
        replace(
            visuals[-1],
            issue_id="QA-no-geometry",
            visual_role="warning",
            region=None,
            expected_geometry=None,
            actual_geometry=None,
            measurement_json=None,
        )
    )

    for issue in review["issues"]:
        if issue["issue_id"] == "QA-connectivity":
            issue["category"] = "endpoint_gap"
            issue["technical_feedback"] = (
                "Endpoint gap of 2.000 mm exceeds tolerance (0.500 mm). "
                "Connect endpoints at this junction as required by the reference."
            )
            issue["applied_deduction"] = 0.0
            issue["raw_deduction"] = 0.0
            issue["deduction_status"] = "informational"
            issue["classification"] = "supporting_evidence"
            issue["finding_role"] = "supporting"
            issue["measurement"] = {
                "actual_points": [[3 * 35.0, 40.0], [3 * 35.0 + 2.0, 40.0]],
                "expected_point": [3 * 35.0, 40.0],
                "distance": 2.0,
                "tolerance": 0.5,
                "unit": "mm",
            }

    review["svg"] = render_svg(
        replace(
            drawing,
            reference_entities=references,
            student_entities=students,
            issues=tuple(visuals),
            extents=(0.0, 0.0, 330.0, 210.0),
        )
    )
    return review


if __name__ == "__main__":
    print(json.dumps({"review": connectivity_browser_fixture(), "uploads": dense_uploads()}))
