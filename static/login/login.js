document.querySelectorAll(".tier-card").forEach((card) => {
  card.addEventListener("click", () => {
    window.location.href = card.dataset.target;
  });
});

document.getElementById("back-to-landing-login").addEventListener("click", () => {
  if (document.referrer && document.referrer.includes(window.location.host)) {
    history.back();
  } else {
    window.location.href = "/";
  }
});