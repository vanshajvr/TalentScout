const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add("visible");
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.2 });

document.querySelectorAll(".reveal").forEach((el) => revealObserver.observe(el));

const params = new URLSearchParams(window.location.search);
if (params.get("start") === "true") {
  const landing = document.getElementById("landing-view");
  const home = document.getElementById("home-view");
  if (landing && home) {
    landing.style.display = "none";
    home.style.display = "grid";
  }
}

const DEMO_SCRIPT = [
  { role: "bot", text: "What draws you to backend engineering?" },
  { role: "user", text: "I like systems where correctness actually matters." },
  { role: "bot", text: "Makes sense — what's a bug you're proud of catching?" },
  { role: "user", text: "A silent state bug that only hit on the first request." },
];

async function typeText(el, text, speed = 22) {
  el.textContent = "";
  for (let i = 0; i < text.length; i++) {
    el.textContent += text[i];
    await new Promise((r) => setTimeout(r, speed));
  }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function runDemoLoop() {
  const container = document.getElementById("demo-preview");
  if (!container) return;

  while (true) {
    container.innerHTML = "";
    for (const line of DEMO_SCRIPT) {
      const bubble = document.createElement("div");
      bubble.className = "demo-bubble demo-bubble-" + (line.role === "user" ? "user" : "bot");
      container.appendChild(bubble);
      container.scrollTop = container.scrollHeight;
      await typeText(bubble, line.text);
      await sleep(900);
    }
    await sleep(2200);
  }
}

runDemoLoop();

const TIMELINE_DETAILS = {
  upload: {
    title: "Drop in a resume, get a profile",
    body: "PDF or DOCX — even data hidden behind hyperlinks gets extracted. Email, phone, tech stack, and experience are pulled automatically, then shown to the candidate to confirm or edit before anything's saved.",
  },
  interview: {
    title: "Questions that adapt as you go",
    body: "Each question is generated live from the candidate's actual tech stack and stated experience level — fundamentals for a junior candidate, trade-offs and failure modes for a senior one. No fixed question bank.",
  },
  scored: {
    title: "Correctness, reasoning, communication",
    body: "Every answer is scored on three dimensions with a one-line justification — not just a transcript. Recruiters see a number they can sort by, not pages of raw text to read cold.",
  },
  review: {
    title: "One dashboard, every candidate",
    body: "Filter by role, tech stack, or experience. Export to CSV. See the full interview transcript and scores side by side before deciding who gets a callback.",
  },
};

function renderTimelineDetail(step) {
  const detail = TIMELINE_DETAILS[step];
  const container = document.getElementById("timeline-detail");
  if (!detail || !container) return;
  container.innerHTML = `
    <div class="timeline-detail-title">${detail.title}</div>
    <div class="timeline-detail-body">${detail.body}</div>
  `;
}

document.querySelectorAll(".timeline-step").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".timeline-step").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderTimelineDetail(btn.dataset.step);
  });
});

renderTimelineDetail("upload");

const ROLE_PREVIEWS = {
  candidates: `
    <div class="preview-mock">
      <div class="demo-bubble demo-bubble-bot" style="animation:none;">What draws you to backend engineering?</div>
      <div class="demo-bubble demo-bubble-user" style="animation:none;">I like systems where correctness matters.</div>
    </div>
  `,
  recruiters: `
    <div class="preview-mock preview-table">
      <div class="preview-row"><span>Vanshaj Verma</span><span class="preview-score">4.6</span></div>
      <div class="preview-row"><span>Priya Sharma</span><span class="preview-score">4.1</span></div>
      <div class="preview-row"><span>Arjun Mehta</span><span class="preview-score">3.4</span></div>
    </div>
  `,
  hr: `
    <div class="preview-mock preview-org">
      <div class="preview-org-row"><i class="ti ti-key"></i> Invite code generated</div>
      <div class="preview-org-row"><i class="ti ti-users"></i> 3 recruiters in your org</div>
      <div class="preview-org-row"><i class="ti ti-shield-check"></i> Candidates isolated per org</div>
    </div>
  `,
};

function renderRolePreview(role) {
  const container = document.getElementById("role-preview");
  if (!container || !ROLE_PREVIEWS[role]) return;
  container.innerHTML = ROLE_PREVIEWS[role];
}

document.querySelectorAll(".role-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".role-card").forEach((c) => c.classList.remove("active"));
    card.classList.add("active");
    renderRolePreview(card.dataset.role);
  });
});

renderRolePreview("candidates");