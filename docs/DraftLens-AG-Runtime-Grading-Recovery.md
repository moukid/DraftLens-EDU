# DraftLens EDU — runtime grading recovery after failed retest

This corrective brief supplements DraftLens-AG-Square-Grading-Repair.md. Where acceptance or runtime activation is less explicit in the earlier brief, this brief takes precedence. Do not treat passing an isolated scorer test as proof that the running application is repaired.

## Objective and authorization

Repair the actual instructor workflow that produced Test_result-2.pdf. Perform diagnosis, reversible code/configuration changes, verification, and self-audit. Preserve pending UI/UX work. Do not commit, push, merge, deploy, reset, stash, or discard user changes. Do not spawn agents. Use the existing project virtual environment and applicable AGENTS.md/rules. Stop only for a genuine blocker, security/privacy risk, or a grading decision not covered below.

Authoritative repository: <repo-root>
Private CAD root: <private-cad-root>
Locate the exact square test files read-only under that root. Do not assume <private-testing-set-4> contains the newly supplied files. Do not move, overwrite, or track CAD files. Keep real-file evidence, logs, paths, and extracted geometry outside the repository. Any repository test fixtures must be generated synthetically under the existing no-tracked-CAD policy.

## Observed second retest and required outcomes

All scores here are reported in the instructor's PDF, not independently captured API responses. Preserve that distinction until reproducing them.

| Student file | Second reported total | Required total for instructor square policy |
|---|---:|---:|
| sq_10-40_test.dxf | 100 | 100 |
| sq_10-10_test.dxf | 27.7 | 100 |
| sq_09-36_test.dxf | 95 | 91 |
| sq_09-35_test.dxf | 95 | 90 |
| sq_09-34_test.dxf | 95 | 89 |
| sq_08-32_test.dxf | 95 | 82 |
| sq_05-20_test.dxf | 65.83 | 55 |
| sq_04-16_test.dxf | 54.67 | 46 |
| sq_04-14_test.dxf | 49.08 | 44 |

The 04-14 instructor column still says 43, but the previously stated policy gives 44. Do not silently add an unexplained extra deduction.

The polyline row shows 11.67 geometry + 6.25 completion + 10 file quality, totaling 27.92, while the total column says 27.7. First compare the original application/API values; this could be a manual transcription inconsistency rather than a scorer defect. Do not invent a rounding explanation for the difference.

The 6.25 completion value equals 25*(10 raw polylines/40 raw reference LINEs). This is a diagnostic clue to investigate, not a proven code cause. The repeated score of 95 for 36, 35, 34, and 32 edges suggests a policy plateau, configuration issue, or ineffective repair; trace it. The geometry scores for 20, 16, and 14 correct edges are numerically compatible with a denominator of 30 (65*n/30); inspect actual denominator logic rather than guessing or patching constants.

## Phase 1 — identify the exact runtime and previous work

Before edits, record privately:

1. Current branch, HEAD, repository/worktree path, working diff, pending UI/UX changes, and any AG/Codex repair/audit reports already present. Read the reports and compare claims with the actual patch and tests. Do not rely on test counts alone.
2. Running DL server process, listening port, launch command, interpreter, working directory, imported application module location, and served frontend/build identity where available. Verify whether it runs the intended worktree. Do not terminate unrelated processes. If the intended process cannot be replaced safely, start a separately identified local instance and explicitly identify its URL for testing.
3. The exact URL used for the instructor flow if observable from existing configuration/context. If the instructor URL is unavailable, validate a clearly identified intended local URL and report that it remains to be compared with the instructor's previous URL. Do not claim that an unobserved old process was stale.
4. Effective alignment mode, reference identity, approved rubric identity/version, weights, policy ID, partial-part deduction, construction requirement, and current cache/approval state for one reproduction. Keep raw evidence private.
5. Locate the new implementation in the source. Determine whether it is absent, disconnected from /api/review, gated by a profile never selected, overridden by old approval/defaults, or served by a different process/worktree. Rule out these alternatives with observations. If current results differ from the PDF, report them exactly.

Reproduce all nine files through the application's real review endpoint under the same approved settings before changing code. If prior input files or the implementation are missing, list the exact missing items; continue code inspection and generated synthetic reproduction where possible, but mark real-file verification BLOCKED.

## Phase 2 — repair and activate the instructor workflow

The required instructor square policy is:

- Weights Geometry 65, Completion 25, File quality 10.
- Ten equal required objects; each square carries 6.5 geometry + 2.5 completion marks.
- Entirely absent square loses its full 9-mark content allocation once.
- Missing required geometric edge within a present partial square loses p total marks, p=1 here, with per-object loss capped at 9.
- Thus, for this accurate-remaining-geometry set with separately verified file quality of 10: G=100-9*M-p*E. M counts entirely absent squares; E counts missing required edges within partial squares only.
- Correct results are the table above, derived from reference/rubric budgets, never filenames or square-specific score overrides.
- Retain the earlier proposed partial-loss allocation: distribute combined content loss in the Geometry:Completion ratio of 65:25. Identify this as the proposed category allocation, not an independently approved pedagogical standard. Whole-square absence yields 58.5/22.5/10 for 09-36, 52/20/10 for 08-32, 32.5/12.5/10 for 05-20, and 26/10/10 for 04-16.
- For partial cases, expected full-precision category values are approximately 57.7777778/22.2222222/10 for 09-35, 57.0555556/21.9444444/10 for 09-34, and 24.5555556/9.4444444/10 for 04-14. Define presentation rounding that reconciles categories and total; do not round internal deductions prematurely.
- Missing objects earn no allocated geometry credit; do not invent measured dimensional errors for absent geometry.
- File quality remains independently assessed. Do not automatically award empty/corrupt input 10 or bypass compatibility/unit decisions.

Crucially, this policy must be selectable, persisted in the approved rubric, visibly active, and actually consumed by the running backend for these instructor reviews. If backend support exists but UI activation is missing, finish the UI/API integration. Merely adding a function, test helper, hidden flag, or unused profile is insufficient.

Invalidate an old approval/result through the established flow when grading parameters change; require fresh legitimate approval. Never forge approval tokens, bypass instructor confirmation, or silently reuse a legacy rubric. Show the active policy and p=1 setting in the rubric/results sufficiently for the instructor to verify the selected behavior. Scope activation to the selected instructor/reference workflow; do not silently rewrite historical rubrics or change every assignment globally.

Geometry equivalence is a general correctness requirement whenever entity construction is not explicitly assessed: ten closed four-edge polylines and forty equivalent LINEs must normalize to the same required geometry, with equal credit. Preserve original identities for overlays. Reference grouping anchors incomplete student objects. Do not let fragments disappear, student matches be reused across repeated squares, or vertex/entity order affect scores. Handle collinear segmentation without multiplying required parts. Do not flatten curved segments into straight lines or introduce new scale/placement forgiveness to pass the tests.

Separate geometric closure from a requirement to use joined/closed polylines. Four LINEs can form a correctly connected square. Missing edges may explain an open-loop finding without causing another connectivity deduction. A separately selected construction requirement may have its own explicit capped allocation; it must not be inferred from reference representation.

## Phase 3 — evidence required for READY FOR CODEX AUDIT

1. Reproduce all nine expected totals through the real /api/review route with the active approved instructor policy, using local user files privately and generated synthetic cases in the automated suite. Capture category awards, object/part counts, causal losses, reference/rubric identity, and total from the response. One approved configuration must apply consistently across submissions.
2. In a fresh browser session, use the identified server URL, select the instructor policy, approve the rubric through the actual UI, review both full representations, 09-36, and at least one partial-object case, and confirm the visible policy and total match the API. Verify that uploaded files/results are the currently selected ones. Verify PDF output if scoring/report code is affected. Report browser/PDF limitations as BLOCKED, not PASS.
3. Verify that changing policy, p, weights, construction requirements, or reference invalidates old approval/results. Detect old-result display or stale requests without losing unrelated user data. Do not bypass server-authoritative validation to make the UI work.
4. Keep meaningful regression tests for representation equivalence in both directions, mixed LINE/polyline input, split collinear edges, matching order invariance, one-to-one repeated-object matching, full/partial absence, category reconciliation, and deletion monotonicity through 4->3->2->1->0 edges. Test p=0.25,0.5,1 and caps.
5. Genuine wrong length, wrong angle, endpoint gap, duplicates, extra geometry, and strict/translation-tolerant placement must retain appropriate findings and penalties. Preserve partial ellipse, units, dimensions, rubric approval, and pending UI/UX regressions. Never weaken tests to match these wrong outputs.
6. Run applicable targeted and full regression suites, syntax/compile checks, and git diff --check. Provide actual commands and counts, distinguishing known baseline failures. Passing unit tests alone cannot satisfy runtime acceptance.
7. Perform the existing privacy gate on the working diff/index. Do not stage or upload CAD or real-file-derived sensitive evidence. Do not clean historical branches or rewrite history as part of this repair.

Write a sanitized concise handoff under the established docs/verification conventions, with private raw evidence external to git. Include before/expected/after totals for all nine files, root causes with code locations, tested runtime identity, activation steps, effective settings, changed files, regressions, browser/PDF results, remaining assumptions, and no-commit/no-push confirmation. Do not include machine paths, raw metadata, coordinates, or private screenshots in public-safe reports.

## Independent Codex audit instruction

Audit the final actual working diff and running application independently; do not merely summarize AG's report or rerun its unit tests. Read applicable repository rules. No implementation changes during the read-only audit unless the user separately authorizes them.

Verify process/worktree/source identity and effective approved policy. Independently run the nine local cases through the actual application route and compare all totals and category awards with this contract. Exercise real UI policy selection/approval for representative cases; compare displayed output and any affected PDF with the API. Inspect raw-entity denominators, normalization, grouping, matching, causal double counting, approval/cache behavior, and privacy. Use existing test harnesses where appropriate without treating their assertions as independent proof.

PASS requires the actual acceptance cases under explicitly active settings, meaningful regressions, browser verification, and privacy gate to pass. Missing mandatory evidence is BLOCKED; wrong grading is FAIL. Do not approve because the full suite passes. Do not commit/push/merge. If reporting PASS for another legacy policy, clearly state that it does not satisfy this repair. Produce a short sanitized audit report with the tested branch/HEAD/diff identity and runtime identity so the instructor can launch the same version.
