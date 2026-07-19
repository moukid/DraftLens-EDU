"use strict";

const state = {
  reference: null,
  student: null,
  referenceId: null,
  referenceCanContinue: false,
  provisionalRubric: null,
  rubricId: null,
  review: null,
  selectedIssueId: null,
  filter: "all",
  loading: false,
};

const byId = (id) => document.getElementById(id);
const referenceInput = byId("reference-file");
const studentInput = byId("student-file");
const fallbackInput = byId("fallback-mode");
const completionPolicyInput = byId("completion-scoring-mode");
const approveButton = byId("approve-rubric");
const reviewButton = byId("run-review");

referenceInput.addEventListener("change", () => inspectReference(referenceInput.files[0] || null));
studentInput.addEventListener("change", () => selectStudent(studentInput.files[0] || null));
fallbackInput.addEventListener("change", updateReviewAvailability);
approveButton.addEventListener("click", approveRubric);
reviewButton.addEventListener("click", runReview);
completionPolicyInput.addEventListener("change", () => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.completion_scoring_mode = completionPolicyInput.value;
  renderCompletionPolicySummary(completionPolicyInput.value);
  markRubricDirty();
});
byId("rubric-name").addEventListener("input", (event) => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.title = event.target.value;
  markRubricDirty();
});
document.querySelectorAll("[data-tolerance]").forEach((input) => {
  input.addEventListener("input", () => {
    if (!state.provisionalRubric) return;
    const value = Number(input.value);
    if (Number.isFinite(value) && value >= 0) {
      state.provisionalRubric.tolerances[input.dataset.tolerance] = value;
      markRubricDirty();
    }
  });
});
document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => setFilter(button.dataset.filter));
});
byId("drawing-viewport").addEventListener("click", (event) => {
  const visual = event.target.closest("[data-issue-id]");
  if (visual) selectIssue(visual.getAttribute("data-issue-id"), true);
});

function uploadForm(field, file) {
  const form = new FormData();
  form.append(field, file, file.name);
  return form;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let body = {};
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "The request could not be completed.";
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return body;
}

function clearChildren(element) {
  element.replaceChildren();
}

function setWorkflowStatus(message, tone = "neutral") {
  const element = byId("workflow-status");
  element.textContent = message;
  element.className = "status-pill " + tone;
}

function setLoading(loading, message) {
  state.loading = loading;
  document.body.classList.toggle("is-loading", loading);
  referenceInput.disabled = loading;
  studentInput.disabled = loading;
  fallbackInput.disabled = loading || Boolean(state.rubricId);
  completionPolicyInput.disabled = loading || Boolean(state.rubricId);
  reviewButton.textContent = loading && message === "review" ? "Generating review…" : "Generate visual review";
  approveButton.textContent = loading && message === "approval" ? "Approving…" : "Approve rubric";
  updateWeightTotal();
  updateReviewAvailability();
}

function showError(error) {
  const element = byId("api-error");
  let message = error && error.message ? error.message : "The request could not be completed.";
  if (error && error.status === 409 && message.includes("No approved rubric")) {
    message = "No approved rubric is associated with this reference. Approve the rubric above or explicitly enable fallback mode.";
  } else if (error && error.status === 422 && message.includes("Invalid or unsupported DXF")) {
    message = "This file is not a valid supported DXF. Check the export and try again.";
  } else if (error && error.status === 409 && message.includes("not associated")) {
    message = "The selected rubric belongs to another reference drawing. Re-analyze and approve this reference.";
  } else if (error && error.status === 409 && message.includes("not approved")) {
    message = "The selected rubric is not approved. Review and approve it before grading.";
  }
  element.textContent = message;
  element.hidden = false;
  setWorkflowStatus("Action required", "danger");
}

function hideError() {
  const element = byId("api-error");
  element.textContent = "";
  element.hidden = true;
}

function resetReview() {
  state.review = null;
  state.selectedIssueId = null;
  state.filter = "all";
  byId("review-results").hidden = true;
  byId("review-placeholder").hidden = false;
  clearChildren(byId("drawing-viewport"));
  clearChildren(byId("issue-list"));
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === "all";
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function resetReferenceDependentState() {
  state.referenceId = null;
  state.referenceCanContinue = false;
  state.provisionalRubric = null;
  state.rubricId = null;
  state.student = null;
  studentInput.value = "";
  byId("student-name").textContent = "Choose a .dxf file";
  fallbackInput.checked = false;
  fallbackInput.disabled = false;
  completionPolicyInput.disabled = false;
  byId("completion-policy-summary").textContent = "";
  byId("analysis-summary").hidden = true;
  byId("rubric-editor").hidden = true;
  byId("rubric-empty").hidden = false;
  byId("rubric-status").textContent = "";
  resetReview();
}

async function inspectReference(file) {
  hideError();
  resetReferenceDependentState();
  state.reference = file;
  byId("reference-name").textContent = file ? file.name : "Choose a .dxf file";
  if (!file) {
    byId("validation-status").className = "validation-state neutral";
    byId("validation-status").textContent = "Not analyzed";
    byId("validation-message").textContent = "Upload a reference to inspect entities, extents, and validation findings.";
    setWorkflowStatus("Waiting for reference");
    updateReviewAvailability();
    return;
  }

  setLoading(true, "reference");
  setWorkflowStatus("Analyzing reference", "working");
  byId("validation-status").className = "validation-state working";
  byId("validation-status").textContent = "Analyzing";
  byId("validation-message").textContent = "Running deterministic validation and assignment analysis.";

  try {
    const [validationResponse, analysis, suggestion] = await Promise.all([
      requestJson("/api/reference/validate", {method: "POST", body: uploadForm("reference", file)}),
      requestJson("/api/assignment/analyze", {method: "POST", body: uploadForm("reference", file)}),
      requestJson("/api/rubric/suggest", {method: "POST", body: uploadForm("reference", file)}),
    ]);
    const validation = validationResponse.validation;
    state.referenceId = suggestion.reference_id;
    state.referenceCanContinue = Boolean(validation.can_continue);
    state.provisionalRubric = JSON.parse(JSON.stringify(suggestion.rubric));
    renderValidation(validation);
    renderAnalysis(analysis, validation);
    renderRubricEditor();
    setWorkflowStatus(
      validation.can_continue ? "Reference ready for rubric approval" : "Reference has critical issues",
      validation.can_continue ? "success" : "danger"
    );
  } catch (error) {
    state.reference = null;
    referenceInput.value = "";
    byId("reference-name").textContent = "Choose a .dxf file";
    byId("validation-status").className = "validation-state danger";
    byId("validation-status").textContent = "Reference rejected";
    byId("validation-message").textContent = "The reference could not be analyzed.";
    showError(error);
  } finally {
    setLoading(false);
  }
}

function renderValidation(validation) {
  const critical = Number(validation.summary.critical || 0);
  const warnings = Number(validation.summary.warnings || 0);
  const status = byId("validation-status");
  status.className = "validation-state " + (critical ? "danger" : warnings ? "warning" : "success");
  status.textContent = critical ? "Critical issues found" : warnings ? "Ready with warnings" : "Reference valid";
  byId("validation-message").textContent = critical
    ? critical + " critical issue(s) must be corrected before grading."
    : warnings
      ? warnings + " warning(s) require instructor review before rubric approval."
      : "The reference passed deterministic validation.";
}

function renderAnalysis(analysis, validation) {
  byId("analysis-summary").hidden = false;
  byId("analysis-type").textContent = humanize(analysis.likely_assignment_type);
  byId("analysis-entities").textContent = String(
    Object.values(analysis.entity_counts || {}).reduce((total, count) => total + Number(count || 0), 0)
  );
  byId("analysis-warnings").textContent = String(validation.summary.warnings || 0);
  byId("analysis-critical").textContent = String(validation.summary.critical || 0);
  const features = byId("analysis-features");
  clearChildren(features);
  const values = analysis.detected_features && analysis.detected_features.length
    ? analysis.detected_features
    : ["No repeated structural features detected"];
  values.forEach((feature) => {
    const item = document.createElement("li");
    item.textContent = feature;
    features.append(item);
  });
}

function renderRubricEditor() {
  const rubric = state.provisionalRubric;
  if (!rubric) return;
  byId("rubric-empty").hidden = true;
  byId("rubric-editor").hidden = false;
  byId("rubric-name").value = rubric.title || "";
  completionPolicyInput.value = rubric.completion_scoring_mode || "rule_based";
  completionPolicyInput.disabled = Boolean(state.rubricId);
  renderCompletionPolicySummary(completionPolicyInput.value);
  const categories = byId("rubric-categories");
  clearChildren(categories);
  rubric.categories.forEach((category, index) => {
    const row = document.createElement("label");
    row.className = "rubric-row";
    const name = document.createElement("span");
    name.textContent = category.name;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.value = String(category.weight);
    input.dataset.categoryIndex = String(index);
    const suffix = document.createElement("span");
    suffix.textContent = "%";
    row.append(name, input, suffix);
    input.addEventListener("input", () => {
      const value = Number(input.value);
      if (Number.isFinite(value) && value >= 0 && value <= 100) {
        rubric.categories[index].weight = value;
        rubric.categories[index].max_deduction = value;
        markRubricDirty();
      } else {
        updateWeightTotal();
      }
    });
    categories.append(row);
  });
  Object.entries(rubric.tolerances || {}).forEach(([key, value]) => {
    const input = document.querySelector("[data-tolerance='" + key + "']");
    if (input) input.value = String(value);
  });
  byId("rubric-status").textContent = state.referenceCanContinue
    ? "Instructor approval is required before review."
    : "Correct critical reference issues before approving this rubric.";
  updateWeightTotal();
}

function completionPolicyLabel(mode) {
  return mode === "proportional" ? "Proportional completion" : "Rule-based deductions";
}

function completionPolicyDescription(mode) {
  return mode === "proportional"
    ? "Missing-item rule deductions are suppressed; the completion category deducts in proportion to unfinished required geometry."
    : "Enabled issue rules apply directly; the completion percentage is informational and adds no separate deduction.";
}

function renderCompletionPolicySummary(mode) {
  byId("completion-policy-summary").textContent = completionPolicyDescription(mode);
}


function rubricWeightTotal() {
  if (!state.provisionalRubric) return 0;
  return state.provisionalRubric.categories.reduce((sum, category) => sum + Number(category.weight || 0), 0);
}

function updateWeightTotal() {
  const total = rubricWeightTotal();
  const display = byId("weight-total");
  display.textContent = formatNumber(total) + "%";
  const valid = Math.abs(total - 100) <= 0.001;
  display.classList.toggle("invalid", !valid);
  approveButton.disabled = state.loading || !state.provisionalRubric || !state.referenceCanContinue || !valid;
}

function markRubricDirty() {
  if (state.rubricId) {
    state.rubricId = null;
    fallbackInput.disabled = false;
    completionPolicyInput.disabled = false;
  }
  if (state.provisionalRubric) state.provisionalRubric.approved = false;
  byId("rubric-status").textContent = "Changes require instructor approval.";
  updateWeightTotal();
  updateReviewAvailability();
}

async function approveRubric() {
  if (!state.provisionalRubric || !state.referenceId || approveButton.disabled) return;
  hideError();
  setLoading(true, "approval");
  setWorkflowStatus("Approving rubric", "working");
  try {
    const response = await requestJson("/api/rubric/approve", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({reference_id: state.referenceId, rubric: state.provisionalRubric}),
    });
    state.rubricId = response.rubric_id;
    state.provisionalRubric = JSON.parse(JSON.stringify(response.rubric));
    fallbackInput.checked = false;
    fallbackInput.disabled = true;
    completionPolicyInput.disabled = true;
    byId("rubric-status").textContent = "Approved and associated. Completion policy: " + completionPolicyLabel(state.provisionalRubric.completion_scoring_mode) + ".";
    setWorkflowStatus("Rubric approved — add student drawing", "success");
  } catch (error) {
    showError(error);
  } finally {
    setLoading(false);
  }
}

function selectStudent(file) {
  hideError();
  state.student = file;
  byId("student-name").textContent = file ? file.name : "Choose a .dxf file";
  resetReview();
  updateReviewAvailability();
  if (file) {
    setWorkflowStatus(canRunReview() ? "Ready to generate review" : "Student loaded — rubric approval required", canRunReview() ? "success" : "warning");
  }
}

function canRunReview() {
  return Boolean(
    state.reference &&
    state.student &&
    state.referenceCanContinue &&
    (state.rubricId || fallbackInput.checked)
  );
}

function updateReviewAvailability() {
  reviewButton.disabled = state.loading || !canRunReview();
}

async function runReview() {
  if (!canRunReview()) return;
  hideError();
  setLoading(true, "review");
  setWorkflowStatus("Generating deterministic review", "working");
  const form = new FormData();
  form.append("reference", state.reference, state.reference.name);
  form.append("student", state.student, state.student.name);
  if (state.rubricId) form.append("rubric_id", state.rubricId);
  if (fallbackInput.checked && !state.rubricId) form.append("allow_fallback", "true");

  try {
    state.review = await requestJson("/api/review", {method: "POST", body: form});
    renderResults(state.review);
    setWorkflowStatus("Review complete", "success");
  } catch (error) {
    resetReview();
    showError(error);
  } finally {
    setLoading(false);
  }
}

function renderResults(review) {
  byId("review-placeholder").hidden = true;
  byId("review-results").hidden = false;
  byId("result-score").textContent = formatNumber(review.score);
  byId("result-units").textContent = review.units || "unitless";
  byId("result-issues").textContent = String(review.issues.length);
  const unsupported = [
    ...((review.unsupported_entities && review.unsupported_entities.reference) || []),
    ...((review.unsupported_entities && review.unsupported_entities.student) || []),
  ];
  byId("result-unsupported").textContent = String(unsupported.length);
  const source = humanize(review.rubric_selection && review.rubric_selection.source);
  const completionMode = review.completion_scoring_mode || review.rubric.completion_scoring_mode || "rule_based";
  byId("result-rubric").textContent = (review.rubric.title || "Applied rubric") + " · " + source + " · " + completionPolicyLabel(completionMode);
  renderScoreBreakdown(review, completionMode);
  const critical = review.issues.filter((issue) => issue.severity === "critical").length;
  byId("critical-summary").textContent = critical ? critical + " critical issue(s)" : "No critical issues";
  renderSafeSvg(review.svg);
  state.filter = "all";
  state.selectedIssueId = null;
  setFilter("all");
  if (review.issues.length) selectIssue(review.issues[0].issue_id, false);
  byId("review-results").scrollIntoView();
}
function renderScoreBreakdown(review, completionMode) {
  const breakdown = review.score_breakdown || {};
  const categories = breakdown.category_subtotals || [];
  const container = byId("score-breakdown-categories");
  clearChildren(container);
  categories.forEach((category) => {
    const row = document.createElement("div");
    row.className = "score-breakdown-row";
    const name = document.createElement("strong");
    name.textContent = category.name || humanize(category.id);
    const detail = document.createElement("span");
    detail.className = "score-breakdown-values";
    detail.textContent =
      "Earned " + formatNumber(category.score) + " / " + formatNumber(category.weight) +
      " · Applied " + formatDeduction(category.deduction);
    row.append(name, detail);
    container.append(row);
  });
  byId("result-applied-deduction").textContent = formatDeduction(breakdown.total_applied_deduction);
  byId("result-final-score").textContent = formatNumber(breakdown.final_score) + " / 100";
  byId("result-policy").textContent = completionPolicyLabel(completionMode) + ". " + completionPolicyDescription(completionMode);
}



function isUnsafeUrlValue(value) {
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("javascript:") || normalized.includes("data:text/html")) return true;
  if (normalized.includes("url(")) return !/^url\(\s*#[a-z0-9_.:-]+\s*\)$/i.test(normalized);
  return false;
}

function sanitizeSvgDocument(documentNode) {
  const root = documentNode.documentElement;
  const blockedElements = new Set(["script", "foreignobject", "iframe", "object", "embed", "image", "link", "audio", "video"]);
  [...root.querySelectorAll("*")].forEach((node) => {
    if (blockedElements.has(node.localName.toLowerCase())) node.remove();
  });
  const elements = [root, ...root.querySelectorAll("*")];
  elements.forEach((element) => {
    [...element.attributes].forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      const value = attribute.value;
      if (name.startsWith("on") || isUnsafeUrlValue(value)) {
        element.removeAttribute(attribute.name);
        return;
      }
      if (name === "href" || name === "xlink:href" || name === "src") {
        if (!value.trim().startsWith("#")) element.removeAttribute(attribute.name);
      }
      if (name === "style" && /(?:@import|expression\s*\(|javascript:|url\s*\()/i.test(value)) {
        element.removeAttribute(attribute.name);
      }
    });
  });
  root.querySelectorAll("style").forEach((style) => {
    if (/(?:@import|expression\s*\(|javascript:|url\s*\()/i.test(style.textContent || "")) style.remove();
  });
  return root;
}

function renderSafeSvg(markup) {
  const parser = new DOMParser();
  const documentNode = parser.parseFromString(String(markup || ""), "image/svg+xml");
  if (documentNode.querySelector("parsererror") || documentNode.documentElement.localName !== "svg") {
    throw new Error("The reviewed drawing SVG could not be displayed safely.");
  }
  const sanitized = sanitizeSvgDocument(documentNode);
  sanitized.classList.add("reviewed-svg");
  const imported = document.importNode(sanitized, true);
  byId("drawing-viewport").replaceChildren(imported);
}

function setFilter(filter) {
  state.filter = filter || "all";
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  renderIssueList();
}

function renderIssueList() {
  const list = byId("issue-list");
  clearChildren(list);
  if (!state.review) {
    byId("issue-empty").hidden = true;
    return;
  }
  const visible = state.review.issues.filter((issue) => state.filter === "all" || issue.visual_role === state.filter);
  byId("issue-empty").hidden = visible.length !== 0;
  visible.forEach((issue) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "issue-card role-" + safeClass(issue.visual_role);
    button.dataset.issueId = issue.issue_id;
    button.setAttribute("aria-pressed", String(issue.issue_id === state.selectedIssueId));
    if (issue.issue_id === state.selectedIssueId) button.classList.add("is-selected");

    const top = document.createElement("span");
    top.className = "issue-card-top";
    const category = document.createElement("strong");
    category.textContent = humanize(issue.category);
    const identity = document.createElement("span");
    identity.textContent = issue.issue_id;
    top.append(category, identity);

    const feedback = document.createElement("span");
    feedback.className = "issue-card-message";
    feedback.textContent = issue.technical_feedback;
    const evidence = document.createElement("span");
    evidence.className = "issue-card-evidence";
    evidence.textContent = humanize(issue.severity) + " · Applied: " + formatDeduction(appliedDeduction(issue));
    const deductionDetail = document.createElement("span");
    deductionDetail.className = "issue-card-deduction";
    deductionDetail.textContent = formatDeductionDetail(issue);
    button.append(top, feedback, evidence, deductionDetail);
    button.addEventListener("click", () => selectIssue(issue.issue_id, true));
    list.append(button);
  });
}

function selectIssue(issueId, scrollList) {
  if (!state.review) return;
  const issue = state.review.issues.find((item) => item.issue_id === issueId);
  if (!issue) return;
  state.selectedIssueId = issueId;
  renderIssueList();
  document.querySelectorAll("#drawing-viewport [data-issue-id]").forEach((element) => {
    element.classList.toggle("is-selected", element.getAttribute("data-issue-id") === issueId);
  });
  renderFeedback(issue);
  if (scrollList) {
    const card = document.querySelector("#issue-list [data-issue-id='" + cssEscape(issueId) + "']");
    if (card) card.scrollIntoView({block: "nearest"});
  }
}

function renderFeedback(issue) {
  byId("feedback-empty").hidden = true;
  byId("feedback-detail").hidden = false;
  byId("feedback-severity").textContent = humanize(issue.severity);
  byId("feedback-severity").className = "severity-chip severity-" + safeClass(issue.severity);
  byId("feedback-id").textContent = issue.issue_id;
  byId("feedback-category").textContent = humanize(issue.category);
  byId("feedback-text").textContent = issue.technical_feedback;
  byId("evidence-expected").textContent = issue.expected_entity_id || "Not applicable";
  byId("evidence-actual").textContent = issue.source_entity_id || "Not applicable";
  byId("evidence-measurement").textContent = formatMeasurement(issue.measurement);
  byId("evidence-rule").textContent = issue.rubric_rule_id || "Validation finding";
  byId("evidence-deduction").textContent = formatDeduction(appliedDeduction(issue));
  byId("evidence-raw-deduction").textContent = formatDeduction(rawDeduction(issue));
  byId("evidence-deduction-status").textContent = deductionStatusText(issue);
  byId("evidence-confidence").textContent = humanize(issue.confidence);

  const commands = commandsForIssue(issue);
  const commandBox = byId("feedback-commands");
  const commandList = byId("command-list");
  clearChildren(commandList);
  commands.forEach((command) => {
    const item = document.createElement("li");
    item.textContent = command;
    commandList.append(item);
  });
  commandBox.hidden = commands.length === 0;
}

function commandsForIssue(issue) {
  const categories = state.review && state.review.rubric ? state.review.rubric.categories || [] : [];
  for (const category of categories) {
    const rule = (category.rules || []).find((item) => item.id === issue.rubric_rule_id);
    if (rule) return Array.isArray(rule.commands) ? rule.commands : [];
  }
  return [];
}

function formatMeasurement(measurement) {
  if (measurement === null || measurement === undefined) return "No numeric measurement";
  if (typeof measurement !== "object") return String(measurement);
  const entries = Object.entries(measurement);
  if (!entries.length) return "No numeric measurement";
  return entries.map(([key, value]) => humanize(key) + ": " + formatEvidenceValue(value)).join(" · ");
}

function formatEvidenceValue(value) {
  if (typeof value === "number") return formatNumber(value);
  if (Array.isArray(value)) return value.map(formatEvidenceValue).join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value).map(([key, nested]) => humanize(key) + " " + formatEvidenceValue(nested)).join(", ");
  }
  return String(value ?? "—");
}

function appliedDeduction(issue) {
  return Number(issue.applied_deduction ?? issue.deduction ?? 0);
}

function rawDeduction(issue) {
  return Number(issue.raw_deduction ?? issue.deduction ?? 0);
}

function deductionStatusText(issue) {
  if (issue.suppression_reason) return "Suppressed: " + issue.suppression_reason;
  if (issue.deduction_status === "capped") return "Capped by rubric limits";
  if (appliedDeduction(issue) > 0) return "Applied";
  return "Not scored";
}

function formatDeductionDetail(issue) {
  return (
    "Raw rule: " + formatDeduction(rawDeduction(issue)) +
    " | Applied: " + formatDeduction(appliedDeduction(issue)) +
    " | " + deductionStatusText(issue)
  );
}


function formatDeduction(value) {
  const number = Number(value || 0);
  return number > 0 ? "−" + formatNumber(number) + " points" : "No deduction";
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function humanize(value) {
  return String(value || "not specified").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function safeClass(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

updateWeightTotal();
updateReviewAvailability();
