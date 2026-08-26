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