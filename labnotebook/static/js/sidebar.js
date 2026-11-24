/* Sidebar: experiments and projects for quick switching, search, quick create and the PubChem Local status.
   Groups collapse; the whole sidebar can be hidden (remembered per browser). */
import { $, $$, api, esc, toast } from "./util.js";
import { resizer } from "./resize.js";
import { themeSwitch, bindThemeSwitch } from "./theme.js";
import { state } from "./state.js";
import { changePassword, signOut } from "./login.js";
import { openFeedback } from "./feedback.js";

let unseen = { replies: 0, new_reports: 0 };
async function checkUnseen() {
  try { unseen = await api("GET", "/api/feedback/unseen"); } catch { return; }
  drawBadges();
}
function drawBadges() {
  const n = (unseen.replies || 0) + (unseen.new_reports || 0);
  const b = $("#sb-badge");
  if (b) { b.textContent = n; b.hidden = !n; b.title = [unseen.new_reports ? `${unseen.new_reports} new report(s) in Admin → Feedback` : "",
    unseen.replies ? `${unseen.replies} reply(ies) to your reports` : ""].filter(Boolean).join("; "); }
  const r = $("#sb-fb-count");
  if (r) { r.textContent = unseen.replies || ""; r.hidden = !unseen.replies; }
  const a = $("#sb-admin-count");
  if (a) { a.textContent = unseen.new_reports || ""; a.hidden = !unseen.new_reports; }
}
window.addEventListener("feedback-seen", checkUnseen);

const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
let cache = { experiments: [], projects: [] };
let filter = "";
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const closedGroups = new Set(store.get("ln.sb.closed", []));

export async function refreshSidebar() {
  try {
    const [{ experiments }, { projects }] = await Promise.all([api("GET", "/api/experiments"), api("GET", "/api/projects")]);
    cache = { experiments, projects };
  } catch { /* keep the old list */ }
  draw();
}

/** Update one experiment's title/status in the list without a round trip. */
export function patchSidebar(id, fields) {
  const e = cache.experiments.find((x) => x.id === id);
  if (e && Object.entries(fields).some(([k, v]) => e[k] !== v)) { Object.assign(e, fields); draw(); }
}

export function markActive() {
  const h = location.hash || "#/";
  $$("#sidebar [data-href]").forEach((a) => {
    const href = a.dataset.href;
    a.classList.toggle("active", href === "#/" ? h === "#/" || h === "#" : h.startsWith(href));
  });
}

function group(key, title, count, items) {
  const closed = closedGroups.has(key) && !filter;
  return `<div class="sb-group ${closed ? "closed" : ""}" data-group="${key}">
    <button class="sb-h" data-toggle-group="${key}" aria-expanded="${!closed}"><span class="chev">›</span>${title}<span class="sb-count">${count}</span></button>
    <ul class="sb-list">${items}</ul></div>`;
}

function draw() {
  const root = $("#sidebar");
  const q = filter.trim().toLowerCase();
  const exps = cache.experiments.filter((e) => !q || `${e.title} ${e.course || ""}`.toLowerCase().includes(q));
  const seqs = cache.projects.filter((s) => !q || s.title.toLowerCase().includes(q));
  const running = exps.filter((e) => e.status === "in_progress");
  const focused = document.activeElement?.id === "sb-search";
  const expItem = (e) => `<li><a href="#/exp/${e.id}/${e.status === "in_progress" ? "bench" : "plan"}" data-href="#/exp/${e.id}/" class="sb-item">
    <i class="dot ${esc(e.status)}" title="${esc(STATUS_LABELS[e.status] || e.status)}"></i>
    <span class="sb-title">${esc(e.title)}</span><span class="sb-meta">${esc((e.date || "").slice(5))}</span></a></li>`;
  root.innerHTML = `
    <div class="sb-top">
      <a href="#/" class="brand" data-href="#/"><img src="/static/icon.svg" alt="" width="22" height="22"><span>Lab Notebook</span></a>
      <button class="icon-btn" id="sb-hide" title="Hide sidebar" aria-label="Hide sidebar">⟨</button>
    </div>
    <div class="sb-nav">
      <button class="sb-item" id="sb-new-exp"><span class="ico">＋</span><span class="sb-title">New experiment</span></button>
      <button class="sb-item" id="sb-new-seq"><span class="ico">⇢</span><span class="sb-title">New project</span></button>
      <a class="sb-item" href="#/" data-href="#/"><span class="ico">▦</span><span class="sb-title">Dashboard</span></a>
      <a class="sb-item" href="#/stockroom" data-href="#/stockroom"><span class="ico">⛁</span><span class="sb-title">Stockroom</span></a>
      <label class="sb-item sb-searchrow"><span class="ico">⌕</span><input id="sb-search" placeholder="Search" value="${esc(filter)}" aria-label="Search experiments and projects"></label>
    </div>
    <nav class="sb-scroll">
      ${running.length ? group("running", "Running", running.length, running.map(expItem).join("")) : ""}
      ${group("exps", "Experiments", exps.length, exps.map(expItem).join("") || `<li class="sb-empty">${q ? "No matches" : "None yet"}</li>`)}
      ${group("seqs", "Projects", seqs.length, seqs.map((s) => `<li><a href="#/project/${s.id}" data-href="#/project/${s.id}" class="sb-item">
        <i class="route">⇢</i><span class="sb-title">${esc(s.title)}</span><span class="sb-meta">${s.experiments.length}</span></a></li>`).join("")
        || `<li class="sb-empty">${q ? "No matches" : "None yet"}</li>`)}
    </nav>
    <div class="sb-foot"><span id="pubchem-status" class="pill">PubChem Local …</span><span class="spacer"></span>${themeSwitch()}</div>
    ${state.user ? `<details class="sb-user"><summary><span class="avatar" aria-hidden="true">${esc((state.user.display_name || state.user.username).slice(0, 1).toUpperCase())}</span>
      <span class="sb-title">${esc(state.user.display_name || state.user.username)}</span><span class="sb-badge" id="sb-badge" hidden></span>
      ${state.user.is_admin ? '<span class="tag role-admin">admin</span>' : state.user.demo ? '<span class="tag t-warn">demo</span>' : ""}</summary>
      <div class="menu-list">
        ${state.user.is_admin ? '<a href="#/admin" data-href="#/admin">⚙ Admin dashboard <span class="sb-badge" id="sb-admin-count" hidden></span></a>' : ""}
        <button id="sb-report">⚑ Report a problem</button>
        <button id="sb-myreports">My reports <span class="sb-badge" id="sb-fb-count" hidden></span></button>
        <button id="sb-password">Change password…</button>
        <button id="sb-signout">Sign out</button>
        <span class="menu-note">Lab Notebook ${esc(state.config?.version || "")}</span>
      </div></details>` : ""}
    ${resizer("--side", "parent", 200, 480, "Resize the sidebar")}`;
  markActive();
  const s = $("#sb-search", root);
  s.addEventListener("input", () => { filter = s.value; draw(); });
  if (focused) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  $$("[data-toggle-group]", root).forEach((b) => (b.onclick = () => {
    const k = b.dataset.toggleGroup;
    closedGroups.has(k) ? closedGroups.delete(k) : closedGroups.add(k);
    store.set("ln.sb.closed", [...closedGroups]);
    draw();
  }));
  $("#sb-hide", root).onclick = () => setHidden(true);
  bindThemeSwitch(root);
  const pw = $("#sb-password", root);
  if (pw) pw.onclick = async () => {
    try { await changePassword(); toast("Password changed. Other devices were signed out."); }
    catch (e) { toast(e.message, true); }
  };
  const close = () => { const d = $(".sb-user", root); if (d) d.open = false; };
  $("#sb-report", root)?.addEventListener("click", () => { close(); openFeedback("new"); });
  $("#sb-myreports", root)?.addEventListener("click", () => { close(); openFeedback("mine"); });
  drawBadges();
  if (state.user) checkUnseen();
  const so = $("#sb-signout", root);
  if (so) so.onclick = () => signOut();
  $("#sb-new-exp", root).onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      await refreshSidebar();
      location.hash = `#/exp/${d.experiment.id}/plan`;
    } catch (e) { toast(e.message, true); }
  };
  $("#sb-new-seq", root).onclick = async () => {
    try {
      const d = await api("POST", "/api/projects", { title: "New project" });
      await refreshSidebar();
      location.hash = `#/project/${d.project.id}`;
    } catch (e) { toast(e.message, true); }
  };
  root.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => document.body.classList.remove("sb-open")));
  window.dispatchEvent(new Event("sidebar-drawn"));
}

export function setHidden(hidden) {
  document.body.classList.toggle("sb-hidden", hidden);
  store.set("ln.sb.hidden", hidden);
}

export function initSidebar() {
  setHidden(store.get("ln.sb.hidden", false));
  $("#menu-btn").onclick = () => {
    if (window.matchMedia("(max-width: 900px)").matches) document.body.classList.toggle("sb-open");
    else setHidden(!document.body.classList.contains("sb-hidden"));
  };
  $("#scrim").onclick = () => document.body.classList.remove("sb-open");
  window.addEventListener("hashchange", markActive);
  refreshSidebar();
}
