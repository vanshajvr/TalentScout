document.querySelectorAll(".tier-card").forEach((card) => {
  card.addEventListener("click", () => {
    window.location.href = card.dataset.target;
  });
});

document.getElementById("back-to-landing-login").addEventListener("click", () => {
  window.location.href = "/";
});