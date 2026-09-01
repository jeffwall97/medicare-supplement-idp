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

let pollTimer = null;

const el = (id) => document.getElementById(id);

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
  line.textContent = meta.label;
  line.className = `status-line ${meta.tone}`;
}

function renderDetail(doc) {
  const panel = el("detail-panel");
  const table = el("canonical-table");
  const record = doc.canonicalRecord;

  if (!record) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  table.innerHTML = "";
  Object.entries(record)
    .filter(([key]) => !["documentId", "sourceBucket", "sourceKey"].includes(key))
    .forEach(([key, value]) => {
      const row = document.createElement("tr");
      const keyCell = document.createElement("td");
      const valueCell = document.createElement("td");
      keyCell.textContent = key;
      valueCell.textContent = value;
      row.append(keyCell, valueCell);
      table.appendChild(row);
    });

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

function renderDocument(doc) {
  el("tracking-filename").textContent = doc.originalFilename || doc.sourceKey || "";
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
  const response = await fetch(`${API_BASE}/documents/${documentId}`);
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
  const response = await fetch(`${API_BASE}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name }),
  });
  if (!response.ok) throw new Error(`Could not start upload (${response.status})`);
  return response.json();
}

async function uploadToS3(uploadUrl, file) {
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

async function loadHistory() {
  try {
    const response = await fetch(`${API_BASE}/documents?limit=25`);
    if (!response.ok) throw new Error(`Could not load history (${response.status})`);
    const { documents } = await response.json();

    const body = el("history-body");
    body.innerHTML = "";
    el("history-empty").hidden = documents.length > 0;

    documents.forEach((doc) => {
      const row = document.createElement("tr");
      row.className = "clickable";
      row.addEventListener("click", () => trackDocument(doc.documentId));
      row.innerHTML = `
        <td>${doc.originalFilename || doc.sourceKey || doc.documentId}</td>
        <td>${doc.state || ""}</td>
        <td>${pillFor(doc.status)}</td>
        <td>${formatTimestamp(doc.ingestedAt)}</td>
      `;
      body.appendChild(row);
    });
  } catch (err) {
    console.error(err);
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
setupFileDrop();
loadHistory();
