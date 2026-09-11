"""Tests for interactive legend, synchronized findings, and header credit."""
import io
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from app.main import app
from tests.synthetic_data import fixture_root

client = TestClient(app)
AUDIT = fixture_root() / "simple_audit"


def _run_ui_behavior(js_code: str) -> dict:
    from tests.test_ui import NODE_HARNESS_PREAMBLE
    runner = NODE_HARNESS_PREAMBLE + "\n" + js_code
    res = subprocess.run(
        ["node", "-e", runner],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parent.parent,
    )
    return json.loads(res.stdout)


def test_header_credit_present_exact_text_and_placement():
    """Verify header credit text is exact, placed directly below tagline, with CSS."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    exact_credit = "All rights reserved to MOUKiD BADiE &amp; Mervat El-Sawaf"
    exact_tagline = "Deterministic CAD grading and visual evidence"

    assert exact_credit in html
    assert exact_tagline in html

    # Direct placement under tagline
    tagline_idx = html.index(exact_tagline)
    credit_idx = html.index(exact_credit)
    assert tagline_idx < credit_idx
    between = html[tagline_idx:credit_idx]
    assert "</p>" in between
    assert '<p class="header-credit">' in between

    # CSS check
    css = client.get("/static/style.css").text
    assert ".header-credit" in css
    assert "word-break: break-word" in css


def test_legend_controls_structure_and_accessibility():
    """Verify 9 interactive legend buttons exist with type, data-role, and aria-pressed."""
    from tests.test_review_usability import page
    response, parser = page()

    roles = [
        "all",
        "reference",
        "student",
        "missing",
        "extra",
        "inaccurate",
        "connectivity",
        "warning",
        "critical",
    ]

    html = response.text
    assert '<ul id="overlay-legend" class="legend" role="toolbar"' in html
    assert 'id="drawing-empty-overlay"' in html

    for role in roles:
        assert f'data-role="{role}"' in html
        assert f'legend-{role}' in html

    # Initial state: "all" is active and aria-pressed="true", others are "false"
    assert 'class="legend-filter-btn legend-all active" data-role="all" aria-pressed="true"' in html
    for role in roles:
        if role != "all":
            assert f'data-role="{role}" aria-pressed="false"' in html


def test_drawing_role_css_filtering_rules():
    """Verify exact visibility CSS rules for all roles including pointer-events: none."""
    css = client.get("/static/style.css").text

    # Verify hiding reference and student in category modes
    assert '.drawing-viewport[data-active-role]:not([data-active-role="all"]):not([data-active-role="reference"]) svg [data-layer="reference"]' in css
    assert '.drawing-viewport[data-active-role]:not([data-active-role="all"]):not([data-active-role="student"]) svg [data-layer="student"]' in css

    # Verify hiding issue layers in reference and student modes
    assert '.drawing-viewport[data-active-role="reference"] svg [data-layer="issues"]' in css
    assert '.drawing-viewport[data-active-role="student"] svg [data-layer="issues"]' in css

    # Verify issue categories filtering
    for role in ["missing", "extra", "inaccurate", "connectivity", "warning", "critical"]:
        rule = f'.drawing-viewport[data-active-role="{role}"] svg [data-layer="issues"] > g:not([data-role="{role}"])'
        assert rule in css

    # Verify pointer-events: none on hidden layers
    assert "display: none !important" in css
    assert "pointer-events: none !important" in css


def test_behavioral_two_way_synchronization_in_node_vm():
    """Verify two-way sync between Legend buttons and Findings filter buttons."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const state = sandbox.getState();

    // Mock review data
    state.review = {
      issues: [
        { issue_id: 'I-01', visual_role: 'missing', finding_role: 'primary', severity: 'minor', technical_feedback: 'Missing' },
        { issue_id: 'I-02', visual_role: 'extra', finding_role: 'primary', severity: 'minor', technical_feedback: 'Extra' },
        { issue_id: 'I-03', visual_role: 'inaccurate', finding_role: 'primary', severity: 'major', technical_feedback: 'Inaccurate' },
        { issue_id: 'I-04', visual_role: 'connectivity', finding_role: 'supporting', severity: 'minor', technical_feedback: 'Gap' }
      ]
    };

    // 1. Activate Missing via setActiveRole('missing')
    sandbox.setActiveRole('missing');
    const role1 = sandbox.getActiveRole();
    const filter1 = state.filter;
    const viewMode1 = state.viewMode;

    // 2. Activate Extra via setFilter('extra')
    sandbox.setFilter('extra');
    const role2 = sandbox.getActiveRole();
    const filter2 = state.filter;

    // 3. Activate Reference via setActiveRole('reference')
    // Should filter drawing to reference, but leave Findings filter on 'all'
    sandbox.setActiveRole('reference');
    const role3 = sandbox.getActiveRole();
    const filter3 = state.filter;

    // 4. Activate Student via setActiveRole('student')
    // Should filter drawing to student, leave Findings filter on 'all'
    sandbox.setActiveRole('student');
    const role4 = sandbox.getActiveRole();
    const filter4 = state.filter;
    const viewMode4 = state.viewMode;

    // 5. Reset to All via setActiveRole('all')
    sandbox.setActiveRole('all');
    const role5 = sandbox.getActiveRole();
    const filter5 = state.filter;
    const viewMode5 = state.viewMode;

    console.log(JSON.stringify({
      role1, filter1, viewMode1,
      role2, filter2,
      role3, filter3,
      role4, filter4, viewMode4,
      role5, filter5, viewMode5
    }));
    """
    res = _run_ui_behavior(js)
    assert res["role1"] == "missing"
    assert res["filter1"] == "missing"
    assert res["viewMode1"] == "review"

    assert res["role2"] == "extra"
    assert res["filter2"] == "extra"

    assert res["role3"] == "reference"
    assert res["filter3"] == "all"

    assert res["role4"] == "student"
    assert res["filter4"] == "all"
    assert res["viewMode4"] == "student"

    assert res["role5"] == "all"
    assert res["filter5"] == "all"
    assert res["viewMode5"] == "review"


def test_behavioral_finding_selection_and_incompatible_filter_switching():
    """Verify selecting finding activates its visual_role, and incompatible filter switch clears it."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const state = sandbox.getState();

    state.review = {
      issues: [
        { issue_id: 'I-MISS', visual_role: 'missing', finding_role: 'primary', severity: 'minor', technical_feedback: 'Missing' },
        { issue_id: 'I-EXTRA', visual_role: 'extra', finding_role: 'primary', severity: 'minor', technical_feedback: 'Extra' }
      ]
    };

    // 1. Initially on 'all'
    sandbox.setActiveRole('all');

    // 2. Select I-MISS
    sandbox.selectIssue('I-MISS', false);
    const sel1 = state.selectedIssueId;
    const role1 = sandbox.getActiveRole();
    const filter1 = state.filter;

    // 3. Switch to 'all' -> I-MISS is compatible, should remain selected
    sandbox.setActiveRole('all');
    const sel2 = state.selectedIssueId;

    // 4. Switch to 'extra' -> I-MISS is incompatible, should be CLEARED
    sandbox.setActiveRole('extra');
    const sel3 = state.selectedIssueId;

    // 5. Select I-EXTRA
    sandbox.selectIssue('I-EXTRA', false);
    const sel4 = state.selectedIssueId;
    const role4 = sandbox.getActiveRole();

    // 6. Switch to 'reference' -> Reference hides all issues, should be CLEARED
    sandbox.setActiveRole('reference');
    const sel5 = state.selectedIssueId;

    console.log(JSON.stringify({
      sel1, role1, filter1,
      sel2,
      sel3,
      sel4, role4,
      sel5
    }));
    """
    res = _run_ui_behavior(js)
    assert res["sel1"] == "I-MISS"
    assert res["role1"] == "missing"
    assert res["filter1"] == "missing"

    # Compatible with 'all' -> kept
    assert res["sel2"] == "I-MISS"

    # Incompatible with 'extra' -> cleared
    assert res["sel3"] is None

    # Selected extra
    assert res["sel4"] == "I-EXTRA"
    assert res["role4"] == "extra"

    # Incompatible with 'reference' -> cleared
    assert res["sel5"] is None


def test_behavioral_zoom_and_pan_preserved_across_all_filter_switches():
    """Verify zoom and pan coordinates survive filtering across all nine visual roles."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const viewport = getOrCreate('drawing-viewport');
    const svg = new MockElement('', 'svg');
    svg.setAttribute('viewBox', '150 250 500 400');
    viewport.replaceChildren(svg);

    const nav = sandbox.getViewerNav();
    nav.baseX = 0;
    nav.baseY = 0;
    nav.baseWidth = 1000;
    nav.baseHeight = 800;
    nav.currentX = 150;
    nav.currentY = 250;
    nav.currentWidth = 500;
    nav.currentHeight = 400;
    nav.scale = 2.0;

    const state = sandbox.getState();
    state.review = {
      issues: [
        { issue_id: 'I-01', visual_role: 'missing', finding_role: 'primary' },
        { issue_id: 'I-02', visual_role: 'inaccurate', finding_role: 'primary' }
      ]
    };

    const roles = ['all', 'reference', 'student', 'missing', 'extra', 'inaccurate', 'connectivity', 'warning', 'critical'];
    const results = [];

    for (const role of roles) {
      sandbox.setActiveRole(role);
      results.push({
        role,
        scale: nav.scale,
        currentX: nav.currentX,
        currentY: nav.currentY,
        currentWidth: nav.currentWidth,
        currentHeight: nav.currentHeight
      });
    }

    // Select issue
    sandbox.selectIssue('I-01', false);
    const selectScale = nav.scale;
    const selectX = nav.currentX;

    console.log(JSON.stringify({
      results,
      selectScale,
      selectX
    }));
    """
    res = _run_ui_behavior(js)
    for entry in res["results"]:
        assert entry["scale"] == 2.0
        assert entry["currentX"] == 150
        assert entry["currentY"] == 250
        assert entry["currentWidth"] == 500
        assert entry["currentHeight"] == 400

    assert res["selectScale"] == 2.0
    assert res["selectX"] == 150


def test_pdf_report_export_is_independent_of_browser_filter_and_retains_complete_legend():
    """Verify PDF export endpoint generates complete report with full legend regardless of filter."""
    ref = AUDIT / "00_reference_000-Simple.dxf"
    stud = AUDIT / "03_wrong_length_73C_80_units.dxf"

    # Generate review via /api/review
    resp = client.post(
        "/api/review",
        data={"allow_fallback": "true"},
        files={
            "reference": ("ref.dxf", ref.read_bytes(), "application/dxf"),
            "student": ("stud.dxf", stud.read_bytes(), "application/dxf")
        }
    )
    assert resp.status_code == 200
    review_id = resp.json()["review_id"]

    # Request PDF export
    pdf_resp = client.get(f"/api/reviews/{review_id}/report.pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"

    reader = PdfReader(io.BytesIO(pdf_resp.content))
    assert len(reader.pages) >= 3

    # Verify dedicated drawing page (Page 2) contains full vector legend with all 8 roles
    p2_text = reader.pages[1].extract_text() or ""
    assert "Drawing overlay legend" in p2_text
    for role_label in ["Reference", "Student", "Missing", "Extra", "Inaccurate", "Connectivity", "Warning", "Critical"]:
        assert role_label in p2_text
