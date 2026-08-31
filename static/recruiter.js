const API = "";
let token = localStorage.getItem("recruiter_token") || null;

const loginView = document.getElementById("login-view");
const dashView = document.getElementById("dash-view");
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

const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");
const signupName = document.getElementById("signup-name");
const signupEmail = document.getElementById("signup-email");
const signupPassword = document.getElementById("signup-password");
const signupBtn = document.getElementById("signup-btn");
const signupError = document.getElementById("signup-error");
const loginMode = document.getElementById("login-mode");
const signupMode = document.getElementById("signup-mode");

const orgSignupMode = document.getElementById("org-signup-mode");
const orgSignupBtn = document.getElementById("org-signup-btn");
const orgSignupError = document.getElementById("org-signup-error");
const inviteSection = document.getElementById("invite-section");
const generateInviteBtn = document.getElementById("generate-invite-btn");
const inviteCodeDisplay = document.getElementById("invite-code-display");

const isAdminSignup = new URLSearchParams(window.location.search).get("admin") === "true";
if (isAdminSignup && !token) {
  loginMode.style.display = "none";
  signupMode.style.display = "none";
  orgSignupMode.style.display = "block";
}

async function showDashboard() {
  loginView.style.display = "none";
  dashView.style.display = "grid";
  loadOverview();
  loadCandidates();

  const res = await authedFetch(`${API}/recruiter/me`);
  const me = await res.json();
  if (me.role === "admin") {
    inviteSection.style.display = "block";
  }
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

function formatError(err) {
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail) && err.detail[0]?.msg) return err.detail[0].msg;
  return "Could not create account.";
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
  candidateCount.textContent = `${rows.length} candidate${rows.length === 1 ? "" : "s"}`;

  candidatesBody.innerHTML = "";
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="row-check" data-id="${c.id}" ${selectedIds.has(c.id) ? "checked" : ""}></td>
      <td>${c.name || "—"}</td>
      <td>${c.email || "—"}</td>
      <td>${c.phone || "—"}</td>      
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

document.getElementById("show-signup").addEventListener("click", (e) => {
  e.preventDefault();
  loginMode.style.display = "none";
  signupMode.style.display = "block";
});

document.getElementById("show-login").addEventListener("click", (e) => {
  e.preventDefault();
  signupMode.style.display = "none";
  loginMode.style.display = "block";
});

document.getElementById("toggle-invite-visibility").addEventListener("click", () => {
  const input = document.getElementById("signup-invite");
  const icon = document.getElementById("invite-eye-icon");
  if (input.type === "password") {
    input.type = "text";
    icon.className = "ti ti-eye-off";
  } else {
    input.type = "password";
    icon.className = "ti ti-eye";
  }
});

loginBtn.addEventListener("click", async () => {
  loginError.style.display = "none";
  const res = await fetch(`${API}/recruiter/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: loginEmail.value, password: loginPassword.value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    loginError.textContent = err.detail || "Incorrect email or password.";
    loginError.style.display = "block";
    return;
  }
  const data = await res.json();
  token = data.token;
  localStorage.setItem("recruiter_token", token);
  showDashboard();
});

signupBtn.addEventListener("click", async () => {
  signupError.style.display = "none";
  const res = await fetch(`${API}/recruiter/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      name: signupName.value, 
      email: signupEmail.value, 
      password: signupPassword.value, 
      invite_code: document.getElementById("signup-invite").value }),
  });
  if (!res.ok) {
  const err = await res.json().catch(() => ({}));
  signupError.textContent = formatError(err);
  signupError.style.display = "block";
  return;
}
  const data = await res.json();
  token = data.token;
  localStorage.setItem("recruiter_token", token);
  showDashboard();
});

orgSignupBtn.addEventListener("click", async () => {
  orgSignupError.style.display = "none";
  const res = await fetch(`${API}/recruiter/signup/org`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      org_name: document.getElementById("org-signup-orgname").value,
      name: document.getElementById("org-signup-name").value,
      email: document.getElementById("org-signup-email").value,
      password: document.getElementById("org-signup-password").value,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    orgSignupError.textContent = formatError(err);
    orgSignupError.style.display = "block";
    return;
  }
  const data = await res.json();
  token = data.token;
  localStorage.setItem("recruiter_token", token);
  showDashboard();
});

document.getElementById("show-login-from-org").addEventListener("click", (e) => {
  e.preventDefault();
  orgSignupMode.style.display = "none";
  loginMode.style.display = "block";
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

generateInviteBtn.addEventListener("click", async () => {
  const res = await fetch(`${API}/recruiter/invite`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return;
  const data = await res.json();
  inviteCodeDisplay.textContent = data.code;
  inviteCodeDisplay.style.display = "block";
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

function goBackOrHome() {
  if (document.referrer && document.referrer.includes(window.location.host)) {
    history.back();
  } else {
    window.location.href = "/";
  }
}

document.getElementById("back-link-login")?.addEventListener("click", goBackOrHome);
document.getElementById("back-link-dash")?.addEventListener("click", goBackOrHome);