from tests.synthetic_data import fixture_root, samples_root
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

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
        "assignment-type",
        "completion-scoring-mode",
        "completion-policy-summary",
        "normalization-mode",
        "normalization-policy-summary",
        "normalization-card",
        "result-normalization-mode",
        "result-transform",
        "normalization-evidence",
        "result-transform-reason",
        "score-breakdown-categories",
        "result-policy",
        "result-applied-deduction",
        "evidence-raw-deduction",
        "evidence-deduction-status",
        "approve-rubric",
        "fallback-mode",
        "student-file",
        "student-metadata-name",
        "student-metadata-id",
        "course-section",
        "download-report",
        "report-status",
        "run-review",
        "review-results",
        "result-score",
        "result-assignment-type",
        "result-detected-features",
        "result-issues",
        "result-supporting",
        "result-reference-notes",
        "drawing-viewport",
        "drawing-view-controls",
        "view-review-comparison",
        "view-student-only",
        "overlay-legend",
        "student-only-status",
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
    assert parser.assets == ["/static/style.css?v=review-usability-2", "data:,", "/static/app.js?v=review-usability-2"]
    lowered = response.text.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "//cdn" not in lowered
    assert "node_modules" not in lowered


def test_static_assets_share_a_deterministic_release_version():
    _, first = page()
    _, repeated = page()
    static_assets = [asset for asset in first.assets if asset.startswith("/static/")]
    versions = {
        parse_qs(urlsplit(asset).query).get("v", [])[-1]
        for asset in static_assets
    }

    assert static_assets == ["/static/style.css?v=review-usability-2", "/static/app.js?v=review-usability-2"]
    assert versions == {"review-usability-2"}
    assert repeated.assets == first.assets
    assert all(client.get(asset).status_code == 200 for asset in static_assets)


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
    assert "presentedIssues(review).find(isPrimaryStudentIssue)" in javascript
    assert "No student issues detected" in javascript
    assert "Supporting topology evidence" in javascript
    assert "No separate deduction" in javascript
    assert "Primary issues" in response.text
    assert "Supporting" in response.text
    assert "Reference notes" in response.text
    assert ".issue-card.finding-supporting" in stylesheet
    assert ".issue-card.finding-reference" in stylesheet
    assert "hidden" in parser.elements["feedback-detail"][1]

def test_normalization_selector_invalidates_approval_and_result_evidence_is_visible():
    response, parser = page()
    javascript = client.get("/static/app.js").text
    stylesheet = client.get("/static/style.css").text

    assert parser.elements["normalization-mode"][0] == "select"
    assert "Strict placement" in response.text
    assert "Translation-tolerant placement" in response.text
    assert "Absolute coordinates matter" in javascript
    assert "Local movement remains an error" in javascript
    listener = javascript[
        javascript.index('normalizationModeInput.addEventListener("change"'):
        javascript.index('byId("assignment-title").addEventListener')
    ]
    assert "state.provisionalRubric.normalization_mode = normalizationModeInput.value" in listener
    assert "markRubricDirty();" in listener
    dirty = javascript[javascript.index("function markRubricDirty"):javascript.index("async function approveRubric")]
    assert "state.rubricId = null" in dirty
    assert "normalizationModeInput.disabled = false" in dirty
    assert "normalizationModeInput.disabled = loading;" in javascript
    assert "normalizationModeInput.disabled = false" in javascript
    assert "placementModeLabel(state.provisionalRubric.normalization_mode)" in javascript
    assert "renderNormalizationDecision(review)" in javascript
    assert 'byId("result-transform").textContent = "None permitted"' in javascript
    assert "decision.rejection_reason" in javascript
    assert "resetNormalizationDecision();" in javascript
    assert ".normalization-card" in stylesheet


def test_assignment_type_is_instructor_confirmed_and_invalidates_approval():
    response, parser = page()
    javascript = client.get("/static/app.js").text

    assert parser.elements["assignment-type"][0] == "select"
    assert "Suggested assignment type" in response.text
    assert "Detected structure" in response.text
    for option in (
        "Geometric Construction Exercise",
        "Mixed Geometric Composition",
        "Geometric Pattern",
        "Complex Geometric Pattern",
        "Interior Plan",
        "Architectural Drawing",
        "Technical Drawing",
        "Other",
    ):
        assert f'>{option}</option>' in response.text
    listener = javascript[
        javascript.index('assignmentTypeInput.addEventListener("change"'):
        javascript.index('byId("assignment-title").addEventListener')
    ]
    assert "state.provisionalRubric.assignment_type = assignmentTypeInput.value" in listener
    assert "markRubricDirty();" in listener
    dirty = javascript[javascript.index("function markRubricDirty"):javascript.index("async function approveRubric")]
    assert "state.rubricId = null" in dirty
    assert "updateReviewAvailability();" in dirty
    assert "assignmentTypeInput.disabled = false" in dirty
    assert 'byId("result-assignment-type").textContent' in javascript
    assert 'byId("result-detected-features").textContent' in javascript
    assert 'byId("result-assignment-title").textContent' in javascript
    assert "Islamic Geometric Pattern" not in response.text


def test_final_acceptance_presentation_controls_are_wired():
    response, parser = page()
    javascript = client.get("/static/app.js").text
    stylesheet = client.get("/static/style.css").text
    assert parser.elements["assignment-title"][0] == "input"
    assert 'reviewButton.addEventListener("click", () => runReview(false))' in javascript
    assert 'gradeAnywayButton.addEventListener("click", () => runReview(true))' in javascript
    assert "finding_presentation" in javascript
    assert "How to correct" in response.text
    assert "category-earned" in javascript and ".category-earned" in stylesheet
    assert 'data-tolerance="vertex"' in response.text and "Vertex tolerance unavailable" in response.text


def test_reference_analysis_timeout_clears_loading_and_displays_error():
    javascript = client.get("/static/app.js").text
    request_json = javascript[
        javascript.index("async function requestJson"):
        javascript.index("function clearChildren")
    ]
    inspect_reference = javascript[
        javascript.index("async function inspectReference"):
        javascript.index("function renderValidation")
    ]
    show_error = javascript[
        javascript.index("function showError"):
        javascript.index("function hideError")
    ]

    assert "const REFERENCE_ANALYSIS_TIMEOUT_MS = 30000;" in javascript
    assert "new AbortController()" in request_json
    assert "controller.abort()" in request_json
    assert 'error.name === "AbortError"' in request_json
    assert "timeoutError.status = 408;" in request_json
    assert "window.clearTimeout(timeoutId)" in request_json
    assert inspect_reference.count("REFERENCE_ANALYSIS_TIMEOUT_MS") == 3
    assert "showError(error);" in inspect_reference
    assert "finally" in inspect_reference
    assert "setLoading(false);" in inspect_reference
    assert "element.textContent = message;" in show_error


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


def test_optional_metadata_and_authoritative_pdf_download_are_wired():
    _, parser = page()
    javascript = client.get("/static/app.js").text

    assert parser.elements["student-metadata-name"][1]["maxlength"] == "120"
    assert parser.elements["student-metadata-id"][1]["maxlength"] == "64"
    assert parser.elements["course-section"][1]["maxlength"] == "120"
    assert "disabled" in parser.elements["download-report"][1]
    assert 'const metadataFields = [["student_name", metadataInputs[0]], ["student_id", metadataInputs[1]], ["course_section", metadataInputs[2]]]' in javascript
    assert 'if (input.value.trim()) form.append(name, input.value);' in javascript
    assert "state.review.review_id" in javascript
    assert "state.review.report_available" in javascript
    assert 'encodeURIComponent(state.review.review_id)' in javascript
    assert 'fetch("/api/reviews/" + reviewId + "/report.pdf"' in javascript
    assert 'URL.createObjectURL(blob)' in javascript
    assert 'PDF export failed. Your review is still available.' in javascript

    listener_start = javascript.index('metadataInputs.forEach((input) => input.addEventListener("input"')
    listener_end = javascript.index('completionPolicyInput.addEventListener', listener_start)
    metadata_listener = javascript[listener_start:listener_end]
    assert "resetReview();" in metadata_listener
    assert "markRubricDirty();" not in metadata_listener


def test_drawing_view_control_defaults_to_review_comparison_with_semantic_state():
    response, parser = page()
    control = parser.elements["drawing-view-controls"][1]
    review = parser.elements["view-review-comparison"][1]
    student = parser.elements["view-student-only"][1]
    status = parser.elements["student-only-status"][1]

    assert control["role"] == "group"
    assert control["aria-label"] == "Drawing view"
    assert review["type"] == student["type"] == "button"
    assert review["aria-controls"] == student["aria-controls"] == "drawing-viewport"
    assert review["aria-pressed"] == "true"
    assert student["aria-pressed"] == "false"
    assert "hidden" not in parser.elements["overlay-legend"][1]
    assert "hidden" in status
    assert "Review comparison" in response.text
    assert "Student only" in response.text
    assert "Student submission only &mdash; DraftLens overlays are hidden." in response.text


def test_student_only_view_hides_overlay_roles_but_not_original_student_layer():
    stylesheet = client.get("/static/style.css").text
    javascript = client.get("/static/app.js").text
    mode_css = stylesheet[
        stylesheet.index('.drawing-viewport.student-only-view svg [data-layer="reference"]'):
        stylesheet.index(".drawing-viewport [data-issue-id]")
    ]
    mode_function = javascript[
        javascript.index("function setDrawingViewMode"):
        javascript.index("function resetNormalizationDecision")
    ]

    assert '[data-layer="reference"]' in mode_css
    assert '[data-layer="issues"]' in mode_css
    assert '[data-layer="student"]' not in mode_css
    assert "display: none" in mode_css
    assert 'classList.toggle("student-only-view", studentOnly)' in mode_function
    assert 'byId("overlay-legend").hidden = studentOnly' in mode_function
    assert 'byId("student-only-status").hidden = !studentOnly' in mode_function
    assert 'viewReviewButton.setAttribute("aria-pressed", String(!studentOnly))' in mode_function
    assert 'viewStudentButton.setAttribute("aria-pressed", String(studentOnly))' in mode_function


def test_student_only_toggle_is_constant_time_and_preserves_review_and_selection():
    javascript = client.get("/static/app.js").text
    mode_function = javascript[
        javascript.index("function setDrawingViewMode"):
        javascript.index("function resetNormalizationDecision")
    ]
    reset_review = javascript[
        javascript.index("function resetReview"):
        javascript.index("function setDrawingViewMode")
    ]
    render_results = javascript[
        javascript.index("function renderResults"):
        javascript.index("function formatTranslation")
    ]
    viewport_listener = javascript[
        javascript.index('byId("drawing-viewport").addEventListener'):
        javascript.index("function uploadForm")
    ]

    for forbidden in ("fetch(", "requestJson(", "renderSafeSvg(", "replaceChildren(", "querySelectorAll("):
        assert forbidden not in mode_function
    assert "state.review =" not in mode_function
    assert "state.selectedIssueId =" not in mode_function
    assert "review_id" not in mode_function
    assert "report_available" not in mode_function
    assert "score" not in mode_function
    assert 'setDrawingViewMode("review");' in reset_review
    assert 'setDrawingViewMode("review");' in render_results
    assert 'if (state.viewMode === "student") return;' in viewport_listener
    assert 'setDrawingViewMode("student")' in viewport_listener

    select_student = javascript[
        javascript.index("function selectStudent"):
        javascript.index("function canRunReview")
    ]
    reset_reference = javascript[
        javascript.index("function resetReferenceDependentState"):
        javascript.index("async function inspectReference")
    ]
    assert "resetReview();" in select_student
    assert "resetReview();" in reset_reference


def test_translation_review_svg_keeps_student_geometry_in_submitted_coordinates():
    fixtures = fixture_root() / "simple_audit-II"
    reference_path = fixtures / "01-ARC-Reference.dxf"
    student_path = fixtures / "01-ARC-All-Moved.dxf"
    with reference_path.open("rb") as reference:
        suggestion_response = client.post(
            "/api/rubric/suggest",
            files={"reference": ("reference.dxf", reference, "application/dxf")},
        )
    assert suggestion_response.status_code == 200
    suggestion = suggestion_response.json()
    rubric = suggestion["rubric"]
    rubric["normalization_mode"] = "translation"
    rubric["assignment_type"] = suggestion["suggested_assignment_type"]
    approval = client.post(
        "/api/rubric/approve",
        json={"reference_id": suggestion["reference_id"], "rubric": rubric},
    )
    assert approval.status_code == 200
    with reference_path.open("rb") as reference, student_path.open("rb") as student:
        review_response = client.post(
            "/api/review",
            data={"rubric_id": approval.json()["rubric_id"]},
            files={
                "reference": ("reference.dxf", reference, "application/dxf"),
                "student": ("student.dxf", student, "application/dxf"),
            },
        )
    assert review_response.status_code == 200
    body = review_response.json()
    assert body["score"] == 100
    assert body["normalization_decision"]["transform_applied"] is True

    root = ET.fromstring(body["svg"])
    layers = {group.attrib.get("data-layer"): group for group in root.findall("{http://www.w3.org/2000/svg}g")}
    reference_paths = [item.attrib["d"] for item in layers["reference"].iter("{http://www.w3.org/2000/svg}path")]
    student_paths = [item.attrib["d"] for item in layers["student"].iter("{http://www.w3.org/2000/svg}path")]
    assert reference_paths
    assert student_paths
    assert reference_paths != student_paths


def test_compatibility_card_exposes_spatial_coherence_evidence():
    response, parser = page()
    javascript = client.get("/static/app.js").text
    for element_id in (
        "compatibility-reference-entities",
        "compatibility-student-entities",
        "compatibility-matches",
        "compatibility-coherent-matches",
        "compatibility-displacement-support",
        "compatibility-reference-coverage",
        "compatibility-student-coverage",
    ):
        assert element_id in parser.elements
    for label in (
        "Supported reference entities",
        "Supported student entities",
        "Raw intrinsic matches",
        "Spatially coherent matches",
        "Dominant displacement support",
        "Reference coherent coverage",
        "Student coherent coverage",
    ):
        assert label in response.text
    assert 'compatibility.compatibility_status === "incompatible"' in javascript
    assert '"Likely wrong assignment file"' in javascript
    assert "compatibility.coherent_match_count" in javascript
    assert "compatibility.displacement_consensus_support" in javascript
    assert "compatibility.coherent_reference_coverage" in javascript
    assert "compatibility.coherent_student_coverage" in javascript
    assert "view-student-only" in parser.elements


def test_validation_findings_ui_wiring_and_safe_rendering():
    response, parser = page()
    javascript = client.get("/static/app.js").text
    stylesheet = client.get("/static/style.css").text

    # Container exists in HTML
    for element_id in (
        "validation-findings",
        "validation-findings-list",
        "validation-findings-count",
    ):
        assert element_id in parser.elements

    # Findings container is hidden initially
    assert "hidden" in parser.elements["validation-findings"][1]

    # Safe DOM rendering verified (strictly no unsafe execution)
    assert 'document.createElement("li")' in javascript
    assert 'clearChildren(list)' in javascript
    assert "resetValidationFindings()" in javascript
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "eval(" not in javascript

    # Distinguishes critical vs warning and shows blocking status
    assert '"Critical — Blocks reference"' in javascript
    assert '"Warning — Advisory"' in javascript
    assert "is-critical" in javascript
    assert "is-warning" in javascript

    # Optional entity metadata handled safely without undefined/null
    assert "finding.entity_type" in javascript
    assert "finding.source_handle" in javascript
    assert "finding.layer" in javascript
    assert "finding.explanation" in javascript
    assert "finding.suggested_correction" in javascript
    assert '"Handle: "' in javascript
    assert '"Layer: "' in javascript

    # CSS styling present
    assert ".validation-findings" in stylesheet
    assert ".validation-finding-item" in stylesheet
    assert ".validation-finding-item.is-critical" in stylesheet
    assert ".validation-finding-item.is-warning" in stylesheet
    assert ".validation-finding-badge" in stylesheet


NODE_HARNESS_PREAMBLE = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const appJs = fs.readFileSync('app/static/app.js', 'utf8');

class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...names) { names.forEach(n => this.set.add(n)); this.sync(); }
  remove(...names) { names.forEach(n => this.set.delete(n)); this.sync(); }
  toggle(name, force) {
    if (force === true) this.set.add(name);
    else if (force === false) this.set.delete(name);
    else if (this.set.has(name)) this.set.delete(name);
    else this.set.add(name);
    this.sync();
  }
  contains(name) { return this.set.has(name); }
  sync() { this.el.className = Array.from(this.set).join(' '); }
}

class MockElement {
  constructor(id, tag = 'div') {
    this.id = id || '';
    this.tagName = tag.toUpperCase();
    this._className = '';
    this.classList = new ClassList(this);
    this.hidden = false;
    this.textContent = '';
    this.children = [];
    this.dataset = {};
    this.files = [];
    this.attributes = {};
    this.eventListeners = {};
    this.value = '';
    this.disabled = false;
    this.checked = false;
  }
  get className() { return this._className; }
  set className(val) {
    this._className = val || '';
    this.classList.set = new Set(this._className.split(/\s+/).filter(Boolean));
  }
  get firstChild() { return this.children[0] || null; }
  querySelector() { return new MockElement('mock-sub'); }
  querySelectorAll() { return []; }
  closest() { return null; }
  click() {}
  addEventListener(evt, fn) {
    if (!this.eventListeners[evt]) this.eventListeners[evt] = [];
    this.eventListeners[evt].push(fn);
  }
  setAttribute(name, val) { this.attributes[name] = String(val); }
  getAttribute(name) { return this.attributes[name] !== undefined ? this.attributes[name] : null; }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...nodes) {
    for (const n of nodes) {
      if (typeof n === 'string') {
        const textNode = new MockElement('', '#text');
        textNode.textContent = n;
        this.children.push(textNode);
      } else {
        this.children.push(n);
      }
    }
  }
  appendChild(node) { this.append(node); return node; }
  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx !== -1) this.children.splice(idx, 1);
    return child;
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  allText() {
    let out = this.textContent || '';
    for (const c of this.children) {
      out += ' ' + c.allText();
    }
    return out.trim();
  }
  toTree() {
    return {
      id: this.id,
      tag: this.tagName,
      className: this.className,
      hidden: this.hidden,
      text: this.textContent,
      allText: this.allText(),
      children: this.children.map(c => c.toTree())
    };
  }
}

function createHarness() {
  const elements = new Map();
  function getOrCreate(id, tag = 'div') {
    if (!elements.has(id)) elements.set(id, new MockElement(id, tag));
    return elements.get(id);
  }

  const body = getOrCreate('body', 'body');
  const sandbox = {
    document: {
      body,
      getElementById: (id) => getOrCreate(id),
      createElement: (tag) => new MockElement('', tag),
      querySelector: (sel) => getOrCreate('sub-' + sel),
      querySelectorAll: () => [],
    },
    console,
    setTimeout,
    clearTimeout,
    AbortController,
    FormData,
    File,
    Blob,
    Array, Object, String, Number, Boolean, Set, Map, JSON, Math, Promise
  };
  sandbox.window = sandbox;
  sandbox.fetch = async () => { throw new Error('not implemented'); };

  vm.createContext(sandbox);
  vm.runInContext(appJs, sandbox);
  return { sandbox, elements, getOrCreate };
}
"""



def _run_ui_behavior(js_code: str) -> dict:
    runner = NODE_HARNESS_PREAMBLE + "\n" + js_code
    res = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parent.parent,
    )
    return json.loads(res.stdout)


def test_behavioral_critical_finding_rendering():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    sandbox.renderValidation({
      summary: { critical: 1, warnings: 0 },
      findings: [{
        code: 'zero_length',
        severity: 'critical',
        message: 'A zero-length line makes the reference invalid.',
        entity_id: 'R-0001',
        entity_type: 'LINE',
        source_handle: '4F',
        layer: 'WALLS',
        blocks_reference: true,
        explanation: 'A line entity has identical start and end points.',
        suggested_correction: 'Inspect the identified entity in AutoCAD and remove if unintended.'
      }]
    });
    const container = getOrCreate('validation-findings');
    const list = getOrCreate('validation-findings-list');
    const count = getOrCreate('validation-findings-count');
    const item = list.children[0];
    console.log(JSON.stringify({
      containerHidden: container.hidden,
      countText: count.textContent,
      itemCount: list.children.length,
      itemClassName: item.className,
      allText: item.allText()
    }));
    """
    res = _run_ui_behavior(js)
    assert res["containerHidden"] is False
    assert res["countText"] == "1"
    assert res["itemCount"] == 1
    assert "is-critical" in res["itemClassName"]
    # 1. Critical label is displayed
    assert "Critical" in res["allText"]
    # 2. Blocks-reference status is displayed
    assert "Blocks reference" in res["allText"]
    # 3. Entity type, handle, and layer are shown when available
    assert "LINE" in res["allText"]
    assert "Handle: 4F" in res["allText"]
    assert "Layer: WALLS" in res["allText"]
    # 4. Explanation and suggested correction are shown
    assert "identical start and end points" in res["allText"]
    assert "Suggested action:" in res["allText"]
    assert "Inspect the identified entity in AutoCAD" in res["allText"]


def test_behavioral_warning_finding_rendering():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    sandbox.renderValidation({
      summary: { critical: 0, warnings: 1 },
      findings: [{
        code: 'open_polyline',
        severity: 'warning',
        message: 'Polyline endpoints are nearly coincident.',
        entity_id: 'R-0002',
        entity_type: 'LWPOLYLINE',
        source_handle: '12',
        layer: 'BOUNDARY',
        blocks_reference: false,
        explanation: 'Polyline endpoints are nearly coincident but not marked closed.',
        suggested_correction: 'Use PEDIT to close the boundary.'
      }]
    });
    const list = getOrCreate('validation-findings-list');
    const item = list.children[0];
    console.log(JSON.stringify({
      itemClassName: item.className,
      allText: item.allText()
    }));
    """
    res = _run_ui_behavior(js)
    assert "is-warning" in res["itemClassName"]
    assert "is-critical" not in res["itemClassName"]
    # 1. Warning/advisory status is displayed
    assert "Warning" in res["allText"]
    assert "Advisory" in res["allText"]
    # 2. It is not presented as blocking
    assert "Blocks reference" not in res["allText"]
    # 3. Available metadata is shown
    assert "LWPOLYLINE" in res["allText"]
    assert "Handle: 12" in res["allText"]
    assert "Layer: BOUNDARY" in res["allText"]
    assert "PEDIT" in res["allText"]


def test_behavioral_missing_metadata_safety():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    sandbox.renderValidation({
      summary: { critical: 1, warnings: 0 },
      findings: [{
        code: 'zero_radius',
        severity: 'critical',
        message: 'Zero radius circle.',
        blocks_reference: true,
        entity_type: null,
        source_handle: null,
        layer: null,
        explanation: 'Non-positive radius.',
        suggested_correction: 'Specify radius.'
      }]
    });
    const list = getOrCreate('validation-findings-list');
    const item = list.children[0];
    console.log(JSON.stringify({
      allText: item.allText()
    }));
    """
    res = _run_ui_behavior(js)
    text = res["allText"]
    # Missing entity type, handle, or layer does not produce:
    # undefined, null, [object Object]
    assert "undefined" not in text
    assert "null" not in text
    assert "[object" not in text
    assert "Handle:" not in text
    assert "Layer:" not in text
    assert "Zero radius circle" in text


def test_behavioral_hostile_server_text_safe_dom():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    sandbox.renderValidation({
      summary: { critical: 1, warnings: 0 },
      findings: [{
        code: 'custom_code',
        severity: 'critical',
        message: '<script>alert(1)</script>',
        entity_type: '<img src=x onerror=alert(2)>',
        source_handle: '<svg onload=alert(3)>',
        layer: '<b onmouseover=alert(4)>L</b>',
        blocks_reference: true,
        explanation: '<b>Malicious markup</b> <iframe src=\"//evil.com\"></iframe>',
        suggested_correction: '<script>fetch(\"/evil\")</script>'
      }]
    });
    const list = getOrCreate('validation-findings-list');
    const item = list.children[0];

    function collectTags(node, tags = []) {
      tags.push(node.tag);
      for (const child of node.children) {
        collectTags(child, tags);
      }
      return tags;
    }

    const tags = collectTags(item.toTree());
    console.log(JSON.stringify({
      tags,
      allText: item.allText()
    }));
    """
    res = _run_ui_behavior(js)
    # Ensure no executable or hostile tags were created as HTML elements
    forbidden_tags = {"SCRIPT", "IMG", "SVG", "IFRAME", "B"}
    created_tags = set(res["tags"])
    assert not (created_tags & forbidden_tags), f"Hostile elements created: {created_tags & forbidden_tags}"
    # Values containing HTML-like text are rendered as text content
    assert "<script>alert(1)</script>" in res["allText"]
    assert "<img src=x onerror=alert(2)>" in res["allText"]
    assert "<iframe" in res["allText"]


def test_behavioral_empty_findings_clears_and_hides_container():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    // First populate findings
    sandbox.renderValidation({
      summary: { critical: 1, warnings: 0 },
      findings: [{
        code: 'zero_length',
        severity: 'critical',
        message: 'Issue',
        blocks_reference: true
      }]
    });
    const containerBefore = getOrCreate('validation-findings').hidden;
    const countBefore = getOrCreate('validation-findings-count').textContent;
    const itemsBefore = getOrCreate('validation-findings-list').children.length;

    // Now send empty findings
    sandbox.renderValidation({
      summary: { critical: 0, warnings: 0 },
      findings: []
    });
    const containerAfter = getOrCreate('validation-findings').hidden;
    const countAfter = getOrCreate('validation-findings-count').textContent;
    const itemsAfter = getOrCreate('validation-findings-list').children.length;

    console.log(JSON.stringify({
      containerBefore, countBefore, itemsBefore,
      containerAfter, countAfter, itemsAfter
    }));
    """
    res = _run_ui_behavior(js)
    assert res["containerBefore"] is False
    assert res["countBefore"] == "1"
    assert res["itemsBefore"] == 1
    # Findings container is cleared, hidden, count reset
    assert res["containerAfter"] is True
    assert res["countAfter"] == "0"
    assert res["itemsAfter"] == 0


def test_behavioral_reset_flows():
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const container = getOrCreate('validation-findings');
    const list = getOrCreate('validation-findings-list');
    const count = getOrCreate('validation-findings-count');

    function populate() {
      sandbox.renderValidation({
        summary: { critical: 1, warnings: 0 },
        findings: [{
          code: 'zero_length',
          severity: 'critical',
          message: 'Zero length',
          blocks_reference: true
        }]
      });
    }

    // 1. Cleared reference reset via inspectReference(null)
    populate();
    const populatedHidden = container.hidden;
    const populatedCount = list.children.length;
    sandbox.inspectReference(null);
    const afterClearedHidden = container.hidden;
    const afterClearedCount = list.children.length;

    // 2. Helper-level reference state reset
    populate();
    sandbox.resetReferenceDependentState();
    const afterRefDepHidden = container.hidden;
    const afterRefDepCount = list.children.length;

    // 3. Helper-level findings reset
    populate();
    sandbox.resetValidationFindings();
    const afterResetFindingsHidden = container.hidden;
    const afterResetFindingsCount = list.children.length;

    console.log(JSON.stringify({
      populatedHidden, populatedCount,
      afterClearedHidden, afterClearedCount,
      afterRefDepHidden, afterRefDepCount,
      afterResetFindingsHidden, afterResetFindingsCount
    }));
    """
    res = _run_ui_behavior(js)
    assert res["populatedHidden"] is False
    assert res["populatedCount"] == 1

    # Cleared reference reset via inspectReference(null): existing findings disappear
    assert res["afterClearedHidden"] is True
    assert res["afterClearedCount"] == 0

    # Direct helper assertions also confirm clean reset
    assert res["afterRefDepHidden"] is True
    assert res["afterRefDepCount"] == 0
    assert res["afterResetFindingsHidden"] is True
    assert res["afterResetFindingsCount"] == 0


def test_behavioral_inspect_reference_new_file_flow():
    js = """
    (async () => {
      const { sandbox, getOrCreate } = createHarness();
      const container = getOrCreate('validation-findings');
      const list = getOrCreate('validation-findings-list');
      const count = getOrCreate('validation-findings-count');

      // 1. Seed the mock DOM with visible stale findings
      sandbox.renderValidation({
        summary: { critical: 1, warnings: 0 },
        findings: [{
          code: 'zero_length',
          severity: 'critical',
          message: 'Stale critical finding',
          blocks_reference: true,
          entity_type: 'LINE',
          source_handle: '99',
          layer: 'STALE_LAYER',
          explanation: 'Stale explanation from previous file',
          suggested_correction: 'Remove stale entity'
        }]
      });

      const seededHidden = container.hidden;
      const seededCount = count.textContent;
      const seededItemCount = list.children.length;
      const seededText = list.allText();

      // 2. Mock fetch using the Node VM harness and verify that stale findings
      // are cleared before or during the request lifecycle (not merely after a reset helper).
      let stateWhenFetchInvoked = null;
      sandbox.fetch = async (url) => {
        if (!stateWhenFetchInvoked) {
          stateWhenFetchInvoked = {
            hidden: container.hidden,
            count: count.textContent,
            itemCount: list.children.length,
            text: list.allText()
          };
        }
        if (url === '/api/reference/validate') {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              validation: {
                can_continue: true,
                summary: { critical: 0, warnings: 1 },
                findings: [{
                  code: 'open_polyline',
                  severity: 'warning',
                  message: 'New reference advisory warning',
                  blocks_reference: false,
                  entity_type: 'LWPOLYLINE',
                  source_handle: '55',
                  layer: 'NEW_BOUNDARY',
                  explanation: 'Polyline is open in new drawing',
                  suggested_correction: 'Close boundary with PEDIT'
                }]
              }
            })
          };
        }
        if (url === '/api/assignment/analyze') {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              suggested_assignment_type: 'Mechanical Component',
              entity_counts: { LWPOLYLINE: 1 }
            })
          };
        }
        if (url === '/api/rubric/suggest') {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              reference_id: 'ref-new-123',
              suggested_assignment_type: 'Mechanical Component',
              rubric: {
                assignment_title: 'Exercise 1',
                categories: [],
                tolerances: {}
              }
            })
          };
        }
        throw new Error('Unexpected URL ' + url);
      };

      // 3. Provide a mock File object and call the actual inspectReference(file)
      const mockFile = new sandbox.File(['dummy dxf content'], 'new_valid_reference.dxf');
      await sandbox.inspectReference(mockFile);

      const finalState = {
        seededHidden, seededCount, seededItemCount, seededText,
        stateWhenFetchInvoked,
        finalHidden: container.hidden,
        finalCount: count.textContent,
        finalItemCount: list.children.length,
        finalText: list.allText()
      };

      console.log(JSON.stringify(finalState));
    })();
    """
    res = _run_ui_behavior(js)
    # Verify seeded state had stale critical findings
    assert res["seededHidden"] is False
    assert res["seededCount"] == "1"
    assert res["seededItemCount"] == 1
    assert "Stale critical finding" in res["seededText"]
    assert "Handle: 99" in res["seededText"]

    # Verify reset occurred before / during the request lifecycle (when fetch was called)
    fetch_state = res["stateWhenFetchInvoked"]
    assert fetch_state["hidden"] is True
    assert fetch_state["count"] == "0"
    assert fetch_state["itemCount"] == 0
    assert fetch_state["text"] == ""

    # Verify final completed state is consistent with mocked response
    assert res["finalHidden"] is False
    assert res["finalCount"] == "1"
    assert res["finalItemCount"] == 1
    assert "New reference advisory warning" in res["finalText"]
    assert "LWPOLYLINE" in res["finalText"]
    assert "Handle: 55" in res["finalText"]
    assert "Layer: NEW_BOUNDARY" in res["finalText"]
    assert "Close boundary with PEDIT" in res["finalText"]
    # Ensure no stale metadata remains
    assert "Stale critical finding" not in res["finalText"]
    assert "99" not in res["finalText"]
    assert "STALE_LAYER" not in res["finalText"]


def test_behavioral_inspect_reference_failure_flow():
    js = """
    (async () => {
      const { sandbox, getOrCreate } = createHarness();
      const container = getOrCreate('validation-findings');
      const list = getOrCreate('validation-findings-list');
      const count = getOrCreate('validation-findings-count');
      const status = getOrCreate('validation-status');
      const message = getOrCreate('validation-message');
      const apiError = getOrCreate('api-error');

      // 1. Seed the mock DOM with visible stale findings
      sandbox.renderValidation({
        summary: { critical: 1, warnings: 0 },
        findings: [{
          code: 'zero_length',
          severity: 'critical',
          message: 'Stale error before failure',
          blocks_reference: true,
          entity_type: 'LINE',
          source_handle: '88',
          layer: 'OLD_LAYER',
          explanation: 'Stale explanation',
          suggested_correction: 'Stale action'
        }]
      });

      const seededHidden = container.hidden;
      const seededCount = count.textContent;
      const seededItemCount = list.children.length;

      // 2. Configure fetch to return the exact failed-response form handled by inspectReference()
      sandbox.fetch = async (url) => {
        if (url === '/api/reference/validate') {
          return {
            ok: false,
            status: 422,
            json: async () => ({
              detail: 'Invalid or unsupported DXF file format.'
            })
          };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      };

      // 3. Provide mock reference File, call and await inspectReference(file)
      // This exercises the real catch/failure path of inspectReference
      const mockFile = new sandbox.File(['bad content'], 'corrupted_drawing.dxf');
      await sandbox.inspectReference(mockFile);

      console.log(JSON.stringify({
        seededHidden, seededCount, seededItemCount,
        containerHidden: container.hidden,
        countText: count.textContent,
        itemCount: list.children.length,
        listText: list.allText(),
        statusClass: status.className,
        statusText: status.textContent,
        messageText: message.textContent,
        apiErrorHidden: apiError.hidden,
        apiErrorText: apiError.textContent
      }));
    })();
    """
    res = _run_ui_behavior(js)
    # Verify seeded state
    assert res["seededHidden"] is False
    assert res["seededCount"] == "1"
    assert res["seededItemCount"] == 1

    # Verify failure/catch path cleared findings and reset count
    assert res["containerHidden"] is True
    assert res["countText"] == "0"
    assert res["itemCount"] == 0
    assert res["listText"] == ""

    # Verify no stale entity metadata remains
    assert "88" not in res["listText"]
    assert "OLD_LAYER" not in res["listText"]
    assert "Stale error before failure" not in res["listText"]

    # Verify validation failure state and message are shown correctly
    assert res["statusText"] == "Reference rejected"
    assert "danger" in res["statusClass"]
    assert res["messageText"] == "The reference could not be analyzed."
    assert res["apiErrorHidden"] is False
    assert "This file is not a valid supported DXF" in res["apiErrorText"]
