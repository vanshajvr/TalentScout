const API = "";

const params = new URLSearchParams(window.location.search);
const sessionId = params.get("session_id");

const introView = document.getElementById("mcq-intro");
const questionView = document.getElementById("mcq-question");
const summaryView = document.getElementById("mcq-summary");

const beginBtn = document.getElementById("mcq-begin-btn");
const introError = document.getElementById("mcq-intro-error");

const progressLabel = document.getElementById("mcq-progress-label");
const progressFill = document.getElementById("mcq-progress-fill");
const timerEl = document.getElementById("mcq-timer");
const questionTextEl = document.getElementById("mcq-question-text");
const codeBlockEl = document.getElementById("mcq-code-block");
const optionsEl = document.getElementById("mcq-options");
const openTextWrap = document.getElementById("mcq-open-text-wrap");
const openTextEl = document.getElementById("mcq-open-text");
const charCountEl = document.getElementById("mcq-char-count");
const nextBtn = document.getElementById("mcq-next-btn");
const questionError = document.getElementById("mcq-question-error");

const summaryTime = document.getElementById("mcq-summary-time");
const finishBtn = document.getElementById("mcq-finish-btn");

const TOTAL_QUESTIONS = 17;
const MAX_OPEN_TEXT_CHARS = 300;

let selectedOptionId = null;
let timerInterval = null;
let assessmentDone = false;
let startedAt = null;

function showView(view) {
  [introView, questionView, summaryView].forEach((v) => (v.style.display = "none"));
  view.style.display = "flex";
}

async function apiCall(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function startTimer(remainingSeconds) {
  stopTimer();
  let remaining = remainingSeconds;
  timerEl.style.display = "flex";
  renderTimer(remaining);

  timerInterval = setInterval(() => {
    remaining -= 1;
    renderTimer(remaining);
    if (remaining <= 0) {
      stopTimer();
      submitAnswer(); // server enforces the real deadline; this just auto-advances the UI
    }
  }, 1000);
}

function renderTimer(seconds) {
  const clamped = Math.max(0, seconds);
  const mins = Math.floor(clamped / 60);
  const secs = clamped % 60;
  timerEl.textContent = `${mins}:${String(secs).padStart(2, "0")}`;
  timerEl.classList.toggle("mcq-timer-urgent", clamped <= 10);
}

function renderQuestion(data) {
  selectedOptionId = null;
  questionError.style.display = "none";
  progressLabel.textContent = `Question ${data.question_index + 1} of ${data.total_questions || TOTAL_QUESTIONS}`;
  progressFill.style.width = `${((data.question_index + 1) / (data.total_questions || TOTAL_QUESTIONS)) * 100}%`;

  optionsEl.innerHTML = "";
  openTextWrap.style.display = "none";
  codeBlockEl.style.display = "none";
  nextBtn.disabled = true;

  if (data.question_type === "technical") {
    startTimer(data.remaining_time_seconds ?? 60);
  } else {
    stopTimer();
    timerEl.style.display = "none";
  }

  const codeMatch = data.question_text.match(/```([\s\S]*?)```/);
  if (codeMatch) {
    questionTextEl.textContent = data.question_text.replace(codeMatch[0], "").trim();
    codeBlockEl.textContent = codeMatch[1].trim();
    codeBlockEl.style.display = "block";
  } else {
    questionTextEl.textContent = data.question_text;
  }

  if (data.question_type === "open_text") {
    openTextWrap.style.display = "block";
    openTextEl.value = "";
    charCountEl.textContent = `0 / ${data.max_chars || MAX_OPEN_TEXT_CHARS}`;
    nextBtn.textContent = "Submit";
  } else {
    nextBtn.innerHTML = `Next <i class="ti ti-arrow-right" aria-hidden="true"></i>`;
    (data.options || []).forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mcq-option";
      btn.textContent = opt.text;
      btn.addEventListener("click", () => {
        selectedOptionId = opt.id;
        [...optionsEl.children].forEach((c) => c.classList.remove("mcq-option-selected"));
        btn.classList.add("mcq-option-selected");
        nextBtn.disabled = false;
      });
      optionsEl.appendChild(btn);
    });
  }
}

async function submitAnswer() {
  nextBtn.disabled = true;
  const payload = {};
  if (openTextWrap.style.display !== "none") {
    payload.text_response = openTextEl.value.trim();
  } else {
    payload.selected_option_id = selectedOptionId;
  }

  try {
    const data = await apiCall(`/sessions/${sessionId}/mcq/answer`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.completed) {
      finishAssessment();
    } else {
      renderQuestion(data);
    }
  } catch (err) {
    questionError.textContent = err.message;
    questionError.style.display = "block";
    nextBtn.disabled = false;
  }
}

function finishAssessment() {
  assessmentDone = true;
  stopTimer();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (startedAt) {
    const minutes = Math.round((Date.now() - startedAt) / 60000);
    summaryTime.textContent = `Completed in ${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  showView(summaryView);
}

async function reportIntegrityEvent(eventType) {
  try {
    await apiCall(`/sessions/${sessionId}/mcq/integrity-event`, {
      method: "POST",
      body: JSON.stringify({ event_type: eventType }),
    });
  } catch (err) {
    // Best-effort — don't interrupt the assessment over a logging call failing.
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden && !assessmentDone) reportIntegrityEvent("tab_switch");
});

document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement && !assessmentDone) reportIntegrityEvent("fullscreen_exit");
});

openTextEl.addEventListener("input", () => {
  const len = openTextEl.value.length;
  charCountEl.textContent = `${len} / ${MAX_OPEN_TEXT_CHARS}`;
  nextBtn.disabled = len === 0;
});

nextBtn.addEventListener("click", () => submitAnswer());

beginBtn.addEventListener("click", async () => {
  if (!sessionId) {
    introError.textContent = "Missing session — please return to the previous screen and try again.";
    introError.style.display = "block";
    return;
  }
  beginBtn.disabled = true;
  introError.style.display = "none";
  try {
    await document.documentElement.requestFullscreen().catch(() => {});
    const data = await apiCall(`/sessions/${sessionId}/mcq/current`);
    startedAt = Date.now();
    showView(questionView);
    if (data.completed) {
      finishAssessment();
    } else {
      renderQuestion(data);
    }
  } catch (err) {
    introError.textContent = err.message;
    introError.style.display = "block";
    beginBtn.disabled = false;
  }
});

finishBtn.addEventListener("click", () => {
  window.location.href = "/";
});

if (!sessionId) {
  introError.textContent = "Missing session — please return to the previous screen and try again.";
  introError.style.display = "block";
  beginBtn.disabled = true;
}