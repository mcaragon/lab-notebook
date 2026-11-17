/* Sequence page: separate experiments linked into one route, with the overall scheme, yields and report. */
import { $, $$, api, debounce, esc, fmt, toast } from "./util.js";
import { refreshSidebar } from "./sidebar.js";

const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
let seq = null;

export async function renderSequence(app, id) {
  try {
    seq = await api("GET", `/api/sequences/${id}`);
  } catch (e) {
    app.innerHTML = `<div class="panel">Could not load the sequence: ${esc(e.message)} <a href="#/">Back</a></div>`;
    return;
  }
  draw(app);
}

async function change(app, method, path, body) {
  try {
    const d = await api(method, path, body);
    if (d?.sequence) { seq = d; draw(app); refreshSidebar(); }
    return d;
  } catch (e) { toast(e.message, true); throw e; }
}

// Text fields save without redrawing the page (keeps focus while typing)
const saveField = debounce(async (app, field, value) => {
  try {
    seq.sequence = (await api("PUT", `/api/sequences/${seq.sequence.id}`, { [field]: value })).sequence;
    if (field === "title") refreshSidebar();
  }
  catch (e) { toast("Not saved: " + e.message, true); }
}, 700);

async function draw(app) {
  const s = seq.sequence;
  document.title = `${s.title} · Lab Notebook`;
  let all = [];
  try { all = (await api("GET", "/api/experiments")).experiments; } catch { /* ignore */ }
  const inSeq = new Set(seq.experiments.map((e) => e.id));
  app.innerHTML = `
    <div class="exp-head">
      <a href="#/" class="btn icon" title="All experiments" aria-label="All experiments">←</a>
      <span class="badge" style="margin:0">Sequence</span>
      <input class="title" id="seq-title" value="${esc(s.title)}" aria-label="Sequence title">
    </div>
    <div class="panel">
      <div class="row sec-head"><h2>Route</h2><span class="spacer"></span>
        <label class="inline small">Scheme style <select id="seq-style">${[["auto", "Automatic"], ["inline", "Conditions on arrows"], ["lettered", "Lettered (a), (b)…"]]
          .map(([k, v]) => `<option value="${k}" ${s.scheme_style === k ? "selected" : ""}>${v}</option>`).join("")}</select></label></div>
      <div class="scheme-paper">${seq.experiments.length ? seq.scheme_html : '<div class="empty">Add experiments to build the route.</div>'}</div>
      ${seq.summary.length ? `<div class="table-wrap"><table class="seq-sum">
        <thead><tr><th class="num">Step</th><th>Experiment</th><th>Date</th><th>Product</th><th class="num">Isolated</th><th class="num">Yield</th></tr></thead>
        <tbody>${seq.summary.map((r) => `<tr><td class="num">${r.n}</td>
          <td><a href="#/exp/${r.experiment_id}">${esc(r.experiment)}</a>${r.n_steps_exp > 1 ? ` <span class="sub">(step ${r.step_in_exp})</span>` : ""}</td>
          <td class="sub">${esc(r.date || "")}</td><td>${esc(r.product || "–")}</td>
          <td class="num">${r.isolated_mass_g != null ? fmt(r.isolated_mass_g) + " g" : "–"}</td>
          <td class="num yield">${r.yield != null ? r.yield.toFixed(1) + "%" : "–"}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${seq.overall_yield != null ? `<p class="overall"><b>Overall yield:</b> ${seq.overall_yield.toFixed(1)}% over ${seq.summary.length} steps</p>` : ""}
    </div>
    <div class="panel">
      <div class="row sec-head"><h2>Experiments</h2><span class="spacer"></span>
        <button class="btn primary" id="seq-next">+ Next experiment</button></div>
      <ol class="seq-list">${seq.experiments.map((e, i) => `<li data-eid="${e.id}">
        <span class="seq-no">${i + 1}</span>
        <a href="#/exp/${e.id}" class="grow">${esc(e.title)}</a>
        <span class="sub">${esc(e.date || "")}</span>
        <span class="status ${esc(e.status)}">${esc(STATUS_LABELS[e.status] || e.status)}</span>
        ${e.linked === false ? `<span class="badge alert" title="No starting material of this experiment matches the previous experiment's product">not linked</span>` : ""}
        <button class="btn icon" data-up="${e.id}" title="Move up" aria-label="Move up">↑</button>
        <button class="btn icon" data-down="${e.id}" title="Move down" aria-label="Move down">↓</button>
        <button class="btn icon danger" data-remove="${e.id}" title="Remove from sequence (the experiment is kept)" aria-label="Remove">✕</button>
      </li>`).join("") || '<li class="empty">No experiments yet.</li>'}</ol>
      <div class="row"><select id="seq-add" class="grow" aria-label="Add an existing experiment"><option value="">Add an existing experiment…</option>
        ${all.filter((e) => !inSeq.has(e.id)).map((e) => `<option value="${e.id}">${esc(e.title)} (${esc(e.date || "")})</option>`).join("")}</select></div>
      <p class="hint">“Next experiment” creates a new experiment that starts from the last product. Existing experiments can be linked
        after the fact: an experiment continues the route when one of its starting materials is the previous experiment's product.</p>
      <label class="field" style="margin-top:10px">Notes (shown in the report)<textarea id="seq-notes" rows="3">${esc(s.notes || "")}</textarea></label>
    </div>
    <div class="panel row">
      <h2>Report</h2><span class="spacer"></span>
      <a class="btn primary" href="/api/sequences/${s.id}/report.pdf" target="_blank" rel="noopener">⬇ PDF</a>
      <a class="btn" href="/api/sequences/${s.id}/report.md?download=true">⬇ Markdown</a>
      <a class="btn" href="/api/sequences/${s.id}/report.html" target="_blank" rel="noopener">Print view</a>
      <button class="btn danger" id="seq-del">Delete sequence</button>
    </div>`;
  $("#seq-title", app).addEventListener("input", (e) => saveField(app, "title", e.target.value || "Untitled sequence"));
  $("#seq-notes", app).addEventListener("input", (e) => saveField(app, "notes", e.target.value));
  $("#seq-style", app).onchange = (e) => change(app, "PUT", `/api/sequences/${s.id}`, { scheme_style: e.target.value });
  $("#seq-add", app).onchange = (e) => e.target.value && change(app, "POST", `/api/sequences/${s.id}/experiments`, { experiment_id: Number(e.target.value) });
  $("#seq-next", app).onclick = async () => {
    const d = await change(app, "POST", `/api/sequences/${s.id}/next`, {});
    if (d?.experiment_id) location.hash = `#/exp/${d.experiment_id}`;
  };
  const move = (id, dir) => {
    const ids = seq.experiments.map((e) => e.id);
    const i = ids.indexOf(id), j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    change(app, "PUT", `/api/sequences/${s.id}/order`, ids);
  };
  $$("[data-up]", app).forEach((b) => (b.onclick = () => move(Number(b.dataset.up), -1)));
  $$("[data-down]", app).forEach((b) => (b.onclick = () => move(Number(b.dataset.down), 1)));
  $$("[data-remove]", app).forEach((b) => (b.onclick = () => change(app, "DELETE", `/api/sequences/${s.id}/experiments/${b.dataset.remove}`)));
  $("#seq-del", app).onclick = async () => {
    if (!confirm(`Delete the sequence “${s.title}”? Its experiments are kept.`)) return;
    await api("DELETE", `/api/sequences/${s.id}`);
    refreshSidebar();
    location.hash = "#/";
  };
}
