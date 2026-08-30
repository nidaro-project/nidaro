// Nidaro app JS — theme state only. HTMX handles interaction; no framework lives here.
(() => {
  "use strict";

  const STORAGE_KEY = "nidaro-theme";
  const SUPPORTED_THEMES = ["daylight", "meadow", "dusk"];

  const applyTheme = (theme) => {
    if (!SUPPORTED_THEMES.includes(theme)) return;
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Private mode etc. — the in-page theme still applies for this visit.
    }
    document.querySelectorAll("[data-theme-choice]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.themeChoice === theme));
    });
  };

  document.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-theme-choice]");
    if (choice) applyTheme(choice.dataset.themeChoice);
  });

  applyTheme(document.documentElement.dataset.theme || localStorage.getItem(STORAGE_KEY) || "daylight");
})();
