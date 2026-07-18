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
