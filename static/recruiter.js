
const API = "";
let token = localStorage.getItem("recruiter_token") || null;

const loginView = document.getElementById("login-view");
const dashView = document.getElementById("dash-view");
const passwordInput = document.getElementById("password-input");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");
const candidatesBody = document.getElementById("candidates-body");
const candidateCount = document.getElementById("candidate-count");
const exportBtn = document.getElementById("export-btn");
const applyBtn = document.getElementById("apply-filters");

function showDashboard() {
  loginView.style.display = "none";
  dashView.style.display = "flex";
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

async function loadCandidates() {
  candidateCount.textContent = "Loading…";
  const params = currentFilters();
  const res = await fetch(`${API}/recruiter/candidates?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    localStorage.removeItem("recruiter_token");
    token = null;
    dashView.style.display = "none";
    loginView.style.display = "block";
    return;
  }
  const rows = await res.json();
  candidateCount.textContent = `${rows.length} candidate${rows.length === 1 ? "" : "s"}`;
  candidatesBody.innerHTML = "";
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
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
}

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

if (token) showDashboard();