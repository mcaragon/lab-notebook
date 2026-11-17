/* Lab Notebook frontend: vanilla JS modules, no build step. Routes: #/ (list), #/exp/<id>[/<section>]. */
import { $, $$, api, debounce, esc, toast } from "./util.js";
import { state, setData, expId } from "./state.js";
import { flushExp, saveExp, sectionField, bindSections, hasPendingExp } from "./expfields.js";
import { renderReaction } from "./reaction.js";
import { renderReagents } from "./reagents.js";
import { renderProcedure } from "./procedure.js";
import { renderBench, startTicker } from "./bench.js";
import { renderResults, renderRefs, renderReport } from "./results.js";

const app = $("#app");
const SECTIONS = [
  ["overview", "Overview"], ["reaction", "Reaction"], ["reagents", "Reagents"], ["procedure", "Procedure & log"],
  ["results", "Results"], ["refs", "References"], ["report", "Report"],
];
const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };

// ------------------------------------------------------------------------------------------- PubChem status
async function checkHealth() {
  const el = $("#pubchem-status");
  try {
    const h = await api("GET", "/api/health");
    el.textContent = h.pubchem.reachable ? "PubChem Local" : "PubChem Local offline";
    el.className = "pill " + (h.pubchem.reachable ? "ok" : "bad");
    el.title = h.pubchem.reachable ? `Connected: ${h.pubchem.url}` : `${h.pubchem.error}\nManual entry still works.`;
  } catch {
    el.textContent = "Server unreachable";
    el.className = "pill bad";
  }
}

// ------------------------------------------------------------------------------------------- routing
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "exp" && parts[1]) {
    const id = Number(parts[1]);
    if (!state.data || state.data.experiment.id !== id) {
      await flushExp.flush();
      state.open.clear();
      state.currentProc = null;
      try {
        state.data = await api("GET", `/api/experiments/${id}`);
      } catch (e) {
        app.innerHTML = `<div class="panel">Could not load the experiment: ${esc(e.message)} <a href="#/">Back</a></div>`;
        return;
      }
      renderShell();
      setData(state.data);
    }
    if (parts[2]) document.getElementById(`sec-${parts[2]}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    await flushExp.flush();
    state.data = null;
    state.renderers = [];
    renderList();
  }
}

// ------------------------------------------------------------------------------------------- experiment list
async function renderList() {
  document.title = "Lab Notebook";
  document.body.classList.remove("running");
  app.innerHTML = `<div class="panel list-panel"><div class="row"><h2 style="margin:0">Experiments</h2><span class="spacer"></span>
    <button class="btn primary" id="new-exp">+ New experiment</button></div><div id="list" class="empty">Loading…</div></div>`;
  $("#new-exp").onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      state.data = null;
      location.hash = `#/exp/${d.experiment.id}`;
    } catch (e) { toast(e.message, true); }
  };
  try {
    const { experiments } = await api("GET", "/api/experiments");
    const list = $("#list");
    if (!experiments.length) { list.innerHTML = "No experiments yet. Create one to start planning."; return; }
    list.className = "";
    list.innerHTML = `<ul class="exp-list">${experiments.map((e) => `<li><a href="#/exp/${e.id}">
      <span class="title">${esc(e.title)}</span>
      <span class="muted small">${esc(e.course || "")}</span>
      <span class="muted small">${esc(e.date || "")}</span>
      <span class="status ${esc(e.status)}">${esc(STATUS_LABELS[e.status] || e.status)}</span>
      <span class="muted small">${e.n_steps > 1 ? `${e.n_steps} steps · ` : ""}${e.n_reagents} chemicals</span></a></li>`).join("")}</ul>`;
  } catch (e) {
    $("#list").textContent = "Could not load experiments: " + e.message;
  }
}

// ------------------------------------------------------------------------------------------- shell
function renderShell() {
  const exp = state.data.experiment;
  document.title = `${exp.title} · Lab Notebook`;
  app.innerHTML = `
    <div class="exp-head">
      <a href="#/" class="btn icon" title="All experiments" aria-label="All experiments">←</a>
      <input class="title" id="exp-title" data-key="exp-title" value="${esc(exp.title)}" aria-label="Title">
      <span class="saved" id="saved"></span>
    </div>
    <div id="bench" class="bench"></div>
    <div class="exp-layout">
      <nav class="toc" aria-label="Sections">${SECTIONS.map(([k, v]) => `<a href="#/exp/${exp.id}/${k}" data-sec="${k}">${v}</a>`).join("")}</nav>
      <div class="exp-body">
        ${SECTIONS.map(([k, v]) => `<section id="sec-${k}" class="sec" aria-label="${v}"></section>`).join("")}
      </div>
    </div>`;
  $("#exp-title").addEventListener("input", (e) => {
    saveExp({ title: e.target.value || "Untitled experiment" });
    document.title = `${e.target.value} · Lab Notebook`;
  });
  // highlight the section in view
  const links = $$(".toc a");
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting) links.forEach((a) => a.classList.toggle("active", `sec-${a.dataset.sec}` === en.target.id));
    }
  }, { rootMargin: "-20% 0px -70% 0px" });
  $$(".sec").forEach((s) => io.observe(s));
  $$(".toc a").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    $(`#sec-${a.dataset.sec}`).scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", a.getAttribute("href"));
  }));

  // keep the section nav below the (variable-height) bench bar
  new ResizeObserver(([en]) => document.documentElement.style.setProperty("--bench", `${Math.ceil(en.contentRect.height) + 8}px`))
    .observe($("#bench"));
  renderOverview($("#sec-overview"));
  state.renderers = [
    () => { const st = $("#f-status"); if (st && st !== document.activeElement) st.value = state.data.experiment.status; },
    () => renderBench($("#bench")),
    () => renderReaction($("#sec-reaction")),
    () => renderReagents($("#sec-reagents")),
    () => renderProcedure($("#sec-procedure")),
    () => renderResults($("#sec-results")),
    () => renderRefs($("#sec-refs")),
  ];
  renderReport($("#sec-report"));
}

function renderOverview(root) {
  const exp = state.data.experiment;
  root.innerHTML = `<div class="panel">
    <div class="grid meta-grid">
      <label class="field">Date<input type="date" id="f-date" value="${esc(exp.date || "")}"></label>
      <label class="field">Status<select id="f-status">${Object.entries(STATUS_LABELS).map(([k, v]) =>
        `<option value="${k}" ${exp.status === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="field">Author<input id="f-author" value="${esc(exp.author || "")}"></label>
      <label class="field">Course / lab<input id="f-course" value="${esc(exp.course || "")}"></label>
    </div>
    <div style="height:12px"></div>
    ${sectionField("objective", "Objective", "", 3)}
    <div class="row" style="margin-top:12px">
      <button class="btn" id="dup">Duplicate as new plan</button><span class="spacer"></span>
      <button class="btn danger" id="del">Delete experiment</button>
    </div></div>`;
  [["f-date", "date"], ["f-author", "author"], ["f-course", "course"]].forEach(([id, k]) =>
    $("#" + id, root).addEventListener("input", (e) => saveExp({ [k]: e.target.value })));
  $("#f-status", root).addEventListener("change", (e) => saveExp({ status: e.target.value }, true));
  bindSections(root);
  $("#dup", root).onclick = async () => {
    try {
      const d = await api("POST", `/api/experiments/${exp.id}/duplicate`);
      state.data = null;
      location.hash = `#/exp/${d.experiment.id}`;
      toast("Copied the plan: steps, reagents with planned amounts, procedure and references.");
    } catch (e) { toast(e.message, true); }
  };
  $("#del", root).onclick = async () => {
    if (!confirm(`Delete “${exp.title}” with all its reagents, procedure and log? This cannot be undone.`)) return;
    try { await api("DELETE", `/api/experiments/${exp.id}`); state.data = null; location.hash = "#/"; }
    catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------------------------------- boot
(async function boot() {
  try {
    state.config = await api("GET", "/api/config");
  } catch (e) {
    app.innerHTML = `<div class="panel">Could not reach the Lab Notebook server: ${esc(e.message)}</div>`;
    return;
  }
  checkHealth();
  setInterval(checkHealth, 60000);
  startTicker();
  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", (e) => {
    if (hasPendingExp()) { e.preventDefault(); e.returnValue = ""; }
  });
  // Refresh when coming back to the tab (another device may have logged something)
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible" && state.data) {
      try { setData(await api("GET", `/api/experiments/${expId()}`)); } catch { /* offline */ }
    }
  });
  route();
})();

