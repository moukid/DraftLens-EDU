/* Live browser QA for Gaps & Connections presentation and interactions. */
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require(process.env.DRAFTLENS_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.DRAFTLENS_QA_URL || 'http://127.0.0.1:8017';
if (!['localhost','127.0.0.1'].includes(new URL(url).hostname)) throw Error('Loopback only');

const destination = fs.mkdtempSync(path.join(os.tmpdir(), 'draftlens-conn-qa-'));
const fixture = JSON.parse(execFileSync(process.env.DRAFTLENS_QA_PYTHON || 'python',
  ['-B','-m','tests.connectivity_synthetic'], {cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));

const failures = [], passes = [];
async function check(name, fn) {
  try { await fn(); passes.push(name); console.log('PASS:', name); }
  catch (error) { failures.push({name, error: String(error)}); console.log('FAIL:', name, String(error)); }
}

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1366, height: 768}});
    page.on('pageerror', e => console.error('Browser error:', e));
    await page.goto(url);

    const expectedExplanation = "Highlights places where drawing elements do not connect as required by the reference, such as gaps between endpoints or broken junctions. Intentional openings are not errors. Supporting findings may carry no additional deduction.";

    await check('1. Terminology: Legend and Filter buttons display Gaps & Connections with correct title', async () => {
      const legendBtn = page.locator('#overlay-legend button[data-role="connectivity"]');
      const filterBtn = page.locator('.filters button[data-filter="connectivity"]');
      
      assert.equal((await legendBtn.textContent()).trim(), 'Gaps & Connections');
      assert.equal(await legendBtn.getAttribute('title'), expectedExplanation);
      assert.equal((await filterBtn.textContent()).trim(), 'Gaps & Connections');
      assert.equal(await filterBtn.getAttribute('title'), expectedExplanation);
    });

    // Upload and run review using fixture DXFs to get real initial state
    const upload = key => ({name: `synthetic-${key}.dxf`, mimeType: 'application/dxf', buffer: Buffer.from(fixture.uploads[key], 'base64')});
    await page.locator('#reference-file').setInputFiles(upload('reference'));
    await page.locator('#rubric-editor').waitFor({state: 'visible'});
    await page.locator('#assignment-type').selectOption('Other');
    await page.locator('#approve-rubric').click();
    await page.waitForFunction(() => Boolean(getState().rubricId));
    await page.locator('#student-file').setInputFiles(upload('student'));
    await page.locator('#run-review').click();
    await page.waitForFunction(() => Boolean(getState().review?.report_available));

    await check('2. Student underlay visible at 0.40 opacity when Gaps & Connections is active', async () => {
      await page.locator('#overlay-legend button[data-role="connectivity"]').click();
      
      // Check explanation banner is visible
      const expElem = page.locator('#connectivity-explanation');
      assert.equal(await expElem.isVisible(), true);
      assert.equal((await expElem.textContent()).trim(), expectedExplanation);

      // Check student layer underlay style
      const studentLayerStyle = await page.evaluate(() => {
        const el = document.querySelector('svg > g[data-layer="student"]');
        if (!el) return null;
        const style = window.getComputedStyle(el);
        return {
          display: style.display,
          opacity: style.opacity,
          pointerEvents: style.pointerEvents,
        };
      });
      assert.ok(studentLayerStyle, 'student layer exists');
      assert.notEqual(studentLayerStyle.display, 'none');
      assert.equal(studentLayerStyle.opacity, '0.4');
      assert.equal(studentLayerStyle.pointerEvents, 'none');
    });

    await check('3. Student underlay preserved across all error roles (missing, extra, inaccurate, warning, critical)', async () => {
      for (const role of ['missing', 'extra', 'inaccurate', 'warning', 'critical']) {
        await page.locator(`#overlay-legend button[data-role="${role}"]`).click();
        const style = await page.evaluate(() => {
          const el = document.querySelector('svg > g[data-layer="student"]');
          const s = window.getComputedStyle(el);
          return { display: s.display, opacity: s.opacity };
        });
        assert.notEqual(style.display, 'none', `${role} hides student layer`);
        assert.equal(style.opacity, '0.4', `${role} opacity is not 0.40`);
      }
    });

    // Load connectivity synthetic review fixture
    const loadConnectivityFixture = () => page.evaluate(r => {
      getState().review = structuredClone(r);
      renderResults(getState().review);
    }, fixture.review);

    await loadConnectivityFixture();

    await check('4. Localized connectivity markers rendered and bounding box hidden by default', async () => {
      await page.locator('#overlay-legend button[data-role="connectivity"]').click();

      // Verify localized markers exist and are visible
      const connectorVisible = await page.evaluate(() => {
        const el = document.querySelector('.connectivity-connector[data-issue-id="QA-connectivity"]');
        if (!el) return false;
        return window.getComputedStyle(el).display !== 'none';
      });
      assert.equal(connectorVisible, true, 'connectivity-connector is visible');

      const endpointsCount = await page.evaluate(() => {
        const circles = Array.from(document.querySelectorAll('.connectivity-endpoint[data-issue-id="QA-connectivity"]'));
        return circles.filter(c => window.getComputedStyle(c).display !== 'none').length;
      });
      assert.equal(endpointsCount, 2, 'two connectivity-endpoint circles are visible');

      // Verify bounding rectangle is HIDDEN by default
      const regionVisibleBefore = await page.evaluate(() => {
        const r = document.querySelector('.connectivity-region.technical-only[data-issue-id="QA-connectivity"]');
        if (!r) return false;
        return window.getComputedStyle(r).display !== 'none';
      });
      assert.equal(regionVisibleBefore, false, 'technical-only bounding box is hidden by default');

      // Check "Show technical details" checkbox
      await page.locator('#toggle-technical-details').check();

      const regionVisibleAfter = await page.evaluate(() => {
        const r = document.querySelector('.connectivity-region.technical-only[data-issue-id="QA-connectivity"]');
        if (!r) return false;
        return window.getComputedStyle(r).display !== 'none';
      });
      assert.equal(regionVisibleAfter, true, 'technical-only bounding box becomes visible when checked');

      // Uncheck "Show technical details"
      await page.locator('#toggle-technical-details').uncheck();
      const regionVisibleUnchecked = await page.evaluate(() => {
        const r = document.querySelector('.connectivity-region.technical-only[data-issue-id="QA-connectivity"]');
        return window.getComputedStyle(r).display !== 'none';
      });
      assert.equal(regionVisibleUnchecked, false, 'technical-only bounding box hides when unchecked');
    });

    await check('5. Supporting details collapsed by default; expanding reveals and selects finding with plain-language explanation', async () => {
      await loadConnectivityFixture();
      
      // Find the issue group for the primary issue (QA-inaccurate)
      const group = page.locator('.issue-group').filter({has: page.locator('[data-issue-id="QA-inaccurate"]')});
      const details = group.locator('details');
      
      // Verify supporting details is collapsed by default
      assert.equal(await details.getAttribute('open'), null, 'supporting evidence collapsed by default');
      
      // Expand supporting details
      await details.locator('summary').click();
      assert.notEqual(await details.getAttribute('open'), null, 'supporting evidence expands');
      
      // Click supporting connectivity button
      const connBtn = details.getByRole('button', {name: /QA-connectivity:/});
      await connBtn.click();

      // Legend switches to connectivity
      assert.equal(await page.locator('#overlay-legend button[data-role="connectivity"]').getAttribute('aria-pressed'), 'true');
      
      // Feedback details populated
      const detailVisible = await page.locator('#feedback-detail').isVisible();
      assert.equal(detailVisible, true, 'feedback-detail is visible');

      const feedbackId = await page.locator('#feedback-id').textContent();
      assert.equal(feedbackId, 'QA-connectivity');

      const feedbackText = await page.locator('#feedback-text').textContent();
      assert.match(feedbackText, /exceeds tolerance/i);
      assert.match(feedbackText, /Connect endpoints at this junction/i);

      // Supporting guidance label
      const supportingLabel = page.locator('#guidance-supporting-label');
      assert.equal(await supportingLabel.isVisible(), true);
      assert.match(await supportingLabel.textContent(), /Supporting connection evidence/);

      // Verify deduction display shows 0
      const deductionText = await page.locator('#evidence-deduction').textContent();
      assert.match(deductionText, /No deduction|0(\.00?)?/);
    });

    await check('6. Pan/zoom position preserved when toggling filters and selecting findings', async () => {
      await loadConnectivityFixture();
      await page.locator('#viewer-zoom-in').click();
      const viewBoxAfterZoom = await page.locator('#drawing-viewport svg').getAttribute('viewBox');

      // Switch to another role and back
      await page.locator('#overlay-legend button[data-role="missing"]').click();
      assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'), viewBoxAfterZoom);

      await page.locator('#overlay-legend button[data-role="connectivity"]').click();
      assert.equal(await page.locator('#drawing-viewport svg').getAttribute('viewBox'), viewBoxAfterZoom);
    });

    await check('7. Small UI fixes: Bold rubric category headings, Angle alignment, and two-line footer credit', async () => {
      // 1. Two-line footer credit
      const footerPs = await page.locator('footer p').allTextContents();
      assert.equal(footerPs.length, 2, 'Footer has 2 lines');
      assert.equal(footerPs[0].trim(), 'DraftLens EDU · Approved rubrics · Deterministic geometry · Traceable evidence');
      assert.equal(footerPs[1].trim(), 'Copyright reserved @MOUKiD BADiE - Mervat El-Sawaf');

      // 2. Angle alignment in tolerance-grid
      const angleLabel = page.locator('.tolerance-grid label:has([data-tolerance="angle"])');
      const angleSmall = angleLabel.locator('small');
      assert.equal(await angleSmall.count(), 1, 'Angle label contains small description');
      assert.match(await angleSmall.textContent(), /Degrees/);
      assert.equal(await page.locator('.tolerance-grid > small').count(), 0, 'No loose tolerance notes disrupting grid rows');

      // 3. Rubric category headings bold
      await page.evaluate(() => {
        state.provisionalRubric = {
          assignment_title: 'Test Assignment',
          assignment_type: 'Other',
          normalization_mode: 'translation',
          completion_scoring_mode: 'rule_based',
          categories: [{name: 'Geometry Accuracy', id: 'geometry_accuracy', weight: 40}],
          tolerances: {position: 0.5, length: 0.5, angle: 1.0}
        };
        renderRubricEditor();
      });
      const strongText = await page.locator('.rubric-row strong').textContent();
      assert.equal(strongText.trim(), 'Geometry Accuracy');
    });

    console.log('\n--- Connectivity QA Summary ---');
    console.log(`Passed: ${passes.length}`);
    console.log(`Failed: ${failures.length}`);
    if (failures.length > 0) {
      console.error('Failures:', failures);
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
  }
})();
