import pytest
from app.main import REFERENCE_RUBRICS, REVIEW_SNAPSHOTS, RUBRIC_REFERENCES, RUBRICS

@pytest.fixture(autouse=True)
def clear_in_memory_rubrics():
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
    REVIEW_SNAPSHOTS.clear()
    yield
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
    REVIEW_SNAPSHOTS.clear()
