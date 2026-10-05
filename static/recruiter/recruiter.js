const API = "";
let token = localStorage.getItem("recruiter_token") || null;

const loginView = document.getElementById("login-view");
const dashView = document.getElementById("dash-view");
const candidatesBody = document.getElementById("candidates-body");
const exportBtn = document.getElementById("export-btn");
const applyBtn = document.getElementById("apply-filters");
const statGrid = document.getElementById("stat-grid");
const responsesSelect = document.getElementById("responses-candidate-select");
const responsesList = document.getElementById("responses-list");
const deleteBtn = document.getElementById("delete-btn");
const selectAll = document.getElementById("select-all");
let selectedIds = new Set();
let candidatesById = new Map();
let jobsCache = [];
let orgSlug = null;
let responsesCandidateId = null;

const jobList = document.getElementById("job-list");
const jobTitleInput = document.getElementById("job-title");
const jobDescInput = document.getElementById("job-description");
const jobMustInput = document.getElementById("job-must");
const jobNiceInput = document.getElementById("job-nice");
const jobMinExpInput = document.getElementById("job-min-exp");
const jobError = document.getElementById("job-error");
const jobExtractBtn = document.getElementById("job-extract-btn");
const jobCreateBtn = document.getElementById("job-create-btn");
const filterJob = document.getElementById("filter-job");

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

const logsSelect = document.getElementById("logs-candidate-select");
const logsList = document.getElementById("logs-list");

const dashOrgName = document.getElementById("dash-org-name");
const dashUserBlock = document.getElementById("dash-user-block");
const dashUserName = document.getElementById("dash-user-name");
const dashUserEmail = document.getElementById("dash-user-email");
const dashAvatar = document.getElementById("dash-avatar");
const dashRoleBadge = document.getElementById("dash-role-badge");

async function showDashboard() {
  loginView.style.display = "none";
  dashView.style.display = "grid";

  const me = await (await authedFetch(`${API}/recruiter/me`)).json();
  dashUserName.textContent = me.name;
  dashUserEmail.textContent = me.email;
  dashAvatar.textContent = me.name.split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
  dashRoleBadge.textContent = me.role;
  dashUserBlock.style.display = "flex";

  const org = await (await authedFetch(`${API}/recruiter/org`)).json();
  dashOrgName.textContent = org.org_name;
  orgSlug = org.org_slug;

  loadOverview();
  loadJobs();
  loadCandidates();
}

function currentFilters() {
  const role = document.getElementById("filter-role").value.trim();
  const tech = document.getElementById("filter-tech").value.trim();
  const experience = document.getElementById("filter-experience").value.trim();
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (filterJob.value) params.set("job_id", filterJob.value);
  if (role) params.set("role", role);
  if (tech) params.set("tech", tech);
  if (experience) params.set("min_experience", experience);
  if (status) params.set("status", status);
  return params;
}

async function authedFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  });
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
    <div class="stat-card"><div class="stat-value">${data.abandoned}</div><div class="stat-label">Abandoned</div></div>
    <div class="stat-card"><div class="stat-value">${data.avg_experience ?? "—"}</div><div class="stat-label">Avg. experience (yrs)</div></div>
  `;
}

async function loadCandidates() {
  const params = currentFilters();
  const res = await authedFetch(`${API}/recruiter/candidates?${params.toString()}`);
  const rows = await res.json();

  candidatesBody.innerHTML = "";
  candidatesById = new Map(rows.map((c) => [c.id, c]));
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="row-check" data-id="${c.id}" ${selectedIds.has(c.id) ? "checked" : ""}></td>
      <td>${escapeHtml(c.name) || "—"}</td>
      <td>${escapeHtml(c.job_title) || "—"}</td>
      <td>${fitBadge(c)}</td>
      <td>${escapeHtml(c.email) || "—"}</td>
      <td>${escapeHtml(c.phone) || "—"}</td>      
      <td>${escapeHtml(c.location) || "—"}</td>
      <td>${c.experience ?? "—"}</td>
      <td>${escapeHtml(c.role) || "—"}</td>
      <td>${escapeHtml((c.tech_stack || []).join(", ")) || "—"}</td>
      <td>${escapeHtml(c.resume_filename) || "—"}</td>
      <td><span class="badge ${escapeHtml(c.status)}">${escapeHtml(c.status)}</span></td>
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

  logsSelect.innerHTML = '<option value="">Select a candidate…</option>';
  rows.forEach((c) => {
  const opt = document.createElement("option");
  opt.value = c.id;
  opt.textContent = c.name || c.email || c.id;
  logsSelect.appendChild(opt);
  });
}

async function loadCandidateQuestions(candidateId) {
  if (!candidateId) {
    responsesList.innerHTML = "";
    return;
  }
  responsesCandidateId = candidateId;
  responsesList.innerHTML = '<div class="empty-note">Loading…</div>';
  const res = await authedFetch(`${API}/recruiter/candidates/${candidateId}/questions`);
  const data = await res.json();

  if (data.assessment_type === "mcq") {
    renderMcqResults(data.mcq);
  } else {
    renderLegacyQuestions(data.legacy_questions || []);
  }
  const candidate = candidatesById.get(candidateId);
  if (candidate && candidate.fit_summary) {
    responsesList.prepend(renderFitCard(candidate));
  }
}

function fitBand(score) {
  if (score >= 75) return "fit-high";
  if (score >= 50) return "fit-mid";
  return "fit-low";
}

function fitBadge(c) {
  if (c.fit_score == null) return "—";
  return `<span class="fit-score ${fitBand(c.fit_score)}" title="${escapeHtml(c.fit_summary)}">${c.fit_score}</span>`;
}

function renderFitCard(c) {
  const card = document.createElement("div");
  card.className = "fit-card";
  const d = c.fit_details || {};
  const chips = [
    ...((d.must_have && d.must_have.matched) || []).map((m) => `<span class="skill-chip" title="Found in ${escapeHtml(m.source === "tech_stack" ? "confirmed tech stack" : "resume text")}">${escapeHtml(m.skill)}</span>`),
    ...((d.must_have && d.must_have.missing) || []).map((s) => `<span class="skill-chip missing" title="Must-have not found">${escapeHtml(s)}</span>`),
    ...((d.nice_to_have && d.nice_to_have.matched) || []).map((m) => `<span class="skill-chip nice" title="Nice-to-have">${escapeHtml(m.skill)}</span>`),
  ].join("");
  card.innerHTML = `
    <div class="fit-card-head">
      ${c.fit_score != null ? `<span class="fit-score ${fitBand(c.fit_score)}">${c.fit_score}</span>` : ""}
      <span>Fit for ${escapeHtml(c.job_title || "this job")}</span>
    </div>
    <div class="fit-card-summary">${escapeHtml(c.fit_summary)}</div>
    ${chips ? `<div class="skill-chips">${chips}</div>` : ""}
  `;
  return card;
}

function parseSkillInput(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function showJobError(message) {
  jobError.textContent = message;
  jobError.style.display = message ? "block" : "none";
}

async function loadJobs() {
  const res = await authedFetch(`${API}/recruiter/jobs`);
  jobsCache = await res.json();
  renderJobs();

  const previous = filterJob.value;
  filterJob.innerHTML = '<option value="">Any job</option><option value="none">General link (no job)</option>';
  jobsCache.forEach((j) => {
    const opt = document.createElement("option");
    opt.value = j.id;
    opt.textContent = j.status === "open" ? j.title : `${j.title} (closed)`;
    filterJob.appendChild(opt);
  });
  filterJob.value = Array.from(filterJob.options).some((o) => o.value === previous) ? previous : "";
}

function jobScreeningLink(job) {
  return `${window.location.origin}/screen/${orgSlug}/jobs/${job.id}`;
}

function renderJobs() {
  jobList.innerHTML = "";
  if (jobsCache.length === 0) {
    jobList.innerHTML = '<div class="empty-note" style="padding:0;">No job openings yet. Create one above to get a job-specific screening link.</div>';
    return;
  }
  jobsCache.forEach((job) => {
    const card = document.createElement("div");
    card.className = "job-card";
    const chips = [
      ...job.must_have_skills.map((s) => `<span class="skill-chip">${escapeHtml(s)}</span>`),
      ...job.nice_to_have_skills.map((s) => `<span class="skill-chip nice" title="Nice-to-have">${escapeHtml(s)}</span>`),
    ].join("");
    card.innerHTML = `
      <div class="job-card-head">
        <span class="job-card-title">${escapeHtml(job.title)}</span>
        <span class="badge ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
      </div>
      ${chips ? `<div class="skill-chips">${chips}</div>` : ""}
      <div class="job-card-meta">
        ${job.candidate_count} candidate${job.candidate_count === 1 ? "" : "s"}
        ${job.min_experience != null ? ` · ${job.min_experience}+ yrs required` : ""}
      </div>
      <div class="job-card-actions">
        <button data-action="ranked">View ranked candidates</button>
        ${job.status === "open" ? '<button data-action="copy">Copy screening link</button>' : ""}
        <button data-action="toggle">${job.status === "open" ? "Close job" : "Reopen job"}</button>
      </div>
    `;
    card.querySelector('[data-action="ranked"]').addEventListener("click", () => {
      filterJob.value = job.id;
      document.querySelector('.rec-nav-item[data-tab="candidates"]').click();
      loadCandidates();
    });
    card.querySelector('[data-action="copy"]')?.addEventListener("click", async (e) => {
      try {
        await navigator.clipboard.writeText(jobScreeningLink(job));
        e.target.textContent = "Copied!";
      } catch (err) {
        prompt("Copy this screening link:", jobScreeningLink(job));
      }
    });
    card.querySelector('[data-action="toggle"]').addEventListener("click", async () => {
      const res = await authedFetch(`${API}/recruiter/jobs/${job.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: job.status === "open" ? "closed" : "open" }),
      });
      if (!res.ok) {
        alert(formatError(await res.json().catch(() => ({}))));
        return;
      }
      loadJobs();
    });
    jobList.appendChild(card);
  });
}

jobExtractBtn.addEventListener("click", async () => {
  showJobError("");
  if (!jobTitleInput.value.trim() || !jobDescInput.value.trim()) {
    showJobError("Enter a job title and paste the description first.");
    return;
  }
  jobExtractBtn.disabled = true;
  jobExtractBtn.textContent = "Extracting…";
  try {
    const res = await authedFetch(`${API}/recruiter/jobs/parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: jobTitleInput.value.trim(), description: jobDescInput.value.trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showJobError(formatError(data));
      return;
    }
    jobMustInput.value = data.must_have_skills.join(", ");
    jobNiceInput.value = data.nice_to_have_skills.join(", ");
    jobMinExpInput.value = data.min_experience ?? "";
  } finally {
    jobExtractBtn.disabled = false;
    jobExtractBtn.textContent = "Extract requirements with AI";
  }
});

jobCreateBtn.addEventListener("click", async () => {
  showJobError("");
  const minExp = jobMinExpInput.value.trim();
  jobCreateBtn.disabled = true;
  try {
    const res = await authedFetch(`${API}/recruiter/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: jobTitleInput.value.trim(),
        description: jobDescInput.value.trim(),
        must_have_skills: parseSkillInput(jobMustInput.value),
        nice_to_have_skills: parseSkillInput(jobNiceInput.value),
        min_experience: minExp === "" ? null : Number(minExp),
      }),
    });
    if (!res.ok) {
      showJobError(formatError(await res.json().catch(() => ({}))));
      return;
    }
    [jobTitleInput, jobDescInput, jobMustInput, jobNiceInput, jobMinExpInput].forEach((el) => (el.value = ""));
    loadJobs();
  } finally {
    jobCreateBtn.disabled = false;
  }
});

filterJob.addEventListener("change", loadCandidates);

function renderMcqResults(mcq) {
  responsesList.innerHTML = "";

  const summary = document.createElement("div");
  summary.className = "qa-summary";
  const flagged = mcq.tab_switch_count > 0 || mcq.fullscreen_exit_count > 0;
  summary.innerHTML = `
    <div class="qa-summary-stat">
      <div class="qa-summary-value">${mcq.technical_score} / ${mcq.technical_total}</div>
      <div class="qa-summary-label">Technical score</div>
    </div>
    <div class="qa-summary-stat">
      <div class="qa-summary-value">${escapeHtml(mcq.final_difficulty_tier || "—")}</div>
      <div class="qa-summary-label">Final difficulty</div>
    </div>
    <div class="qa-summary-stat">
      <div class="qa-summary-value">${mcq.duration_minutes != null ? mcq.duration_minutes + " min" : "In progress"}</div>
      <div class="qa-summary-label">Duration</div>
    </div>
    <div class="qa-summary-stat">
      <div class="qa-summary-value">${mcq.open_text_avg != null ? mcq.open_text_avg + " / 5" : "—"}</div>
      <div class="qa-summary-label">Written answers</div>
    </div>
    <div class="qa-summary-stat">
      <div class="qa-summary-value${flagged ? " flag-warn" : ""}">${mcq.tab_switch_count} / ${mcq.fullscreen_exit_count}</div>
      <div class="qa-summary-label">Tab switches / FS exits</div>
    </div>
  `;
  responsesList.appendChild(summary);

  mcq.questions.forEach((q) => {
    const div = document.createElement("div");
    div.className = "qa-item";

    let html = `<div class="qa-tech">${escapeHtml(q.question_type)}`;
    if (q.difficulty_tier) html += ` · ${escapeHtml(q.difficulty_tier)}`;
    if (q.question_type === "technical") {
      html += `<span class="qa-badge ${q.is_correct ? "correct" : "incorrect"}">${q.is_correct ? "Correct" : "Incorrect"}</span>`;
    }
    html += `</div><div class="qa-question">${escapeHtml(q.question_text)}</div>`;

    if (q.question_type === "open_text") {
      html += `<div class="qa-answer">${escapeHtml(q.text_response) || "(no response recorded)"}</div>`;
      html += `<div class="judge-block" data-question-index="${q.question_index}"></div>`;
    } else if (q.options) {
      q.options.forEach((opt) => {
        let cls = "qa-option-row";
        if (q.question_type === "technical") {
          if (opt.id === q.correct_option_id) cls += " qa-correct-option";
          else if (opt.id === q.selected_option_id) cls += " qa-selected-wrong";
        } else if (opt.id === q.selected_option_id) {
          cls += " qa-selected-neutral";
        }
        html += `<div class="${cls}">${escapeHtml(opt.text)}</div>`;
      });
    }
    if (q.time_taken_seconds != null) {
      html += `<div class="qa-answer" style="margin-top:6px;">Time taken: ${q.time_taken_seconds}s</div>`;
    }

    div.innerHTML = html;
    if (q.question_type === "open_text" && q.judge) {
      renderJudgeBlock(div.querySelector(".judge-block"), q.question_index, q.judge);
    }
    responsesList.appendChild(div);
  });
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

async function gradeCandidateAnswers(force) {
  const res = await authedFetch(`${API}/recruiter/candidates/${responsesCandidateId}/judge?force=${force}`, { method: "POST" });
  if (!res.ok) {
    alert(formatError(await res.json().catch(() => ({}))));
    return;
  }
  const data = await res.json();
  if (data.failed) alert(`${data.failed} answer(s) couldn't be graded — the AI service may be unavailable. Try again shortly.`);
  loadCandidateQuestions(responsesCandidateId);
}

function renderJudgeBlock(el, questionIndex, judge) {
  if (judge.status === "unanswered") {
    el.remove();
    return;
  }
  if (judge.status === "pending" || judge.status === "failed") {
    el.innerHTML = `
      <span class="judge-note">${judge.status === "pending" ? "AI grading in progress…" : "AI grading failed."}</span>
      <button class="judge-link" data-action="grade">${judge.status === "pending" ? "Grade now" : "Retry"}</button>
    `;
    el.querySelector('[data-action="grade"]').addEventListener("click", (e) => {
      e.target.disabled = true;
      e.target.textContent = "Grading…";
      gradeCandidateAnswers(false);
    });
    return;
  }

  const chips = judge.dimensions
    .map((d) => `<span class="judge-chip">${capitalize(d)} <strong>${judge.scores[d]}</strong></span>`)
    .join("");
  const source = judge.status === "overridden"
    ? `Overridden by a recruiter · AI scored ${judge.dimensions.map((d) => judge.ai_scores ? judge.ai_scores[d] : "—").join("/")}`
    : `AI-graded${judge.model ? ` (${escapeHtml(judge.model)})` : ""} · advisory`;
  el.innerHTML = `
    ${judge.manipulation_attempt ? '<div class="judge-flag"><i class="ti ti-alert-triangle"></i> This answer appears to try to instruct the AI grader. Its scores cover only the genuine content — worth a manual read.</div>' : ""}
    <div class="judge-chips">${chips}<span class="judge-overall">${judge.overall} / 5</span></div>
    ${judge.rationale ? `<div class="judge-rationale">${escapeHtml(judge.rationale)}</div>` : ""}
    <div class="judge-source">${source}
      <button class="judge-link" data-action="edit">Override</button>
      ${judge.status === "overridden" ? '<button class="judge-link" data-action="revert">Revert to AI</button>' : ""}
    </div>
    <div class="judge-edit" style="display:none;">
      ${judge.dimensions.map((d) => `
        <label>${capitalize(d)}
          <select data-dim="${d}">${[1, 2, 3, 4, 5].map((n) => `<option value="${n}" ${judge.scores[d] === n ? "selected" : ""}>${n}</option>`).join("")}</select>
        </label>`).join("")}
      <button class="judge-link" data-action="save">Save</button>
    </div>
  `;

  const saveOverride = async (scores) => {
    const res = await authedFetch(`${API}/recruiter/candidates/${responsesCandidateId}/answers/${questionIndex}/override`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scores }),
    });
    if (!res.ok) {
      alert(formatError(await res.json().catch(() => ({}))));
      return;
    }
    loadCandidateQuestions(responsesCandidateId);
  };

  el.querySelector('[data-action="edit"]').addEventListener("click", () => {
    el.querySelector(".judge-edit").style.display = "flex";
  });
  el.querySelector('[data-action="save"]').addEventListener("click", () => {
    const scores = {};
    el.querySelectorAll(".judge-edit select").forEach((sel) => (scores[sel.dataset.dim] = Number(sel.value)));
    saveOverride(scores);
  });
  el.querySelector('[data-action="revert"]')?.addEventListener("click", () => saveOverride(null));
}

function renderLegacyQuestions(questions) {
  responsesList.innerHTML = "";
  if (questions.length === 0) {
    responsesList.innerHTML = '<div class="empty-note">No interview responses yet for this candidate.</div>';
    return;
  }
  questions.forEach((q) => {
    const div = document.createElement("div");
    div.className = "qa-item";
    div.innerHTML = `
      <div class="qa-tech">${escapeHtml(q.technology)} · ${escapeHtml(q.difficulty_tier)}</div>
      <div class="qa-question">${escapeHtml(q.question_text)}</div>
      <div class="qa-answer">${escapeHtml(q.answer_text) || "(no answer recorded yet)"}</div>
    `;
    responsesList.appendChild(div);
  });
}

async function loadCandidateLogs(candidateId) {
  if (!candidateId) {
    logsList.innerHTML = "";
    return;
  }
  logsList.innerHTML = '<div class="empty-note">Loading…</div>';
  const res = await authedFetch(`${API}/recruiter/candidates/${candidateId}/logs`);
  const logs = await res.json();

  if (logs.length === 0) {
    logsList.innerHTML = '<div class="empty-note">No logs recorded for this candidate yet.</div>';
    return;
  }

  logsList.innerHTML = "";
  logs.forEach((l) => {
    const div = document.createElement("div");
    div.className = "log-item";
    const time = new Date(l.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    div.innerHTML = `
      <span class="log-time">${escapeHtml(time)}</span>
      <span class="log-badge ${escapeHtml(l.event_type)}">${escapeHtml(l.event_type.replace("_", " "))}</span>
      <span class="log-detail">${escapeHtml(l.detail)}</span>
    `;
    logsList.appendChild(div);
  });
}

logsSelect.addEventListener("change", () => {
  loadCandidateLogs(logsSelect.value);
});

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

wireProfileDropdown({
  getToken: () => token,
  onLogout: () => {
    localStorage.removeItem("recruiter_token");
    token = null;
    window.location.href = "/login";
  },
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

  const res = await fetch(`${API}/recruiter/candidates/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ candidate_ids: Array.from(selectedIds) }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(formatError(err) || "Failed to delete candidates — please try again.");
    return;
  }

  selectedIds.clear();
  loadOverview();
  loadCandidates();
});

if (token) showDashboard();

document.getElementById("back-link-login")?.addEventListener("click", goBackOrHome);
document.getElementById("back-link-dash")?.addEventListener("click", goBackOrHome);