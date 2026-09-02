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

function getOrgSlugFromPath() {
  const match = window.location.pathname.match(/^\/screen\/([a-z0-9-]+)$/);
  return match ? match[1] : null;
}

window.CURRENT_ORG_SLUG = getOrgSlugFromPath();

if (window.CURRENT_ORG_SLUG) {
  const landing = document.getElementById("landing-view");
  const home = document.getElementById("home-view");
  if (landing && home) {
    landing.style.display = "none";
    home.style.display = "grid";
  }
}

window.CURRENT_ORG_SLUG = getOrgSlugFromPath();

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

const railSteps = Array.from(document.querySelectorAll(".rail-step"));
const railDots = Array.from(document.querySelectorAll(".rail-dot"));
let hovering = false;

function setActiveStep(index) {
  railSteps.forEach((el, i) => el.classList.toggle("active", i === index));
  railDots.forEach((el, i) => el.classList.toggle("active", i === index));
}

railSteps.forEach((el, i) => {
  el.addEventListener("mouseenter", () => {
    hovering = true;
    setActiveStep(i);
  });
  el.addEventListener("mouseleave", () => {
    hovering = false;
  });
});

if (railSteps.length) {
  const railObserver = new IntersectionObserver((entries) => {
    if (hovering) return;
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const index = railSteps.indexOf(entry.target);
        if (index !== -1) setActiveStep(index);
      }
    });
  }, { threshold: 0.6 });

  railSteps.forEach((el) => railObserver.observe(el));
}

const ROLE_PREVIEWS = {
  candidates: `
    <div class="preview-mock">
      <div class="preview-bubble preview-bubble-bot">What draws you to backend engineering?</div>
      <div class="preview-bubble preview-bubble-user">I like systems where correctness matters.</div>
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
  card.addEventListener("mouseenter", () => {
    document.querySelectorAll(".role-card").forEach((c) => c.classList.remove("active"));
    card.classList.add("active");
    renderRolePreview(card.dataset.role);
  });
});

renderRolePreview("candidates");