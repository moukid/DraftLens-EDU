/* Independent acceptance: real uploads/endpoints; no injected review or object state. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.DRAFTLENS_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.DRAFTLENS_QA_URL || 'http://127.0.0.1:8018';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(url).hostname));
const root = path.resolve(__dirname, '..');
const fixtures = JSON.parse(execFileSync(process.env.DRAFTLENS_QA_PYTHON || 'python',
  ['-B', '-m', 'tests.stage_audit_synthetic'], {cwd: root, encoding: 'utf8'}));
const destination = fs.mkdtempSync(path.join(os.tmpdir(), 'draftlens-final-stage-'));
const upload = key => ({name: `synthetic-${key}.dxf`, mimeType: 'application/dxf', buffer: Buffer.from(fixtures[key], 'base64')});
const passes = [];
async function check(name, fn) { await fn(); passes.push(name); console.log('PASS:', name); }

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', e => { if (e.type() === 'error') errors.push(e.text()); });
  const objects = () => page.evaluate(() => getState().referenceObjects);
  const selectDecision = (id, value) => page.getByLabel(id + ' decision', {exact: true}).selectOption(value);
  const approve = async () => {
    await page.locator('#approve-rubric').click();
    await page.waitForFunction(() => Boolean(getState().rubricId));
  };
  const expandSetup = async () => {
    const button = page.locator('#edit-setup');
    if (await button.count() && await button.isVisible()) await button.click();
    const details = page.locator('#setup-details');
    if (await details.count() && !(await details.getAttribute('open'))) await details.locator('summary').click();
  };
  const save = async () => {
    const response = page.waitForResponse(r => r.url().endsWith('/api/reference/objects/confirm'));
    await page.locator('#confirm-reference-objects').click();
    const result = await response;
    assert.equal(result.status(), 200, await result.text());
    return result.json();
  };
  try {
    await page.goto(url);
    await check('audited worktree assets served byte-for-byte', async () => {
      const served = await (await page.request.get(url + '/static/app.js')).text();
      assert.equal(served.replace(/\r\n/g, '\n'), fs.readFileSync(path.join(root, 'app/static/app.js'), 'utf8').replace(/\r\n/g, '\n'));
    });
    await page.locator('#reference-file').setInputFiles(upload('reference'));
    await page.locator('#rubric-editor').waitFor({state: 'visible'});
    await check('explicit assignment, translation default, metadata separation', async () => {
      assert.equal(await page.locator('#assignment-type').inputValue(), '');
      assert.ok(await page.locator('#approve-rubric').isDisabled());
      assert.equal(await page.locator('#normalization-mode').inputValue(), 'translation');
      const data = await page.evaluate(() => getState().referenceObjectData);
      assert.equal(data.plan_markers.length, 3);
      assert.equal(data.legend_markers.length, 1);
      assert.equal(data.available_entities.length, 8);
      assert.deepEqual(data.reference_bbox, [0, 0, 100, 80]);
      assert.equal(data.definitions_saved, false);
      await page.locator('#assignment-type').selectOption('Architectural Drawing');
      await page.locator('#normalization-mode').selectOption('strict');
      await page.locator('#normalization-mode').selectOption('translation');
    });
    const initial = await objects();
    const door = initial.find(o => o.type_code === 'D1');
    const windowObject = initial.find(o => o.type_code === 'W1');
    const unknown = initial.find(o => o.type_code === 'X9');
    await page.locator('.reference-object-card').filter({hasText: door.occurrence_id + ' ('}).getByRole('button', {name: 'Inspect', exact: true}).click();
    await check('arc preview and member add/remove preserve zoom at actual pointer coordinates', async () => {
      const arc = page.locator('#reference-object-preview path');
      assert.equal(await arc.count(), 1);
      assert.match(await arc.getAttribute('d'), / A 8 8 /);
      await page.locator('#object-preview-zoom-in').click();
      const before = await page.locator('#reference-object-preview').getAttribute('viewBox');
      const member = await arc.getAttribute('data-entity-id');
      const wasMember = (await objects()).find(o => o.type_code === 'D1').member_entity_ids.includes(member);
      const graphic = page.locator(`#reference-object-preview [data-entity-id="${member}"]`);
      await graphic.scrollIntoViewIfNeeded();
      const point = await graphic.evaluate(e => {
        const p = e.getPointAtLength(e.getTotalLength() * 0.7);
        return new DOMPoint(p.x, p.y).matrixTransform(e.getScreenCTM()).toJSON();
      });
      await page.mouse.click(point.x, point.y);
      assert.equal((await objects()).find(o => o.type_code === 'D1').member_entity_ids.includes(member), !wasMember);
      assert.equal(await page.locator('#reference-object-preview').getAttribute('viewBox'), before);
      await page.mouse.click(point.x, point.y);
      assert.equal((await objects()).find(o => o.type_code === 'D1').member_entity_ids.includes(member), wasMember);
      assert.equal(await page.locator('#reference-object-preview').getAttribute('viewBox'), before);
      await page.locator('#object-preview-expand').click();
      assert.ok(await page.locator('#reference-object-preview-panel').evaluate(e => e.classList.contains('is-expanded')));
      await page.keyboard.press('Escape');
      assert.ok(!(await page.locator('#reference-object-preview-panel').evaluate(e => e.classList.contains('is-expanded'))));
    });
    await check('overlap decision, exclusion, unresolved and saved reopen', async () => {
      await selectDecision(door.occurrence_id, 'confirmed');
      await selectDecision(windowObject.occurrence_id, 'confirmed');
      await page.locator('#confirm-reference-objects').click();
      assert.match(await page.locator('#confirm-objects-status').textContent(), /Acknowledge overlapping/);
      await page.locator('#overlap-ack-check').check();
      let saved = await save();
      assert.equal(saved.confirmed_count, 2);
      assert.equal(saved.unresolved_count, 1);
      await selectDecision(windowObject.occurrence_id, 'excluded');
      await selectDecision(door.occurrence_id, 'unresolved');
      saved = await save();
      assert.equal(saved.confirmed_count, 0);
      assert.equal(saved.unresolved_count, 2);
      await selectDecision(door.occurrence_id, 'confirmed');
      saved = await save();
      assert.equal(saved.confirmed_count, 1);
      await page.locator('#apply-legend-filter').click();
      await page.waitForFunction(() => getState().referenceObjectData?.definitions_saved === true);
      assert.deepEqual((await objects()).map(o => [o.occurrence_id, o.status, o.member_entity_ids]), saved.objects.map(o => [o.occurrence_id, o.status, o.member_entity_ids]));
    });
    await approve();
    await page.locator('#student-file').setInputFiles(upload('cm'));
    await page.locator('#run-review').click();
    await page.waitForFunction(() => Boolean(getState().review));
    await check('real unit mismatch withholds grade; acknowledgment creates consistent report', async () => {
      assert.equal(await page.evaluate(() => getState().review.grading_status), 'withheld');
      assert.equal(await page.evaluate(() => getState().review.score), null);
      await page.locator('#unit-scale-ack-check').check();
      await page.locator('#grade-anyway').click();
      await page.waitForFunction(() => getState().review?.report_available === true);
      const review = await page.evaluate(() => getState().review);
      assert.equal(review.assignment_type, 'Architectural Drawing');
      assert.equal(review.unit_scale_review.acknowledged, true);
      assert.equal(review.reference_objects_summary.confirmed_count, 1);
      fs.writeFileSync(path.join(destination, 'unit-review.json'), JSON.stringify(review, null, 2));
      const pdf = await (await page.request.get(`${url}/api/reviews/${review.review_id}/report.pdf`)).body();
      fs.writeFileSync(path.join(destination, 'unit-decision.pdf'), pdf);
      await page.screenshot({path: path.join(destination, 'desktop.png'), fullPage: true});
    });
    await check('saved object change clears current review and requires renewed approval', async () => {
      await expandSetup();
      await selectDecision(door.occurrence_id, 'unresolved');
      assert.equal(await page.evaluate(() => getState().review), null);
      assert.ok(await page.locator('#run-review').isDisabled());
      const saved = await save();
      assert.equal(saved.approval_invalidated, true);
      assert.equal(await page.evaluate(() => getState().rubricId), null);
      await approve();
      await expandSetup();
      await page.locator('#code-mappings-input').fill('{"X9":"Custom marker"}');
      await page.locator('#apply-legend-filter').click();
      await page.waitForFunction(() => getState().rubricId === null);
      assert.equal(await page.evaluate(() => getState().review), null);
      await approve();
    });
    await page.locator('#student-file').setInputFiles(upload('gap'));
    await page.locator('#run-review').click();
    await page.waitForFunction(() => getState().review?.report_available === true);
    await check('real gap evidence, complete underlays, filters and deterministic downloads', async () => {
      const review = await page.evaluate(() => getState().review);
      const gap = review.issues.find(i => i.category === 'endpoint_gap');
      assert.ok(gap, 'uploaded student creates actual gap evidence');
      assert.equal(gap.applied_deduction, 0);
      const initialPdf = await (await page.request.get(`${url}/api/reviews/${review.review_id}/report.pdf`)).body();
      const studentCount = await page.locator('#drawing-viewport svg > g[data-layer="student"] [data-entity-id]').count();
      for (const role of ['missing','extra','inaccurate','connectivity','warning','critical']) {
        await page.locator(`#overlay-legend [data-role="${role}"]`).click();
        const visible = await page.locator('#drawing-viewport svg > g[data-layer="student"] [data-entity-id]').evaluateAll(es => es.filter(e => getComputedStyle(e).display !== 'none').length);
        assert.equal(visible, studentCount);
      }
      const finalPdf = await (await page.request.get(`${url}/api/reviews/${review.review_id}/report.pdf`)).body();
      assert.deepEqual(finalPdf, initialPdf);
      fs.writeFileSync(path.join(destination, 'gap-review.pdf'), finalPdf);
      const appendix = await (await page.request.get(`${url}/api/reviews/${review.review_id}/report.pdf?include_appendix=true`)).body();
      fs.writeFileSync(path.join(destination, 'gap-appendix.pdf'), appendix);
      assert.ok(appendix.length > finalPdf.length);
      await page.locator('#overlay-legend [data-role="connectivity"]').click();
      await page.locator('#drawing-viewport').screenshot({path:path.join(destination, 'actual-gap.png')});
      const download = page.waitForEvent('download');
      await page.locator('#download-report').click();
      assert.equal(await (await download).failure(), null);
    });
    await check('narrow layout, exact footer, and reference replacement reset', async () => {
      await page.setViewportSize({width: 390, height: 844});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
      assert.deepEqual((await page.locator('footer p').allTextContents()).map(s => s.trim()), ['DraftLens EDU · Approved rubrics · Deterministic geometry · Traceable evidence', 'Copyright reserved @MOUKiD BADiE - Mervat El-Sawaf']);
      await page.screenshot({path:path.join(destination, 'narrow.png'), fullPage:true});
      await expandSetup();
      await page.locator('#reference-file').setInputFiles(upload('student'));
      await page.waitForFunction(() => getState().provisionalRubric && !getState().loading);
      assert.equal(await page.locator('#assignment-type').inputValue(), '');
      assert.equal(await page.evaluate(() => getState().rubricId), null);
    });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed:passes.length, artifacts:destination}, null, 2));
  } catch (error) {
    console.error(error);
    await page.screenshot({path:path.join(destination, 'failure.png'), fullPage:true});
    console.error('Artifacts:', destination);
    throw error;
  } finally { await page.context().close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
