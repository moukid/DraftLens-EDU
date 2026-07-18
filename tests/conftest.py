import pytest
from app.main import REFERENCE_RUBRICS, RUBRIC_REFERENCES, RUBRICS

@pytest.fixture(autouse=True)
def clear_in_memory_rubrics():
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
    yield
    RUBRICS.clear()
    REFERENCE_RUBRICS.clear()
    RUBRIC_REFERENCES.clear()
