import pytest
from pydantic import ValidationError
from app.rubric import Rubric, RubricCategory, default_rubric

def test_default_rubric_totals_100_and_is_provisional():
    rubric = default_rubric()
    assert sum(category.weight for category in rubric.categories) == 100
    assert rubric.approved is False
    assert rubric.tolerances.radius == 1.0

def test_rubric_rejects_weights_that_do_not_total_100():
    with pytest.raises(ValidationError, match="weights must total 100"):
        Rubric(categories=[
            RubricCategory(id="geometry", name="Geometry", weight=80),
            RubricCategory(id="completion", name="Completion", weight=10),
        ])
