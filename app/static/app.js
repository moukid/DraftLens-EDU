"use strict";

const REFERENCE_ANALYSIS_TIMEOUT_MS = 30000;
const CATEGORY_DEFINITIONS = {
  geometry: "Matched geometry, dimensions, placement, shape, and topology.",
  completion: "Required-reference coverage and explicitly incomplete expected geometry.",
  quality: "Student-file hygiene: extra, duplicate, unsupported, or invalid geometry.",
};


const state = {
  reference: null,
  student: null,
  referenceId: null,
  referenceCanContinue: false,
  suggestedAssignmentType: null,
  provisionalRubric: null,
  rubricId: null,
  review: null,
  selectedIssueId: null,
  filter: "all",
  viewMode: "review",
  loading: false,
};

const byId = (id) => document.getElementById(id);
const referenceInput = byId("reference-file");
const studentInput = byId("student-file");
const fallbackInput = byId("fallback-mode");
const completionPolicyInput = byId("completion-scoring-mode");
const normalizationModeInput = byId("normalization-mode");
const assignmentTypeInput = byId("assignment-type");
const ruleBasedOption = completionPolicyInput.querySelector('option[value="rule_based"]');
ruleBasedOption.textContent = "Rule-based completion";
const approveButton = byId("approve-rubric");
const reviewButton = byId("run-review");
const downloadReportButton = byId("download-report");
const editSetupButton = byId("edit-setup");
const downloadReportHeaderButton = byId("download-report-header");
const includeAppendixCheckbox = byId("include-appendix");
const includeAppendixHeaderCheckbox = byId("include-appendix-header");
const viewerZoomInButton = byId("viewer-zoom-in");
const viewerZoomOutButton = byId("viewer-zoom-out");
const viewerResetButton = byId("viewer-reset");
const viewerLocateButton = byId("viewer-locate-issue");
const viewerExpandButton = byId("viewer-expand");
const viewerExitExpandButton = byId("viewer-exit-expand");
const toggleTechnicalDetailsCheckbox = byId("toggle-technical-details");
const metadataInputs = [byId("student-metadata-name"), byId("student-metadata-id"), byId("course-section")];
const viewReviewButton = byId("view-review-comparison");
const viewStudentButton = byId("view-student-only");
const gradeAnywayButton = byId("grade-anyway");
const chooseAnotherFileButton = byId("choose-another-file");

const viewerNav = {
  baseX: 0,
  baseY: 0,
  baseWidth: 1000,
  baseHeight: 1000,
  currentX: 0,
  currentY: 0,
  currentWidth: 1000,
  currentHeight: 1000,
  scale: 1.0,
  minScale: 0.2,
  maxScale: 20.0,
  isDragging: false,
  startX: 0,
  startY: 0,
  startViewX: 0,
  startViewY: 0,
  totalDragDistance: 0,
  justDragged: false,
  isExpanded: false,
};
let showTechnicalDetails = false;



referenceInput.addEventListener("change", () => inspectReference(referenceInput.files[0] || null));
studentInput.addEventListener("change", () => selectStudent(studentInput.files[0] || null));
fallbackInput.addEventListener("change", updateReviewAvailability);
approveButton.addEventListener("click", approveRubric);
reviewButton.addEventListener("click", () => runReview(false));
downloadReportButton.addEventListener("click", downloadReport);
metadataInputs.forEach((input) => input.addEventListener("input", () => {
  const hadReview = Boolean(state.review);
  resetReview();
  updateReviewAvailability();
  if (hadReview) {
    setWorkflowStatus("Metadata changed - regenerate review", "warning");
  }
}));

completionPolicyInput.addEventListener("change", () => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.completion_scoring_mode = completionPolicyInput.value;
  renderCompletionPolicySummary(completionPolicyInput.value);
  markRubricDirty();
});
normalizationModeInput.addEventListener("change", () => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.normalization_mode = normalizationModeInput.value;
  renderNormalizationPolicySummary(normalizationModeInput.value);
  markRubricDirty();
});
assignmentTypeInput.addEventListener("change", () => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.assignment_type = assignmentTypeInput.value;
  markRubricDirty();
});
byId("assignment-title").addEventListener("input", (event) => {
  if (!state.provisionalRubric) return;
  state.provisionalRubric.assignment_title = event.target.value;
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
  if (viewerNav.justDragged) {
    viewerNav.justDragged = false;
    return;
  }
  if (state.viewMode === "student") return;
  const visual = event.target.closest("[data-issue-id]");
  const issueId = visual ? visual.getAttribute("data-issue-id") : viewerNav.pointerIssueId;
  if (issueId) selectIssue(issueId, true);
});
viewReviewButton.addEventListener("click", () => setDrawingViewMode("review"));
viewStudentButton.addEventListener("click", () => setDrawingViewMode("student"));
gradeAnywayButton.addEventListener("click", () => runReview(true));
chooseAnotherFileButton.addEventListener("click", () => studentInput.click());

if (editSetupButton) {
  editSetupButton.addEventListener("click", () => {
    const col = document.querySelector(".setup-column");
    const isCurrentlyCollapsed = col ? col.classList.contains("is-collapsed") : false;
    setSetupCollapsed(!isCurrentlyCollapsed);
  });
}
if (downloadReportHeaderButton) downloadReportHeaderButton.addEventListener("click", downloadReport);
if (includeAppendixCheckbox && includeAppendixHeaderCheckbox) {
  includeAppendixCheckbox.addEventListener("change", () => {
    includeAppendixHeaderCheckbox.checked = includeAppendixCheckbox.checked;
  });
  includeAppendixHeaderCheckbox.addEventListener("change", () => {
    includeAppendixCheckbox.checked = includeAppendixHeaderCheckbox.checked;
  });
}
if (viewerZoomInButton) viewerZoomInButton.addEventListener("click", () => zoomViewer(1.25));
if (viewerZoomOutButton) viewerZoomOutButton.addEventListener("click", () => zoomViewer(0.8));
if (viewerResetButton) viewerResetButton.addEventListener("click", resetViewerNav);
if (viewerLocateButton) viewerLocateButton.addEventListener("click", () => {
  if (state.selectedIssueId) locateIssueInViewer(state.selectedIssueId);
});
if (viewerExpandButton) viewerExpandButton.addEventListener("click", () => setExpandedView(true));
if (viewerExitExpandButton) viewerExitExpandButton.addEventListener("click", () => setExpandedView(false));
if (toggleTechnicalDetailsCheckbox) {
  toggleTechnicalDetailsCheckbox.addEventListener("change", () => {
    showTechnicalDetails = toggleTechnicalDetailsCheckbox.checked;
    renderIssueList();
    if (state.selectedIssueId) {
      const sel = (state.review && state.review.issues || []).find((i) => i.issue_id === state.selectedIssueId);
      if (sel) renderFeedback(sel);
    }
  });
}
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && viewerNav.isExpanded) {
      setExpandedView(false);
    }
    if (e.key === "Tab" && viewerNav.isExpanded) {
      const panel = document.querySelector(".drawing-panel");
      const controls = Array.from(panel.querySelectorAll('button:not(:disabled), summary, [tabindex="0"]'))
        .filter((el) => el.getClientRects().length > 0);
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}

const drawingViewportEl = byId("drawing-viewport");
drawingViewportEl.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || viewerNav.isDragging || !getViewportSvg()) return;
  const visual = e.target && e.target.closest("[data-issue-id]");
  viewerNav.pointerIssueId = visual ? visual.getAttribute("data-issue-id") : null;
  const matrix = getViewportSvg().getScreenCTM && getViewportSvg().getScreenCTM();
  viewerNav.dragMatrix = matrix ? matrix.inverse() : null;
  viewerNav.pointerId = e.pointerId;
  viewerNav.isDragging = true;
  viewerNav.startX = e.clientX;
  viewerNav.startY = e.clientY;
  viewerNav.startViewX = viewerNav.currentX;
  viewerNav.startViewY = viewerNav.currentY;
  viewerNav.totalDragDistance = 0;
  viewerNav.justDragged = false;
  if (typeof drawingViewportEl.setPointerCapture === "function") {
    try { drawingViewportEl.setPointerCapture(e.pointerId); } catch (_) {}
  }
});

drawingViewportEl.addEventListener("pointermove", (e) => {
  if (!viewerNav.isDragging || e.pointerId !== viewerNav.pointerId) return;
  const dx = e.clientX - viewerNav.startX;
  const dy = e.clientY - viewerNav.startY;
  const dist = Math.hypot(dx, dy);
  viewerNav.totalDragDistance = dist;
  if (dist > 5) {
    viewerNav.justDragged = true;
    drawingViewportEl.classList.add("is-panning");
  }
  if (!viewerNav.justDragged) return;
  // The inverse screen matrix accounts for preserveAspectRatio letterboxing.
  const m = viewerNav.dragMatrix;
  if (!m) return;
  viewerNav.currentX = viewerNav.startViewX - (dx * m.a + dy * m.c);
  viewerNav.currentY = viewerNav.startViewY - (dx * m.b + dy * m.d);
  applyViewBox();
});

const endViewportDrag = (e) => {
  if (!viewerNav.isDragging || e.pointerId !== viewerNav.pointerId) return;
  viewerNav.isDragging = false;
  if (typeof drawingViewportEl.releasePointerCapture === "function" && e.pointerId) {
    try { drawingViewportEl.releasePointerCapture(e.pointerId); } catch (_) {}
  }
  drawingViewportEl.classList.remove("is-panning");
  // Keep suppression until the generated click (or next pointerdown), not a timer.
};
drawingViewportEl.addEventListener("pointerup", endViewportDrag);
drawingViewportEl.addEventListener("pointercancel", endViewportDrag);
drawingViewportEl.addEventListener("lostpointercapture", endViewportDrag);

drawingViewportEl.addEventListener("keydown", (e) => {
  if (["+", "=", "-", "0", "Home", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
    e.preventDefault();
    if (e.key === "+" || e.key === "=") zoomViewer(1.25);
    else if (e.key === "-") zoomViewer(0.8);
    else if (e.key === "0" || e.key === "Home") resetViewerNav();
    else {
      viewerNav.currentX += (e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0) * viewerNav.currentWidth * .1;
      viewerNav.currentY += (e.key === "ArrowUp" ? -1 : e.key === "ArrowDown" ? 1 : 0) * viewerNav.currentHeight * .1;
      applyViewBox();
    }
  }
});

drawingViewportEl.addEventListener("wheel", (e) => {
  if (typeof e.preventDefault === "function") e.preventDefault();
  const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
  zoomViewer(zoomFactor, e.clientX, e.clientY);
}, { passive: false });

function uploadForm(field, file) {
  const form = new FormData();
  form.append(field, file, file.name);
  return form;
}

async function requestJson(url, options, timeoutMs = 0) {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timeoutId = controller
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;
  let response;
  try {
    response = await fetch(url, controller ? {...options, signal: controller.signal} : options);
  } catch (error) {
    if (error && error.name === "AbortError") {
      const timeoutError = new Error("Reference analysis exceeded 30 seconds. Try the file again or simplify unusually complex geometry.");
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw error;
  } finally {
    if (timeoutId !== null) window.clearTimeout(timeoutId);
  }
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
  normalizationModeInput.disabled = loading;
  assignmentTypeInput.disabled = loading;
  reviewButton.textContent = loading && message === "review" ? "Generating review…" : "Generate visual review";
  metadataInputs.forEach((input) => { input.disabled = loading; });
  updateReportAvailability();
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
  state.filter = "all";
  setDrawingViewMode("review");
  resetNormalizationDecision();
  byId("compatibility-card").hidden = true;
  downloadReportButton.disabled = true;
  if (downloadReportHeaderButton) downloadReportHeaderButton.disabled = true;
  byId("report-status").textContent = "Generate a review to enable its authoritative report.";
  const unsupportedNotice = byId("unsupported-notice");
  if (unsupportedNotice) unsupportedNotice.hidden = true;
  resetViewerNav();
  viewerNav.isDragging = false;
  viewerNav.justDragged = false;
  viewerNav.pointerIssueId = null;
  setExpandedView(false);
  showTechnicalDetails = false;
  if (toggleTechnicalDetailsCheckbox) toggleTechnicalDetailsCheckbox.checked = false;

  resetIssueSelection("Select an issue in the list or drawing.");
  byId("review-results").hidden = true;
  byId("review-placeholder").hidden = false;
  clearChildren(byId("drawing-viewport"));
  clearChildren(byId("issue-list"));
  byId("issue-empty").hidden = true;
  byId("finding-summary").hidden = true;
  byId("finding-summary-totals").textContent = "";
  clearChildren(byId("finding-summary-groups"));
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === "all";
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setDrawingViewMode(mode) {
  const studentOnly = mode === "student";
  state.viewMode = studentOnly ? "student" : "review";
  byId("drawing-viewport").classList.toggle("student-only-view", studentOnly);
  viewReviewButton.setAttribute("aria-pressed", String(!studentOnly));
  viewStudentButton.setAttribute("aria-pressed", String(studentOnly));
  byId("overlay-legend").hidden = studentOnly;
  byId("student-only-status").hidden = !studentOnly;
}

function resetNormalizationDecision() {
  [
    "result-normalization-mode",
    "result-transform",
    "result-applied-translation",
    "result-candidate-translation",
    "result-transform-support",
    "result-transform-ratio",
    "result-transform-confidence",
    "result-error-reduction",
    "result-transform-reason",
  ].forEach((id) => { byId(id).textContent = "—"; });
  byId("normalization-evidence").hidden = true;
  byId("result-transform-reason-row").hidden = true;
}

function resetIssueSelection(message) {
  state.selectedIssueId = null;
  if (viewerLocateButton) viewerLocateButton.disabled = true;
  document.querySelectorAll("#drawing-viewport [data-issue-id]").forEach((element) => {
    element.classList.remove("is-selected");
  });
  const empty = byId("feedback-empty");
  empty.textContent = message || "Select an issue in the list or drawing.";
  empty.hidden = false;
  byId("feedback-detail").hidden = true;
  byId("feedback-severity").textContent = "—";
  byId("feedback-severity").className = "severity-chip";
  [
    "feedback-id",
    "feedback-category",
    "feedback-text",
    "evidence-expected",
    "evidence-actual",
    "evidence-measurement",
    "evidence-rule",
    "evidence-deduction",
    "evidence-raw-deduction",
    "evidence-score-category",
    "evidence-after-rule-cap",
    "evidence-after-category-cap",
    "evidence-deduction-status",
    "evidence-confidence",
  ].forEach((id) => { byId(id).textContent = "—"; });
  resetCorrectionGuidance();
}

function resetCorrectionGuidance() {
  ["command-list", "guidance-alternatives", "guidance-precision"].forEach((id) => clearChildren(byId(id)));
  byId("guidance-primary").textContent = "—";
  byId("guidance-related-id").textContent = "—";
  byId("guidance-explanation").textContent = "";
  [
    "guidance-primary-row",
    "guidance-alternatives-row",
    "guidance-precision-row",
    "guidance-supporting-label",
    "guidance-related",
    "guidance-no-command",
  ].forEach((id) => { byId(id).hidden = true; });
  byId("feedback-commands").hidden = true;
}
function resetValidationFindings() {
  const container = byId("validation-findings");
  const list = byId("validation-findings-list");
  const count = byId("validation-findings-count");
  if (container) container.hidden = true;
  if (list) clearChildren(list);
  if (count) count.textContent = "0";
}

function resetReferenceDependentState() {
  state.referenceId = null;
  state.referenceCanContinue = false;
  state.suggestedAssignmentType = null;
  state.provisionalRubric = null;
  state.rubricId = null;
  state.student = null;
  studentInput.value = "";
  byId("student-name").textContent = "Choose a .dxf file";
  fallbackInput.checked = false;
  fallbackInput.disabled = false;
  completionPolicyInput.disabled = false;
  normalizationModeInput.disabled = false;
  assignmentTypeInput.disabled = false;
  byId("completion-policy-summary").textContent = "";
  byId("normalization-policy-summary").textContent = "";
  byId("analysis-summary").hidden = true;
  resetValidationFindings();
  byId("rubric-editor").hidden = true;
  byId("rubric-empty").hidden = false;
  byId("rubric-status").textContent = "";
  resetReview();
  updateSetupSummary();
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
    resetValidationFindings();
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
      requestJson("/api/reference/validate", {method: "POST", body: uploadForm("reference", file)}, REFERENCE_ANALYSIS_TIMEOUT_MS),
      requestJson("/api/assignment/analyze", {method: "POST", body: uploadForm("reference", file)}, REFERENCE_ANALYSIS_TIMEOUT_MS),
      requestJson("/api/rubric/suggest", {method: "POST", body: uploadForm("reference", file)}, REFERENCE_ANALYSIS_TIMEOUT_MS),
    ]);
    const validation = validationResponse.validation;
    state.referenceId = suggestion.reference_id;
    state.referenceCanContinue = Boolean(validation.can_continue);
    state.suggestedAssignmentType = suggestion.suggested_assignment_type || analysis.suggested_assignment_type;
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
    resetValidationFindings();
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

  const container = byId("validation-findings");
  const list = byId("validation-findings-list");
  const countEl = byId("validation-findings-count");
  if (!container || !list) return;

  const findings = Array.isArray(validation.findings) ? validation.findings : [];
  if (findings.length === 0) {
    container.hidden = true;
    clearChildren(list);
    if (countEl) countEl.textContent = "0";
    return;
  }

  container.hidden = false;
  if (countEl) countEl.textContent = String(findings.length);
  clearChildren(list);

  findings.forEach((finding) => {
    const item = document.createElement("li");
    const isCritical = finding.severity === "critical";
    item.className = "validation-finding-item " + (isCritical ? "is-critical" : "is-warning");

    const header = document.createElement("div");
    header.className = "validation-finding-header";

    const badge = document.createElement("span");
    badge.className = "validation-finding-badge " + (isCritical ? "danger" : "warning");
    badge.textContent = isCritical ? "Critical — Blocks reference" : "Warning — Advisory";
    header.append(badge);

    const title = document.createElement("strong");
    title.className = "validation-finding-title";
    title.textContent = finding.message || (isCritical ? "Critical reference issue" : "Reference warning");
    header.append(title);
    item.append(header);

    const metaRow = document.createElement("div");
    metaRow.className = "validation-finding-meta";
    let hasMeta = false;

    if (finding.entity_type) {
      const typeTag = document.createElement("span");
      typeTag.className = "validation-tag entity-type";
      typeTag.textContent = String(finding.entity_type);
      metaRow.append(typeTag);
      hasMeta = true;
    }
    if (finding.source_handle) {
      const handleTag = document.createElement("span");
      handleTag.className = "validation-tag entity-handle";
      handleTag.textContent = "Handle: " + String(finding.source_handle);
      metaRow.append(handleTag);
      hasMeta = true;
    }
    if (finding.layer) {
      const layerTag = document.createElement("span");
      layerTag.className = "validation-tag entity-layer";
      layerTag.textContent = "Layer: " + String(finding.layer);
      metaRow.append(layerTag);
      hasMeta = true;
    }
    if (hasMeta) {
      item.append(metaRow);
    }

    if (finding.explanation) {
      const explP = document.createElement("p");
      explP.className = "validation-finding-explanation";
      explP.textContent = finding.explanation;
      item.append(explP);
    }

    if (finding.suggested_correction) {
      const corrDiv = document.createElement("div");
      corrDiv.className = "validation-finding-correction";
      const corrLabel = document.createElement("strong");
      corrLabel.textContent = "Suggested action: ";
      const corrText = document.createElement("span");
      corrText.textContent = finding.suggested_correction;
      corrDiv.append(corrLabel, corrText);
      item.append(corrDiv);
    }

    list.append(item);
  });
}

function renderAnalysis(analysis, validation) {
  byId("analysis-summary").hidden = false;
  byId("analysis-type").textContent = analysis.suggested_assignment_type || humanize(analysis.likely_assignment_type);
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
  byId("assignment-title").value = rubric.assignment_title || "Assignment";
  assignmentTypeInput.value = rubric.assignment_type || state.suggestedAssignmentType || "Geometric Construction Exercise";
  rubric.assignment_type = assignmentTypeInput.value;
  assignmentTypeInput.disabled = state.loading;
  normalizationModeInput.value = rubric.normalization_mode || "strict";
  normalizationModeInput.disabled = state.loading;
  renderNormalizationPolicySummary(normalizationModeInput.value);
  completionPolicyInput.value = rubric.completion_scoring_mode || "rule_based";
  completionPolicyInput.disabled = Boolean(state.rubricId);
  renderCompletionPolicySummary(completionPolicyInput.value);
  const categories = byId("rubric-categories");
  clearChildren(categories);
  rubric.categories.forEach((category, index) => {
    const row = document.createElement("label");
    row.className = "rubric-row";
    const name = document.createElement("span");
    name.textContent = category.name + " - " + (CATEGORY_DEFINITIONS[category.id] || "");
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
        rubric.rubric_modified_by_instructor = true;
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

function placementModeLabel(mode) {
  return mode === "translation" ? "Translation-tolerant placement" : "Strict placement";
}

function placementModeDescription(mode) {
  return mode === "translation"
    ? "A consistent whole-drawing translation may be accepted when robust entity consensus exists. Local movement remains an error."
    : "Absolute coordinates matter. A shifted drawing receives position deductions.";
}

function renderNormalizationPolicySummary(mode) {
  byId("normalization-policy-summary").textContent = placementModeDescription(mode);
}

function completionPolicyLabel(mode) {
  return mode === "proportional" ? "Proportional completion" : "Rule-based completion";
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
  const assignmentTypeConfirmed = Boolean(assignmentTypeInput.value);
  display.classList.toggle("invalid", !valid);
  approveButton.disabled = state.loading || !state.provisionalRubric || !state.referenceCanContinue || !valid || !assignmentTypeConfirmed;
}

function markRubricDirty() {
  if (state.rubricId) {
    state.rubricId = null;
    fallbackInput.disabled = false;
    completionPolicyInput.disabled = false;
    normalizationModeInput.disabled = false;
    assignmentTypeInput.disabled = false;
  }
  if (state.provisionalRubric) {
    state.provisionalRubric.approved = false;
    state.provisionalRubric.rubric_modified_by_instructor = true;
  }
  byId("rubric-status").textContent = "Changes require instructor approval.";
  updateSetupSummary();
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
    normalizationModeInput.disabled = false;
    assignmentTypeInput.disabled = false;
    byId("rubric-status").textContent = "Approved and associated. Assignment type: " + state.provisionalRubric.assignment_type + ". Placement: " + placementModeLabel(state.provisionalRubric.normalization_mode) + ". Completion policy: " + completionPolicyLabel(state.provisionalRubric.completion_scoring_mode) + ".";
    setWorkflowStatus("Rubric approved — add student drawing", "success");
    updateSetupSummary();
    setSetupCollapsed(true);
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

function updateReportAvailability() {
  const available = Boolean(state.review && state.review.review_id && state.review.report_available);
  downloadReportButton.disabled = state.loading || state.reportLoading || !available;
  if (downloadReportHeaderButton) downloadReportHeaderButton.disabled = state.loading || state.reportLoading || !available;
  if (available) byId("report-status").textContent = "Authoritative PDF report ready.";
  else if (state.review && state.review.grading_status === "withheld") {
    byId("report-status").textContent = "PDF report unavailable while grading is withheld.";
  }
}

async function downloadReport() {
  if (state.loading || state.reportLoading || !state.review || !state.review.review_id || !state.review.report_available) return;
  const reviewId = encodeURIComponent(state.review.review_id);
  const includeAppendix = Boolean(
    (includeAppendixHeaderCheckbox && includeAppendixHeaderCheckbox.checked) ||
    (includeAppendixCheckbox && includeAppendixCheckbox.checked)
  );
  state.reportLoading = true;
  updateReportAvailability();
  hideError();
  byId("report-status").textContent = "Preparing PDF report...";
  try {
    const response = await fetch("/api/reviews/" + reviewId + "/report.pdf" + (includeAppendix ? "?include_appendix=true" : ""));
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "PDF export failed. Please try again.");
    }
    const blob = await response.blob();
    const location = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = location;
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    link.download = filename ? decodeURIComponent(filename[1]) : "DraftLens_Report.pdf";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(location), 1000);
    byId("report-status").textContent = "PDF report downloaded.";
  } catch (error) {
    showError(error);
    byId("report-status").textContent = "PDF export failed. Your review is still available.";
  } finally {
    state.reportLoading = false;
    const available = Boolean(state.review && state.review.report_available);
    downloadReportButton.disabled = state.loading || !available;
    if (downloadReportHeaderButton) downloadReportHeaderButton.disabled = state.loading || !available;
  }
}

async function runReview(instructorOverride = false) {
  if (!canRunReview()) return;
  hideError();
  resetReview();
  setLoading(true, "review");
  setWorkflowStatus("Generating deterministic review", "working");
  const form = new FormData();
  form.append("reference", state.reference, state.reference.name);
  form.append("student", state.student, state.student.name);
  if (state.rubricId) form.append("rubric_id", state.rubricId);
  if (fallbackInput.checked && !state.rubricId) form.append("allow_fallback", "true");
  if (instructorOverride) form.append("grade_anyway", "true");
  const metadataFields = [["student_name", metadataInputs[0]], ["student_id", metadataInputs[1]], ["course_section", metadataInputs[2]]];
  metadataFields.forEach(([name, input]) => {
    if (input.value.trim()) form.append(name, input.value);
  });

  try {
    state.review = await requestJson("/api/review", {method: "POST", body: form});
    renderResults(state.review);
    updateReportAvailability();
    if (state.review.grading_status === "withheld") {
      setWorkflowStatus("Grading withheld - instructor review required", "warning");
    } else {
      setWorkflowStatus("Review complete", "success");
    }
  } catch (error) {
    resetReview();
    showError(error);
  } finally {
    setLoading(false);
  }
}

function renderResults(review) {
  setDrawingViewMode("review");
  byId("review-placeholder").hidden = true;
  byId("review-results").hidden = false;
  const gradingWithheld = review.grading_status === "withheld";
  byId("result-score").textContent = gradingWithheld ? "Not graded" : formatNumber(review.score);
  byId("result-assignment-title").textContent = review.assignment_title || (review.rubric && review.rubric.assignment_title) || "Assignment";
  byId("result-score").nextElementSibling.hidden = gradingWithheld;
  byId("result-units").textContent = review.units || "unitless";
  byId("result-assignment-type").textContent = review.assignment_type || (review.rubric && review.rubric.assignment_type) || "Not confirmed";
  byId("result-detected-features").textContent = (review.detected_features || []).join(", ") || "No repeated structural features detected";
  const counts = findingCounts(review);
  byId("result-issues").textContent = String(counts.primary_student_issues);
  byId("result-supporting").textContent = String(counts.supporting_findings);
  byId("result-reference-notes").textContent = String(counts.reference_validation_notes);
  const unsupported = [
    ...((review.unsupported_entities && review.unsupported_entities.reference) || []),
    ...((review.unsupported_entities && review.unsupported_entities.student) || []),
  ];
  byId("result-unsupported").textContent = String(counts.unsupported_entities ?? unsupported.length);
  const source = (review.rubric_template_name || "DraftLens baseline rubric template") + " / " + humanize(review.rubric_source || "baseline_template");
  const completionMode = review.completion_scoring_mode || review.rubric.completion_scoring_mode || "rule_based";
  const normalizationMode = review.normalization_mode || review.rubric.normalization_mode || "strict";
  byId("result-rubric").textContent = (review.rubric.title || "Applied rubric") + " · " + source + " · " + completionPolicyLabel(completionMode) + " · " + placementModeLabel(normalizationMode);
  byId("result-rubric").textContent = (review.rubric_template_name || "DraftLens Baseline Rubric") + " / " + humanize(review.rubric_source || "baseline_template") + " / " + completionPolicyLabel(completionMode) + " / " + placementModeLabel(normalizationMode);
  renderFindingSummary(review);
  renderCompatibility(review);
  renderScoreBreakdown(review, completionMode);
  renderNormalizationDecision(review);
  renderUnsupportedNotice(review);
  updateSetupSummary();
  setSetupCollapsed(true);
  const critical = review.issues.filter((issue) => isPrimaryStudentIssue(issue) && issue.severity === "critical").length;
  byId("critical-summary").textContent = critical ? critical + " critical student issue(s)" : "No critical student issues";
  renderSafeSvg(review.svg);
  state.filter = "all";
  resetIssueSelection();
  setFilter("all");
  const firstPrimary = presentedIssues(review).find(isPrimaryStudentIssue);
  if (firstPrimary) {
    selectIssue(firstPrimary.issue_id, false);
  } else {
    const message = review.issues.length
      ? "No primary student issues. Supporting and reference findings are listed separately."
      : "No student issues detected. The drawing matches the approved reference.";
    resetIssueSelection(message);
  }
  byId("review-results").scrollIntoView();
}

function renderCompatibility(review) {
  const compatibility = review.compatibility || review;
  const withheld = review.grading_status === "withheld";
  const overridden = compatibility.instructor_override === true;
  const card = byId("compatibility-card");
  card.hidden = !(withheld || overridden);
  if (card.hidden) return;
  const incompatible = compatibility.compatibility_status === "incompatible";
  byId("compatibility-heading").textContent = overridden
    ? "Compatibility overridden"
    : incompatible ? "Likely wrong assignment file" : "Grading withheld";
  byId("compatibility-message").textContent = review.compatibility_message || "Compatibility requires instructor review.";
  byId("compatibility-status").textContent = humanize(compatibility.compatibility_status);
  byId("compatibility-confidence").textContent = humanize(compatibility.compatibility_confidence);
  byId("compatibility-reference-entities").textContent = String(compatibility.reference_supported_entity_count || 0);
  byId("compatibility-student-entities").textContent = String(compatibility.student_supported_entity_count || 0);
  const rawMatches = Number(compatibility.confident_match_count || 0);
  const coherentMatches = Number(compatibility.coherent_match_count || 0);
  byId("compatibility-matches").textContent = String(rawMatches);
  byId("compatibility-coherent-matches").textContent = String(coherentMatches);
  byId("compatibility-displacement-support").textContent =
    String(compatibility.displacement_consensus_support || 0) + "/" + String(rawMatches);
  byId("compatibility-reference-coverage").textContent = formatNumber(Number(compatibility.coherent_reference_coverage || 0) * 100) + "%";
  byId("compatibility-student-coverage").textContent = formatNumber(Number(compatibility.coherent_student_coverage || 0) * 100) + "%";
  const scale = compatibility.estimated_uniform_scale;
  byId("compatibility-scale").textContent = scale ? formatNumber(scale) + "x" : "Not detected";
  byId("compatibility-reasons").textContent = (compatibility.compatibility_reason_codes || []).map(humanize).join(" / ");
  const actions = Array.isArray(review.available_actions) ? review.available_actions : [];
  gradeAnywayButton.hidden = !(withheld && actions.includes("grade_anyway"));
  chooseAnotherFileButton.hidden = !withheld;
}

function formatTranslation(vector) {
  if (!Array.isArray(vector) || vector.length < 2) return "Not available";
  return "X = " + Number(vector[0]).toFixed(3) + " · Y = " + Number(vector[1]).toFixed(3);
}

function renderNormalizationDecision(review) {
  const mode = review.normalization_mode || (review.rubric && review.rubric.normalization_mode) || "strict";
  const decision = review.normalization_decision || {};
  byId("result-normalization-mode").textContent = placementModeLabel(mode);
  if (mode === "strict") {
    byId("result-transform").textContent = "None permitted";
    const displacement = decision.global_displacement;
    if (!displacement) {
      byId("normalization-evidence").hidden = true;
      byId("result-transform-reason-row").hidden = true;
      return;
    }
    byId("normalization-evidence").hidden = false;
    byId("result-applied-translation").textContent = "None";
    byId("result-candidate-translation").textContent = formatTranslation(decision.candidate_translation);
    byId("result-transform-support").textContent = String(displacement.support_count || 0) + " of " + String(displacement.evidence_count || 0) + " compatible entities";
    byId("result-transform-ratio").textContent = formatNumber(Number(displacement.support_ratio || 0) * 100) + "%";
    byId("result-transform-confidence").textContent = humanize(decision.confidence);
    byId("result-error-reduction").textContent = "Not applied in Strict placement";
    byId("result-transform-reason-row").hidden = false;
    byId("result-transform-reason").textContent = "Robust translation detected; absolute placement remains graded.";
    return;
  }

  byId("normalization-evidence").hidden = false;
  byId("result-transform").textContent = decision.transform_applied ? "Applied translation" : "None";
  byId("result-applied-translation").textContent = decision.transform_applied
    ? formatTranslation(decision.selected_translation)
    : "None";
  byId("result-candidate-translation").textContent = formatTranslation(decision.candidate_translation);
  byId("result-transform-support").textContent = String(decision.support_count || 0) + " of " + String(decision.evidence_count || 0) + " compatible entities";
  byId("result-transform-ratio").textContent = formatNumber(Number(decision.support_ratio || 0) * 100) + "%";
  byId("result-transform-confidence").textContent = humanize(decision.confidence);
  const reduction = decision.total_error_reduction;
  const reductionRatio = decision.error_reduction_ratio;
  byId("result-error-reduction").textContent = reduction === null || reduction === undefined
    ? "Not applicable"
    : formatNumber(reduction) + " (" + formatNumber(Number(reductionRatio || 0) * 100) + "%)";
  const reason = decision.rejection_reason || "";
  byId("result-transform-reason-row").hidden = decision.transform_applied || !reason;
  byId("result-transform-reason").textContent = reason ? humanize(reason) : "—";
}

function findingRole(issue) {
  if (issue.finding_role) return issue.finding_role;
  if (issue.category === "unsupported_entity") return "unsupported";
  if (issue.provenance === "reference_validation") return "reference";
  if (issue.provenance === "comparison" && issue.classification === "primary") return "primary";
  if (issue.provenance === "comparison" && ["supporting_evidence", "derived", "suppressed"].includes(issue.classification)) return "supporting";
  return "informational";
}

function isPrimaryStudentIssue(issue) {
  return findingRole(issue) === "primary";
}

function findingCounts(review) {
  if (review.finding_counts) return review.finding_counts;
  const issues = review.issues || [];
  const unsupported = review.unsupported_entities || {};
  return {
    primary_student_issues: issues.filter((issue) => findingRole(issue) === "primary").length,
    supporting_findings: issues.filter((issue) => findingRole(issue) === "supporting").length,
    reference_validation_notes: issues.filter((issue) => findingRole(issue) === "reference").length,
    unsupported_entities: (unsupported.reference || []).length + (unsupported.student || []).length,
  };
}

function presentedIssues(review) {
  const presentation = review.finding_presentation || {};
  if (showTechnicalDetails) return review.issues || [];
  if (presentation.default_issue_ids) {
    const displayed = new Set(presentation.default_issue_ids);
    return (review.issues || []).filter((issue) => displayed.has(issue.issue_id));
  }
  return (review.issues || []).filter((issue) =>
    !["supporting", "unsupported"].includes(findingRole(issue)) || essentialFinding(issue));
}

function essentialFinding(issue) {
  return issue.severity === "critical" || issue.blocks_reference || issue.blocking || appliedDeduction(issue) > 0;
}

function renderFindingSummary(review) {
  const presentation = review.finding_presentation || {};
  const section = byId("finding-summary");
  section.hidden = !presentation.compacted;
  clearChildren(byId("finding-summary-groups"));
  if (!presentation.compacted) {
    byId("finding-summary-totals").textContent = "";
    return;
  }
  byId("finding-summary-totals").textContent =
    String(presentation.total_raw_count || 0) + " primary findings / " +
    String(presentation.total_displayed_count || 0) + " representatives / " +
    String(presentation.total_summarized_count || 0) + " additional summarized findings. All primary findings, including capped findings, remain listed.";
  (presentation.summary_groups || []).forEach((group) => {
    const row = document.createElement("div");
    row.className = "finding-summary-row";
    const title = document.createElement("strong");
    title.textContent = humanize(group.issue_type);
    const counts = document.createElement("span");
    counts.textContent =
      String(group.total_count || 0) + " total; " +
      String(group.contributed_count || 0) + " contributed; " +
      String(group.summarized_count || 0) + " capped findings summarized.";
    const evidence = document.createElement("small");
    evidence.textContent =
      humanize(group.score_category || "not_scored") + " / " +
      humanize(group.deduction_status || "not_scored") + " / " +
      humanize(group.cap_reason || "none") + " / contribution " +
      formatDeduction(group.score_contribution);
    row.append(title, counts, evidence);
    byId("finding-summary-groups").append(row);
  });
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
    detail.textContent = "";
    const earned = document.createElement("strong");
    earned.className = "category-earned";
    earned.textContent = formatNumber(category.score);
    const available = document.createElement("span");
    available.textContent = " / " + formatNumber(category.weight);
    const applied = document.createElement("small");
    applied.textContent = "Applied " + formatDeduction(category.deduction);
    detail.append(earned, available, applied);
    const definition = document.createElement("p");
    definition.className = "score-category-definition";
    definition.textContent = category.definition || "";
    const explanation = document.createElement("details");
    explanation.className = "score-category-evidence";
    const summary = document.createElement("summary");
    summary.textContent = "Why points were deducted";
    explanation.append(summary);
    const evidence = category.deduction_evidence || [];
    if (!evidence.length) {
      const empty = document.createElement("p");
      empty.textContent = "No scored findings contributed to this category.";
      explanation.append(empty);
    } else {
      evidence.forEach((entry) => {
        const item = document.createElement("p");
        const reason = entry.cap_reason || entry.suppression_reason || entry.deduction_status;
        item.textContent = (entry.issue_id || "Policy") + " / " + (entry.rule_id || "No rule") + " / " + humanize(entry.score_category) + " / raw " + formatDeduction(entry.raw_deduction) + " / final " + formatDeduction(entry.final_applied_contribution) + " / " + humanize(reason);
        explanation.append(item);
      });
    }
    container.append(row, definition, explanation);
  });
  byId("result-applied-deduction").textContent = formatDeduction(breakdown.total_applied_deduction);
  byId("result-final-score").textContent = breakdown.final_score === null ? "Not graded" : formatNumber(breakdown.final_score) + " / 100";
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

  const viewBoxAttr = sanitized.getAttribute("viewBox");
  if (viewBoxAttr) {
    const parts = viewBoxAttr.trim().split(/\s+/).map(Number);
    if (parts.length === 4 && parts.every(Number.isFinite) && parts[2] > 0 && parts[3] > 0) {
      viewerNav.baseX = parts[0];
      viewerNav.baseY = parts[1];
      viewerNav.baseWidth = parts[2];
      viewerNav.baseHeight = parts[3];
      viewerNav.currentX = parts[0];
      viewerNav.currentY = parts[1];
      viewerNav.currentWidth = parts[2];
      viewerNav.currentHeight = parts[3];
      viewerNav.scale = 1.0;
    }
  }

  const imported = document.importNode(sanitized, true);
  byId("drawing-viewport").replaceChildren(imported);
}

function getViewportSvg() {
  const viewport = byId("drawing-viewport");
  if (!viewport) return null;
  if (viewport.children && viewport.children.length > 0) {
    const found = viewport.children.find ? viewport.children.find((c) => (c.tagName || c.nodeName || "").toLowerCase() === "svg") : viewport.children[0];
    if (found) return found;
  }
  if (typeof viewport.querySelector === "function") {
    return viewport.querySelector("svg");
  }
  return null;
}

function applyViewBox() {
  const svg = getViewportSvg();
  if (!svg) return;
  const vb = `${viewerNav.currentX} ${viewerNav.currentY} ${viewerNav.currentWidth} ${viewerNav.currentHeight}`;
  svg.setAttribute("viewBox", vb);
}

function resetViewerNav() {
  viewerNav.currentX = viewerNav.baseX;
  viewerNav.currentY = viewerNav.baseY;
  viewerNav.currentWidth = viewerNav.baseWidth;
  viewerNav.currentHeight = viewerNav.baseHeight;
  viewerNav.scale = 1.0;
  applyViewBox();
}

function zoomViewer(factor, clientX, clientY) {
  const svg = getViewportSvg();
  if (!svg) return;

  const newScale = Math.min(Math.max(viewerNav.scale * factor, viewerNav.minScale), viewerNav.maxScale);
  if (Math.abs(newScale - viewerNav.scale) < 1e-4) return;

  let normX = 0.5;
  let normY = 0.5;
  if (clientX !== undefined && clientY !== undefined && svg.getScreenCTM && svg.createSVGPoint) {
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const anchor = point.matrixTransform(matrix.inverse());
    normX = (anchor.x - viewerNav.currentX) / viewerNav.currentWidth;
    normY = (anchor.y - viewerNav.currentY) / viewerNav.currentHeight;
  }

  const targetSvgX = viewerNav.currentX + normX * viewerNav.currentWidth;
  const targetSvgY = viewerNav.currentY + normY * viewerNav.currentHeight;

  const newWidth = viewerNav.baseWidth / newScale;
  const newHeight = viewerNav.baseHeight / newScale;

  viewerNav.currentX = targetSvgX - normX * newWidth;
  viewerNav.currentY = targetSvgY - normY * newHeight;
  viewerNav.currentWidth = newWidth;
  viewerNav.currentHeight = newHeight;
  viewerNav.scale = newScale;
  applyViewBox();
}

function locateIssueInViewer(issueId) {
  if (!issueId) return;
  const viewport = byId("drawing-viewport");
  if (!viewport) return;
  const svg = viewport.querySelector("svg");
  if (!svg) return;
  const element = svg.querySelector(`[data-issue-id="${cssEscape(issueId)}"]`);
  if (!element) return;

  let bbox = null;
  if (typeof element.getBBox === "function") {
    try {
      bbox = element.getBBox();
    } catch (_) {}
  }
  if (!bbox || ![bbox.x, bbox.y, bbox.width, bbox.height].every(Number.isFinite)) {
    return;
  }

  const padding = Math.max(bbox.width, bbox.height) * 0.8 + 20;
  const targetWidth = Math.max(bbox.width + padding * 2, viewerNav.baseWidth * 0.15);
  const targetHeight = Math.max(bbox.height + padding * 2, viewerNav.baseHeight * 0.15);
  const cx = bbox.x + bbox.width / 2;
  const cy = bbox.y + bbox.height / 2;

  viewerNav.scale = Math.min(Math.max(Math.min(viewerNav.baseWidth / targetWidth, viewerNav.baseHeight / targetHeight), viewerNav.minScale), viewerNav.maxScale);
  viewerNav.currentWidth = viewerNav.baseWidth / viewerNav.scale;
  viewerNav.currentHeight = viewerNav.baseHeight / viewerNav.scale;
  viewerNav.currentX = cx - viewerNav.currentWidth / 2;
  viewerNav.currentY = cy - viewerNav.currentHeight / 2;
  applyViewBox();
}

function setExpandedView(expanded) {
  const wasExpanded = viewerNav.isExpanded;
  viewerNav.isExpanded = Boolean(expanded);
  const drawingPanel = document.querySelector(".drawing-panel");
  if (drawingPanel) {
    drawingPanel.classList.toggle("is-expanded", viewerNav.isExpanded);
    if (viewerNav.isExpanded) {
      drawingPanel.setAttribute("role", "dialog");
      drawingPanel.setAttribute("aria-modal", "true");
    } else {
      drawingPanel.removeAttribute("role");
      drawingPanel.removeAttribute("aria-modal");
    }
  }
  document.body.classList.toggle("viewer-is-expanded", viewerNav.isExpanded);
  if (viewerExpandButton) viewerExpandButton.hidden = viewerNav.isExpanded;
  if (viewerExitExpandButton) viewerExitExpandButton.hidden = !viewerNav.isExpanded;
  if (viewerNav.isExpanded && !wasExpanded) {
    viewerNav.returnFocus = document.activeElement;
    if (drawingViewportEl.focus) drawingViewportEl.focus({preventScroll: true});
  } else if (wasExpanded && viewerNav.returnFocus && viewerNav.returnFocus.focus) {
    viewerNav.returnFocus.focus({preventScroll: true});
  }
}

function updateSetupSummary() {
  const card = byId("setup-summary");
  if (!card) return;
  if (!state.reference) {
    card.hidden = true;
    const col = document.querySelector(".setup-column");
    if (col) col.classList.remove("is-collapsed");
    return;
  }
  const refName = state.reference ? state.reference.name : "—";
  const title = (state.provisionalRubric && state.provisionalRubric.assignment_title) || "—";
  const type = (state.provisionalRubric && state.provisionalRubric.assignment_type) || state.suggestedAssignmentType || "—";
  const normMode = state.provisionalRubric ? placementModeLabel(state.provisionalRubric.normalization_mode) : "—";

  byId("summary-reference-name").textContent = refName;
  byId("summary-assignment-title").textContent = title;
  byId("summary-assignment-type").textContent = type;
  byId("summary-placement-policy").textContent = normMode;
  card.hidden = false;
  byId("setup-summary-heading").textContent = state.rubricId ? "Approved assignment" : "Assignment - approval required";
}

function setSetupCollapsed(collapsed) {
  const col = document.querySelector(".setup-column");
  if (!col) return;
  col.classList.toggle("is-collapsed", collapsed);
  if (editSetupButton) {
    editSetupButton.textContent = collapsed ? "Edit assignment" : "Hide setup";
    editSetupButton.setAttribute("aria-expanded", String(!collapsed));
  }
}

function renderUnsupportedNotice(review) {
  const banner = byId("unsupported-notice");
  if (!banner) return;
  const presentation = review.finding_presentation || {};
  const summary = presentation.unsupported_summary || null;
  const total = summary ? summary.total_count : 0;
  if (!total) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  const textEl = byId("unsupported-notice-text");
  if (textEl) {
    textEl.textContent = summary.notice || `${total} unsupported entities were not automatically assessed. Assessment scope is limited to supported 2D geometry.`;
  }
  const listEl = byId("unsupported-notice-list");
  if (listEl) {
    clearChildren(listEl);
    (summary.groups || []).forEach((group) => {
      const li = document.createElement("li");
      const layers = (group.layers || []).join(", ") || "default";
      li.textContent = `${group.source}: ${group.count} × ${group.entity_type} (Layers: ${layers})`;
      listEl.append(li);
    });
  }
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
  const presentation = state.review.finding_presentation || {};
  const linkedSupporting = presentation.linked_supporting_by_primary || {};
  const issueById = new Map((state.review.issues || []).map((issue) => [issue.issue_id, issue]));

  const visible = presentedIssues(state.review).filter((issue) => {
    if (state.filter !== "all" && issue.visual_role !== state.filter) return false;
    return true;
  });
  byId("issue-empty").hidden = visible.length !== 0;
  visible.forEach((issue) => {
    const group = document.createElement("div");
    group.className = "issue-group";
    const button = document.createElement("button");
    button.type = "button";
    const role = findingRole(issue);
    button.className = "issue-card role-" + safeClass(issue.visual_role) + " finding-" + safeClass(role);
    button.dataset.issueId = issue.issue_id;
    button.setAttribute("aria-pressed", String(issue.issue_id === state.selectedIssueId));
    if (issue.issue_id === state.selectedIssueId) button.classList.add("is-selected");

    const top = document.createElement("span");
    top.className = "issue-card-top";
    const category = document.createElement("strong");
    category.textContent = role === "supporting"
      ? "Supporting topology evidence"
      : role === "reference"
        ? "Reference validation note"
        : humanize(issue.category);
    const identity = document.createElement("span");
    identity.textContent = issue.issue_id;
    top.append(category, identity);

    const feedback = document.createElement("span");
    feedback.className = "issue-card-message";
    feedback.textContent = issue.technical_feedback;

    const guidance = issue.correction_guidance;
    const primaryCmd = guidance && guidance.primary_command ? guidance.primary_command : "";
    if (primaryCmd) {
      const cmdPreview = document.createElement("span");
      cmdPreview.className = "issue-card-command-preview";
      cmdPreview.textContent = "Action: " + primaryCmd;
      button.append(top, feedback, cmdPreview);
    } else {
      button.append(top, feedback);
    }

    const evidence = document.createElement("span");
    evidence.className = "issue-card-evidence";
    evidence.textContent = role === "supporting"
      ? humanize(issue.severity) + " · Supporting finding"
      : role === "reference"
        ? humanize(issue.severity) + " · Reference validation"
        : humanize(issue.severity) + " · Applied: " + formatDeduction(appliedDeduction(issue));
    const deductionDetail = document.createElement("span");
    deductionDetail.className = "issue-card-deduction";
    deductionDetail.textContent = role === "supporting" ? "No separate deduction" : (showTechnicalDetails ? formatDeductionDetail(issue) : ("Applied: " + formatDeduction(appliedDeduction(issue))));
    button.append(evidence, deductionDetail);

    // Linked supporting topology findings collapsible
    group.append(button);
    const linked = (linkedSupporting[issue.issue_id] || []).map((id) => issueById.get(id)).filter(Boolean);
    if (linked.length > 0) {
      const collapse = document.createElement("details");
      collapse.className = "supporting-findings-collapse";
      const summary = document.createElement("summary");
      summary.textContent = `${linked.length} supporting finding(s) - linked evidence`;
      collapse.open = linked.some((sup) => essentialFinding(sup) || sup.issue_id === state.selectedIssueId);
      collapse.append(summary);
      const sublist = document.createElement("ul");
      sublist.className = "supporting-findings-sublist";
      linked.forEach((sup) => {
        const item = document.createElement("li");
        const link = document.createElement("button");
        link.type = "button";
        link.textContent = `${sup.issue_id}: ${sup.technical_feedback || humanize(sup.category)}`;
        link.addEventListener("click", () => selectIssue(sup.issue_id, false));
        item.append(link);
        sublist.append(item);
      });
      collapse.append(sublist);
      collapse.addEventListener("click", (e) => e.stopPropagation());
      group.append(collapse);
    }

    button.addEventListener("click", () => selectIssue(issue.issue_id, true));
    list.append(group);
  });
}

function selectIssue(issueId, scrollList) {
  if (!state.review) return;
  const issue = state.review.issues.find((item) => item.issue_id === issueId);
  if (!issue) return;
  state.selectedIssueId = issueId;
  if (viewerLocateButton) viewerLocateButton.disabled = false;
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
  byId("evidence-score-category").textContent = humanize(issue.score_category || "not_scored");
  byId("evidence-after-rule-cap").textContent = formatDeduction(issue.deduction_after_rule_cap);
  byId("evidence-after-category-cap").textContent = formatDeduction(issue.deduction_after_category_cap);
  byId("evidence-deduction-status").textContent = deductionStatusText(issue);
  byId("evidence-confidence").textContent = humanize(issue.confidence);

  renderCorrectionGuidance(issue);
}

function appendCommandItems(elementId, commands) {
  const list = byId(elementId);
  clearChildren(list);
  commands.forEach((command) => {
    const item = document.createElement("li");
    item.textContent = command;
    list.append(item);
  });
}

function commandsForIssue(issue) {
  if (Array.isArray(issue.recommended_commands)) return [...new Set(issue.recommended_commands)];
  const guidance = issue.correction_guidance;
  if (!guidance) return [];
  return [...new Set([
    guidance.primary_command,
    ...(guidance.alternative_commands || []),
    ...(guidance.precision_aids || []),
  ].filter(Boolean))];
}

function renderCorrectionGuidance(issue) {
  resetCorrectionGuidance();
  const guidance = issue.correction_guidance;
  if (!guidance) return;
  if (findingRole(issue) !== "primary") return;

  const primary = guidance.primary_command || "";
  const alternatives = Array.isArray(guidance.alternative_commands) ? guidance.alternative_commands : [];
  const precisionAids = Array.isArray(guidance.precision_aids) ? guidance.precision_aids : [];
  const relatedId = guidance.related_primary_issue_id || "";
  const explanation = guidance.explanation || "";
  const commands = commandsForIssue(issue);

  appendCommandItems("command-list", commands);
  appendCommandItems("guidance-alternatives", alternatives.length ? alternatives : ["None"]);
  appendCommandItems("guidance-precision", precisionAids.length ? precisionAids : ["None"]);
  byId("guidance-primary").textContent = primary || "—";
  byId("guidance-explanation").textContent = explanation;
  byId("guidance-related-id").textContent = relatedId || "—";
  byId("guidance-primary-row").hidden = !primary;
  byId("guidance-primary-row").querySelector("dt").textContent = "Primary command";
  byId("guidance-alternatives-row").hidden = !primary;
  byId("guidance-precision-row").hidden = !primary;
  byId("guidance-related").hidden = !relatedId;
  byId("guidance-supporting-label").hidden = findingRole(issue) !== "supporting";
  byId("guidance-no-command").hidden = Boolean(primary);
  byId("feedback-commands").hidden = !(primary || alternatives.length || precisionAids.length || relatedId || explanation);
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
  return Number(issue.final_applied_contribution ?? issue.applied_deduction ?? issue.deduction ?? 0);
}

function rawDeduction(issue) {
  return Number(issue.raw_rule_deduction ?? issue.raw_deduction ?? issue.deduction ?? 0);
}

function deductionStatusText(issue) {
  if (issue.suppression_reason) return "Suppressed: " + issue.suppression_reason;
  const status = humanize(issue.deduction_status || (appliedDeduction(issue) > 0 ? "applied" : "not_scored"));
  return issue.cap_reason ? status + ": " + humanize(issue.cap_reason) : status;
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

function getViewerNav() {
  return viewerNav;
}

function getState() {
  return state;
}

updateWeightTotal();
updateReviewAvailability();
