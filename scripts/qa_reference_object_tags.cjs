/* Live Browser QA for Reference Object Tags, Unit/Scale Review & Acceptance Repairs */
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require(process.env.DRAFTLENS_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.DRAFTLENS_QA_URL || 'http://127.0.0.1:8017';
if (!['localhost', '127.0.0.1'].includes(new URL(url).hostname)) {
  throw new Error('Loopback only');
}

const destination = fs.mkdtempSync(path.join(os.tmpdir(), 'draftlens-ref-obj-qa-'));
const pythonPath = process.env.DRAFTLENS_QA_PYTHON || 'python';

// Generate synthetic DXF fixtures in memory via Python helper
const fixtures = JSON.parse(
  execFileSync(pythonPath, ['-B', '-c', `
import json, base64, io, ezdxf

# Reference with DL-Info tags and a rectangle
doc_ref = ezdxf.new("R2010")
doc_ref.units = ezdxf.units.MM
msp_r = doc_ref.modelspace()
msp_r.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALLS"})
msp_r.add_line((100, 0), (100, 100), dxfattribs={"layer": "WALLS"})
msp_r.add_line((100, 100), (0, 100), dxfattribs={"layer": "WALLS"})
msp_r.add_line((0, 100), (0, 0), dxfattribs={"layer": "WALLS"})
# Marker text on DL-Info and DL-Info-Tags
msp_r.add_text("D1", dxfattribs={"layer": "DL-Info", "insert": (50, 50)})
msp_r.add_text("W1", dxfattribs={"layer": "DL-Info-Tags", "insert": (80, 50)})

s_ref = io.StringIO()
doc_ref.write(s_ref)
ref_bytes = s_ref.getvalue().encode("utf-8")

# Student with translated walls (+10, +10), missing one wall
doc_stu = ezdxf.new("R2010")
doc_stu.units = ezdxf.units.MM
msp_s = doc_stu.modelspace()
msp_s.add_line((10, 10), (110, 10), dxfattribs={"layer": "WALLS"})
msp_s.add_line((110, 10), (110, 110), dxfattribs={"layer": "WALLS"})
msp_s.add_line((10, 110), (10, 10), dxfattribs={"layer": "WALLS"})

s_stu = io.StringIO()
doc_stu.write(s_stu)
stu_bytes = s_stu.getvalue().encode("utf-8")

print(json.dumps({
    "reference": base64.b64encode(ref_bytes).decode("ascii"),
    "student": base64.b64encode(stu_bytes).decode("ascii")
}))
`], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8' })
);

const upload = (key) => ({
  name: `synthetic-${key}.dxf`,
  mimeType: 'application/dxf',
  buffer: Buffer.from(fixtures[key], 'base64'),
});

const passes = [];
const failures = [];

async function check(name, fn) {
  try {
    await fn();
    passes.push(name);
    console.log('PASS:', name);
  } catch (error) {
    failures.push({ name, error: String(error) });
    console.log('FAIL:', name, String(error));
  }
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    await page.goto(url);

    await check('1. Initial page render defaults and structure', async () => {
      // Header credit
      const credit = await page.locator('.header-credit').textContent();
      assert.equal(credit, 'All rights reserved to MOUKiD BADiE & Mervat El-Sawaf');

      // Default normalization mode is translation
      const normMode = await page.locator('#normalization-mode').inputValue();
      assert.equal(normMode, 'translation');

      // Placeholder is selected by default on assignment type
      const assignmentType = await page.locator('#assignment-type').inputValue();
      assert.equal(assignmentType, '', 'Assignment type should default to empty placeholder');

      const placeholderText = await page.locator('#assignment-type option[value=""]').textContent();
      assert.equal(placeholderText, 'Select assignment type');
    });

    await check('2. Explicit assignment type selection required to approve rubric', async () => {
      await page.locator('#reference-file').setInputFiles(upload('reference'));
      await page.locator('#rubric-editor').waitFor({ state: 'visible' });

      // Heading cleanup is verified after reference analysis
      const heading = await page.locator('#analysis-summary h2').textContent();
      assert.equal(heading, 'Detected geometric features');

      // Verify that approve-rubric is disabled while assignment type is unselected
      assert.equal(await page.locator('#assignment-type').inputValue(), '');
      assert.equal(
        await page.locator('#approve-rubric').isDisabled(),
        true,
        'Approve button should be disabled when assignment type is unselected'
      );

      // Now select assignment type
      await page.locator('#assignment-type').selectOption('Architectural Drawing');

      // Verify button becomes enabled
      assert.equal(
        await page.locator('#approve-rubric').isEnabled(),
        true,
        'Approve button should be enabled once assignment type is selected'
      );

      // Click approve
      await page.locator('#approve-rubric').click();
      await page.waitForFunction(() => Boolean(getState().rubricId));
      assert.ok(await page.evaluate(() => Boolean(getState().rubricId)));
    });

    await check('3. Reference object tagging inspection & proposals', async () => {
      const refData = await page.evaluate(() => getState().referenceObjectData);
      assert.ok(refData, 'Reference object data should be present');
      console.log('Detected plan markers:', refData.plan_markers?.length || 0);
      assert.ok(refData.plan_markers?.length >= 2, 'Should detect at least 2 plan markers (D1, W1)');
    });

    await check('4. Student upload & review execution', async () => {
      await page.locator('#student-file').setInputFiles(upload('student'));
      await page.waitForFunction(() => Boolean(getState().student));
      await page.locator('#run-review').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#run-review').isEnabled(), true);
      await page.locator('#run-review').click();
      await page.waitForFunction(() => Boolean(getState().review?.report_available));
      const review = await page.evaluate(() => getState().review);
      assert.ok(review, 'Review result should be present');
      assert.equal(typeof review.score, 'number');
      console.log('Review score:', review.score, 'Issues count:', review.issues?.length || 0);
    });

    await check('5. Student underlay visible for all error filters with subdued style', async () => {
      const errorRoles = ['missing', 'extra', 'inaccurate', 'connectivity', 'warning', 'critical'];
      for (const role of errorRoles) {
        await page.locator(`#overlay-legend button[data-role="${role}"]`).click();

        // Check viewport class
        const viewportHasUnderlayClass = await page.evaluate(() =>
          document.getElementById('drawing-viewport').classList.contains('student-underlay-active')
        );
        assert.equal(viewportHasUnderlayClass, true, `Viewport should have student-underlay-active class for ${role}`);

        // Check student layer visibility in DOM
        const studentLayerVisible = await page.evaluate(() => {
          const studentGroup = document.querySelector('#drawing-viewport svg > g[data-layer="student"]');
          if (!studentGroup) return false;
          const children = studentGroup.querySelectorAll('line, path, polyline, circle');
          if (children.length === 0) return false;
          const style = window.getComputedStyle(studentGroup);
          return style.display !== 'none' && style.visibility !== 'hidden';
        });
        assert.equal(studentLayerVisible, true, `Student layer should remain visible during ${role} filter`);

        // Check subdued opacity and pointer-events none
        const underlayStyle = await page.evaluate(() => {
          const studentGroup = document.querySelector('#drawing-viewport svg > g[data-layer="student"]');
          const style = window.getComputedStyle(studentGroup);
          return {
            opacity: style.opacity,
            pointerEvents: style.pointerEvents,
          };
        });
        assert.equal(underlayStyle.opacity, '0.4', `Student underlay opacity should be 0.4 for ${role}`);
        assert.equal(underlayStyle.pointerEvents, 'none', `Student underlay pointer-events should be none for ${role}`);
      }

      // Reset to all
      await page.locator('#overlay-legend button[data-role="all"]').click();
      const underlayActiveAfterReset = await page.evaluate(() =>
        document.getElementById('drawing-viewport').classList.contains('student-underlay-active')
      );
      assert.equal(underlayActiveAfterReset, false, 'student-underlay-active should be removed on "all"');
    });

    await check('6. Download PDF report and verify content bytes', async () => {
      const reviewId = await page.evaluate(() => getState().review.review_id);
      const uri = `${url}/api/reviews/${reviewId}/report.pdf`;
      const response = await page.request.get(uri);
      assert.equal(response.status(), 200);
      assert.equal(response.headers()['content-type'], 'application/pdf');
      const body = await response.body();
      assert.ok(body.length > 5000, 'PDF body should be substantial');
      assert.equal(body.slice(0, 4).toString(), '%PDF', 'PDF signature verified');
    });

    assert.deepEqual(errors, [], `Page errors encountered: ${errors.join('; ')}`);
    console.log(JSON.stringify({ passed: passes.length, failures, artifacts: destination }, null, 2));
    if (failures.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error('Test execution error:', e);
  process.exitCode = 1;
});
