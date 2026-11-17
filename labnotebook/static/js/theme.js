/* Light / dark theme. "Auto" follows the device; Light and Dark override it (remembered per browser). The choice is
   applied before the page is drawn by a small script in index.html, so there is no flash of the other theme. */
import { $, $$ } from "./util.js";

const KEY = "ln.theme";
const MODES = [["light", "☀", "Light"], ["auto", "◐", "Auto (follows the device)"], ["dark", "☾", "Night"]];
const media = window.matchMedia("(prefers-color-scheme: dark)");

export function getTheme() {
  try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; }
}

/** Whether the page is showing the dark theme right now. */
export const isDark = () => (getTheme() === "auto" ? media.matches : getTheme() === "dark");

function apply() {
  const mode = getTheme();
  if (mode === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = isDark() ? "#111113" : "#f1f1f3";
  $$("[data-theme-set]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.themeSet === mode));
    b.classList.toggle("on", b.dataset.themeSet === mode);
  });
  const quick = $("#theme-quick");
  if (quick) {
    quick.textContent = isDark() ? "☀" : "☾";
    quick.title = isDark() ? "Switch to the light theme" : "Switch to night mode";
    quick.setAttribute("aria-label", quick.title);
  }
}

export function setTheme(mode) {
  try { if (mode === "auto") localStorage.removeItem(KEY); else localStorage.setItem(KEY, mode); } catch { /* private mode */ }
  apply();
}

/** The Light / Auto / Night switch (sidebar footer). */
export function themeSwitch() {
  const mode = getTheme();
  return `<div class="theme-switch" role="group" aria-label="Theme">${MODES.map(([k, icon, label]) =>
    `<button type="button" data-theme-set="${k}" class="${k === mode ? "on" : ""}" aria-pressed="${k === mode}" title="${label}">
      <span aria-hidden="true">${icon}</span><span class="ts-l">${k === "dark" ? "Night" : k === "auto" ? "Auto" : "Light"}</span></button>`).join("")}</div>`;
}

export function bindThemeSwitch(root) {
  $$("[data-theme-set]", root).forEach((b) => (b.onclick = () => setTheme(b.dataset.themeSet)));
}

export function initTheme() {
  media.addEventListener("change", apply);
  const quick = $("#theme-quick");
  if (quick) quick.onclick = () => setTheme(isDark() ? "light" : "dark");
  apply();
}
