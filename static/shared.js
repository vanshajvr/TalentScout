function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

function formatError(err) {
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail) && err.detail[0]?.msg) return err.detail[0].msg;
  return "Something went wrong.";
}

function goBackOrHome() {
  if (document.referrer && document.referrer.includes(window.location.host)) {
    history.back();
  } else {
    window.location.href = "/";
  }
}

// Wires the profile-icon dropdown (Change password / Log out) shared between the
// admin and recruiter dashboards. Page-specific bits (which localStorage key holds
// the token, what happens on logout) are injected via getToken/onLogout rather than
// duplicated here, since the two pages use different token storage.
function wireProfileDropdown({ getToken, onLogout }) {
  const userBlock = document.getElementById("dash-user-block");
  const dropdown = document.getElementById("profile-dropdown");
  if (!userBlock || !dropdown) return;

  userBlock.addEventListener("click", (e) => {
    dropdown.style.display = dropdown.style.display === "none" ? "block" : "none";
    e.stopPropagation();
  });
  document.addEventListener("click", () => { dropdown.style.display = "none"; });
  dropdown.addEventListener("click", (e) => e.stopPropagation());

  document.getElementById("logout-btn").addEventListener("click", async () => {
    dropdown.style.display = "none";
    try {
      await fetch("/recruiter/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
      });
    } catch (e) {
      // Best-effort — still log out locally even if this call fails (e.g. offline).
    }
    onLogout();
  });

  const modal = document.getElementById("change-password-modal");
  const currentInput = document.getElementById("cp-current");
  const newInput = document.getElementById("cp-new");
  const errorEl = document.getElementById("cp-error");
  if (!modal) return;

  document.getElementById("change-password-btn").addEventListener("click", () => {
    dropdown.style.display = "none";
    currentInput.value = "";
    newInput.value = "";
    errorEl.style.display = "none";
    modal.style.display = "flex";
  });
  document.getElementById("cp-cancel").addEventListener("click", () => {
    modal.style.display = "none";
  });
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.style.display = "none";
  });

  document.getElementById("cp-submit").addEventListener("click", async () => {
    errorEl.style.display = "none";
    const current_password = currentInput.value;
    const new_password = newInput.value;
    if (!current_password || !new_password) {
      errorEl.textContent = "Please fill in both fields.";
      errorEl.style.display = "block";
      return;
    }
    if (new_password.length < 8) {
      errorEl.textContent = "New password must be at least 8 characters.";
      errorEl.style.display = "block";
      return;
    }
    const res = await fetch("/recruiter/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ current_password, new_password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorEl.textContent = formatError(err) || "Couldn't change password — please try again.";
      errorEl.style.display = "block";
      return;
    }
    modal.style.display = "none";
    alert("Password changed. Please log in again.");
    onLogout();
  });
}