from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator

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
    approved: bool = False
    categories: list[RubricCategory]
    tolerances: ToleranceProfile = Field(default_factory=ToleranceProfile)
    normalization_mode: Literal["strict", "translation", "translation_rotation", "instructor_defined"] = "translation"
    completion_scoring_mode: Literal["rule_based", "proportional"] = "rule_based"
    accepted_alternatives: list[str] = Field(default_factory=list)

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
        RubricRule(id="RULE-MISSING-01", check="missing_geometry", deduction=5, repeat_cap=25, commands=["LINE", "PLINE", "CIRCLE"]),
        RubricRule(id="RULE-EXTRA-01", check="extra_geometry", deduction=2, repeat_cap=10, severity="moderate", commands=["ERASE", "OVERKILL"]),
        RubricRule(id="RULE-POSITION-01", check="incorrect_position", deduction=3, repeat_cap=15, commands=["MOVE", "OSNAP"]),
        RubricRule(id="RULE-LENGTH-01", check="incorrect_length", deduction=3, repeat_cap=15, commands=["LENGTHEN", "STRETCH"]),
        RubricRule(id="RULE-ANGLE-01", check="incorrect_angle", deduction=3, repeat_cap=15, commands=["ROTATE", "POLAR"]),
        RubricRule(id="RULE-RADIUS-01", check="incorrect_radius", deduction=3, repeat_cap=15, commands=["CIRCLE", "STRETCH"]),
        RubricRule(id="RULE-SHAPE-01", check="incorrect_shape", deduction=4, repeat_cap=15, commands=["PEDIT", "JOIN"]),
    ]
    quality = [
        RubricRule(id="RULE-DUPLICATE-01", check="duplicate_geometry", deduction=1, repeat_cap=5, severity="minor", commands=["OVERKILL"]),
        RubricRule(id="RULE-OPEN-01", check="open_polyline", deduction=2, repeat_cap=5, severity="moderate", commands=["PEDIT", "CLOSE"]),
        RubricRule(id="RULE-UNSUPPORTED-01", check="unsupported_entity", deduction=0, severity="warning"),
    ]
    return Rubric(title=title, categories=[
        RubricCategory(id="geometry", name="Geometric accuracy", weight=65, max_deduction=65, rules=geometry),
        RubricCategory(id="completion", name="Completion", weight=25, max_deduction=25),
        RubricCategory(id="quality", name="File quality", weight=10, max_deduction=10, rules=quality),
    ])

def rubric_rule_map(rubric: Rubric):
    return {rule.check: (rule, category) for category in rubric.categories for rule in category.rules if rule.enabled}
