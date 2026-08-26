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