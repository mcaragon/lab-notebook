/* Sidebar: experiments and sequences for quick switching, search, quick create and the PubChem Local status.
   Groups collapse; the whole sidebar can be hidden (remembered per browser). */
import { $, $$, api, esc, toast } from "./util.js";

const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
let cache = { experiments: [], sequences: [] };
let filter = "";
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const closedGroups = new Set(store.get("ln.sb.closed", []));

export async function refreshSidebar() {
  try {
    const [{ experiments }, { sequences }] = await Promise.all([api("GET", "/api/experiments"), api("GET", "/api/sequences")]);
    cache = { experiments, sequences };
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
  const seqs = cache.sequences.filter((s) => !q || s.title.toLowerCase().includes(q));
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
      <button class="sb-item" id="sb-new-seq"><span class="ico">⇢</span><span class="sb-title">New sequence</span></button>
      <a class="sb-item" href="#/" data-href="#/"><span class="ico">▦</span><span class="sb-title">Dashboard</span></a>
      <label class="sb-item sb-searchrow"><span class="ico">⌕</span><input id="sb-search" placeholder="Search" value="${esc(filter)}" aria-label="Search experiments and sequences"></label>
    </div>
    <nav class="sb-scroll">
      ${running.length ? group("running", "Running", running.length, running.map(expItem).join("")) : ""}
      ${group("exps", "Experiments", exps.length, exps.map(expItem).join("") || `<li class="sb-empty">${q ? "No matches" : "None yet"}</li>`)}
      ${group("seqs", "Sequences", seqs.length, seqs.map((s) => `<li><a href="#/seq/${s.id}" data-href="#/seq/${s.id}" class="sb-item">
        <i class="route">⇢</i><span class="sb-title">${esc(s.title)}</span><span class="sb-meta">${s.experiments.length}</span></a></li>`).join("")
        || `<li class="sb-empty">${q ? "No matches" : "None yet"}</li>`)}
    </nav>
    <div class="sb-foot"><span id="pubchem-status" class="pill">PubChem Local …</span></div>`;
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
  $("#sb-new-exp", root).onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      await refreshSidebar();
      location.hash = `#/exp/${d.experiment.id}/plan`;
    } catch (e) { toast(e.message, true); }
  };
  $("#sb-new-seq", root).onclick = async () => {
    try {
      const d = await api("POST", "/api/sequences", { title: "New sequence" });
      await refreshSidebar();
      location.hash = `#/seq/${d.sequence.id}`;
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
