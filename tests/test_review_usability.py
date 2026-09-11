"""Tests for review and UI usability improvements (#3, #4, #8, #9)."""
from tests.synthetic_data import fixture_root, samples_root
import io
import json
from pathlib import Path
import subprocess
from html.parser import HTMLParser

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from app.main import app

client = TestClient(app)
AUDIT = fixture_root() / "simple_audit"


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


def test_viewer_navigation_toolbar_structure_and_accessibility():
    """Verify Issue #8 navigation toolbar is present and properly attributed."""
    response, parser = page()
    required_ids = {
        "viewer-zoom-in",
        "viewer-zoom-out",
        "viewer-reset",
        "viewer-locate-issue",
        "viewer-expand",
        "viewer-exit-expand",
    }
    assert required_ids <= parser.elements.keys()

    for btn_id in required_ids:
        tag, attrs = parser.elements[btn_id]
        assert tag == "button"
        assert attrs.get("type") == "button"
        assert "aria-label" in attrs
        assert "title" in attrs

    assert "disabled" in parser.elements["viewer-locate-issue"][1]
    assert "hidden" in parser.elements["viewer-exit-expand"][1]


def test_setup_summary_and_edit_assignment_structure():
    """Verify setup summary card and 'Edit assignment' controls exist."""
    response, parser = page()
    summary_ids = {
        "setup-summary",
        "setup-summary-heading",
        "edit-setup",
        "summary-reference-name",
        "summary-assignment-title",
        "summary-assignment-type",
        "summary-placement-policy",
    }
    assert summary_ids <= parser.elements.keys()
    assert "hidden" in parser.elements["setup-summary"][1]
    assert parser.elements["edit-setup"][0] == "button"


def test_unsupported_entities_notice_structure():
    """Verify Issue #4 unsupported entities notice banner elements."""
    response, parser = page()
    notice_ids = {
        "unsupported-notice",
        "unsupported-notice-title",
        "unsupported-notice-text",
        "unsupported-notice-details",
        "unsupported-notice-list",
    }
    assert notice_ids <= parser.elements.keys()
    assert "hidden" in parser.elements["unsupported-notice"][1]


def test_results_header_download_and_appendix_toggles():
    """Verify quick PDF download and appendix options in results bar and setup."""
    response, parser = page()
    export_ids = {
        "download-report-header",
        "include-appendix-header",
        "include-appendix",
        "toggle-technical-details",
    }
    assert export_ids <= parser.elements.keys()
    assert parser.elements["download-report-header"][0] == "button"
    assert parser.elements["include-appendix-header"][1].get("type") == "checkbox"
    assert parser.elements["include-appendix"][1].get("type") == "checkbox"
    assert parser.elements["toggle-technical-details"][1].get("type") == "checkbox"


def test_behavioral_viewer_zoom_and_reset_in_node_vm():
    """Verify Issue #8 zoom math, bounds clamping, and reset via Node VM."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const viewport = getOrCreate('drawing-viewport');

    const svg = new MockElement('', 'svg');
    svg.setAttribute('viewBox', '0 0 1000 800');
    viewport.replaceChildren(svg);

    const nav = sandbox.getViewerNav();
    nav.baseX = 0;
    nav.baseY = 0;
    nav.baseWidth = 1000;
    nav.baseHeight = 800;
    nav.currentX = 0;
    nav.currentY = 0;
    nav.currentWidth = 1000;
    nav.currentHeight = 800;
    nav.scale = 1.0;

    const initialVb = svg.getAttribute('viewBox');

    // Zoom in (1.25x)
    sandbox.zoomViewer(1.25);
    const zoomInScale = nav.scale;
    const zoomInVb = svg.getAttribute('viewBox');
    const zoomInWidth = nav.currentWidth;

    // Zoom in repeatedly to test upper bound clamping (max 20.0)
    for (let i = 0; i < 20; i++) sandbox.zoomViewer(2.0);
    const maxScale = nav.scale;

    // Reset view
    sandbox.resetViewerNav();
    const resetScale = nav.scale;
    const resetVb = svg.getAttribute('viewBox');

    // Zoom out repeatedly to test lower bound clamping (min 0.2)
    for (let i = 0; i < 20; i++) sandbox.zoomViewer(0.5);
    const minScale = nav.scale;

    console.log(JSON.stringify({
      initialVb,
      zoomInScale,
      zoomInVb,
      zoomInWidthSmaller: zoomInWidth < 1000,
      maxScale,
      resetScale,
      resetVb,
      minScale
    }));
    """
    res = _run_ui_behavior(js)
    assert res["initialVb"] == "0 0 1000 800"
    assert res["zoomInScale"] == 1.25
    assert res["zoomInWidthSmaller"] is True
    assert res["maxScale"] == 20.0
    assert res["resetScale"] == 1.0
    assert res["resetVb"] == "0 0 1000 800"
    assert res["minScale"] == 0.2


def test_behavioral_view_preservation_on_mode_and_selection():
    """Verify selecting an issue or switching view mode preserves zoom and pan."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const viewport = getOrCreate('drawing-viewport');
    const svg = new MockElement('', 'svg');
    svg.setAttribute('viewBox', '100 50 600 480');
    viewport.replaceChildren(svg);

    const nav = sandbox.getViewerNav();
    nav.baseX = 0;
    nav.baseY = 0;
    nav.baseWidth = 1000;
    nav.baseHeight = 800;
    nav.currentX = 100;
    nav.currentY = 50;
    nav.currentWidth = 600;
    nav.currentHeight = 480;
    nav.scale = 1.667;

    const state = sandbox.getState();
    state.review = {
      issues: [{
        issue_id: 'I-01',
        category: 'geometry',
        severity: 'critical',
        visual_role: 'missing',
        finding_role: 'primary',
        technical_feedback: 'Missing required line'
      }]
    };

    // 1. Switch to student-only view
    sandbox.setDrawingViewMode('student');
    const studentVb = svg.getAttribute('viewBox');
    const studentScale = nav.scale;

    // 2. Switch back to review comparison
    sandbox.setDrawingViewMode('review');
    const reviewVb = svg.getAttribute('viewBox');

    // 3. Select issue
    sandbox.selectIssue('I-01', false);
    const selectVb = svg.getAttribute('viewBox');
    const selectScale = nav.scale;

    console.log(JSON.stringify({
      studentVb,
      studentScale,
      reviewVb,
      selectVb,
      selectScale
    }));
    """
    res = _run_ui_behavior(js)
    assert res["studentVb"] == "100 50 600 480"
    assert res["reviewVb"] == "100 50 600 480"
    assert res["selectVb"] == "100 50 600 480"
    assert abs(res["studentScale"] - 1.667) < 0.001
    assert abs(res["selectScale"] - 1.667) < 0.001


def test_behavioral_setup_summary_and_collapse_toggle():
    """Verify setup summary population and collapse toggle."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const setupCol = getOrCreate('setup-col', 'div');
    setupCol.className = 'setup-column';
    const summaryCard = getOrCreate('setup-summary');
    const editBtn = getOrCreate('edit-setup');

    const state = sandbox.getState();
    state.reference = { name: 'Assignment-01.dxf' };
    state.provisionalRubric = {
      assignment_title: 'Bracket Floorplate',
      assignment_type: 'Mechanical Component',
      normalization_mode: 'translation'
    };

    sandbox.updateSetupSummary();
    const populatedHidden = summaryCard.hidden;
    const refName = getOrCreate('summary-reference-name').textContent;
    const title = getOrCreate('summary-assignment-title').textContent;
    const type = getOrCreate('summary-assignment-type').textContent;
    const policy = getOrCreate('summary-placement-policy').textContent;

    // Toggle collapse
    sandbox.setSetupCollapsed(true);
    const editBtnText = editBtn.textContent;

    sandbox.setSetupCollapsed(false);
    const editBtnExpandedText = editBtn.textContent;

    console.log(JSON.stringify({
      populatedHidden,
      refName,
      title,
      type,
      policy,
      editBtnText,
      editBtnExpandedText
    }));
    """
    res = _run_ui_behavior(js)
    assert res["populatedHidden"] is False
    assert res["refName"] == "Assignment-01.dxf"
    assert res["title"] == "Bracket Floorplate"
    assert res["type"] == "Mechanical Component"
    assert "Translation-tolerant" in res["policy"]
    assert res["editBtnText"] == "Edit assignment"
    assert res["editBtnExpandedText"] == "Hide setup"


def test_behavioral_unsupported_notice_banner_rendering():
    """Verify Issue #4 unsupported entities notice summarizes noise cleanly."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const banner = getOrCreate('unsupported-notice');
    const textEl = getOrCreate('unsupported-notice-text');
    const listEl = getOrCreate('unsupported-notice-list');

    const reviewWithUnsupported = {
      finding_presentation: {
        unsupported_summary: {
          total_count: 5,
          notice: '5 unsupported entities (HATCH, LEADER) were detected and safely ignored.',
          groups: [
            { source: 'student', entity_type: 'HATCH', count: 3, layers: ['HATCHES'] },
            { source: 'student', entity_type: 'LEADER', count: 2, layers: ['NOTES'] }
          ]
        }
      }
    };

    sandbox.renderUnsupportedNotice(reviewWithUnsupported);
    const bannerHidden = banner.hidden;
    const bannerNoticeText = textEl.textContent;
    const groupCount = listEl.children.length;
    const group1Text = listEl.children[0].allText();

    sandbox.renderUnsupportedNotice({ finding_presentation: { unsupported_summary: { total_count: 0 } } });
    const cleanBannerHidden = banner.hidden;

    console.log(JSON.stringify({
      bannerHidden,
      bannerNoticeText,
      groupCount,
      group1Text,
      cleanBannerHidden
    }));
    """
    res = _run_ui_behavior(js)
    assert res["bannerHidden"] is False
    assert "5 unsupported entities" in res["bannerNoticeText"]
    assert res["groupCount"] == 2
    assert "HATCH" in res["group1Text"]
    assert res["cleanBannerHidden"] is True


def test_behavioral_collapsible_supporting_findings_under_primary():
    """Verify Issue #3 collapsible supporting topology findings under primary cards."""
    js = """
    const { sandbox, getOrCreate } = createHarness();
    const issueList = getOrCreate('issue-list');

    const state = sandbox.getState();
    state.review = {
      issues: [
        {
          issue_id: 'PRIM-01',
          category: 'geometry',
          severity: 'major',
          visual_role: 'inaccurate',
          finding_role: 'primary',
          technical_feedback: 'Wall line shifted by 10mm',
          applied_deduction: 5,
          correction_guidance: { primary_command: 'MOVE' }
        },
        {
          issue_id: 'SUP-01',
          category: 'topology',
          severity: 'minor',
          visual_role: 'connectivity',
          finding_role: 'supporting',
          technical_feedback: 'Endpoint disconnected from corner'
        }
      ],
      finding_presentation: {
        compacted: true,
        displayed_issue_ids: ['PRIM-01'],
        linked_supporting_by_primary: {
          'PRIM-01': ['SUP-01']
        },
        unlinked_supporting_ids: []
      }
    };

    sandbox.renderIssueList();
    const card = issueList.children[0];
    const allCardText = card.allText();

    console.log(JSON.stringify({
      cardCount: issueList.children.length,
      cardText: allCardText
    }));
    """
    res = _run_ui_behavior(js)
    assert res["cardCount"] == 1
    assert "PRIM-01" in res["cardText"]
    assert "Action: MOVE" in res["cardText"]
    assert "1 supporting finding(s)" in res["cardText"]
    assert "SUP-01: Endpoint disconnected from corner" in res["cardText"]
    assert "undefined" not in res["cardText"]


def test_pdf_report_dedicated_drawing_page_and_optional_appendix():
    """Verify Issue #9 dedicated A4 drawing page and optional technical appendix."""
    ref_file = AUDIT / "00_reference_000-Simple.dxf"
    student_file = AUDIT / "03_wrong_length_73C_80_units.dxf"

    # Suggest and approve rubric
    sug_res = client.post(
        "/api/rubric/suggest",
        files={"reference": ("ref.dxf", ref_file.read_bytes(), "application/dxf")},
    )
    assert sug_res.status_code == 200
    sug = sug_res.json()
    rubric = sug["rubric"]
    rubric["assignment_type"] = sug["suggested_assignment_type"]
    app_res = client.post(
        "/api/rubric/approve",
        json={"reference_id": sug["reference_id"], "rubric": rubric},
    )
    assert app_res.status_code == 200
    rubric_id = app_res.json()["rubric_id"]

    # Run review
    rev_res = client.post(
        "/api/review",
        data={"rubric_id": rubric_id},
        files={
            "reference": ("ref.dxf", ref_file.read_bytes(), "application/dxf"),
            "student": ("stud.dxf", student_file.read_bytes(), "application/dxf"),
        },
    )
    assert rev_res.status_code == 200
    review_id = rev_res.json()["review_id"]

    # 1. Standard PDF without appendix
    pdf_standard = client.get(f"/api/reviews/{review_id}/report.pdf")
    assert pdf_standard.status_code == 200
    assert pdf_standard.headers["content-type"] == "application/pdf"
    reader_standard = PdfReader(io.BytesIO(pdf_standard.content))
    assert len(reader_standard.pages) == 3
    text_p1 = reader_standard.pages[0].extract_text()
    assert "Drawing Assessment Report" in text_p1
    assert "Placement policy" in text_p1
    text_p2 = reader_standard.pages[1].extract_text()
    assert "Reviewed drawing" in text_p2
    assert "Drawing overlay legend" in text_p2

    # 2. PDF with technical appendix
    pdf_appendix = client.get(f"/api/reviews/{review_id}/report.pdf?include_appendix=true")
    assert pdf_appendix.status_code == 200
    reader_appendix = PdfReader(io.BytesIO(pdf_appendix.content))
    assert len(reader_appendix.pages) == 4
    text_p4 = reader_appendix.pages[3].extract_text()
    assert "Technical Appendix" in text_p4
