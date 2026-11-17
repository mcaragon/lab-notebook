/* Lab Notebook frontend: vanilla JS modules, no build step.
   Routes: #/ (dashboard), #/exp/<id>[/<tab>] with tabs plan | bench | results | report, #/seq/<id>. */
import { $, $$, api, esc, toast } from "./util.js";
import { state, setData, expId, addRenderer, refresh, sigOf } from "./state.js";
import { flushExp, saveExp, sectionField, bindSections, hasPendingExp } from "./expfields.js";
import { renderReaction } from "./reaction.js";
import { renderReagents } from "./reagents.js";
import { renderProcedure, renderChecklist } from "./procedure.js";
import { renderBench, startTicker } from "./bench.js";
import { renderResults, renderRefs, renderReport } from "./results.js";
import { renderSequence } from "./sequence.js";
import { initSidebar, refreshSidebar, patchSidebar, markActive } from "./sidebar.js";
import { renderGlance, renderHazards } from "./widgets.js";
import { initResizers, resizer } from "./resize.js";

const app = $("#app");
const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
const TABS = [["plan", "Plan"], ["bench", "Bench"], ["results", "Results"], ["report", "Report"]];
const TAB_HINTS = {
  plan: "Reaction, reagents and hazards", bench: "Reagent checklist, procedure and log",
  results: "Yields, write-up and references", report: "PDF, Markdown and print view",
};

// ------------------------------------------------------------------------------------------- PubChem status
let health = null;
async function checkHealth() {
  try {
    const h = await api("GET", "/api/health");
    health = { ok: h.pubchem.reachable, title: h.pubchem.reachable ? `Connected: ${h.pubchem.url}` : `${h.pubchem.error}\nManual entry still works.` };
  } catch {
    health = { ok: false, title: "The Lab Notebook server is unreachable" };
  }
  showHealth();
}
function showHealth() {
  const el = $("#pubchem-status");
  if (!el || !health) return;
  el.textContent = health.ok ? "PubChem Local" : "PubChem Local offline";
  el.className = "pill " + (health.ok ? "ok" : "bad");
  el.title = health.title;
}
window.addEventListener("sidebar-drawn", showHealth);

// ------------------------------------------------------------------------------------------- routing
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  markActive();
  document.body.classList.toggle("exp-view", parts[0] === "exp" && !!parts[1]);
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
      renderShell(parts[2]);
    } else {
      showTab(parts[2] || state.tab);
    }
  } else {
    await flushExp.flush();
    state.data = null;
    state.renderers = [];
    document.body.classList.remove("running");
    if (parts[0] === "seq" && parts[1]) renderSequence(app, Number(parts[1]));
    else renderHome();
  }
}

// ------------------------------------------------------------------------------------------- dashboard
async function renderHome() {
  document.title = "Lab Notebook";
  app.innerHTML = `<div class="home"><div class="page-head"><div><h1>Lab Notebook</h1><p class="hint">Plan, run and write up organic chemistry experiments.</p></div>
    <span class="spacer"></span><button class="btn" id="h-new-seq">⇢ New sequence</button><button class="btn primary" id="h-new-exp">＋ New experiment</button></div>
    <div id="home-body" class="empty">Loading…</div></div>`;
  $("#h-new-exp").onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      refreshSidebar();
      location.hash = `#/exp/${d.experiment.id}/plan`;
    } catch (e) { toast(e.message, true); }
  };
  $("#h-new-seq").onclick = async () => {
    try {
      const d = await api("POST", "/api/sequences", { title: "New sequence" });
      refreshSidebar();
      location.hash = `#/seq/${d.sequence.id}`;
    } catch (e) { toast(e.message, true); }
  };
  try {
    const [{ experiments }, { sequences }] = await Promise.all([api("GET", "/api/experiments"), api("GET", "/api/sequences")]);
    const by = (s) => experiments.filter((e) => e.status === s);
    const card = (e) => `<a class="exp-card s-${esc(e.status)}" href="#/exp/${e.id}/${e.status === "in_progress" ? "bench" : "plan"}">
      <span class="status ${esc(e.status)}">${esc(STATUS_LABELS[e.status] || e.status)}</span>
      <b>${esc(e.title)}</b>
      <span class="sub">${[e.course, e.date].filter(Boolean).map(esc).join(" · ")}</span>
      <span class="ec-foot"><span>${e.n_steps > 1 ? `${e.n_steps} steps` : "1 step"}</span><span>${e.n_reagents} chemicals</span></span></a>`;
    $("#home-body").className = "";
    $("#home-body").innerHTML = `
      <div class="stat-row">
        <div class="stat s-in_progress"><span class="k-l">In progress</span><b>${by("in_progress").length}</b></div>
        <div class="stat s-planned"><span class="k-l">Planned</span><b>${by("planned").length}</b></div>
        <div class="stat s-completed"><span class="k-l">Completed</span><b>${by("completed").length}</b></div>
        <div class="stat s-seq"><span class="k-l">Sequences</span><b>${sequences.length}</b></div>
      </div>
      ${by("in_progress").length ? `<h2 class="home-h">Running now</h2><div class="card-grid">${by("in_progress").map(card).join("")}</div>` : ""}
      <h2 class="home-h">All experiments</h2>
      ${experiments.length ? `<div class="card-grid">${experiments.map(card).join("")}</div>` : '<p class="empty">No experiments yet. Create one to start planning.</p>'}
      <h2 class="home-h">Sequences</h2>
      ${sequences.length ? `<div class="card-grid">${sequences.map((q) => `<a class="exp-card s-seq" href="#/seq/${q.id}">
        <span class="status seq">Sequence</span><b>${esc(q.title)}</b>
        <span class="sub">${q.experiments.map((e) => esc(e.title)).join(" → ") || "no experiments yet"}</span>
        <span class="ec-foot"><span>${q.experiments.length} experiment${q.experiments.length === 1 ? "" : "s"}</span></span></a>`).join("")}</div>`
        : '<p class="empty">A sequence links separate experiments (e.g. one per step, on different days) into one route with an overall scheme, yield and report.</p>'}`;
  } catch (e) {
    $("#home-body").textContent = "Could not load: " + e.message;
  }
}

// ------------------------------------------------------------------------------------------- experiment shell
function renderShell(tab) {
  const exp = state.data.experiment;
  document.title = `${exp.title} · Lab Notebook`;
  app.innerHTML = `
    <div class="exp-head">
      <input class="title" id="exp-title" data-key="exp-title" value="${esc(exp.title)}" aria-label="Title">
      <span class="saved" id="saved"></span>
      <nav class="tabs" role="tablist">${TABS.map(([k, v]) =>
        `<a role="tab" href="#/exp/${exp.id}/${k}" data-tab="${k}" title="${TAB_HINTS[k]}">${v}</a>`).join("")}</nav>
    </div>
    <div id="bench" class="bench"></div>
    <div class="tab-body" data-tab="plan"><div class="layout-2">
      <div class="col-main"><section id="sec-reaction"></section><section id="sec-reagents"></section></div>
      ${resizer("--rail", "next", 260, 720, "Resize the side panel")}
      <div class="col-side"><section id="sec-glance"></section><section id="sec-hazards"></section><section id="sec-overview"></section></div>
    </div></div>
    <div class="tab-body" data-tab="bench"><div class="layout-bench">
      <div class="col-left"><section id="sec-checklist"></section></div>
      ${resizer("--bench-left", "prev", 220, 640, "Resize the reagent checklist")}
      <div class="col-main"><section id="sec-procedure"></section></div>
    </div></div>
    <div class="tab-body" data-tab="results"><div class="layout-2">
      <div class="col-main"><section id="sec-results"></section></div>
      ${resizer("--rail", "next", 260, 720, "Resize the side panel")}
      <div class="col-side"><section id="sec-refs"></section></div>
    </div></div>
    <div class="tab-body" data-tab="report"><section id="sec-report"></section></div>`;
  applyCollapsed();
  $("#exp-title").addEventListener("input", (e) => {
    const t = e.target.value || "Untitled experiment";
    saveExp({ title: t });
    document.title = `${t} · Lab Notebook`;
    patchSidebar(exp.id, { title: t });
  });
  const d = () => state.data;
  state.renderers = [];
  addRenderer("*", () => sigOf(d().experiment.status), () => {
    const st = $("#f-status");
    if (st && st !== document.activeElement) st.value = d().experiment.status;
    patchSidebar(expId(), { status: d().experiment.status });
  });
  addRenderer("*", () => sigOf(d().experiment.started_at, d().experiment.ended_at, d().timers), () => renderBench($("#bench")));
  addRenderer("plan", () => sigOf(d().steps, d().scheme_html, d().experiment.scheme_style), () => renderReaction($("#sec-reaction")));
  addRenderer("plan", () => sigOf(d().reagents, d().steps.map((x) => [x.id, x.title]), d().stoich, d().refs.map((x) => x.id)),
    () => renderReagents($("#sec-reagents")));
  addRenderer("plan", () => sigOf(d().reagents.map((r) => [r.id, r.name, r.label, r.role, r.calc, r.actual_value]), d().steps.length,
    d().experiment.started_at, d().experiment.ended_at), () => renderGlance($("#sec-glance")));
  addRenderer("plan", () => sigOf(d().reagents.map((r) => [r.id, r.name, r.label, r.pictograms, r.signal_word, r.hazard_statements,
    r.extra_hazards, r.flash_point])), () => renderHazards($("#sec-hazards")));
  addRenderer("plan", () => sigOf(d().sequences), () => renderOverview($("#sec-overview")));
  addRenderer("bench", () => sigOf(d().reagents.map((r) => [r.id, r.name, r.label, r.role, r.step_id, r.calc, r.actual_value,
    r.actual_basis, r.basis, r.actual_mass_g, r.crude_mass_g, r.form]), d().steps.map((x) => [x.id, x.title])),
    () => renderChecklist($("#sec-checklist")));
  addRenderer("bench", () => sigOf(d().procedure, d().entries, d().steps.map((x) => x.id),
    d().reagents.map((r) => [r.id, r.name, r.label, r.role, r.form, r.mp])), () => renderProcedure($("#sec-procedure")));
  addRenderer("results", () => sigOf(d().reagents.filter((r) => r.role === "product").map((r) => [r.id, r.name, r.calc, r.expected_ref_id]),
    d().stoich.overall_yield, d().refs.map((x) => x.id), d().steps.length), () => renderResults($("#sec-results")));
  addRenderer("results", () => sigOf(d().refs), () => renderRefs($("#sec-refs")));
  addRenderer("report", () => sigOf(expId()), () => renderReport($("#sec-report")));
  showTab(tab || (exp.started_at && !exp.ended_at ? "bench" : "plan"));
}

export function showTab(tab) {
  if (!TABS.some(([k]) => k === tab)) tab = "plan";
  state.tab = tab;
  $$(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  $$(".tab-body").forEach((b) => b.classList.toggle("hidden", b.dataset.tab !== tab));
  refresh();
  const want = `#/exp/${expId()}/${tab}`;
  if (location.hash !== want) history.replaceState(null, "", want);
  markActive();
}

function renderOverview(root) {
  const exp = state.data.experiment;
  root.innerHTML = `<div class="panel widget">
    <div class="w-h"><h3>Details</h3></div>
    <div class="grid two">
      <label class="field">Date<input type="date" id="f-date" value="${esc(exp.date || "")}"></label>
      <label class="field">Status<select id="f-status">${Object.entries(STATUS_LABELS).map(([k, v]) =>
        `<option value="${k}" ${exp.status === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="field">Author<input id="f-author" value="${esc(exp.author || "")}"></label>
      <label class="field">Course / lab<input id="f-course" value="${esc(exp.course || "")}"></label>
    </div>
    <div style="height:10px"></div>
    ${sectionField("objective", "Objective", "", 3)}
    <div class="w-sub">Sequence</div>
    <div class="row seq-row">
      ${(state.data.sequences || []).map((q) => `<a class="chip" href="#/seq/${q.id}">⇢ ${esc(q.title)}</a>`).join("")}
      <select id="seq-pick" aria-label="Add to a sequence"><option value="">Add to sequence…</option><option value="new">New sequence…</option></select>
    </div>
    <div class="row" style="margin-top:14px">
      <button class="btn small" id="dup">Duplicate as new plan</button><span class="spacer"></span>
      <button class="btn small danger" id="del">Delete</button>
    </div></div>`;
  [["f-date", "date"], ["f-author", "author"], ["f-course", "course"]].forEach(([id, k]) =>
    $("#" + id, root).addEventListener("input", (e) => saveExp({ [k]: e.target.value })));
  $("#f-status", root).addEventListener("change", (e) => { saveExp({ status: e.target.value }, true); patchSidebar(exp.id, { status: e.target.value }); });
  const pick = $("#seq-pick", root);
  api("GET", "/api/sequences").then(({ sequences }) => {
    const mine = new Set((state.data.sequences || []).map((q) => q.id));
    pick.insertAdjacentHTML("beforeend", sequences.filter((q) => !mine.has(q.id))
      .map((q) => `<option value="${q.id}">${esc(q.title)}</option>`).join(""));
  }).catch(() => {});
  pick.onchange = async () => {
    try {
      if (pick.value === "new") {
        const title = prompt("Name of the new sequence:", exp.title);
        if (!title) { pick.value = ""; return; }
        const d = await api("POST", "/api/sequences", { title, experiment_ids: [exp.id] });
        refreshSidebar();
        location.hash = `#/seq/${d.sequence.id}`;
      } else if (pick.value) {
        const d = await api("POST", `/api/sequences/${pick.value}/experiments`, { experiment_id: exp.id });
        state.data = null;
        refreshSidebar();
        location.hash = `#/seq/${d.sequence.id}`;
      }
    } catch (e) { toast(e.message, true); }
  };
  bindSections(root);
  $("#dup", root).onclick = async () => {
    try {
      const d = await api("POST", `/api/experiments/${exp.id}/duplicate`);
      state.data = null;
      refreshSidebar();
      location.hash = `#/exp/${d.experiment.id}/plan`;
      toast("Copied the plan: steps, reagents with planned amounts, procedure and references.");
    } catch (e) { toast(e.message, true); }
  };
  $("#del", root).onclick = async () => {
    if (!confirm(`Delete “${exp.title}” with all its reagents, procedure and log? This cannot be undone.`)) return;
    try { await api("DELETE", `/api/experiments/${exp.id}`); state.data = null; refreshSidebar(); location.hash = "#/"; }
    catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------------------------------- collapsible sections
// Clicking a section or panel title folds it; the choice is remembered per section.
const COLLAPSE_KEY = "ln.collapsed";
const collapsed = new Set((() => { try { return JSON.parse(localStorage.getItem(COLLAPSE_KEY)) || []; } catch { return []; } })());
function applyCollapsed() {
  $$("#app section[id]").forEach((sec) => sec.classList.toggle("collapsed", collapsed.has(sec.id)));
}
document.addEventListener("click", (e) => {
  const h = e.target.closest(".sec-head h2, .w-h h3");
  const sec = h?.closest("section[id]");
  if (!sec) return;
  sec.classList.toggle("collapsed");
  if (sec.classList.contains("collapsed")) collapsed.add(sec.id); else collapsed.delete(sec.id);
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsed])); } catch { /* private mode */ }
});

// ------------------------------------------------------------------------------------------- boot
(async function boot() {
  try {
    state.config = await api("GET", "/api/config");
  } catch (e) {
    app.innerHTML = `<div class="panel">Could not reach the Lab Notebook server: ${esc(e.message)}</div>`;
    return;
  }
  initSidebar();
  initResizers();
  checkHealth();
  setInterval(checkHealth, 60000);
  startTicker();
  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", (e) => {
    if (hasPendingExp()) { e.preventDefault(); e.returnValue = ""; }
  });
  // Refresh when coming back to the app (another device may have logged something)
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible" && state.data) {
      try { setData(await api("GET", `/api/experiments/${expId()}`)); } catch { /* offline */ }
    }
  });
  route();
})();
