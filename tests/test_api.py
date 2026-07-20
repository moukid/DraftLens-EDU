from pathlib import Path
import io
import xml.etree.ElementTree as ET
import ezdxf
import pytest
from fastapi.testclient import TestClient
from app.main import RUBRIC_REFERENCES, RUBRICS, app
from app.rubric import default_rubric
S=Path(__file__).parents[1]/"samples"; client=TestClient(app)
A=Path(__file__).parent/"fixtures"/"simple_audit"
AUDIT_II=Path(__file__).parent/"fixtures"/"simple_audit-II"
AUDIT_REFERENCE=A/"00_reference_000-Simple.dxf"
AUDIT_MISSING=A/"02_missing_line_73B.dxf"
def test_health(): assert client.get('/health').json()=={"status":"ok"}
def test_grade_flow():
 with open(S/'reference.dxf','rb') as a,open(S/'student_missing_wall.dxf','rb') as b:r=client.post('/api/grade',data={'allow_fallback':'true'},files={'reference':('reference.dxf',a,'application/dxf'),'student':('student.dxf',b,'application/dxf')})
 assert r.status_code==200 and r.json()['score']<100 and r.json()['reference']['entities']
def test_rejects_non_dxf():
 r=client.post('/api/grade',files={'reference':('x.txt',b'x','text/plain'),'student':('x.dxf',b'x','application/dxf')}); assert r.status_code==400


def test_reference_foundation_flow():
 with open(S/"reference.dxf","rb") as source:
  validation=client.post("/api/reference/validate",files={"reference":("reference.dxf",source,"application/dxf")})
 assert validation.status_code==200
 assert validation.json()["validation"]["can_continue"] is True
 with open(S/"reference.dxf","rb") as source:
  analysis=client.post("/api/assignment/analyze",files={"reference":("reference.dxf",source,"application/dxf")})
 assert analysis.status_code==200 and analysis.json()["entity_counts"]["LINE"]>=1

def test_rubric_suggestion_requires_approval_and_can_be_approved():
 with open(S/"reference.dxf","rb") as source:
  suggestion=client.post("/api/rubric/suggest",files={"reference":("reference.dxf",source,"application/dxf")})
 assert suggestion.status_code==200
 body=suggestion.json()
 assert body["provisional"] is True and body["rubric"]["approved"] is False
 assert body["completion_scoring_mode"]==body["rubric"]["completion_scoring_mode"]=="rule_based"
 approved=client.post("/api/rubric/approve",json={"reference_id":body["reference_id"],"rubric":body["rubric"]})
 assert approved.status_code==200
 assert approved.json()["rubric"]["approved"] is True
 assert approved.json()["completion_scoring_mode"]=="rule_based"

def test_reference_validation_rejects_invalid_dxf_cleanly():
 response=client.post("/api/reference/validate",files={"reference":("broken.dxf",b"not a dxf","application/dxf")})
 assert response.status_code==422
 assert "Invalid or unsupported DXF" in response.json()["detail"]

def _review_approve(reference_path=S/"reference.dxf",completion_mode=None):
 with open(reference_path,"rb") as source:
  suggestion=client.post("/api/rubric/suggest",files={"reference":("reference.dxf",source,"application/dxf")}).json()
 if completion_mode is not None:
  suggestion["rubric"]["completion_scoring_mode"]=completion_mode
 approval=client.post("/api/rubric/approve",json={"reference_id":suggestion["reference_id"],"rubric":suggestion["rubric"]})
 assert approval.status_code==200
 return suggestion,approval.json()

def _post_review(student_path=S/"student_missing_wall.dxf",reference_path=S/"reference.dxf",data=None):
 with open(reference_path,"rb") as reference,open(student_path,"rb") as student:
  return client.post("/api/review",data=data or {},files={
   "reference":("reference.dxf",reference,"application/dxf"),
   "student":("student.dxf",student,"application/dxf"),
  })

def _post_grade(student_path=S/"student_missing_wall.dxf",reference_path=S/"reference.dxf",data=None):
 with open(reference_path,"rb") as reference,open(student_path,"rb") as student:
  return client.post("/api/grade",data=data or {},files={
   "reference":("reference.dxf",reference,"application/dxf"),
   "student":("student.dxf",student,"application/dxf"),
  })

def _document_bytes(*,text=None,unsupported=False,units=ezdxf.units.MM):
 document=ezdxf.new("R2010")
 document.units=units
 modelspace=document.modelspace()
 modelspace.add_line((0,0),(10,0))
 if text is not None:
  modelspace.add_text(text).set_placement((1,2))
 if unsupported:
  modelspace.add_hatch()
 stream=io.StringIO()
 document.write(stream)
 return stream.getvalue().encode("utf-8")

def _all_strings(value):
 if isinstance(value,str):
  yield value
 elif isinstance(value,dict):
  for key,item in value.items():
   yield from _all_strings(key)
   yield from _all_strings(item)
 elif isinstance(value,list):
  for item in value:
   yield from _all_strings(item)

def test_review_uses_associated_approved_rubric_and_returns_stable_contract():
 _,approval=_review_approve()
 response=_post_review()
 assert response.status_code==200
 body=response.json()
 assert body["rubric_selection"]=={"rubric_id":approval["rubric_id"],"source":"associated_approved"}
 assert body["rubric"]["approved"] is True
 assert body["score"]<100
 assert body["units"]=="m"
 assert len(body["extents"])==4
 assert body["issues"] and body["technical_feedback"]
 assert body["svg"].startswith("<svg ")
 for finding in body["issues"]:
  assert {"issue_id","visual_role","css_classes","finding_role","technical_feedback","deduction","raw_deduction","applied_deduction","deduction_status","suppression_reason","rubric_rule_id","confidence","correction_guidance","recommended_commands"}<=finding.keys()

@pytest.mark.parametrize(
 ("reference_name", "student_name"),
 (
  ("02-SQUARE-Reference.dxf", "02-SQUARE-Student-OK.dxf"),
  ("03-T-Junction-Reference.dxf", "03-T-Junction-Student-OK.dxf"),
  ("04-T-Crossing-Reference.dxf", "04-T-Crossing-Student-OK.dxf"),
 ),
)
def test_exact_manual_acceptance_reviews_have_no_student_or_supporting_findings(reference_name,student_name):
 body=_post_review(
  reference_path=AUDIT_II/reference_name,
  student_path=AUDIT_II/student_name,
  data={"allow_fallback":"true"},
 ).json()
 assert body["score"]==100
 assert body["student_issue_count"]==0
 assert body["supporting_finding_count"]==0
 assert body["reference_note_count"]==0
 assert body["issues"]==[]


def test_displaced_square_separates_primary_and_supporting_findings():
 body=_post_review(
  reference_path=AUDIT_II/"02-SQUARE-Reference.dxf",
  student_path=AUDIT_II/"02-SQUARE-Gap-3Unit.dxf",
  data={"allow_fallback":"true"},
 ).json()
 assert body["score"]==97
 assert body["finding_counts"]=={
  "primary_student_issues":1,
  "supporting_findings":2,
  "reference_validation_notes":0,
  "unsupported_entities":0,
 }
 primary=[finding for finding in body["issues"] if finding["finding_role"]=="primary"]
 supporting=[finding for finding in body["issues"] if finding["finding_role"]=="supporting"]
 assert [finding["category"] for finding in primary]==["incorrect_position"]
 assert [finding["category"] for finding in supporting]==["endpoint_gap","endpoint_gap"]
 assert all(finding["applied_deduction"]==0 for finding in supporting)
 assert all(finding["recommended_commands"]==[] for finding in supporting)
 assert all(finding["correction_guidance"]["related_primary_issue_id"]==primary[0]["issue_id"] for finding in supporting)
 assert all("linked primary issue" in finding["correction_guidance"]["explanation"] for finding in supporting)


def test_reference_validation_notes_are_counted_separately():
 unitless=_document_bytes(units=0)
 response=client.post("/api/review",data={"allow_fallback":"true"},files={
  "reference":("reference.dxf",unitless,"application/dxf"),
  "student":("student.dxf",unitless,"application/dxf"),
 })
 assert response.status_code==200
 body=response.json()
 assert body["student_issue_count"]==0
 assert body["supporting_finding_count"]==0
 assert body["reference_note_count"]==1
 note=next(finding for finding in body["issues"] if finding["finding_role"]=="reference")
 assert note["category"]=="reference_warning"
 assert note["provenance"]=="reference_validation"
 assert "insertion units" in note["technical_feedback"]

def test_review_proportional_policy_suppresses_raw_missing_rule_and_reconciles_score():
 _,approval=_review_approve(reference_path=AUDIT_REFERENCE,completion_mode="proportional")
 body=_post_review(reference_path=AUDIT_REFERENCE,student_path=AUDIT_MISSING).json()
 assert approval["completion_scoring_mode"]=="proportional"
 assert body["completion_scoring_mode"]=="proportional"
 assert body["score"]==pytest.approx(98.7)
 missing=next(finding for finding in body["issues"] if finding["category"]=="missing_geometry")
 assert missing["raw_deduction"]==5
 assert missing["applied_deduction"]==missing["deduction"]==0
 assert missing["deduction_status"]=="suppressed"
 assert "proportional completion policy" in missing["suppression_reason"]
 assert missing["correction_guidance"] is None
 assert missing["recommended_commands"]==[]
 breakdown=body["score_breakdown"]
 completion=next(category for category in breakdown["category_subtotals"] if category["id"]=="completion")
 assert completion["deduction"]==pytest.approx(1.32,abs=0.01)
 assert breakdown["total_applied_deduction"]==pytest.approx(sum(category["deduction"] for category in breakdown["category_subtotals"]))
 assert breakdown["final_score"]==body["score"]

def test_review_default_suggested_rule_based_policy_applies_missing_rule_without_completion_deduction():
 _,approval=_review_approve(reference_path=AUDIT_REFERENCE)
 body=_post_review(reference_path=AUDIT_REFERENCE,student_path=AUDIT_MISSING).json()
 assert approval["completion_scoring_mode"]=="rule_based"
 assert body["completion_scoring_mode"]=="rule_based"
 assert body["score"]==95
 missing=next(finding for finding in body["issues"] if finding["category"]=="missing_geometry")
 assert missing["raw_deduction"]==missing["applied_deduction"]==missing["deduction"]==5
 assert missing["deduction_status"]=="applied"
 assert missing["suppression_reason"] is None
 assert missing["correction_guidance"]["primary_command"]=="LINE"
 assert missing["recommended_commands"]==["LINE","COPY"]
 breakdown=body["score_breakdown"]
 completion=next(category for category in breakdown["category_subtotals"] if category["id"]=="completion")
 assert completion["deduction"]==0
 assert breakdown["total_applied_deduction"]==5
 assert breakdown["final_score"]==body["score"]


def test_review_explicit_fallback_is_successful_but_not_implicit():
 rejected=_post_review()
 assert rejected.status_code==409
 assert "No approved rubric" in rejected.json()["detail"]
 accepted=_post_review(data={"allow_fallback":"true"})
 assert accepted.status_code==200
 assert accepted.json()["rubric_selection"]=={"rubric_id":None,"source":"explicit_fallback"}

def test_review_rejects_unapproved_and_mismatched_rubrics():
 suggestion,_=_review_approve()
 unapproved_id="review-unapproved"
 RUBRICS[unapproved_id]=default_rubric()
 RUBRIC_REFERENCES[unapproved_id]=suggestion["reference_id"]
 unapproved=_post_review(data={"rubric_id":unapproved_id})
 assert unapproved.status_code==409
 assert "not approved" in unapproved.json()["detail"]

 _,approval=_review_approve()
 mismatched=_post_review(reference_path=S/"student_good.dxf",data={"rubric_id":approval["rubric_id"]})
 assert mismatched.status_code==409
 assert "not associated" in mismatched.json()["detail"]

def test_review_rejects_malformed_reference_and_student_without_internal_details():
 malformed_reference=client.post("/api/review",data={"allow_fallback":"true"},files={
  "reference":("reference.dxf",b"not a dxf","application/dxf"),
  "student":("student.dxf",(S/"student_good.dxf").read_bytes(),"application/dxf"),
 })
 assert malformed_reference.status_code==422
 malformed_student=client.post("/api/review",data={"allow_fallback":"true"},files={
  "reference":("reference.dxf",(S/"reference.dxf").read_bytes(),"application/dxf"),
  "student":("student.dxf",b"not a dxf","application/dxf"),
 })
 assert malformed_student.status_code==422
 for response in (malformed_reference,malformed_student):
  detail=response.json()["detail"]
  assert "Invalid or unsupported DXF" in detail
  assert "Traceback" not in detail and ":\\" not in detail

def test_review_repeated_requests_are_deterministic():
 _review_approve()
 first=_post_review().json()
 second=_post_review().json()
 assert first==second
 assert first["svg"]==second["svg"]

def test_grade_and_review_scores_and_rubric_selection_are_identical():
 _review_approve()
 grade=_post_grade().json()
 review=_post_review().json()
 assert review["score"]==grade["score"]
 assert review["rubric_selection"]==grade["rubric_selection"]
 assert review["rubric"]==grade["rubric"]

def test_review_json_and_svg_share_issue_ids_and_visual_classes():
 _review_approve()
 body=_post_review().json()
 root=ET.fromstring(body["svg"])
 svg_issue_ids={element.attrib["data-issue-id"] for element in root.iter() if "data-issue-id" in element.attrib}
 visual_issues=[finding for finding in body["issues"] if finding["expected_geometry"] or finding["actual_geometry"] or finding["region"]]
 assert {finding["issue_id"] for finding in visual_issues}<=svg_issue_ids
 svg_classes={name for element in root.iter() for name in element.attrib.get("class","").split()}
 for finding in visual_issues:
  assert set(finding["css_classes"])&svg_classes

def test_review_missing_geometry_uses_reference_ghost():
 _review_approve()
 body=_post_review().json()
 missing=next(finding for finding in body["issues"] if finding["visual_role"]=="missing")
 assert missing["expected_geometry"]["source"]=="reference"
 assert missing["actual_geometry"] is None
 assert f'data-issue-id="{missing["issue_id"]}"' in body["svg"]
 assert 'class="missing"' in body["svg"]

def test_review_inaccurate_geometry_contains_expected_and_actual_overlays():
 _review_approve()
 body=_post_review(student_path=S/"student_door_window_errors.dxf").json()
 inaccurate=next(finding for finding in body["issues"] if finding["visual_role"]=="inaccurate")
 assert inaccurate["expected_geometry"]["source"]=="reference"
 assert inaccurate["actual_geometry"]["source"]=="student"
 assert 'class="inaccurate-expected"' in body["svg"]
 assert 'class="inaccurate-actual"' in body["svg"]

def test_review_reports_unsupported_student_entities():
 reference=_document_bytes()
 student=_document_bytes(unsupported=True)
 response=client.post("/api/review",data={"allow_fallback":"true"},files={
  "reference":("reference.dxf",reference,"application/dxf"),
  "student":("student.dxf",student,"application/dxf"),
 })
 assert response.status_code==200
 body=response.json()
 assert body["unsupported_entities"]["student"][0]["entity_type"]=="HATCH"
 assert body["unsupported_entities"]["student"][0]["source"]=="student"
 unsupported_issue=next(finding for finding in body["issues"] if finding["category"]=="unsupported_entity")
 assert f'data-issue-id="{unsupported_issue["issue_id"]}"' in body["svg"]

def test_review_api_preserves_safe_svg_escaping():
 malicious='<script>&"'
 document=_document_bytes(text=malicious)
 response=client.post("/api/review",data={"allow_fallback":"true"},files={
  "reference":("reference.dxf",document,"application/dxf"),
  "student":("student.dxf",document,"application/dxf"),
 })
 assert response.status_code==200
 svg=response.json()["svg"]
 assert "<script>" not in svg
 assert "&lt;script&gt;&amp;&quot;" in svg
 root=ET.fromstring(svg)
 assert not any(element.tag.endswith("script") for element in root.iter())

def test_review_responses_contain_no_machine_paths_or_internal_details():
 _review_approve()
 body=_post_review().json()
 for value in _all_strings(body):
  assert ":\\" not in value
  assert "Traceback" not in value
  assert "__file__" not in value
