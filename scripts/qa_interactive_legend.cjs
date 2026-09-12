/* Live production SVG regression QA. See docs/review-usability-handoff.md. */
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require(process.env.DRAFTLENS_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.DRAFTLENS_QA_URL || 'http://127.0.0.1:8766';
if (!['localhost','127.0.0.1'].includes(new URL(url).hostname)) throw Error('Loopback only');
const destination = fs.mkdtempSync(path.join(os.tmpdir(), 'draftlens-legend-qa-'));
const fixture = JSON.parse(execFileSync(process.env.DRAFTLENS_QA_PYTHON || 'python',
  ['-B','-m','tests.legend_synthetic'], {cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
const roles = ['all','reference','student','missing','extra','inaccurate','connectivity','warning','critical'];
const failures = [], passes = [];
async function check(name, fn) {
  try {await fn(); passes.push(name); console.log('PASS:',name);}
  catch(error) {failures.push({name,error:String(error)}); console.log('FAIL:',name,String(error));}
}
(async()=>{
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1366,height:768}});
    const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
    await page.goto(url);
    const upload = key=>({name:`synthetic-${key}.dxf`,mimeType:'application/dxf',buffer:Buffer.from(fixture.uploads[key],'base64')});
    await page.locator('#reference-file').setInputFiles(upload('reference'));
    await page.locator('#rubric-editor').waitFor({state:'visible'});
    await page.locator('#assignment-type').selectOption('Other');
    await page.locator('#approve-rubric').click();
    await page.waitForFunction(()=>Boolean(getState().rubricId));
    await page.locator('#student-file').setInputFiles(upload('student'));
    await page.locator('#run-review').click();
    await page.waitForFunction(()=>Boolean(getState().review?.report_available));
    const realReview = await page.evaluate(()=>JSON.parse(JSON.stringify(getState().review)));
    console.log('Dense real review:',realReview.score,realReview.issues.length,'issues');
    const uri=`${url}/api/reviews/${realReview.review_id}/report.pdf`;
    const standard=await (await page.request.get(uri)).body();
    const technical=await (await page.request.get(uri+'?include_appendix=true')).body();
    await check('real restrictive-filter downloads preserve complete PDF bytes and review data',async()=>{
      await page.locator('[data-filter="missing"]').click();
      for (const [appendix,expected] of [[false,standard],[true,technical]]) {
        await page.locator('#include-appendix-header').setChecked(appendix);
        const pending=page.waitForEvent('download');
        await page.locator('#download-report-header').click();
        const download=await pending;
        const file=path.join(destination,appendix?'technical.pdf':'standard.pdf');
        await download.saveAs(file); assert.deepEqual(fs.readFileSync(file),expected);
      }
      assert.deepEqual(await page.evaluate(()=>getState().review),realReview);
    });
    const loadFixture=()=>page.evaluate(r=>{getState().review=structuredClone(r);renderResults(getState().review);},fixture.review);
    const legend=role=>page.locator(`#overlay-legend button[data-role="${role}"]`);
    const visibleShapes=()=>page.evaluate(()=>Array.from(document.querySelectorAll('#drawing-viewport svg line,#drawing-viewport svg path,#drawing-viewport svg circle,#drawing-viewport svg ellipse,#drawing-viewport svg rect,#drawing-viewport svg text,#drawing-viewport svg polyline')).filter(el=>{
      for(let n=el;n && n.tagName.toLowerCase()!=='svg';n=n.parentElement) {
        if(getComputedStyle(n).display==='none' || getComputedStyle(n).visibility==='hidden') return false;
      }
      return true;
    }).map(el=>({role:el.closest('[data-role]')?.getAttribute('data-role') || el.closest('svg > g[data-layer]')?.getAttribute('data-layer'),cls:el.getAttribute('class'),id:el.closest('[data-issue-id]')?.getAttribute('data-issue-id')})));
    await loadFixture();
    await check('all nine legend controls exclusively show authoritative geometry, including CAD layer-name collisions',async()=>{
      for (const role of roles) {
        await legend(role).click();
        const shapes=await visibleShapes();
        const expected=role==='all'?327:role==='reference'||role==='student'?160:role==='inaccurate'?2:1;
        assert.equal(shapes.length,expected,`${role}: unexpected visible geometry count`);
        assert.ok(role==='all'||shapes.every(s=>s.role===role),`${role} leaks unrelated graphics`);
        assert.equal(await legend(role).getAttribute('aria-pressed'),'true');
        assert.equal(await page.locator('#overlay-legend [aria-pressed="true"]').count(),1);
      }
    });
    await loadFixture();
    await check('both filter directions and explicit support-role discovery',async()=>{
      for (const role of roles.slice(3)) {
        await page.locator(`[data-filter="${role}"]`).click();
        assert.equal(await legend(role).getAttribute('aria-pressed'),'true');
        assert.ok(await page.locator('#issue-list .issue-card').count()>0,role+' has indications but no findings');
        await legend('all').click(); await legend(role).click();
        assert.equal(await page.locator(`[data-filter="${role}"]`).getAttribute('aria-pressed'),'true');
      }
      for (const role of ['reference','student']) {
        await legend(role).click(); assert.equal(await page.locator('[data-filter="all"]').getAttribute('aria-pressed'),'true');
      }
      await page.locator('[data-filter="all"]').click(); assert.equal(await legend('all').getAttribute('aria-pressed'),'true');
    });
    await loadFixture();
    await check('individual selection preserves focus, selection, and navigation',async()=>{
      await page.locator('#viewer-zoom-in').click();
      const before=await page.locator('#drawing-viewport svg').getAttribute('viewBox');
      await page.locator('#issue-list .issue-card[data-issue-id="QA-inaccurate"]').focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(()=>document.activeElement?.dataset.issueId),'QA-inaccurate');
      assert.equal(await legend('inaccurate').getAttribute('aria-pressed'),'true');
      assert.equal(await page.locator('#feedback-id').textContent(),'QA-inaccurate');
      assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),before);
      assert.equal((await visibleShapes()).filter(s=>s.id==='QA-inaccurate').length,2);
      await legend('extra').click();
      assert.equal(await page.evaluate(()=>getState().selectedIssueId),null);
      assert.equal(await page.locator('#feedback-detail').isVisible(),false);
    });
    await loadFixture();
    await check('linked supporting evidence survives role transition and technical toggle',async()=>{
      const detail=page.locator('.issue-group').filter({has:page.locator('[data-issue-id="QA-inaccurate"]')}).locator('details');
      await detail.locator('summary').click();
      await detail.getByRole('button',{name:/QA-connectivity:/}).click();
      assert.equal(await legend('connectivity').getAttribute('aria-pressed'),'true');
      assert.equal(await page.locator('#issue-list .issue-card[data-issue-id="QA-connectivity"]').count(),1);
      assert.equal(await page.evaluate(()=>document.activeElement?.dataset.issueId),'QA-connectivity');
      await page.locator('#toggle-technical-details').check();
      await page.locator('#toggle-technical-details').uncheck();
      assert.equal(await page.locator('#issue-list .issue-card[data-issue-id="QA-connectivity"]').count(),1);
    });
    await loadFixture();
    await check('critical/blocking and unsupported notices remain outside every filter',async()=>{
      await legend('missing').click();
      assert.equal(await page.locator('#unsupported-notice').isVisible(),true);
      const notices=page.locator('#assessment-notices');
      assert.equal(await notices.isVisible(),true);
      assert.match(await notices.textContent(),/QA-critical/); assert.match(await notices.textContent(),/QA-warning/);
    });
    await loadFixture();
    await check('expanded keyboard traversal reaches every legend button without escaping',async()=>{
      await page.locator('#viewer-expand').click();
      await page.locator('#drawing-viewport').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(()=>document.activeElement?.dataset.role),'all');
      for (let i=1;i<roles.length;i++) {
        await page.keyboard.press('Tab'); assert.equal(await page.evaluate(()=>document.activeElement?.dataset.role),roles[i]);
      }
      await page.keyboard.press('Tab'); assert.equal(await page.evaluate(()=>document.activeElement.id),'viewer-zoom-in');
      await page.keyboard.press('Shift+Tab'); assert.equal(await page.evaluate(()=>document.activeElement?.dataset.role),'critical');
    });
    await page.keyboard.press('Escape');
    await loadFixture();
    await check('nested same-role wrappers preserve expected/actual; hidden geometry cannot intercept clicks',async()=>{
      await page.evaluate(()=>{
        const svg=document.querySelector('#drawing-viewport svg');
        const issue=svg.querySelector('[data-role="inaccurate"]');
        const wrapper=document.createElementNS(svg.namespaceURI,'g');
        issue.replaceWith(wrapper); wrapper.append(issue);
      });
      await legend('inaccurate').click();
      assert.equal((await visibleShapes()).length,2);
      const hiddenHit=await page.evaluate(()=>{
        const node=document.querySelector('svg > g[data-layer="student"] [data-entity-id]');
        const b=node.getBoundingClientRect();
        return document.elementsFromPoint(b.x+b.width/2,b.y+b.height/2).includes(node);
      });
      assert.equal(hiddenHit,false);
    });
    await loadFixture();
    await check('real SVG pointer selection and hidden-shape hit testing',async()=>{
      await legend('all').click();
      await page.locator('#drawing-viewport').scrollIntoViewIfNeeded();
      const point=await page.evaluate(()=>{
        const line=document.querySelector('g[data-role="inaccurate"] .inaccurate-actual');
        const p=line.getPointAtLength(line.getTotalLength()/2);
        const screen=new DOMPoint(p.x,p.y).matrixTransform(line.getScreenCTM());
        return {x:screen.x,y:screen.y};
      });
      await page.mouse.click(point.x,point.y);
      assert.equal(await page.evaluate(()=>getState().selectedIssueId),'QA-inaccurate');
      assert.equal(await legend('inaccurate').getAttribute('aria-pressed'),'true');
      await legend('missing').click();
      await page.locator('#drawing-viewport').scrollIntoViewIfNeeded();
      const hit=await page.evaluate(()=>{
        const svg=document.querySelector('#drawing-viewport svg');
        const line=svg.querySelector('g[data-role="inaccurate"] .inaccurate-actual');
        const p=line.getPointAtLength(line.getTotalLength()/2);
        const screen=new DOMPoint(p.x,p.y).matrixTransform(svg.getScreenCTM());
        return document.elementsFromPoint(screen.x,screen.y).some(e=>e.closest?.('[data-role="inaccurate"]'));
      });
      assert.equal(hit,false);
      assert.equal(await page.evaluate(()=>getState().selectedIssueId),null);
    });
    await loadFixture();
    await check('all filters and view modes preserve pan/zoom; Fit uses full bounds; Locate centers selected graphics',async()=>{
      await page.locator('#viewer-zoom-in').click();
      await page.locator('#drawing-viewport').focus();
      await page.keyboard.press('ArrowRight');
      const before=await page.locator('#drawing-viewport svg').getAttribute('viewBox');
      for (const role of roles) {
        await legend(role).click();
        assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),before);
        assert.equal(await page.locator('#view-student-only').getAttribute('aria-pressed'),String(role==='student'));
        assert.equal(await page.locator('#view-review-comparison').getAttribute('aria-pressed'),String(role==='all'));
      }
      await page.locator('#view-student-only').click(); assert.equal(await legend('student').getAttribute('aria-pressed'),'true');
      await page.locator('#view-review-comparison').click(); assert.equal(await legend('all').getAttribute('aria-pressed'),'true');
      await page.locator('#issue-list .issue-card[data-issue-id="QA-inaccurate"]').click();
      assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),before);
      await page.locator('#viewer-locate-issue').click();
      const centered=await page.evaluate(()=>{
        const n=getViewerNav(), b=document.querySelector('g[data-issue-id="QA-inaccurate"]').getBBox();
        return Math.abs(n.currentX+n.currentWidth/2-b.x-b.width/2)<1e-5 && Math.abs(n.currentY+n.currentHeight/2-b.y-b.height/2)<1e-5;
      });
      assert.equal(centered,true);
      await page.locator('#viewer-reset').click();
      assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'),'0 0 1200 800');
      await legend('warning').click();
      await page.locator('#issue-list [data-issue-id="QA-no-geometry"]').click();
      assert.equal(await page.locator('#viewer-locate-issue').isDisabled(),true);
    });
    await loadFixture();
    await check('empty category message is accurate, navigation is retained and new review defaults All',async()=>{
      await page.evaluate(()=>{document.querySelector('svg > g[data-layer="issues"] [data-role="extra"]').remove();});
      await legend('extra').click();
      assert.equal(await page.locator('#drawing-empty-overlay').isVisible(),true);
      assert.match(await page.locator('#drawing-empty-overlay').textContent(),/No extra indications/);
      await legend('reference').click(); assert.equal(await page.locator('#drawing-empty-overlay').isVisible(),false);
      await loadFixture(); assert.equal(await legend('all').getAttribute('aria-pressed'),'true');
    });
    await check('header exact text, contrast and desktop/narrow layout',async()=>{
      for(const width of [1366,760,390]) {
        await page.setViewportSize({width,height:768});
        assert.equal(await page.locator('.header-credit').textContent(),'All rights reserved to MOUKiD BADiE & Mervat El-Sawaf');
        assert.equal(await page.locator('.brand').textContent(),'DraftLens EDU');
        assert.equal(await page.locator('.header-credit').evaluate(el=>el.previousElementSibling.textContent),'Deterministic CAD grading and visual evidence');
        const contrast=await page.locator('.header-credit').evaluate(el=>{
          const luminance=color=>{
            const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
            return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
          };
          const fg=luminance(getComputedStyle(el).color), bg=luminance(getComputedStyle(document.querySelector('.app-header')).backgroundColor);
          return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
        });
        assert.ok(contrast>=4.5,`header contrast ${contrast}`);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
        await page.locator('.app-header').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(destination,`header-${width}.png`)});
        await legend('inaccurate').click();
        await page.locator('.drawing-panel').screenshot({path:path.join(destination,`inaccurate-${width}.png`)});
        for(const role of roles) {
          await legend(role).click();
          const shapes=await visibleShapes();
          assert.equal(shapes.length,role==='all'?327:['reference','student'].includes(role)?160:role==='inaccurate'?2:1,`${width} ${role}`);
        }
        await legend('all').click();
        await page.locator('.drawing-panel').screenshot({path:path.join(destination,`all-${width}.png`)});
      }
    });
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:passes.length,failures,artifacts:destination},null,2));
    if(failures.length) process.exitCode=1;
  } finally {await browser.close();}
})().catch(e=>{console.error(e);console.error(destination);process.exitCode=1;});
