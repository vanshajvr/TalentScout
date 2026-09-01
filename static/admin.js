const API = "";
let token = localStorage.getItem("admin_token") || null;

const loginView = document.getElementById("login-view");
const dashView = document.getElementById("dash-view");
const loginMode = document.getElementById("login-mode");
const signupMode = document.getElementById("signup-mode");
const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");
const signupOrgname = document.getElementById("signup-orgname");
const signupName = document.getElementById("signup-name");
const signupEmail = document.getElementById("signup-email");
const signupPassword = document.getElementById("signup-password");
const signupBtn = document.getElementById("signup-btn");
const signupError = document.getElementById("signup-error");
const teamBody = document.getElementById("team-body");
const invitesBody = document.getElementById("invites-body");
const orgSub = document.getElementById("org-sub");
const generateInviteBtn = document.getElementById("generate-invite-btn");
const inviteCodeDisplay = document.getElementById("invite-code-display");

const inviteCodeText = document.getElementById("invite-code-text");
const copyInviteBtn = document.getElementById("copy-invite-btn");
const copyInviteIcon = document.getElementById("copy-invite-icon");

const dashOrgName = document.getElementById("dash-org-name");
const dashUserBlock = document.getElementById("dash-user-block");
const dashUserName = document.getElementById("dash-user-name");
const dashUserEmail = document.getElementById("dash-user-email");
const dashAvatar = document.getElementById("dash-avatar");
const dashRoleBadge = document.getElementById("dash-role-badge");

async function authedFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    localStorage.removeItem("admin_token");
    token = null;
    dashView.style.display = "none";
    loginView.style.display = "block";
    throw new Error("unauthorized");
  }
  return res;
}

async function showDashboard() {
  loginView.style.display = "none";
  dashView.style.display = "grid";

  const me = await (await authedFetch(`${API}/recruiter/me`)).json();
  dashUserName.textContent = me.name;
  dashUserEmail.textContent = me.email;
  dashAvatar.textContent = me.name.split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
  dashRoleBadge.textContent = me.role;
  dashUserBlock.style.display = "flex";

  const org = await (await authedFetch(`${API}/admin/overview`)).json();
  dashOrgName.textContent = org.org_name;

  const screeningLink = `${window.location.origin}/screen/${org.org_slug}`;
  document.getElementById("screening-link-text").textContent = screeningLink;

  loadTeam();
}

document.getElementById("copy-link-btn").addEventListener("click", async () => {
  const text = document.getElementById("screening-link-text").textContent;
  await navigator.clipboard.writeText(text);
  const icon = document.getElementById("copy-link-icon");
  icon.className = "ti ti-check";
  setTimeout(() => { icon.className = "ti ti-copy"; }, 1500);
});

async function loadTeam() {
  const rows = await (await authedFetch(`${API}/admin/team`)).json();
  teamBody.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    const otherRole = r.role === "admin" ? "recruiter" : "admin";
    tr.innerHTML = `
      <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.email)}</td>
      <td><span class="badge ${r.role === "admin" ? "completed" : "in_progress"}">${escapeHtml(r.role)}</span></td>
      <td>${r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}</td>
      <td style="display:flex; gap:6px;">
        <button class="role-btn" data-id="${r.id}" data-role="${otherRole}" style="font-size:12px; padding:5px 10px;">Make ${otherRole}</button>
        <button class="remove-btn" data-id="${r.id}" style="background:var(--warn); color:white; border:none; border-radius:6px; padding:5px 10px; font-size:12px; cursor:pointer;">Remove</button>
      </td>
    `;
    teamBody.appendChild(tr);
  });
  document.querySelectorAll(".role-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const res = await authedFetch(`${API}/admin/team/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recruiter_id: btn.dataset.id, new_role: btn.dataset.role }),
      });
      if (res.ok) loadTeam();
    });
  });
  document.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Remove this team member?")) return;
      await authedFetch(`${API}/admin/team/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recruiter_id: btn.dataset.id }),
      });
      loadTeam();
    });
  });
}

async function loadInvites() {
  const rows = await (await authedFetch(`${API}/admin/invites`)).json();
  invitesBody.innerHTML = "";
  rows.forEach((i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-family:monospace;">${i.code}</td>
      <td>${i.created_at ? new Date(i.created_at).toLocaleDateString() : "—"}</td>
      <td><span class="badge ${i.used ? "completed" : "in_progress"}">${i.used ? "Used" : "Unused"}</span></td>
      <td>${i.used_by_name || "—"}</td>
    `;
    invitesBody.appendChild(tr);
  });
}

document.querySelectorAll(".rec-nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".rec-nav-item").forEach((i) => i.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
    item.classList.add("active");
    document.getElementById(`tab-${item.dataset.tab}`).style.display = "block";
    if (item.dataset.tab === "invites") loadInvites();
  });
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

loginBtn.addEventListener("click", async () => {
  loginError.style.display = "none";
  const res = await fetch(`${API}/recruiter/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: loginEmail.value, password: loginPassword.value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    loginError.textContent = formatError(err);
    loginError.style.display = "block";
    return;
  }
  const data = await res.json();
  token = data.token;
  localStorage.setItem("admin_token", token);
  showDashboard();
});

signupBtn.addEventListener("click", async () => {
  signupError.style.display = "none";
  const res = await fetch(`${API}/admin/signup`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      org_name: signupOrgname.value, name: signupName.value,
      email: signupEmail.value, password: signupPassword.value,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    signupError.textContent = formatError(err);
    signupError.style.display = "block";
    return;
  }
  const data = await res.json();
  token = data.token;
  localStorage.setItem("admin_token", token);
  showDashboard();
});

generateInviteBtn.addEventListener("click", async () => {
  const res = await authedFetch(`${API}/admin/invite`, { method: "POST" });
  const data = await res.json();
  inviteCodeText.textContent = data.code;
  inviteCodeDisplay.style.display = "flex";
  loadInvites();
});

copyInviteBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(inviteCodeText.textContent);
  copyInviteIcon.className = "ti ti-check";
  setTimeout(() => { copyInviteIcon.className = "ti ti-copy"; }, 1500);
});

document.getElementById("logout-btn").addEventListener("click", () => {
  localStorage.removeItem("admin_token");
  token = null;
  window.location.href = "/login";
});

document.getElementById("back-link").addEventListener("click", goBackOrHome);
if (token) showDashboard();