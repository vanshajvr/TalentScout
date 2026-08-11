const API = "";
let token = localStorage.getItem("recruiter_token") || null;
let cachedCandidates = [];

const loginView = document.getElementById("login-view");
const dashView = document.getElementById("dash-view");
const passwordInput = document.getElementById("password-input");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");
const candidatesBody = document.getElementById("candidates-body");
const candidateCount = document.getElementById("candidate-count");
const exportBtn = document.getElementById("export-btn");
const applyBtn = document.getElementById("apply-filters");
const statGrid = document.getElementById("stat-grid");
const responsesSelect = document.getElementById("responses-candidate-select");
const responsesList = document.getElementById("responses-list");
const deleteBtn = document.getElementById("delete-btn");
const selectAll = document.getElementById("select-all");
let selectedIds = new Set();

function showDashboard() {
  loginView.style.display = "none";
  dashView.style.display = "grid";
  loadOverview();
  loadCandidates();
}

function currentFilters() {
  const role = document.getElementById("filter-role").value.trim();
  const tech = document.getElementById("filter-tech").value.trim();
  const experience = document.getElementById("filter-experience").value.trim();
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (role) params.set("role", role);
  if (tech) params.set("tech", tech);
  if (experience) params.set("min_experience", experience);
  if (status) params.set("status", status);
  return params;
}

async function authedFetch(url) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (res.status === 401) {
    localStorage.removeItem("recruiter_token");
    token = null;
    dashView.style.display = "none";
    loginView.style.display = "block";
    throw new Error("unauthorized");
  }
  return res;
}

async function loadOverview() {
  const res = await authedFetch(`${API}/recruiter/overview`);
  const data = await res.json();
  statGrid.innerHTML = `
    <div class="stat-card"><div class="stat-value">${data.total_candidates}</div><div class="stat-label">Total candidates</div></div>
    <div class="stat-card"><div class="stat-value">${data.in_progress}</div><div class="stat-label">In progress</div></div>
    <div class="stat-card"><div class="stat-value">${data.completed}</div><div class="stat-label">Completed</div></div>
    <div class="stat-card"><div class="stat-value">${data.avg_experience ?? "—"}</div><div class="stat-label">Avg. experience (yrs)</div></div>
  `;
}

async function loadCandidates() {
  candidateCount.textContent = "Loading…";
  const params = currentFilters();
  const res = await authedFetch(`${API}/recruiter/candidates?${params.toString()}`);
  const rows = await res.json();
  cachedCandidates = rows;
  candidateCount.textContent = `${rows.length} candidate${rows.length === 1 ? "" : "s"}`;

  candidatesBody.innerHTML = "";
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="row-check" data-id="${c.id}" ${selectedIds.has(c.id) ? "checked" : ""}></td>
      <td>${c.name || "—"}</td>
      <td>${c.email || "—"}${c.email_verified ? " ✅" : ""}</td>
      <td>${c.phone || "—"}${c.phone_verified ? " ✅" : ""}</td>
      <td>${c.location || "—"}</td>
      <td>${c.experience ?? "—"}</td>
      <td>${c.role || "—"}</td>
      <td>${(c.tech_stack || []).join(", ") || "—"}</td>
      <td>${c.resume_filename || "—"}</td>
      <td><span class="badge ${c.status}">${c.status}</span></td>
      <td>${c.created_at ? new Date(c.created_at).toLocaleDateString() : "—"}</td>
    `;
    candidatesBody.appendChild(tr);
  });

  document.querySelectorAll(".row-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      if (cb.checked) selectedIds.add(cb.dataset.id);
      else selectedIds.delete(cb.dataset.id);
    });
  });

  responsesSelect.innerHTML = '<option value="">Select a candidate…</option>';
  rows.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name || c.email || c.id;
    responsesSelect.appendChild(opt);
  });
}

async function loadCandidateQuestions(candidateId) {
  if (!candidateId) {
    responsesList.innerHTML = "";
    return;
  }
  responsesList.innerHTML = '<div class="empty-note">Loading…</div>';
  const res = await authedFetch(`${API}/recruiter/candidates/${candidateId}/questions`);
  const questions = await res.json();

  if (questions.length === 0) {
    responsesList.innerHTML = '<div class="empty-note">No interview responses yet for this candidate.</div>';
    return;
  }

  responsesList.innerHTML = "";
  questions.forEach((q) => {
    const div = document.createElement("div");
    div.className = "qa-item";
    div.innerHTML = `
      <div class="qa-tech">${q.technology} · ${q.difficulty_tier}</div>
      <div class="qa-question">${q.question_text}</div>
      <div class="qa-answer">${q.answer_text || "(no answer recorded yet)"}</div>
    `;
    responsesList.appendChild(div);
  });
}

document.querySelectorAll(".rec-nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".rec-nav-item").forEach((i) => i.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
    item.classList.add("active");
    document.getElementById(`tab-${item.dataset.tab}`).style.display = "block";
  });
});
responsesSelect.addEventListener("change", () => {
  loadCandidateQuestions(responsesSelect.value);
});

loginBtn.addEventListener("click", async () => {
  const password = passwordInput.value;
  loginError.style.display = "none";
  const res = await fetch(`${API}/recruiter/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    loginError.textContent = "Incorrect password.";
    loginError.style.display = "block";
    return;
  }
  const data = await res.json();
  token = data.token;
  localStorage.setItem("recruiter_token", token);
  showDashboard();
});

passwordInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loginBtn.click();
});

applyBtn.addEventListener("click", loadCandidates);

exportBtn.addEventListener("click", () => {
  const params = currentFilters();
  const url = `${API}/recruiter/candidates/export?${params.toString()}`;
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((res) => res.blob())
    .then((blob) => {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "candidates.csv";
      link.click();
    });
});

selectAll.addEventListener("change", () => {
  document.querySelectorAll(".row-check").forEach((cb) => {
    cb.checked = selectAll.checked;
    if (selectAll.checked) selectedIds.add(cb.dataset.id);
    else selectedIds.delete(cb.dataset.id);
  });
});

deleteBtn.addEventListener("click", async () => {
  if (selectedIds.size === 0) {
    alert("Select at least one candidate first.");
    return;
  }
  const confirmed = confirm(`Delete ${selectedIds.size} candidate(s)? This can't be undone.`);
  if (!confirmed) return;

  await fetch(`${API}/recruiter/candidates/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ candidate_ids: Array.from(selectedIds) }),
  });

  selectedIds.clear();
  loadOverview();
  loadCandidates();
});

if (token) showDashboard();