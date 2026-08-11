const API = "";
let sessionId = null;
let lastKnownStep = null;
let pastedThisTurn = false;

const STEPS_ORDER = [
  "greeting", "ask_name", "ask_email", "verify_email",
  "ask_phone", "verify_phone", "ask_location",
  "ask_experience", "ask_role", "upload_resume",
  "ask_tech_stack", "confirm_tech_stack", "interviewing", "end"
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
  div.textContent = text;
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
  const res = await fetch(`${API}/sessions`, { method: "POST" });
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
    lastKnownStep === "confirm_tech_stack" || lastKnownStep === "interviewing";

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

resumeInput.addEventListener("change", async () => {
  const file = resumeInput.files[0];
  if (!file) return;
  addBubble("user", `📎 ${file.name}`);
  setInputEnabled(false);
  showTyping();
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(`${API}/sessions/${sessionId}/resume`, { method: "POST", body: formData });
    const data = await res.json();
    removeTyping();
    data.messages.forEach((m) => addBubble("assistant", m));
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

document.getElementById("pick-candidate").addEventListener("click", () => {
  document.getElementById("landing-view").style.display = "none";
  document.getElementById("home-view").style.display = "flex";
});

document.getElementById("start-screening-btn").addEventListener("click", () => {
  document.getElementById("home-view").style.display = "none";
  document.getElementById("chat-view").style.display = "flex";
  startSession();
});