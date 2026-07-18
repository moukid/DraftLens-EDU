from __future__ import annotations
import json, os
from openai import OpenAI

SYSTEM = """You are a technical-drawing tutor. Explain only the supplied deterministic findings. Never measure, infer geometry, alter deductions, or claim access to a drawing. Return JSON with one key, feedback, containing an array of concise, specific remediation strings in the same order as the findings."""

def structured_findings(result: dict) -> list[dict]:
    allowed=("code","category","severity","message","deduction","expected","actual")
    return [{key: issue.get(key) for key in allowed} for issue in result.get("issues",[])]

def generate_feedback(result: dict) -> list[str] | None:
    if not os.getenv("OPENAI_API_KEY") or not result.get("issues"):
        return None
    payload={"findings":structured_findings(result)}
    response=OpenAI().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6"),instructions=SYSTEM,input=json.dumps(payload),max_output_tokens=1200)
    parsed=json.loads(response.output_text)
    feedback=parsed.get("feedback")
    if not isinstance(feedback,list) or not all(isinstance(x,str) for x in feedback):
        raise ValueError("Model returned an invalid feedback payload")
    return feedback
