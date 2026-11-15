# DraftLens EDU — square grading repair and verification

## Execution instruction

Act as the primary implementer and tester for DraftLens EDU (DL). Diagnose, repair, and verify the grading inconsistencies below. Work through implementation and self-audit without stopping at a plan. Proceed with ordinary reversible implementation decisions. Stop only for a genuine blocker, conflicting requirements that affect grades, or privacy/security concerns. Do not commit, push, merge, publish, or deploy. Finish with an uncommitted patch and a concise Codex handoff. Use one agent unless the user separately authorizes delegation.

## Workspace and preservation

- Authoritative repository: `<repo-root>`.
- `<private-setup-pack>` is a setup-pack source, not the repository.
- Local CAD test root: `<private-cad-root>`.
- Read applicable AGENTS.md, workspace rules, and relevant workflow skills. Record branch, HEAD, worktree, and pre-existing modifications before editing. Use the project virtual environment and established test commands.
- Preserve all pending UI/UX recovery changes and other user work. Do not reset, clean, stash, switch branches destructively, or silently substitute a different baseline. Do not assume a branch from an old report still exists or is current.
- Prefer the current valid working context when changes depend on pending work. If isolation is needed, preserve those dependencies explicitly; never create an isolated worktree that silently omits the UI or backend under test.
- Locate the exact test filenames under the local CAD root; inspect <private-testing-set-4> if present, but do not assume these newly supplied files are already there. If necessary inspect available TestingSet-* folders. Report the exact local source folder. Do not move, overwrite, or rename the user's sets. Future new test sets must use a new sequential folder after the current stage; never recycle a previous set.
- Never stage, track, upload, or embed user DXF/DWG files, extracted CAD metadata, or coordinate dumps in GitHub artifacts. Keep real-file outputs and sensitive traces outside the repository. Do not disable existing CAD privacy guards. Use generated synthetic geometry in automated tests; follow the project's no-tracked-CAD policy even for synthetic files.

## Verified evidence and reported baseline

The supplied reference is `sq_ref_test.dxf`: ten disconnected 50 x 50 squares, represented by 40 LINE entities. The submitted geometry was independently checked: every present edge matches the reference at the original coordinates. `sq_10-10_test.dxf` contains ten closed four-edge LWPOLYLINE entities with the same geometry as the forty-LINE reference. Other student files contain LINE entities only. All model-space entities use layer 0, and the files share INSUNITS=5. No alignment, scale correction, or forgiveness of inaccurate geometry is needed for this particular set.

Reported DL results below come from Test_Comments.pdf; they are not fresh runtime measurements. Reproduce them against the actual current code before attributing causes. If they differ, report current behavior honestly and proceed against the contract.

| File | Complete squares | Partial square edges | Entirely absent squares | Reported DL total |
|---|---:|---|---:|---:|
| sq_10-40_test.dxf | 10 | none | 0 | 100 |
| sq_10-10_test.dxf | 10 | none | 0 | 27.7 |
| sq_09-36_test.dxf | 9 | none | 1 | 80 |
| sq_09-35_test.dxf | 8 | one object with 3 of 4 edges | 1 | 75 |
| sq_09-34_test.dxf | 8 | one object with 2 of 4 edges | 1 | 95 |
| sq_08-32_test.dxf | 8 | none | 2 | 95 |
| sq_05-20_test.dxf | 5 | none | 5 | 65.33 |
| sq_04-16_test.dxf | 4 | none | 6 | 54.67 |
| sq_04-14_test.dxf | 3 | one object with 2 of 4 edges | 6 | 49.33 |

## Grading contract for this repair

Implement a named, explicitly selected instructor policy for this exercise. Do not silently replace every existing rubric or global default. Preserve other approved policies unless a general correctness repair necessarily affects them, and document that effect.

### Object and representation semantics

1. Grade required reference objects and their geometric parts, not raw DXF entity counts.
2. In geometry-equivalence mode, four connected LINE entities and one equivalent closed polyline receive identical geometry/completion credit. Respect the polyline closing segment, direction, starting vertex, tolerances, and supported coordinate/extrusion handling.
3. Retain original entity identities for evidence and overlay selection. A normalized edge is not necessarily a raw CAD entity. Do not make deductions depend on whether an edge was split into multiple collinear entities.
4. Reference grouping determines object budgets. An incomplete student object must still map to its intended reference object; splitting its geometry must not make it disappear from grading or create extra object budgets. Use deterministic one-to-one matching at the appropriate levels; repeated squares cannot reuse one student object to satisfy multiple reference objects.
5. Do not extrapolate the simple disconnected-square grouping rule into a new universal semantic classifier. Preserve established grouping/tagging behavior for touching architectural objects, holes, blocks, and supported curved geometry. Do not flatten arcs into straight edges or add scale/rotation forgiveness to pass these tests.

### Instructor square policy

Weights: Geometry 65, Completion 25, File quality 10. Ten equal reference objects; each has 6.5 geometry marks and 2.5 completion marks, a combined object budget of 9.

- Entirely absent square: loses its allocated 9 marks. Its four absent edges are not separately deducted again.
- Present partial square: configurable fixed TOTAL deduction `p` per missing required geometric edge, default 1 mark for this test profile. Count only absent edges within partial objects here.
- Complete accurate square: earns its full object budget.
- Do not label an absent square as a measured dimensional/accuracy defect. Report absence and unearned allocated marks explicitly.
- Use 44 for sq_04-14_test.dxf, correcting the instructor table's 43; the stated policy gives 100 - 6*9 - 2*1 = 44. Comment A3's 94.5 is an arithmetic inconsistency, not an acceptance target.

For the accurate geometry in this set, expected total is:
`G = 100 - 9*M - p*E`, where M counts entirely absent squares and E counts absent edges in partial squares only. This expression assumes a separately validated file-quality award of 10.

Category allocation, made explicit for this working profile: distribute a partial object's TOTAL deduction between Geometry and Completion in their 65:25 ratio. For object i with combined budget B_i=9, let D_i=0 for complete geometry, B_i for an absent object, and min(B_i, p*missing_required_parts_i) for a partial object. Its earned geometry is 6.5*(1-D_i/B_i); its earned completion is 2.5*(1-D_i/B_i). This is a coverage-adjusted geometry award; do not present it as accuracy measured only on submitted parts. Document this category choice as the proposed profile allocation for instructor/Codex review. Do not invent a second deduction on top of it. Integrate independent genuine geometry defects through the existing causal rules with explicit caps and no duplicate penalties; absence is not evidence of an extra dimensional defect.

Cap deductions at each object's available budget. Validate p is finite and nonnegative, and cap partial losses so removing the final correct part cannot increase the grade. Test p=0.25, 0.5, and 1. Preserve full precision internally, round once for presentation, and make displayed category values and total reconcile under a documented rounding rule.

File quality remains separately assessed, never automatically awarded for any uploaded or empty file. Preserve existing handling of corrupt, empty, unsupported, or incompatible input, with visible status rather than fabricated grades.

Expected totals for this named profile, p=1 and file quality=10:

| File | Required total |
|---|---:|
| sq_10-40_test.dxf | 100 |
| sq_10-10_test.dxf | 100 |
| sq_09-36_test.dxf | 91 |
| sq_09-35_test.dxf | 90 |
| sq_09-34_test.dxf | 89 |
| sq_08-32_test.dxf | 82 |
| sq_05-20_test.dxf | 55 |
| sq_04-16_test.dxf | 46 |
| sq_04-14_test.dxf | 44 |

Do not hardcode filenames, object counts, square sizes, or these outputs into the production scorer. Budgets come from the approved reference/rubric.

### Separate alternative policy

Keep proportional completion distinct from this instructor profile. If supported or added, equal required edges across this 90-mark content budget each carry 2.25 marks. Its expected totals are 88.75 for 09-35, 86.50 for 09-34, and 41.50 for 04-14. Never mix proportional deductions with fixed per-edge deductions or describe them as the same policy. Avoid expanding scope just to implement an unnecessary second policy.

### Connectivity and construction requirements

- Geometric connectivity: whether required endpoints meet and required loops close within tolerance.
- Entity construction: whether the student used joined/closed polylines as an explicitly required technique.
- Four separate LINEs can be geometrically connected and closed. Do not penalize them merely for being separate entities.
- Provide or reuse an explicit instructor option for geometry-only acceptance versus a defined closed-polyline construction requirement. Do not infer construction requirements from the reference entity type.
- One missing edge may produce an open-loop finding, but that consequence must not automatically create another connectivity/closure deduction. Link dependent findings to one causal deduction.
- A genuine endpoint gap in otherwise present geometry is a separate case to test, not proof of an absent whole square.
- Improve necessary labels/help so the UI distinguishes these concepts, using instructor-friendly wording. This is a focused correction, not a UI redesign.

## Implementation sequence

1. Inspect current code and effective rubric configuration. Run the local cases and save baseline observations privately. Trace parse -> normalization -> grouping -> matching -> findings -> scoring -> API -> UI/PDF, as relevant. Verify reference/rubric identities, cached state, policy parameters, alignment mode, and approval state.
2. Identify actual causes with code locations and runtime evidence. Do not guess that all differences share one cause.
3. Add focused synthetic regression tests that fail on current defects. Do not encode incorrect current outputs as expected behavior.
4. Implement the smallest coherent general repair and named grading profile. Reuse existing configuration and approval mechanisms. Persist profile parameters in the approved rubric; changing profile/weights/deductions/construction settings must invalidate approval and stale results through established server-authoritative mechanisms.
5. Run targeted tests, real local test set, and required regressions. Trace the effective rubric for every result; identical settings must remain identical across submissions.
6. Verify the actual UI/API flow, findings, object counts, totals, overlay linkage, and PDF where affected. If browser acceptance is unavailable, state that explicitly and leave the overall verification blocked rather than declaring complete PASS.
7. Self-audit the final diff and privacy policy, then produce the Codex handoff. Leave all changes uncommitted.

## Mandatory verification

- Both full submissions earn 100 in geometry-equivalence mode; test the reverse representation too (polyline reference, LINE student), mixed representation, reordered entities/vertices, reversed directions, and split collinear edges without creating additional required parts.
- All nine exact expected totals pass under the named instructor profile; include geometry/completion/file-quality breakdowns and causal deduction evidence.
- Deleting correct geometry cannot increase a score under unchanged settings. Test the chain 40 -> 36 -> 35 -> 34 -> 32 -> 20 -> 16 -> 14 and targeted deletions through 4, 3, 2, 1, 0 edges of one reference object.
- A complete missing square is charged once; partial missing edges are charged once; diagnostic connectivity findings do not repeat those deductions.
- Test repeated identical squares and disconnected fragments with one-to-one assignment, no reused student matches, no forced inaccurate pairings that conceal absence, and no dependence on file/entity order.
- Test a genuine wrong length, wrong angle, endpoint gap, moved object in both existing placement modes, extra edge, and duplicate edge. Retain intended penalties and privacy protections. Do not make the new scorer accept every square-shaped input as correct.
- Verify equal allocations generalize beyond ten objects and a 50-unit side. Run focused regressions for circles, partial ellipses (Issue #5), dimensions, translations, unit mismatch handling, approved rubric invalidation, and the pending UI/UX integration.
- Execute the project's required full suite, relevant syntax/compile checks, and git diff --check. Report pre-existing failures separately; do not weaken tests or globally suppress warnings to achieve PASS.
- Validate the working diff and index contain no user CAD files or sensitive extracted content. Do not stage files just to perform this check.

## Deliverables and final status

Create a sanitized in-repository handoff at `docs/verification/ag-square-grading-repair-2026-10-16.md` if consistent with repository conventions. Keep local CAD paths, metadata, raw coordinates, screenshots/PDFs derived from private CAD, and raw traces in a private external run directory instead. The public-safe handoff should contain:

- Branch/HEAD/worktree and pre-existing work preserved.
- Root causes with code locations and concise evidence.
- Files changed and the effective named policy, including proposed category allocation.
- Before/expected/after table with category totals and object classifications for all nine cases.
- Exact test commands, pass/fail/skip counts, and browser/PDF status.
- Privacy gate and remaining risks or blockers.
- A compact reproduction/checklist for independent Codex audit.

Final response: verdict READY FOR CODEX AUDIT or BLOCKED; concise causes and changes; test table; handoff path; pending instructor policy assumptions; explicit confirmation that no commit/push/merge was performed. READY FOR CODEX AUDIT is not release approval. Do not claim tests you did not run. Do not change the test contract simply to match existing outputs.
