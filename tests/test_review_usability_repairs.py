"""Independent regression cases for the usability review; all CAD is synthetic."""
import copy
import io
import json
from dataclasses import replace

import pytest
from pypdf import PdfReader

from app.finding_presentation import compact_finding_presentation
from app.pdf_report import generate_pdf
from app.main import REVIEW_SNAPSHOTS
from tests.test_pdf_export import _approve, _review, AUDIT, client
from tests.test_review_usability import _run_ui_behavior


def basic_snapshot():
    reference = AUDIT / '00_reference_000-Simple.dxf'
    _, approved = _approve(reference)
    result = _review(reference, AUDIT / '03_wrong_length_73C_80_units.dxf',
                     data={'rubric_id': approved['rubric_id']})
    assert result.status_code == 200
    return REVIEW_SNAPSHOTS.get(result.json()['review_id'])


def evidence_snapshot(count=60, words=12):
    snapshot = basic_snapshot()
    response = snapshot.review_response
    primary = next(i for i in response['issues'] if i['finding_role'] == 'primary')
    supporting = [dict(primary, issue_id=f'QA-S-{i:03d}', finding_role='supporting',
                       final_applied_contribution=0, technical_feedback='Synthetic evidence ' * words,
                       correction_guidance={'related_primary_issue_id': primary['issue_id']})
                  for i in range(count)]
    response['issues'] = [primary, *supporting]
    response['finding_counts']['supporting_findings'] = count
    response['finding_presentation'] = compact_finding_presentation(response['issues'])
    return replace(snapshot, review_response_json=json.dumps(response))


@pytest.mark.parametrize('count,words', [(60,12),(1,600)])
def test_dense_and_single_long_supporting_rows_paginate_without_losing_ids(count, words):
    snapshot = evidence_snapshot(count, words)
    for appendix in (False, True):
        pdf = generate_pdf(snapshot, include_appendix=appendix)
        assert pdf == generate_pdf(snapshot, include_appendix=appendix)
        reader = PdfReader(io.BytesIO(pdf))
        text = '\n'.join(page.extract_text() for page in reader.pages)
        for issue in snapshot.review_response['issues']:
            assert issue['issue_id'] in text
        assert 'Reviewed drawing' in reader.pages[1].extract_text()
        assert 'Drawing overlay legend' in reader.pages[1].extract_text()
        assert snapshot.review_response['issues'][0]['issue_id'] in reader.pages[2].extract_text()
        if appendix:
            assert 'Supporting evidence for primary issue:' in text


def test_capped_primary_and_essential_findings_never_disappear_from_default_policy():
    issues = [dict(issue_id=f'P-{i:03d}',finding_role='primary',severity='major',
                   category='missing_geometry',final_applied_contribution=0,deduction_status='capped')
              for i in range(45)]
    issues += [dict(issue_id='S-critical',finding_role='supporting',severity='critical'),
               dict(issue_id='U-blocking',finding_role='unsupported',blocking=True),
               dict(issue_id='S-scored',finding_role='supporting',final_applied_contribution=2),
               dict(issue_id='S-optional',finding_role='supporting',severity='minor'),
               dict(issue_id='U-optional',finding_role='unsupported',severity='minor')]
    original = copy.deepcopy(issues)
    presentation = compact_finding_presentation(issues)
    assert set(presentation['default_issue_ids']) == {i['issue_id'] for i in issues[:-2]}
    assert presentation['total_displayed_count'] + presentation['total_summarized_count'] == 45
    assert issues == original
    result = _run_ui_behavior('''
    const {sandbox,getOrCreate}=createHarness();
    sandbox.getState().review=REVIEW;
    sandbox.renderIssueList();
    console.log(JSON.stringify({ids:getOrCreate('issue-list').children.map(g=>g.children[0].dataset.issueId)}));
    '''.replace('REVIEW',json.dumps({'issues':issues,'finding_presentation':presentation})))
    assert set(result['ids']) == set(presentation['default_issue_ids'])


def test_pdf_essential_notices_survive_without_appendix_and_old_presentation_fields():
    snapshot = basic_snapshot()
    response = snapshot.review_response
    original = response['issues'][0]
    response['issues'] += [dict(original,issue_id='ESSENTIAL-S',finding_role='supporting',severity='critical',final_applied_contribution=0),
                           dict(original,issue_id='ESSENTIAL-U',finding_role='unsupported',blocking=True,final_applied_contribution=0),
                           dict(original,issue_id='INFO-1',finding_role='informational',final_applied_contribution=0)]
    response.pop('finding_presentation')  # Backward-compatible snapshot fallback.
    response['unsupported_entities']={'student':[{'entity_type':'HATCH','layer':'QA','handle':'QA-H'}],'reference':[]}
    response['finding_counts']['unsupported_entities']=1
    snapshot = replace(snapshot,review_response_json=json.dumps(response))
    text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(generate_pdf(snapshot))).pages)
    assert all(i['issue_id'] in text for i in response['issues'])
    assert 'not automatically assessed' in text


def test_pdf_export_options_do_not_reuse_wrong_variant_or_modify_snapshot():
    snapshot = basic_snapshot()
    original = snapshot.review_response_json
    uri = f'/api/reviews/{snapshot.review_id}/report.pdf'
    plain = client.get(uri)
    assert plain.headers['cache-control'] == 'no-store'
    appendix = client.get(uri+'?include_appendix=true')
    assert plain.content != appendix.content
    assert plain.content == client.get(uri+'?include_appendix=false').content
    assert appendix.content == client.get(uri+'?include_appendix=true').content
    assert client.get(uri+'?include_appendix=invalid').status_code == 422
    assert snapshot.review_response_json == original


def test_short_horizontal_issue_can_be_located_without_changing_aspect_ratio():
    result = _run_ui_behavior('''
    const {sandbox,getOrCreate}=createHarness();
    const viewport=getOrCreate('drawing-viewport');
    const svg=new MockElement('','svg');
    const line=new MockElement('','line');
    line.getBBox=()=>({x:10,y:20,width:50,height:0});
    svg.querySelector=()=>line;
    viewport.querySelector=()=>svg;
    viewport.replaceChildren(svg);
    const nav=sandbox.getViewerNav();
    nav.baseWidth=1000;nav.baseHeight=800;
    sandbox.locateIssueInViewer('P-1');
    console.log(JSON.stringify({scale:nav.scale,ratio:nav.currentWidth/nav.currentHeight,cx:nav.currentX+nav.currentWidth/2,cy:nav.currentY+nav.currentHeight/2}));
    ''')
    assert result['scale'] > 1
    assert result['ratio'] == pytest.approx(1.25)
    assert (result['cx'],result['cy']) == (35,20)
