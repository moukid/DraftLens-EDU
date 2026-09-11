/* Optional live QA: see docs/review-usability-review.md. No CAD files are stored. */
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require(process.env.DRAFTLENS_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.DRAFTLENS_QA_URL || 'http://127.0.0.1:8766';
if (!['127.0.0.1', 'localhost'].includes(new URL(url).hostname)) throw new Error('QA requires a loopback server');
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'draftlens-usability-qa-'));
const fixtures = JSON.parse(execFileSync(process.env.DRAFTLENS_QA_PYTHON || 'python', ['-B', '-c', `
import json,base64
from tests.synthetic_data import fixture_root
root=fixture_root()/'simple_audit'
print(json.dumps({key:base64.b64encode((root/name).read_bytes()).decode() for key,name in [('reference','00_reference_000-Simple.dxf'),('student','03_wrong_length_73C_80_units.dxf')]}))
`], {cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
const upload = key => ({name:`synthetic-${key}.dxf`,mimeType:'application/dxf',buffer:Buffer.from(fixtures[key],'base64')});
const checks = [];
function pass(name) {checks.push(name); console.log('PASS:',name);}
(async()=>{
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1366,height:768}});
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.locator('#reference-file').setInputFiles(upload('reference'));
    await page.locator('#rubric-editor').waitFor({state:'visible'});
    await page.locator('#assignment-type').selectOption('Other');
    await page.locator('#approve-rubric').click();
    await page.waitForFunction(()=>Boolean(getState().rubricId));
    assert.equal(await page.locator('#student-file').isVisible(),true);
    await page.locator('#student-file').setInputFiles(upload('student'));
    await page.locator('#run-review').click();
    await page.waitForFunction(()=>Boolean(getState().review && getState().review.report_available));
    const original = await page.evaluate(()=>JSON.parse(JSON.stringify(getState().review)));
    assert.equal(original.score,97);
    pass('reference -> approval -> student upload -> authoritative review');
    await page.screenshot({path:path.join(artifacts,'desktop.png'),fullPage:true});

    const viewport = page.locator('#drawing-viewport');
    await viewport.scrollIntoViewIfNeeded();
    const initial = await page.locator('#drawing-viewport svg').getAttribute('viewBox');
    await page.locator('#viewer-zoom-in').click();
    assert.equal(await page.evaluate(()=>getViewerNav().scale),1.25);
    await page.locator('#issue-list .issue-card').first().click();
    assert.equal(await page.evaluate(()=>getViewerNav().scale),1.25);
    await page.locator('#view-student-only').click();
    assert.equal(await page.locator('#student-only-status').isVisible(),true);
    await page.locator('#view-review-comparison').click();
    assert.equal(await page.evaluate(()=>getViewerNav().scale),1.25);
    await page.locator('#viewer-reset').click();
    assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),initial);
    pass('button zoom, selection/mode preservation and fit');

    for (const size of [{width:1366,height:768},{width:760,height:900}]) {
      await page.setViewportSize(size);
      await viewport.scrollIntoViewIfNeeded();
      const box=await viewport.boundingBox();
      // WheelEvent client coordinates are integral in Chromium.
      const cursor={x:Math.round(box.x+box.width*.35),y:Math.round(box.y+box.height*.6)};
      const anchor=()=>page.evaluate(({x,y})=>{const s=document.querySelector('#drawing-viewport svg');const p=s.createSVGPoint();p.x=x;p.y=y;const a=p.matrixTransform(s.getScreenCTM().inverse());return {x:a.x,y:a.y};},cursor);
      const before=await anchor();
      await page.mouse.move(cursor.x,cursor.y);
      const oldScale=await page.evaluate(()=>getViewerNav().scale);
      await page.mouse.wheel(0,-100);
      await page.waitForFunction(s=>getViewerNav().scale>s,oldScale);
      const after=await anchor();
      assert.ok(Math.hypot(after.x-before.x,after.y-before.y)<1e-4,JSON.stringify({before,after}));
      const panBefore=await anchor();
      const selection=await page.evaluate(()=>getState().selectedIssueId);
      await page.mouse.down();
      await page.mouse.move(cursor.x+45,cursor.y+30,{steps:5});
      await page.mouse.up();
      const panAfter=await page.evaluate(({x,y})=>{const s=document.querySelector('#drawing-viewport svg');const p=s.createSVGPoint();p.x=x+45;p.y=y+30;const a=p.matrixTransform(s.getScreenCTM().inverse());return{x:a.x,y:a.y};},cursor);
      assert.ok(Math.hypot(panAfter.x-panBefore.x,panAfter.y-panBefore.y)<1e-4,JSON.stringify({panBefore,panAfter}));
      assert.equal(await page.evaluate(()=>getState().selectedIssueId),selection);
      pass(`wheel anchor and drag pan without selection at ${size.width}x${size.height}`);
    }
    await viewport.focus();
    await page.keyboard.press('+');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),initial);
    await page.locator('#viewer-expand').click();
    assert.equal(await page.locator('#viewer-exit-expand').isVisible(),true);
    await page.locator('#viewer-zoom-in').focus();
    await page.keyboard.press('Shift+Tab');
    assert.equal(await viewport.evaluate(el=>el===document.activeElement),true);
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#viewer-zoom-in').evaluate(el=>el===document.activeElement),true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#viewer-expand').isVisible(),true);
    pass('keyboard zoom/pan/fit and expanded-mode Escape');

    const reportPath=`${url}/api/reviews/${original.review_id}/report.pdf`;
    const standard=await page.request.get(reportPath);
    const standardBytes=await standard.body();
    assert.equal(standard.status(),200);
    assert.equal(standard.headers()['content-type'],'application/pdf');
    await page.locator('#include-appendix-header').check();
    assert.equal(await page.locator('#include-appendix').isChecked(),true);
    const downloadPromise=page.waitForEvent('download');
    await page.locator('#download-report-header').click();
    const download=await downloadPromise;
    assert.equal(await download.failure(),null);
    const appendix=await page.request.get(reportPath+'?include_appendix=true');
    const repeated=await page.request.get(reportPath);
    assert.deepEqual(await repeated.body(),standardBytes);
    assert.notDeepEqual(await appendix.body(),standardBytes);
    pass('real download, synchronized appendix option, deterministic option isolation');
    const currentUrl=page.url();
    let releaseError;
    const holdError=new Promise(resolve=>{releaseError=resolve;});
    await page.route('**/report.pdf*',async route=>{
      await holdError;
      await route.fulfill({status:410,contentType:'application/json',body:JSON.stringify({detail:'Synthetic report expired. Generate a new review.'})});
    });
    await page.locator('#download-report-header').click();
    assert.equal(await page.locator('#download-report-header').isDisabled(),true);
    releaseError();
    await page.waitForFunction(()=>!getState().reportLoading);
    assert.equal(page.url(),currentUrl);
    assert.equal(await page.locator('#review-results').isVisible(),true);
    assert.ok((await page.locator('#api-error').textContent()).includes('expired'));
    await page.unroute('**/report.pdf*');
    pass('download loading and expired-report errors preserve the review');

    await page.locator('#edit-setup').click();
    await page.locator('#assignment-title').fill('Synthetic revised assignment');
    assert.equal(await page.evaluate(()=>getState().rubricId),null);
    assert.equal(await page.locator('#run-review').isDisabled(),true);
    await page.locator('#approve-rubric').click();
    await page.waitForFunction(()=>Boolean(getState().rubricId));
    for(let n=0;n<3;n++) {
      await page.locator('#run-review').click();
      await page.waitForFunction(()=>Boolean(getState().review && !getState().loading));
      assert.equal(await page.evaluate(()=>getViewerNav().scale),1);
      await page.locator('#viewer-zoom-in').click();
      assert.equal(await page.evaluate(()=>getViewerNav().scale),1.25);
    }
    pass('edit requires reapproval; repeated reviews reset navigation without duplicate handlers');

    // Exercise server-shaped edge cases without altering grades or persisted snapshots.
    await page.evaluate(()=>{
      const r=getState().review;
      const p=r.issues.find(i=>i.finding_role==='primary');
      const s={...p,issue_id:'QA-SUP',finding_role:'supporting',severity:'minor',final_applied_contribution:0,technical_feedback:'Synthetic linked evidence'};
      const u={...s,issue_id:'QA-UNSUPPORTED',finding_role:'unsupported',category:'unsupported_entity'};
      const c={...u,issue_id:'QA-CRITICAL',severity:'critical',technical_feedback:'Manual assessment required'};
      r.issues=[p,s,u,c];
      r.finding_presentation={compacted:false,default_issue_ids:[p.issue_id,c.issue_id],linked_supporting_by_primary:{[p.issue_id]:[s.issue_id]},unlinked_supporting_ids:[],unsupported_summary:{total_count:2,notice:'Unsupported DXF content was not automatically assessed.',groups:[{source:'student',entity_type:'HATCH',count:2,layers:['SYNTHETIC']}]}};
      renderIssueList();renderUnsupportedNotice(r);
    });
    assert.equal(await page.locator('#issue-list .issue-card').count(),2);
    assert.equal(await page.locator('#issue-list button button').count(),0);
    await page.locator('.supporting-findings-collapse summary').click();
    await page.getByRole('button',{name:'QA-SUP: Synthetic linked evidence'}).click();
    assert.equal(await page.locator('#feedback-id').textContent(),'QA-SUP');
    assert.equal(await page.locator('#unsupported-notice').isVisible(),true);
    assert.ok(!(await page.locator('#issue-list').textContent()).includes('undefined'));
    await page.locator('#toggle-technical-details').check();
    assert.equal(await page.locator('#issue-list .issue-card').count(),4);
    pass('support links, valid button structure, critical visibility and optional raw findings');

    for (const width of [1366,760,390]) {
      await page.setViewportSize({width,height:768});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow ${width}`);
      await page.locator('.drawing-panel').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(artifacts,`drawing-${width}.png`)});
    }
    pass('desktop, narrow and mobile layout without horizontal overflow');
    await page.evaluate(()=>renderSafeSvg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><script>alert(1)</script><rect x="0" y="0" width="10" height="10" onclick="alert(1)"/><foreignObject>unsafe</foreignObject></svg>'));
    assert.equal(await page.locator('#drawing-viewport script,#drawing-viewport foreignObject,#drawing-viewport [onclick]').count(),0);
    assert.deepEqual(errors,[]);
    pass('SVG sanitization and no uncaught browser errors');
    console.log(JSON.stringify({checks:checks.length,artifacts},null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);console.error('QA artifacts:',artifacts);process.exitCode=1;});
