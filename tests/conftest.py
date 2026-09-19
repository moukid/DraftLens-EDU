import pytest
from app.main import (
    REFERENCE_OBJECT_INSPECTIONS,
    REFERENCE_OBJECTS,
    REFERENCE_RUBRICS,
    REVIEW_SNAPSHOTS,
    RUBRIC_REFERENCES,
    RUBRICS,
)

@pytest.fixture(autouse=True)
def clear_in_memory_rubrics():
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
    REFERENCE_OBJECTS.clear()
    REFERENCE_OBJECT_INSPECTIONS.clear()
    REVIEW_SNAPSHOTS.clear()
    yield
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
    REFERENCE_OBJECTS.clear()
    REFERENCE_OBJECT_INSPECTIONS.clear()
    REVIEW_SNAPSHOTS.clear()
