from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
S=Path(__file__).parents[1]/"samples"; client=TestClient(app)
def test_health(): assert client.get('/health').json()=={"status":"ok"}
def test_grade_flow():
 with open(S/'reference.dxf','rb') as a,open(S/'student_missing_wall.dxf','rb') as b:r=client.post('/api/grade',files={'reference':('reference.dxf',a,'application/dxf'),'student':('student.dxf',b,'application/dxf')})
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
 approved=client.post("/api/rubric/approve",json=body["rubric"])
 assert approved.status_code==200
 assert approved.json()["rubric"]["approved"] is True

def test_reference_validation_rejects_invalid_dxf_cleanly():
 response=client.post("/api/reference/validate",files={"reference":("broken.dxf",b"not a dxf","application/dxf")})
 assert response.status_code==422
 assert "Invalid or unsupported DXF" in response.json()["detail"]