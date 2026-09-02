const API_BASE = "/api";
const POLL_INTERVAL_MS = 3000;
const STEP_ORDER = ["uploaded", "processing", "reviewed", "submitted"];

const STATUS_META = {
  UPLOADED: { step: "uploaded", tone: "pending", label: "Uploaded" },
  PROCESSING: { step: "processing", tone: "pending", label: "Processing" },
  NEEDS_REVIEW: { step: "reviewed", tone: "warn", label: "Needs review" },
  READY_FOR_SUBMISSION: { step: "reviewed", tone: "ok", label: "Ready for submission" },
  SUBMITTED: { step: "submitted", tone: "ok", label: "Submitted" },
  SUBMISSION_FAILED: { step: "submitted", tone: "bad", label: "Submission failed" },
  SUBMISSION_SKIPPED: { step: "submitted", tone: "warn", label: "Submission skipped" },
};

const TERMINAL_STATUSES = new Set(["NEEDS_REVIEW", "SUBMITTED", "SUBMISSION_FAILED", "SUBMISSION_SKIPPED"]);
const SYSTEM_FIELDS = ["documentId", "sourceBucket", "sourceKey"];
// Mirrors idp_common.schema.EDITABLE_FIELDS. A required field that Textract
// never found an answer for is missing from canonicalRecord entirely (not
// just low-confidence) - the edit form must still offer an input for it, or
// there'd be no way to fill it in and clear the resulting schema error.
const CANONICAL_FIELDS = [
  "state",
  "documentType",
  "applicantName",
  "applicantDateOfBirth",
  "applicantAddress",
  "applicantPhone",
  "medicareNumber",
  "partAEffectiveDate",
  "partBEffectiveDate",
  "planSelected",
  "planEffectiveDate",
  "replacingExistingCoverage",
  "signatureDate",
];

let pollTimer = null;
let currentDocumentId = null;
let historyDocuments = [];
let historyPage = 0;
const HISTORY_PAGE_SIZE = 10;
// Mirrors delete_document's BLOCKED_STATUSES - deleting while the pipeline
// may still be writing to the record can race with its UpdateItem calls.
const DELETE_BLOCKED_STATUSES = new Set(["UPLOADED", "PROCESSING"]);
const TRASH_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline>' +
  '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>' +
  '<path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>';
const EYE_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>' +
  '<circle cx="12" cy="12" r="3"></circle></svg>';

const el = (id) => document.getElementById(id);

// --- Auth: Cognito (direct API calls, no SDK) -----------------------------
// USER_PASSWORD_AUTH avoids SRP math in plain JS. cognitoConfig is fetched
// once from the public /api/config route (see get_auth_config) since this
// static frontend has no build step to inject the deploy-time client ID.

const SESSION_KEY = "idpAuthSession";
let cognitoConfig = null;
let pendingVerifyEmail = "";

async function loadAuthConfig() {
  const response = await fetch(`${API_BASE}/config`);
  if (!response.ok) throw new Error("Could not load app configuration");
  cognitoConfig = await response.json();
}

async function cognitoRequest(action, body) {
  const response = await fetch(`https://cognito-idp.${cognitoConfig.region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || data.__type || `${action} failed (${response.status})`);
  return data;
}

function cognitoSignUp(email, password) {
  return cognitoRequest("SignUp", {
    ClientId: cognitoConfig.userPoolClientId,
    Username: email,
    Password: password,
    UserAttributes: [{ Name: "email", Value: email }],
  });
}

function cognitoConfirmSignUp(email, code) {
  return cognitoRequest("ConfirmSignUp", {
    ClientId: cognitoConfig.userPoolClientId,
    Username: email,
    ConfirmationCode: code,
  });
}

function cognitoResendCode(email) {
  return cognitoRequest("ResendConfirmationCode", { ClientId: cognitoConfig.userPoolClientId, Username: email });
}

async function cognitoLogin(email, password) {
  const data = await cognitoRequest("InitiateAuth", {
    ClientId: cognitoConfig.userPoolClientId,
    AuthFlow: "USER_PASSWORD_AUTH",
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  return data.AuthenticationResult;
}

function saveSession(email, idToken) {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ email, idToken }));
}

function getSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

// Wraps fetch for every call to our own API: attaches the ID token, and on
// a 401 (expired/invalid token - no refresh-token flow in this pass) clears
// the stored session and drops back to the login form.
async function authFetch(url, options = {}) {
  const session = getSession();
  const headers = { ...(options.headers || {}) };
  if (session) headers.Authorization = `Bearer ${session.idToken}`;

  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    clearSession();
    showAuthView("login");
    throw new Error("Your session has expired. Please log in again.");
  }
  return response;
}

function clearAuthErrors() {
  el("login-error").hidden = true;
  el("register-error").hidden = true;
  el("verify-error").hidden = true;
}

function showAuthView(view) {
  el("app-content").hidden = true;
  el("account-bar").hidden = true;
  el("auth-card").hidden = false;
  clearAuthErrors();
  el("auth-login").hidden = view !== "login";
  el("auth-register").hidden = view !== "register";
  el("auth-verify").hidden = view !== "verify";
}

function showApp() {
  const session = getSession();
  el("auth-card").hidden = true;
  el("app-content").hidden = false;
  el("account-bar").hidden = false;
  el("account-email").textContent = session ? session.email : "";
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const email = el("login-email").value.trim();
  const password = el("login-password").value;
  const button = el("login-button");
  button.disabled = true;
  button.textContent = "Logging in…";

  try {
    const result = await cognitoLogin(email, password);
    saveSession(email, result.IdToken);
    el("login-form").reset();
    showApp();
    loadHistory();
  } catch (err) {
    const errorEl = el("login-error");
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Log in";
  }
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  const email = el("register-email").value.trim();
  const password = el("register-password").value;
  const button = el("register-button");
  button.disabled = true;
  button.textContent = "Creating account…";

  try {
    await cognitoSignUp(email, password);
    pendingVerifyEmail = email;
    el("verify-email-text").textContent = `We sent a verification code to ${email}.`;
    el("register-form").reset();
    showAuthView("verify");
  } catch (err) {
    const errorEl = el("register-error");
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Create account";
  }
}

async function handleVerifySubmit(event) {
  event.preventDefault();
  const code = el("verify-code").value.trim();
  const button = el("verify-button");
  button.disabled = true;
  button.textContent = "Verifying…";

  try {
    await cognitoConfirmSignUp(pendingVerifyEmail, code);
    el("verify-form").reset();
    el("login-email").value = pendingVerifyEmail;
    showAuthView("login");
  } catch (err) {
    const errorEl = el("verify-error");
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Verify";
  }
}

async function handleResendCode() {
  if (!pendingVerifyEmail) return;
  try {
    await cognitoResendCode(pendingVerifyEmail);
  } catch (err) {
    const errorEl = el("verify-error");
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
}

function handleLogout() {
  clearSession();
  stopPolling();
  currentDocumentId = null;
  el("tracking-card").hidden = true;
  showAuthView("login");
}

function statusMeta(status) {
  return STATUS_META[status] || { step: "uploaded", tone: "pending", label: status || "Unknown" };
}

function renderStepper(status) {
  const meta = statusMeta(status);
  const currentIndex = STEP_ORDER.indexOf(meta.step);

  document.querySelectorAll("#stepper .step").forEach((stepEl) => {
    const index = STEP_ORDER.indexOf(stepEl.dataset.step);
    stepEl.classList.remove("done", "active", "failed", "warn", "skipped");

    if (index < currentIndex) {
      stepEl.classList.add("done");
    } else if (index === currentIndex) {
      stepEl.classList.add("active");
      if (meta.tone === "bad") stepEl.classList.add("failed");
      else if (meta.tone === "warn" && status !== "SUBMISSION_SKIPPED") stepEl.classList.add("warn");
      else if (status === "SUBMISSION_SKIPPED") stepEl.classList.add("skipped");
    }
  });
}

function renderStatusLine(status) {
  const meta = statusMeta(status);
  const line = el("status-line");
  line.className = `status-line ${meta.tone}`;
  el("status-line-label").textContent = meta.label;
  // Still polling (see trackDocument) means processing is genuinely
  // happening behind the scenes - show that rather than a static label.
  el("status-spinner").hidden = TERMINAL_STATUSES.has(status);
}

function renderReadOnlyTable(record) {
  const table = el("canonical-table");
  table.innerHTML = "";
  Object.entries(record)
    .filter(([key]) => !SYSTEM_FIELDS.includes(key))
    .forEach(([key, value]) => {
      const row = document.createElement("tr");
      const keyCell = document.createElement("td");
      const valueCell = document.createElement("td");
      keyCell.textContent = key;
      valueCell.textContent = value;
      row.append(keyCell, valueCell);
      table.appendChild(row);
    });
}

function renderIssues(doc) {
  const issuesPanel = el("issues-panel");
  const lowConfidence = doc.lowConfidenceFields || [];
  const schemaErrors = doc.schemaErrors || [];

  if (lowConfidence.length === 0 && schemaErrors.length === 0) {
    issuesPanel.hidden = true;
    return;
  }

  issuesPanel.hidden = false;
  el("low-confidence-fields").textContent = lowConfidence.length
    ? `Low-confidence fields: ${lowConfidence.join(", ")}`
    : "";
  el("schema-errors").textContent = schemaErrors.length ? `Schema errors: ${schemaErrors.join("; ")}` : "";
}

function clearEditError() {
  el("edit-error").hidden = true;
}

function showEditError(message) {
  const errorEl = el("edit-error");
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function renderEditForm(doc) {
  const record = doc.canonicalRecord || {};
  const lowConfidence = new Set(doc.lowConfidenceFields || []);
  const form = el("edit-form");
  form.innerHTML = "";

  // Union of the known canonical fields (so a field Textract never found any
  // answer for still gets an input) and whatever keys the record actually
  // has (in case it carries something outside that list).
  const extraKeys = Object.keys(record).filter((key) => !SYSTEM_FIELDS.includes(key) && !CANONICAL_FIELDS.includes(key));
  const fields = [...CANONICAL_FIELDS, ...extraKeys];

  fields.forEach((key) => {
    const value = record[key] || "";
    const row = document.createElement("div");
    row.className = "field-row";

    const label = document.createElement("label");
    label.setAttribute("for", `field-${key}`);
    label.textContent = lowConfidence.has(key) ? `${key} (low confidence)` : key;

    const input = document.createElement("input");
    input.type = "text";
    input.id = `field-${key}`;
    input.name = key;
    input.value = value;
    if (lowConfidence.has(key)) input.classList.add("flagged");

    row.append(label, input);
    form.appendChild(row);
  });

  el("resubmit-button").disabled = (doc.schemaErrors || []).length > 0;
  // A fresh render reflects exactly what's saved server-side - nothing
  // unsaved yet, so Save changes starts greyed out until the user edits
  // a field again (see the edit-form "input" listener below).
  el("save-button").disabled = true;
}

function collectEditFormValues() {
  const values = {};
  el("edit-form")
    .querySelectorAll("input")
    .forEach((input) => {
      values[input.name] = input.value;
    });
  return values;
}

function renderDetail(doc) {
  const panel = el("detail-panel");
  const editPanel = el("edit-panel");
  const table = el("canonical-table");
  const record = doc.canonicalRecord;

  if (!record) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  clearEditError();

  const tableHeading = el("canonical-table-heading");
  if (doc.status === "NEEDS_REVIEW") {
    table.hidden = true;
    tableHeading.hidden = true;
    editPanel.hidden = false;
    renderEditForm(doc);
  } else {
    table.hidden = false;
    tableHeading.hidden = false;
    editPanel.hidden = true;
    renderReadOnlyTable(record);
  }

  renderIssues(doc);
}

function renderDocument(doc) {
  currentDocumentId = doc.documentId;
  el("tracking-filename").textContent = doc.originalFilename || doc.sourceKey || "";

  const uploadedByEl = el("tracking-uploaded-by");
  uploadedByEl.hidden = !doc.uploadedBy;
  uploadedByEl.textContent = doc.uploadedBy ? `Uploaded by ${doc.uploadedBy}` : "";

  renderStepper(doc.status);
  renderStatusLine(doc.status);
  renderDetail(doc);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function fetchDocument(documentId) {
  const response = await authFetch(`${API_BASE}/documents/${documentId}`);
  if (!response.ok) throw new Error(`Status check failed (${response.status})`);
  return response.json();
}

function trackDocument(documentId) {
  el("tracking-card").hidden = false;
  stopPolling();

  const poll = async () => {
    try {
      const doc = await fetchDocument(documentId);
      renderDocument(doc);
      if (TERMINAL_STATUSES.has(doc.status)) {
        stopPolling();
        loadHistory();
      }
    } catch (err) {
      stopPolling();
      showUploadError(err.message);
    }
  };

  poll();
  pollTimer = setInterval(poll, POLL_INTERVAL_MS);
}

function showUploadError(message) {
  const errorEl = el("upload-error");
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function clearUploadError() {
  el("upload-error").hidden = true;
}

async function requestUpload(file) {
  const response = await authFetch(`${API_BASE}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name }),
  });
  if (!response.ok) throw new Error(`Could not start upload (${response.status})`);
  return response.json();
}

async function uploadToS3(uploadUrl, file) {
  // Direct presigned PUT to S3 - never through authFetch, an Authorization
  // header here isn't part of the presigned signature and would break it.
  const response = await fetch(uploadUrl, { method: "PUT", body: file });
  if (!response.ok) throw new Error(`Upload to storage failed (${response.status})`);
}

async function handleUploadSubmit(event) {
  event.preventDefault();
  clearUploadError();

  const fileInput = el("file-input");
  const file = fileInput.files[0];
  if (!file) return;

  const button = el("upload-button");
  button.disabled = true;
  button.textContent = "Uploading…";

  try {
    const { documentId, uploadUrl } = await requestUpload(file);
    await uploadToS3(uploadUrl, file);
    trackDocument(documentId);
    fileInput.value = "";
    el("file-drop-label").textContent = "Choose a PDF or drag it here";
  } catch (err) {
    showUploadError(err.message);
  } finally {
    button.disabled = false;
    button.textContent = "Upload";
  }
}

function pillFor(status) {
  const meta = statusMeta(status);
  return `<span class="pill ${meta.tone}">${meta.label}</span>`;
}

function formatTimestamp(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? isoString : date.toLocaleString();
}

async function handleViewClick(documentId) {
  // Open the tab synchronously (within the click's own user gesture) so
  // popup blockers don't step in while we wait on the authenticated fetch;
  // navigate it once we have the presigned URL. view_document hands that
  // URL back as JSON rather than a redirect: a fetch that *follows* a
  // cross-origin redirect needs the final (S3) response to carry CORS
  // headers too, which the bucket doesn't grant for GET. Navigating the
  // tab directly to the URL is a plain top-level navigation, not a
  // CORS-checked request, so that restriction doesn't apply to it.
  const newTab = window.open("", "_blank");
  try {
    const response = await authFetch(`${API_BASE}/documents/${documentId}/view`);
    if (!response.ok) throw new Error(`Could not open document (${response.status})`);
    const { viewUrl } = await response.json();
    if (newTab) newTab.location = viewUrl;
  } catch (err) {
    if (newTab) newTab.close();
    showHistoryError(err.message);
  }
}

function renderHistoryPage() {
  const totalPages = Math.max(1, Math.ceil(historyDocuments.length / HISTORY_PAGE_SIZE));
  historyPage = Math.min(historyPage, totalPages - 1);
  const start = historyPage * HISTORY_PAGE_SIZE;
  const pageDocuments = historyDocuments.slice(start, start + HISTORY_PAGE_SIZE);

  const body = el("history-body");
  body.innerHTML = "";

  const status = el("status-filter").value;
  const emptyEl = el("history-empty");
  emptyEl.hidden = historyDocuments.length > 0;
  emptyEl.textContent = status ? "No documents with this status." : "No documents uploaded yet.";

  pageDocuments.forEach((doc) => {
    const row = document.createElement("tr");
    row.className = "clickable";
    row.addEventListener("click", () => trackDocument(doc.documentId));
    row.innerHTML = `
      <td>${doc.originalFilename || doc.sourceKey || doc.documentId}</td>
      <td>${doc.state || ""}</td>
      <td>${pillFor(doc.status)}</td>
      <td>${formatTimestamp(doc.ingestedAt)}</td>
    `;

    // Built via textContent, not the innerHTML template above - unlike
    // originalFilename (sanitized server-side to a safe charset),
    // uploadedBy is a Cognito email the user themselves supplied at
    // registration and isn't guaranteed free of HTML metacharacters.
    const uploadedByCell = document.createElement("td");
    uploadedByCell.textContent = doc.uploadedBy || "";
    row.appendChild(uploadedByCell);

    const actionsCell = document.createElement("td");
    actionsCell.className = "actions-col";

    const viewLink = document.createElement("a");
    viewLink.className = "icon-button view-button";
    viewLink.innerHTML = EYE_ICON_SVG;
    viewLink.href = "#";
    viewLink.title = "View PDF";
    viewLink.setAttribute("aria-label", "View uploaded PDF");
    viewLink.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      handleViewClick(doc.documentId);
    });
    actionsCell.appendChild(viewLink);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "icon-button delete-button";
    deleteButton.innerHTML = TRASH_ICON_SVG;
    const blocked = DELETE_BLOCKED_STATUSES.has(doc.status);
    deleteButton.disabled = blocked;
    deleteButton.title = blocked ? `Cannot delete while ${statusMeta(doc.status).label.toLowerCase()}` : "Delete permanently";
    deleteButton.setAttribute("aria-label", "Delete document");
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      handleDeleteClick(doc);
    });
    actionsCell.appendChild(deleteButton);
    row.appendChild(actionsCell);

    body.appendChild(row);
  });

  const pager = el("history-pager");
  pager.hidden = historyDocuments.length <= HISTORY_PAGE_SIZE;
  el("history-page-info").textContent = `Page ${historyPage + 1} of ${totalPages}`;
  el("history-prev").disabled = historyPage === 0;
  el("history-next").disabled = historyPage >= totalPages - 1;
}

async function loadHistory() {
  try {
    const status = el("status-filter").value;
    const params = new URLSearchParams({ limit: "100" });
    if (status) params.set("status", status);
    const response = await authFetch(`${API_BASE}/documents?${params}`);
    if (!response.ok) throw new Error(`Could not load history (${response.status})`);
    const { documents } = await response.json();

    historyDocuments = documents;
    historyPage = 0;
    renderHistoryPage();
  } catch (err) {
    console.error(err);
  }
}

function clearHistoryError() {
  el("history-error").hidden = true;
}

function showHistoryError(message) {
  const errorEl = el("history-error");
  errorEl.textContent = message;
  errorEl.hidden = false;
}

async function deleteDocument(documentId) {
  const response = await authFetch(`${API_BASE}/documents/${documentId}`, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.message || `Delete failed (${response.status})`);
  }
}

async function handleDeleteClick(doc) {
  clearHistoryError();
  const label = doc.originalFilename || doc.sourceKey || doc.documentId;
  if (!confirm(`Permanently delete "${label}"? This cannot be undone.`)) return;

  try {
    await deleteDocument(doc.documentId);
    if (currentDocumentId === doc.documentId) {
      stopPolling();
      currentDocumentId = null;
      el("tracking-card").hidden = true;
    }
    await loadHistory();
  } catch (err) {
    showHistoryError(err.message);
  }
}

async function patchDocument(documentId, edits) {
  const response = await authFetch(`${API_BASE}/documents/${documentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edits),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || `Save failed (${response.status})`);
  return body;
}

async function resubmitDocument(documentId) {
  const response = await authFetch(`${API_BASE}/documents/${documentId}/resubmit`, { method: "POST" });
  const body = await response.json();
  if (!response.ok) {
    const detail = body.schemaErrors && body.schemaErrors.length ? `: ${body.schemaErrors.join("; ")}` : "";
    throw new Error((body.message || `Resubmit failed (${response.status})`) + detail);
  }
  return body;
}

async function handleSaveClick() {
  if (!currentDocumentId) return;
  clearEditError();
  const button = el("save-button");
  button.disabled = true;
  button.textContent = "Saving…";

  try {
    const doc = await patchDocument(currentDocumentId, collectEditFormValues());
    // renderDocument -> renderEditForm re-greys Save changes (nothing
    // unsaved right after a successful save) - don't undo that here.
    renderDocument(doc);
    loadHistory();
    button.textContent = "Save changes";
  } catch (err) {
    showEditError(err.message);
    button.disabled = false;
    button.textContent = "Save changes";
  }
}

async function handleResubmitClick() {
  if (!currentDocumentId) return;
  clearEditError();
  const button = el("resubmit-button");
  button.disabled = true;
  button.textContent = "Resubmitting…";

  try {
    const doc = await resubmitDocument(currentDocumentId);
    renderDocument(doc);
    loadHistory();
  } catch (err) {
    showEditError(err.message);
    button.disabled = false;
  } finally {
    button.textContent = "Resubmit";
  }
}

function setupFileDrop() {
  const dropZone = el("file-drop");
  const fileInput = el("file-input");
  const label = el("file-drop-label");

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) label.textContent = fileInput.files[0].name;
  });

  ["dragover", "dragenter"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    })
  );

  ["dragleave", "drop"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
    })
  );

  dropZone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) {
      fileInput.files = e.dataTransfer.files;
      label.textContent = file.name;
    }
  });
}

document.getElementById("upload-form").addEventListener("submit", handleUploadSubmit);
document.getElementById("refresh-button").addEventListener("click", loadHistory);
document.getElementById("history-prev").addEventListener("click", () => {
  historyPage -= 1;
  renderHistoryPage();
});
document.getElementById("history-next").addEventListener("click", () => {
  historyPage += 1;
  renderHistoryPage();
});
document.getElementById("status-filter").addEventListener("change", loadHistory);
document.getElementById("save-button").addEventListener("click", handleSaveClick);
document.getElementById("edit-form").addEventListener("input", () => {
  el("save-button").disabled = false;
});
document.getElementById("resubmit-button").addEventListener("click", handleResubmitClick);

document.getElementById("login-form").addEventListener("submit", handleLoginSubmit);
document.getElementById("register-form").addEventListener("submit", handleRegisterSubmit);
document.getElementById("verify-form").addEventListener("submit", handleVerifySubmit);
document.getElementById("resend-code-button").addEventListener("click", handleResendCode);
document.getElementById("show-register-link").addEventListener("click", (event) => {
  event.preventDefault();
  showAuthView("register");
});
document.getElementById("show-login-link").addEventListener("click", (event) => {
  event.preventDefault();
  showAuthView("login");
});
document.getElementById("verify-show-login-link").addEventListener("click", (event) => {
  event.preventDefault();
  showAuthView("login");
});
document.getElementById("logout-button").addEventListener("click", handleLogout);

setupFileDrop();

async function init() {
  try {
    await loadAuthConfig();
  } catch (err) {
    console.error(err);
  }
  if (getSession()) {
    showApp();
    loadHistory();
  } else {
    showAuthView("login");
  }
}
init();
