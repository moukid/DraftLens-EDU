# DraftLens EDU — AI Development Protocol v1.2

## 1. Mission

Complete DraftLens EDU with minimum duplicated AI work and minimized Codex token consumption while preserving grading correctness, deterministic behavior, data privacy, regression safety, and traceability.

## 2. Operating Model (Two-Agent Architecture)

**Antigravity builds and verifies. Codex audits mature milestones.**

Development is restricted to two primary agents:
- **Antigravity (AG)**: Primary engineering worker and development manager.
- **Codex**: Independent milestone and release-candidate auditor only.
- **Excluded**: Hermes, OpenCode, DeepSeek Harness, and OmniRoute are excluded from the active development pipeline.

### Antigravity — Primary Worker & Owner
Owns day-to-day execution:
- Inspecting codebase and current task state.
- Implementing features, bug fixes, and documentation.
- Running targeted tests and full regression suites.
- Debugging implementation failures locally.
- Enforcing CAD privacy and repository hygiene.
- Maintaining the compact handoff file (`docs/AI_HANDOFF.md`).
- Preparing bounded audit packages for Codex.
- Escalating to the user before major architectural or grading semantic changes.

Antigravity must complete tasks as far as reasonably possible before escalating.

### Codex — Independent Quality Gate
Reserved strictly for high-value milestone verification:
- Verifying mature milestone completions and release candidates.
- Auditing grading correctness and geometric invariants.
- Evaluating regression risk and test adequacy.
- Reviewing privacy, security, and repository hygiene.

Codex is **not** used for:
- Routine or iterative implementation loops.
- Broad repository exploration or file searches.
- First-pass debugging or micro-commits.
- Unstructured, long-context conversation history.

## 3. Standard Workflow Sequence

1. **Requirement / Milestone Scoped**
2. **Antigravity Implementation**
3. **Targeted Local Tests** (scoped unit/integration tests)
4. **Antigravity Repair & Regression Tests**
5. **Local CAD Acceptance** (using authorized local `TestingSet-N`)
6. **Update `docs/AI_HANDOFF.md`**
7. **Ready-for-Codex Gate Evaluated**
8. **Codex Audit Package Prepared** (via `templates/CODEX_AUDIT_REQUEST.md`)
9. **Codex Audit Executed** (returns PASS or FAIL with blockers)
10. **On FAIL**: Antigravity repairs blockers; re-audit is targeted only to failed scope.
11. **On PASS**: Milestone committed and closed.

## 4. Codex Token-Control Rules

1. Never start routine implementation with Codex.
2. Send Codex a narrow audit request, not accumulated project history.
3. Include only acceptance criteria, relevant diff/files, test evidence, known issues, and invariants.
4. Prefer one comprehensive milestone audit over multiple micro-audits.
5. On FAIL, repair with Antigravity; re-audit only the blocking scope and affected regression surface.
6. Do not ask Codex to repeat exploration already verified with reproducible evidence.
7. Keep `AGENTS.md` short and `docs/AI_HANDOFF.md` current.
8. Avoid long terminal dumps; summarize outputs and reference reproducible commands.
9. Do not request unrelated refactors during an audit.
10. Reserve Codex reasoning for material uncertainty, grading verification, and final gates.

## 5. Context Discipline

- Read the minimum context required for the current task.
- Search before opening large files.
- Prefer targeted test files before running the full test suite.
- Do not silently expand scope or perform unrelated code churn.
- Keep durable governance policy in this document; keep transient project state in `docs/AI_HANDOFF.md`.
- Consult this document on demand; do not auto-inject it into routine development prompts.

## 6. Privacy Boundary & CAD Hygiene

- **Authorized Local CAD Root**: `<private-cad-root>`
- **Testing Set Progression**: `<private-testing-set-4>`, `<private-testing-set-5>`, `<private-testing-set-6>`, etc.
- **Strict Local Isolation**: Real/private DXF/DWG test data stays strictly local. Never commit or push CAD files to GitHub.
- **Metadata Protection**: Never place usernames, student data, personal absolute paths, or CAD metadata into tracked fixtures, reports, screenshots, or logs.
- **Synthetic Fixtures**: All repository test fixtures must be synthetic, generated in external temporary directories (`tempfile.mkdtemp()`).
- **Pre-Commit Enforcement**: Always run `python scripts/check_cad_policy.py` before any commit.

## 7. Escalation Rules

Obtain explicit user approval before:
- Making major architectural changes.
- Altering grading rubrics, scoring weights, deduction logic, or tolerances.
- Modifying object-matching algorithms.
- Removing supported application behavior.
- Handling or moving potentially sensitive data outside approved local boundaries.

## 8. Ready-for-Codex Gate

Codex may only be invoked when:
- Implementation is complete for the defined milestone scope.
- Relevant automated tests have been executed with recorded results.
- Known failures or blockers are explicitly documented.
- Acceptance criteria are clearly stated.
- Working-tree diff is fully understood and verified.
- CAD privacy check has passed.
- `docs/AI_HANDOFF.md` is fully current.
- The audit package can be stated narrowly in `templates/CODEX_AUDIT_REQUEST.md`.

## 9. Priority Order

1. Grading correctness
2. Deterministic behavior
3. Student / instructor data privacy
4. Regression safety
5. Traceable evidence
6. Maintainability
7. UI polish
