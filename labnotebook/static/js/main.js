/* Lab Notebook frontend: vanilla JS modules, no build step.
   Routes: #/ (list), #/exp/<id>[/<tab>] with tabs plan | bench | results | report, #/seq/<id>. */
import { $, $$, api, esc, toast } from "./util.js";
import { state, setData, expId, addRenderer, refresh, sigOf } from "./state.js";
import { flushExp, saveExp, sectionField, bindSections, hasPendingExp } from "./expfields.js";
import { renderReaction } from "./reaction.js";
import { renderReagents } from "./reagents.js";
import { renderProcedure, renderChecklist } from "./procedure.js";
import { renderBench, startTicker } from "./bench.js";
import { renderResults, renderRefs, renderReport } from "./results.js";
import { renderSequence } from "./sequence.js";

const app = $("#app");
const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
const TABS = [["plan", "Plan"], ["bench", "Bench"], ["results", "Results"], ["report", "Report"]];
const TAB_HINTS = {
  plan: "Overview, reaction and reagents", bench: "Reagent checklist, procedure and log",
  results: "Yields, write-up and references", report: "PDF, Markdown and print view",
};

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
    else renderList();
  }
}

// ------------------------------------------------------------------------------------------- experiment list
async function renderList() {
  document.title = "Lab Notebook";
  app.innerHTML = `<div class="panel list-panel"><div class="row"><h2 style="margin:0">Experiments</h2><span class="spacer"></span>
    <button class="btn primary" id="new-exp">+ New experiment</button></div><div id="list" class="empty">Loading…</div></div>
    <div class="panel list-panel"><div class="row"><h2 style="margin:0">Sequences</h2><span class="spacer"></span>
    <button class="btn" id="new-seq">+ New sequence</button></div>
    <p class="hint">A sequence links separate experiments (e.g. one per step, on different days) into one route with an overall
      scheme, yield and combined report.</p><div id="seqs" class="empty">Loading…</div></div>`;
  $("#new-exp").onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      state.data = null;
      location.hash = `#/exp/${d.experiment.id}/plan`;
    } catch (e) { toast(e.message, true); }
  };
  $("#new-seq").onclick = async () => {
    try {
      const d = await api("POST", "/api/sequences", { title: "New sequence" });
      location.hash = `#/seq/${d.sequence.id}`;
    } catch (e) { toast(e.message, true); }
  };
  api("GET", "/api/sequences").then(({ sequences }) => {
    const box = $("#seqs");
    if (!box) return;
    if (!sequences.length) { box.textContent = "No sequences yet."; return; }
    box.className = "";
    box.innerHTML = `<ul class="exp-list">${sequences.map((q) => `<li><a href="#/seq/${q.id}">
      <span class="title">${esc(q.title)}</span>
      <span class="muted small">${q.experiments.map((e) => esc(e.title)).join(" → ")}</span>
      <span class="muted small">${q.experiments.length} experiment${q.experiments.length === 1 ? "" : "s"}</span></a></li>`).join("")}</ul>`;
  }).catch(() => { const box = $("#seqs"); if (box) box.textContent = "Could not load sequences."; });
  try {
    const { experiments } = await api("GET", "/api/experiments");
    const list = $("#list");
    if (!experiments.length) { list.innerHTML = "No experiments yet. Create one to start planning."; return; }
    list.className = "";
    list.innerHTML = `<ul class="exp-list">${experiments.map((e) => `<li><a href="#/exp/${e.id}/${e.status === "in_progress" ? "bench" : "plan"}">
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
function renderShell(tab) {
  const exp = state.data.experiment;
  document.title = `${exp.title} · Lab Notebook`;
  app.innerHTML = `
    <div class="exp-head">
      <a href="#/" class="btn icon" title="All experiments" aria-label="All experiments">←</a>
      <input class="title" id="exp-title" data-key="exp-title" value="${esc(exp.title)}" aria-label="Title">
      <span class="saved" id="saved"></span>
    </div>
    <div id="bench" class="bench"></div>
    <nav class="tabs" role="tablist">${TABS.map(([k, v]) =>
      `<a role="tab" href="#/exp/${exp.id}/${k}" data-tab="${k}" title="${TAB_HINTS[k]}">${v}</a>`).join("")}</nav>
    <div class="tab-body" data-tab="plan"><section id="sec-overview"></section><section id="sec-reaction"></section><section id="sec-reagents"></section></div>
    <div class="tab-body" data-tab="bench"><section id="sec-checklist"></section><section id="sec-procedure"></section></div>
    <div class="tab-body" data-tab="results"><section id="sec-results"></section><section id="sec-refs"></section></div>
    <div class="tab-body" data-tab="report"><section id="sec-report"></section></div>`;
  $("#exp-title").addEventListener("input", (e) => {
    saveExp({ title: e.target.value || "Untitled experiment" });
    document.title = `${e.target.value} · Lab Notebook`;
  });
  const d = () => state.data;
  state.renderers = [];
  addRenderer("*", () => sigOf(d().experiment.status), () => {
    const st = $("#f-status");
    if (st && st !== document.activeElement) st.value = d().experiment.status;
  });
  addRenderer("*", () => sigOf(d().experiment.started_at, d().experiment.ended_at, d().timers), () => renderBench($("#bench")));
  addRenderer("plan", () => sigOf(d().sequences), () => renderOverview($("#sec-overview")));
  addRenderer("plan", () => sigOf(d().steps, d().scheme_html, d().experiment.scheme_style), () => renderReaction($("#sec-reaction")));
  addRenderer("plan", () => sigOf(d().reagents, d().steps.map((x) => [x.id, x.title]), d().stoich, d().refs.map((x) => x.id)),
    () => renderReagents($("#sec-reagents")));
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
    ${sectionField("objective", "Objective", "", 2)}
    <div class="row seq-row" style="margin-top:10px">
      <span class="small muted">Sequence:</span>
      ${(state.data.sequences || []).map((q) => `<a class="chip" href="#/seq/${q.id}">${esc(q.title)}</a>`).join("") || '<span class="small muted">none</span>'}
      <select id="seq-pick" aria-label="Add to a sequence"><option value="">Add to sequence…</option><option value="new">New sequence…</option></select>
      <span class="spacer"></span>
      <button class="btn small" id="dup">Duplicate as new plan</button>
      <button class="btn small danger" id="del">Delete</button>
    </div></div>`;
  [["f-date", "date"], ["f-author", "author"], ["f-course", "course"]].forEach(([id, k]) =>
    $("#" + id, root).addEventListener("input", (e) => saveExp({ [k]: e.target.value })));
  $("#f-status", root).addEventListener("change", (e) => saveExp({ status: e.target.value }, true));
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
        location.hash = `#/seq/${d.sequence.id}`;
      } else if (pick.value) {
        const d = await api("POST", `/api/sequences/${pick.value}/experiments`, { experiment_id: exp.id });
        state.data = null;
        location.hash = `#/seq/${d.sequence.id}`;
      }
    } catch (e) { toast(e.message, true); }
  };
  bindSections(root);
  $("#dup", root).onclick = async () => {
    try {
      const d = await api("POST", `/api/experiments/${exp.id}/duplicate`);
      state.data = null;
      location.hash = `#/exp/${d.experiment.id}/plan`;
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
  // Refresh when coming back to the app (another device may have logged something)
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible" && state.data) {
      try { setData(await api("GET", `/api/experiments/${expId()}`)); } catch { /* offline */ }
    }
  });
  route();
})();
