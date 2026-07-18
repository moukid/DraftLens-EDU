from app.feedback import structured_findings
def test_ai_payload_excludes_geometry_and_files():
 result={"issues":[{"code":"MISSING_WALL","category":"walls","severity":"major","message":"Missing","deduction":12,"expected":{"length":10},"actual":None,"location":[2,3],"reference_entity_id":"e1"}],"reference":{"entities":[1]}}
 payload=structured_findings(result)
 assert payload==[{"code":"MISSING_WALL","category":"walls","severity":"major","message":"Missing","deduction":12,"expected":{"length":10},"actual":None}]
