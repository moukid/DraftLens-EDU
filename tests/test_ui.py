from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}
        self.assets = []
        self.filters = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.elements[element_id] = (tag, attributes)
        if tag in {"script", "link"}:
            location = attributes.get("src") or attributes.get("href")
            if location:
                self.assets.append(location)
        if "data-filter" in attributes:
            self.filters.add(attributes["data-filter"])


def page():
    response = client.get("/")
    assert response.status_code == 200
    parser = PageParser()
    parser.feed(response.text)
    return response, parser


def test_visual_review_page_exposes_complete_semantic_workflow():
    response, parser = page()
    required = {
        "workflow-status",
        "reference-file",
        "validation-status",
        "analysis-summary",
        "rubric-editor",
        "rubric-categories",
        "completion-scoring-mode",
        "completion-policy-summary",
        "score-breakdown-categories",
        "result-policy",
        "result-applied-deduction",
        "evidence-raw-deduction",
        "evidence-deduction-status",
        "approve-rubric",
        "fallback-mode",
        "student-file",
        "run-review",
        "review-results",
        "result-score",
        "result-issues",
        "result-supporting",
        "result-reference-notes",
        "drawing-viewport",
        "issue-list",
        "feedback-detail",
        "api-error",
    }
    assert required <= parser.elements.keys()
    assert parser.elements["reference-file"][0] == "input"
    assert parser.elements["student-file"][0] == "input"
    assert parser.elements["drawing-viewport"][0] == "div"
    assert "Reviewed drawing" in response.text
    assert "Technical evidence" in response.text


def test_ui_assets_are_served_from_fastapi_static_mount():
    javascript = client.get("/static/app.js")
    stylesheet = client.get("/static/style.css")
    assert javascript.status_code == 200
    assert stylesheet.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert "text/css" in stylesheet.headers["content-type"]
    assert '"use strict"' in javascript.text
    assert ".drawing-viewport" in stylesheet.text


def test_page_has_no_external_or_cdn_dependencies():
    response, parser = page()
    assert parser.assets == ["/static/style.css", "data:,", "/static/app.js"]
    lowered = response.text.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "//cdn" not in lowered
    assert "node_modules" not in lowered


def test_client_uses_existing_review_and_rubric_pipeline_contracts():
    javascript = client.get("/static/app.js").text
    for endpoint in (
        "/api/reference/validate",
        "/api/assignment/analyze",
        "/api/rubric/suggest",
        "/api/rubric/approve",
        "/api/review",
    ):
        assert endpoint in javascript
    assert 'form.append("reference"' in javascript
    assert 'form.append("student"' in javascript
    assert 'form.append("rubric_id"' in javascript
    assert 'form.append("allow_fallback", "true")' in javascript
    assert "/api/grade" not in javascript


def test_client_sanitizes_server_svg_without_unsafe_html_execution():
    javascript = client.get("/static/app.js").text
    assert "new DOMParser()" in javascript
    assert '"image/svg+xml"' in javascript
    assert 'documentNode.documentElement.localName !== "svg"' in javascript
    assert 'const blockedElements = new Set' in javascript
    assert 'blockedElements.has(node.localName.toLowerCase())' in javascript
    assert 'name.startsWith("on")' in javascript
    assert 'normalized.includes("javascript:")' in javascript
    assert "document.importNode" in javascript
    assert ".replaceChildren(" in javascript
    assert "innerHTML" not in javascript
    assert "eval(" not in javascript
    assert "new Function" not in javascript
    assert "Function(" not in javascript


def test_fallback_is_explicitly_off_and_review_is_disabled_initially():
    _, parser = page()
    fallback = parser.elements["fallback-mode"][1]
    review = parser.elements["run-review"][1]
    assert fallback.get("type") == "checkbox"
    assert "checked" not in fallback
    assert "disabled" in review


def test_issue_filters_and_bidirectional_issue_selection_are_wired():
    _, parser = page()
    assert parser.filters == {
        "all",
        "missing",
        "extra",
        "inaccurate",
        "connectivity",
        "warning",
        "critical",
    }
    javascript = client.get("/static/app.js").text
    assert 'button.dataset.issueId = issue.issue_id' in javascript
    assert 'event.target.closest("[data-issue-id]")' in javascript
    assert 'querySelectorAll("#drawing-viewport [data-issue-id]")' in javascript
    assert 'element.getAttribute("data-issue-id") === issueId' in javascript


def test_review_state_reset_and_finding_roles_are_explicitly_wired():
    response, parser = page()
    javascript = client.get("/static/app.js").text
    stylesheet = client.get("/static/style.css").text
    run_review = javascript[javascript.index("async function runReview"):javascript.index("function renderResults")]

    assert run_review.index("resetReview();") < run_review.index('requestJson("/api/review"')
    assert "state.selectedIssueId = null" in javascript
    assert 'element.classList.remove("is-selected")' in javascript
    assert 'byId("feedback-detail").hidden = true' in javascript
    assert 'resetCorrectionGuidance();' in javascript
    assert "review.issues.find(isPrimaryStudentIssue)" in javascript
    assert "No student issues detected" in javascript
    assert "Supporting topology evidence" in javascript
    assert "No separate deduction" in javascript
    assert "Primary issues" in response.text
    assert "Supporting" in response.text
    assert "Reference notes" in response.text
    assert ".issue-card.finding-supporting" in stylesheet
    assert ".issue-card.finding-reference" in stylesheet
    assert "hidden" in parser.elements["feedback-detail"][1]

def test_completion_policy_and_applied_deduction_contract_are_visible():
    response, parser = page()
    assert parser.elements["completion-scoring-mode"][0] == "select"
    assert "Proportional completion" in response.text
    javascript = client.get("/static/app.js").text
    assert 'ruleBasedOption.textContent = "Rule-based completion"' in javascript
    assert '? "Proportional completion" : "Rule-based completion"' in javascript
    assert "state.provisionalRubric.completion_scoring_mode" in javascript
    assert "completionPolicyDescription" in javascript
    assert "review.score_breakdown" in javascript
    assert 'formatDeduction(appliedDeduction(issue))' in javascript
    assert 'formatDeduction(rawDeduction(issue))' in javascript
    assert "issue.suppression_reason" in javascript
    assert 'byId("evidence-deduction-status")' in javascript


def test_structured_correction_guidance_is_labeled_and_not_rebuilt_from_rubric_commands():
    response, parser = page()
    javascript = client.get("/static/app.js").text

    for element_id in (
        "feedback-commands",
        "guidance-primary",
        "guidance-alternatives",
        "guidance-precision",
        "guidance-explanation",
        "guidance-related-id",
        "guidance-no-command",
    ):
        assert element_id in parser.elements
    assert "Primary correction" in response.text
    assert "Alternatives" in response.text
    assert "Precision aid" in response.text
    assert "No separate correction command" in response.text
    assert "issue.correction_guidance" in javascript
    assert "issue.recommended_commands" in javascript
    command_selector = javascript[javascript.index("function commandsForIssue"):javascript.index("function renderCorrectionGuidance")]
    assert "state.review.rubric" not in command_selector


def test_stage_2b_ui_contains_no_forbidden_feature_hooks():
    html = client.get("/").text.lower()
    javascript = client.get("/static/app.js").text.lower()
    assert 'id="zoom' not in html
    assert 'data-action="zoom"' not in html
    assert 'id="pan-' not in html
    assert 'data-action="pan"' not in html
    assert "annotated dxf" not in html
    assert "/api/report" not in javascript
    assert "websocket" not in javascript
