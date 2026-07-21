from __future__ import annotations
from pathlib import PurePath
import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator

AssignmentType = Literal[
    "Geometric Construction Exercise",
    "Mixed Geometric Composition",
    "Geometric Pattern",
    "Complex Geometric Pattern",
    "Interior Plan",
    "Architectural Drawing",
    "Technical Drawing",
    "Other",
]

BASELINE_RUBRIC_TEMPLATE = "DraftLens Baseline Rubric"
SCORE_CATEGORY_BY_CHECK: dict[str, str] = {
    "incorrect_position": "geometry",
    "incorrect_length": "geometry",
    "incorrect_angle": "geometry",
    "incorrect_radius": "geometry",
    "incorrect_shape": "geometry",
    "endpoint_gap": "geometry",
    "disconnected_geometry": "geometry",
    "global_drawing_displacement": "geometry",
    "unwanted_intersection": "geometry",
    "overlapping_geometry": "geometry",
    "missing_geometry": "completion",
    "open_polyline": "completion",
    "extra_geometry": "quality",
    "duplicate_geometry": "quality",
    "unsupported_entity": "quality",
    "degenerate_geometry": "quality",
    "invalid_geometry": "quality",
    "wrong_units": "quality",
    "wrong_layer": "quality",
}
CATEGORY_DEFINITIONS: dict[str, str] = {
    "geometry": "Correctness of matched geometry, dimensions, placement, shape, and topology.",
    "completion": "Coverage of required reference entities and explicitly incomplete expected geometry.",
    "quality": "Student-file technical hygiene, including extra, duplicate, unsupported, or invalid geometry.",
}

class ToleranceProfile(BaseModel):
    position: float = Field(2.0, ge=0)
    length: float = Field(1.0, ge=0)
    angle: float = Field(3.0, ge=0)
    radius: float = Field(1.0, ge=0)
    dimension: float = Field(1.0, ge=0)
    vertex: float = Field(1.0, ge=0)

class RubricRule(BaseModel):
    id: str
    check: str
    severity: Literal["critical", "major", "moderate", "minor", "warning"] = "major"
    deduction: float = Field(3.0, ge=0)
    repeat_cap: float | None = Field(None, ge=0)
    enabled: bool = True
    commands: list[str] = Field(default_factory=list)

class RubricCategory(BaseModel):
    id: str
    name: str
    weight: float = Field(ge=0, le=100)
    max_deduction: float | None = Field(None, ge=0)
    rules: list[RubricRule] = Field(default_factory=list)

class Rubric(BaseModel):
    title: str = "DraftLens assignment rubric"
    assignment_title: str = "Assignment"
    approved: bool = False
    assignment_type: AssignmentType | None = None
    categories: list[RubricCategory]
    tolerances: ToleranceProfile = Field(default_factory=ToleranceProfile)
    normalization_mode: Literal["strict", "translation", "translation_rotation", "instructor_defined"] = "translation"
    completion_scoring_mode: Literal["rule_based", "proportional"] = "rule_based"
    accepted_alternatives: list[str] = Field(default_factory=list)
    rubric_source: Literal[
        "baseline_template", "instructor_modified", "explicit_fallback"
    ] = "baseline_template"
    rubric_template_name: str = BASELINE_RUBRIC_TEMPLATE
    rubric_modified_by_instructor: bool = False

    @model_validator(mode="after")
    def weights_total_100(self) -> "Rubric":
        if abs(sum(c.weight for c in self.categories) - 100.0) > 0.001:
            raise ValueError("Rubric category weights must total 100%.")
        category_ids = [category.id for category in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("Rubric category IDs must be unique.")
        if "completion" not in category_ids:
            raise ValueError("Rubric must include a completion category.")
        for category in self.categories:
            if category.max_deduction is not None and category.max_deduction > category.weight:
                raise ValueError(f"Category '{category.id}' maximum deduction cannot exceed its weight.")
        rule_ids = [rule.id for category in self.categories for rule in category.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Rubric rule IDs must be unique.")
        return self

def default_rubric(title: str = "Geometric accuracy rubric") -> Rubric:
    geometry = [
        RubricRule(id="RULE-POSITION-01", check="incorrect_position", deduction=3, repeat_cap=15, commands=["MOVE", "OSNAP"]),
        RubricRule(id="RULE-LENGTH-01", check="incorrect_length", deduction=3, repeat_cap=15, commands=["LENGTHEN", "STRETCH"]),
        RubricRule(id="RULE-ANGLE-01", check="incorrect_angle", deduction=3, repeat_cap=15, commands=["ROTATE", "POLAR"]),
        RubricRule(id="RULE-RADIUS-01", check="incorrect_radius", deduction=3, repeat_cap=15, commands=["CIRCLE", "STRETCH"]),
        RubricRule(id="RULE-SHAPE-01", check="incorrect_shape", deduction=4, repeat_cap=15, commands=["PEDIT", "JOIN"]),
        RubricRule(id="RULE-GLOBAL-DISPLACEMENT-01", check="global_drawing_displacement", deduction=50, repeat_cap=50, commands=["MOVE"]),
    ]
    completion = [
        RubricRule(id="RULE-MISSING-01", check="missing_geometry", deduction=5, repeat_cap=25, commands=["LINE", "PLINE", "CIRCLE"]),
    ]
    quality = [
        RubricRule(id="RULE-EXTRA-01", check="extra_geometry", deduction=2, repeat_cap=10, severity="moderate", commands=["ERASE", "OVERKILL"]),
        RubricRule(id="RULE-DUPLICATE-01", check="duplicate_geometry", deduction=1, repeat_cap=5, severity="minor", commands=["OVERKILL"]),
        RubricRule(id="RULE-OPEN-01", check="open_polyline", deduction=2, repeat_cap=5, severity="moderate", commands=["PEDIT", "CLOSE"]),
        RubricRule(id="RULE-UNSUPPORTED-01", check="unsupported_entity", deduction=0, severity="warning"),
    ]
    return Rubric(title=title, categories=[
        RubricCategory(id="geometry", name="Geometric accuracy", weight=65, max_deduction=65, rules=geometry),
        RubricCategory(id="completion", name="Completion", weight=25, max_deduction=25, rules=completion),
        RubricCategory(id="quality", name="File quality", weight=10, max_deduction=10, rules=quality),
    ])

def rubric_rule_map(rubric: Rubric):
    categories = {category.id: category for category in rubric.categories}
    mapping = {}
    for declared_category in rubric.categories:
        for rule in declared_category.rules:
            if not rule.enabled:
                continue
            score_category = categories.get(
                SCORE_CATEGORY_BY_CHECK.get(rule.check, declared_category.id),
                declared_category,
            )
            mapping[rule.check] = (rule, score_category)
    return mapping


def rubric_contract(rubric: Rubric) -> dict[str, object]:
    return {
        "assignment_title": rubric.assignment_title,
        "rubric_source": rubric.rubric_source,
        "rubric_template_name": rubric.rubric_template_name,
        "rubric_modified_by_instructor": rubric.rubric_modified_by_instructor,
        "category_definitions": dict(CATEGORY_DEFINITIONS),
    }


def suggest_assignment_title(filename: str | None) -> str:
    """Return a neutral instructor-editable title from a reference filename."""

    basename = PurePath(str(filename or "Assignment").replace("\\", "/")).name
    stem = PurePath(basename).stem
    cleaned = re.sub(r"[_\-]+", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^(?:\d+\s+)?reference\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+supported\s+geometry$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else "Assignment"
