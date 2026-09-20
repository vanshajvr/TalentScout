const API = "";
let sessionId = null;
let lastKnownStep = null;
let pastedThisTurn = false;

const STEPS_ORDER = [
  "greeting", "ask_name", "upload_resume", "confirm_resume_data",
  "mcq_assessment", "end"
];

const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusLine = document.getElementById("status-line");
const pasteNote = document.getElementById("paste-note");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const resumeInput = document.getElementById("resume-input");
const uploadTrigger = document.getElementById("upload-trigger");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatMessage(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function updateProgress(step) {
  const idx = STEPS_ORDER.indexOf(step);
  const total = STEPS_ORDER.length - 1;
  const pct = idx <= 0 ? 3 : Math.min(100, Math.round((idx / total) * 100));
  progressFill.style.width = pct + "%";
  progressLabel.textContent = step === "end"
    ? "Screening complete"
    : `Step ${Math.max(idx, 1)} of ${total}`;
}

function addBubble(role, text, wasPasted = false) {
  const div = document.createElement("div");
  div.className = "bubble " + (role === "user" ? "user" : "bot");
  div.innerHTML = formatMessage(text);
  if (wasPasted) {
    const tag = document.createElement("span");
    tag.className = "pasted-tag";
    tag.textContent = "pasted";
    div.appendChild(tag);
  }
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "typing";
  div.id = "typing-indicator";
  div.innerHTML = "<span></span><span></span><span></span>";
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function showGeneratingPanel() {
  const div = document.createElement("div");
  div.className = "gen-panel";
  div.id = "typing-indicator";
  div.innerHTML = `
    <div class="label">Be ready for some questions based on your profile…</div>
    <div class="gen-track"><div class="gen-fill"></div></div>
  `;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function showExtractingPanel() {
  const div = document.createElement("div");
  div.className = "gen-panel";
  div.id = "typing-indicator";
  div.innerHTML = `
    <div class="label">Extracting information from your resume…</div>
    <div class="gen-track"><div class="gen-fill"></div></div>
  `;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function showResumeConfirmCard(extracted, sessionData) {
  const div = document.createElement("div");
  div.className = "bubble bot";
  div.style.maxWidth = "90%";

  const intro = document.createElement("div");
  intro.style.marginBottom = "10px";
  intro.textContent = "Here's what I found — edit anything, then confirm:";
  div.appendChild(intro);

  const fieldsWrap = document.createElement("div");
  fieldsWrap.style.display = "flex";
  fieldsWrap.style.flexDirection = "column";
  fieldsWrap.style.gap = "8px";

  // Built via createElement + the .value PROPERTY, not string-interpolated HTML —
  // this is a DOM assignment, never parsed as markup, so it's immune to attribute-
  // breakout/injection regardless of what characters a resume-derived value contains
  // (previously: value="${extracted.email}" etc., where a literal " in the extracted
  // text could break out of the attribute and inject arbitrary markup).
  const fieldDefs = [
    ["edit-email", "Email", extracted.email || ""],
    ["edit-phone", "Phone", extracted.phone || ""],
    ["edit-location", "Location", extracted.location || ""],
    ["edit-education", "Education", extracted.education || ""],
    ["edit-experience", "Years of experience", extracted.experience ?? ""],
    ["edit-role", "Role", extracted.role || ""],
    ["edit-tech", "Tech stack (comma separated)", (extracted.tech_stack || []).join(", ")],
    ["edit-linkedin", "LinkedIn URL", extracted.linkedin || ""],
    ["edit-github", "GitHub URL", extracted.github || ""],
  ];
  fieldDefs.forEach(([id, placeholder, value]) => {
    const input = document.createElement("input");
    input.id = id;
    input.placeholder = placeholder;
    input.value = value;
    fieldsWrap.appendChild(input);
  });
  div.appendChild(fieldsWrap);

  const confirmBtn = document.createElement("button");
  confirmBtn.id = "confirm-resume-btn";
  confirmBtn.style.marginTop = "10px";
  confirmBtn.textContent = "Confirm & Continue";
  div.appendChild(confirmBtn);

  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;

  let replaceDuplicate = false;

  document.getElementById("confirm-resume-btn").addEventListener("click", async () => {
    const confirmBtn = document.getElementById("confirm-resume-btn");
    const fields = ["edit-email", "edit-phone", "edit-location", "edit-experience",
                     "edit-role", "edit-tech", "edit-education", "edit-linkedin", "edit-github"];
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Confirming…";
    fields.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = true;
    });

    setInputEnabled(false);
    showTyping();

    const payload = {
      email: document.getElementById("edit-email").value.trim() || null,
      replace_duplicate: replaceDuplicate,
      phone: document.getElementById("edit-phone").value.trim() || null,
      location: document.getElementById("edit-location").value.trim() || null,
      experience: document.getElementById("edit-experience").value.trim() || null,
      role: document.getElementById("edit-role").value.trim() || null,
      tech_stack: document.getElementById("edit-tech").value.split(",").map(t => t.trim()).filter(Boolean),
      education: document.getElementById("edit-education").value.trim() || null,
      linkedin: document.getElementById("edit-linkedin").value.trim() || null,
      github: document.getElementById("edit-github").value.trim() || null,
    };
    replaceDuplicate = false; // one-shot — only applies to this specific submission

    try {
      const res = await fetch(`${API}/sessions/${sessionId}/resume/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      removeTyping();
      data.messages.forEach((m) => addBubble("assistant", m));
      lastKnownStep = data.step;
      updateProgress(data.step);

      if (data.step === "confirm_resume_data") {
        // server bounced it back (e.g. duplicate email) — reopen the card for editing
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Confirm & Continue";
        fields.forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.disabled = false;
        });
        setInputEnabled(false); // stay in card-editing mode, not free text

        if (data.duplicate_email_choice) {
          const choiceDiv = document.createElement("div");
          choiceDiv.className = "bubble bot";

          const replaceBtn = document.createElement("button");
          replaceBtn.textContent = "Delete old attempt & continue with this email";
          replaceBtn.style.marginRight = "8px";
          replaceBtn.addEventListener("click", () => {
            choiceDiv.remove();
            replaceDuplicate = true;
            confirmBtn.click();
          });

          const editBtn = document.createElement("button");
          editBtn.textContent = "Use a different email instead";
          editBtn.addEventListener("click", () => {
            choiceDiv.remove();
            document.getElementById("edit-email").focus();
          });

          choiceDiv.appendChild(replaceBtn);
          choiceDiv.appendChild(editBtn);
          chatEl.appendChild(choiceDiv);
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      } else if (data.step === "mcq_assessment") {
        window.location.href = `/static/mcq/mcq.html?session_id=${sessionId}`;
      } else {
        setInputEnabled(true);
      }
    } catch (err) {
      removeTyping();
      addBubble("assistant", "Something went wrong — please try again.");
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Confirm & Continue";
      fields.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = false;
      });
      setInputEnabled(true);
    }
  });
}

function removeTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

function setInputEnabled(enabled) {
  inputEl.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) inputEl.focus();
}

function maybeShowResumeUpload() {
  if (lastKnownStep === "upload_resume") {
    setInputEnabled(false);
    inputEl.placeholder = "Please upload your resume to continue…";
    uploadTrigger.style.display = "inline-block";
    setTimeout(() => resumeInput.click(), 400);
  }
}

async function startSession() {
  const orgParam = window.CURRENT_ORG_SLUG ? `?org=${window.CURRENT_ORG_SLUG}` : "";
  const res = await fetch(`${API}/sessions${orgParam}`, { method: "POST" });
  const data = await res.json();
  sessionId = data.session_id;
  addBubble("assistant", data.message);
  lastKnownStep = "greeting";
  statusLine.textContent = "Screening in progress";
  updateProgress("greeting");
  setInputEnabled(true);
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  addBubble("user", text, pastedThisTurn);
  inputEl.value = "";
  inputEl.style.height = "auto";
  inputEl.classList.remove("pasted-flag");
  pasteNote.style.display = "none";
  setInputEnabled(false);

  const expectingGeneration =
    lastKnownStep === "confirm_tech_stack" || lastKnownStep === "mcq_assessment";

  if (expectingGeneration) showGeneratingPanel();
  else showTyping();

  const wasPasted = pastedThisTurn;
  pastedThisTurn = false;
  const startTime = Date.now();

  try {
    const res = await fetch(`${API}/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, pasted: wasPasted }),
    });
    const data = await res.json();

    const elapsed = Date.now() - startTime;
    const minDelay = expectingGeneration ? 0 : 900;
    if (elapsed < minDelay) await sleep(minDelay - elapsed);

    removeTyping();

    for (let i = 0; i < data.messages.length; i++) {
      if (i > 0) {
        showTyping();
        await sleep(700);
        removeTyping();
      }
      addBubble("assistant", data.messages[i]);
    }

    lastKnownStep = data.step;
    updateProgress(data.step);
    maybeShowResumeUpload();

    if (data.step === "end") {
      statusLine.textContent = "Screening complete";
      setInputEnabled(false);
      return;
    }
  } catch (err) {
    removeTyping();
    addBubble("assistant", "Something went wrong — please try again.");
  }

  setInputEnabled(true);
}

function goToLanding() {
  if (document.referrer && document.referrer.includes(window.location.host)) {
    history.back();
  } else {
    document.getElementById("home-view").style.display = "none";
    document.getElementById("chat-view").style.display = "none";
    document.getElementById("home-view").classList.remove("view-fade-in");
    document.getElementById("chat-view").classList.remove("view-fade-in");
    const landing = document.getElementById("landing-view");
    landing.classList.remove("view-fade-out", "hidden");
    landing.style.display = "grid";
  }
}

const backHomeBtn = document.getElementById("back-to-landing-home");
if (backHomeBtn) {
  backHomeBtn.addEventListener("click", () => goToLanding());
}

const backChatBtn = document.getElementById("back-to-landing-chat");
if (backChatBtn) {
  backChatBtn.addEventListener("click", () => {
    const confirmed = confirm("Leaving now will end this screening. Are you sure?");
    if (confirmed) goToLanding();
  });
}

resumeInput.addEventListener("change", async () => {
  const file = resumeInput.files[0];
  if (!file) return;
  addBubble("user", `📎 ${file.name}`);
  setInputEnabled(false);
  uploadTrigger.disabled = true;
  showExtractingPanel();;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(`${API}/sessions/${sessionId}/resume`, { method: "POST", body: formData });
    const data = await res.json();
    removeTyping();
    if (data.step === "confirm_resume_data" && data.extracted) {
      showResumeConfirmCard(data.extracted);
    } else {
      data.messages.forEach((m) => addBubble("assistant", m));
    }
    lastKnownStep = data.step;
    updateProgress(data.step);
    uploadTrigger.style.display = "none";
    inputEl.placeholder = "Type your answer…";
  } catch (err) {
    removeTyping();
    addBubble("assistant", "Upload failed — please try again.");
  }
  resumeInput.value = "";
  setInputEnabled(true);
});

uploadTrigger.addEventListener("click", () => resumeInput.click());

inputEl.addEventListener("paste", () => {
  pastedThisTurn = true;
  inputEl.classList.add("pasted-flag");
  pasteNote.style.display = "block";
});

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = inputEl.scrollHeight + "px";
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

document.getElementById("start-screening-btn").addEventListener("click", () => {
  const home = document.getElementById("home-view");
  const chat = document.getElementById("chat-view");

  home.classList.add("view-fade-out");
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      home.classList.add("hidden");
    });
  });

  setTimeout(() => {
    home.style.display = "none";
    chat.style.display = "grid";
    chat.classList.add("view-fade-in");
    startSession();
  }, 200);
});