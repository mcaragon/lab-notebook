/* Project page: experiments linked by material into a route that can branch and converge. Shows the route map, a
   table of the experiments with what each was made from, yields and what is left, branching, and reports (the whole
   project, or the route to one final product). */
import { $, $$, api, debounce, esc, fmt, toast } from "./util.js";
import { refreshSidebar } from "./sidebar.js";
import { branchFrom } from "./widgets.js";

const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
let proj = null;

export async function renderProject(app, id) {
  try {
    proj = await api("GET", `/api/projects/${id}`);
  } catch (e) {
    app.innerHTML = `<div class="panel">Could not load the project: ${esc(e.message)} <a href="#/">Back</a></div>`;
    return;
  }
  if (location.hash.startsWith("#/seq/")) history.replaceState(null, "", `#/project/${id}`);
  draw(app);
}

async function change(app, method, path, body) {
  try {
    const d = await api(method, path, body);
    if (d?.project) { proj = d; draw(app); refreshSidebar(); }
    return d;
  } catch (e) { toast(e.message, true); throw e; }
}

// Text fields save without redrawing the page (keeps focus while typing)
const saveField = debounce(async (field, value) => {
  try {
    proj.project = (await api("PUT", `/api/projects/${proj.project.id}`, { [field]: value })).project;
    if (field === "title") refreshSidebar();
  } catch (e) { toast("Not saved: " + e.message, true); }
}, 700);

const g = (v) => (v == null ? "–" : `${fmt(v)} g`);

function reportLinks(base, label) {
  return `<span class="rep-label">${label}</span>
    <a class="btn small primary" href="${base.replace("{f}", "pdf")}" target="_blank" rel="noopener">⬇ PDF</a>
    <a class="btn small" href="${base.replace("{f}", "md")}${base.includes("?") ? "&" : "?"}download=true">⬇ Markdown</a>
    <a class="btn small" href="${base.replace("{f}", "html")}" target="_blank" rel="noopener">Print view</a>`;
}

async function draw(app) {
  const p = proj.project;
  document.title = `${p.title} · Lab Notebook`;
  let all = [];
  try { all = (await api("GET", "/api/experiments")).experiments; } catch { /* ignore */ }
  const inProj = new Set(proj.experiments.map((e) => e.id));
  const rows = proj.summary;
  app.innerHTML = `
    <div class="exp-head">
      <a href="#/" class="btn icon" title="Dashboard" aria-label="Dashboard">←</a>
      <span class="badge" style="margin:0">Project</span>
      <input class="title" id="proj-title" value="${esc(p.title)}" aria-label="Project title">
    </div>
    <div class="panel">
      <div class="row sec-head"><h2>Route map</h2><span class="spacer"></span>
        <span class="legend-dots"><i class="dot planned"></i>planned <i class="dot in_progress"></i>in progress <i class="dot completed"></i>completed
          <i class="dash"></i>second starting material</span></div>
      ${rows.length ? `<div class="route-scroll">${proj.map_svg}</div>`
        : '<div class="empty">No experiments yet. Start with a new experiment, or add existing ones.</div>'}
      <div class="row" style="margin-top:10px">
        <button class="btn primary" id="proj-new">＋ New experiment</button>
        <select id="proj-add" class="grow" aria-label="Add an existing experiment"><option value="">Add an existing experiment…</option>
          ${all.filter((e) => !inProj.has(e.id)).map((e) => `<option value="${e.id}">${esc(e.title)} (${esc(e.date || "")})</option>`).join("")}</select>
      </div>
      <p class="hint">Experiments are linked by material: an experiment whose starting material is a portion of another one's product
        continues the route from it. <b>⑂ Branch</b> starts a new experiment from a product; several branches can share one product
        (different reactions, or small-scale trials), and what is left of it is tracked.</p>
    </div>
    ${rows.length ? `<div class="panel">
      <div class="row sec-head"><h2>Experiments</h2></div>
      <div class="table-wrap"><table class="proj-sum">
        <thead><tr><th class="num">#</th><th>Experiment</th><th>From</th><th>Product</th><th class="num">Isolated</th>
          <th class="num">Yield</th><th class="num">Left</th><th class="num">Overall</th><th></th></tr></thead>
        <tbody>${rows.map((r) => `<tr data-eid="${r.id}" style="--depth:${r.col}">
          <td class="num sub">${r.n}</td>
          <td class="t-exp"><span class="indent"></span><i class="dot ${esc(r.status)}" title="${esc(STATUS_LABELS[r.status] || r.status)}"></i>
            <a href="#/exp/${r.id}/plan">${esc(r.title)}</a><div class="sub">${esc(r.date || "")}</div></td>
          <td class="sub">${r.from.map((f) => `${esc(f.title)}${f.taken_g != null ? ` · ${fmt(f.taken_g)} g` : ""}`).join("<br>") || "—"}</td>
          <td>${r.number ? `<b>${r.number}</b> ` : ""}${esc(r.product || "–")}</td>
          <td class="num">${g(r.isolated_g)}</td>
          <td class="num yield">${r.yield != null ? r.yield.toFixed(1) + "%" : "–"}</td>
          <td class="num ${r.remaining_g != null && r.remaining_g < 0 ? "neg" : ""}">${r.remaining_g != null ? g(r.remaining_g) : r.isolated_g != null ? g(r.isolated_g) : "–"}</td>
          <td class="num">${r.overall_yield != null ? `${r.overall_yield.toFixed(1)}%<div class="sub">${r.lls} steps</div>` : "–"}</td>
          <td class="actions">${r.product_id ? `<button class="btn small" data-branch="${r.product_id}" title="New experiment from a portion of ${esc(r.product)}">⑂ Branch</button>` : ""}
            <button class="btn icon danger" data-remove="${r.id}" title="Remove from the project (the experiment is kept)" aria-label="Remove">✕</button></td>
        </tr>`).join("")}</tbody></table></div>
      <p class="hint">Overall yields multiply the yields along the longest chain of experiments leading to each one.</p>
    </div>` : ""}
    <div class="panel">
      <div class="row sec-head"><h2>Reports</h2></div>
      <div class="rep-grid">
        <div class="row">${reportLinks(`/api/projects/${p.id}/report.{f}`, "Whole project")}</div>
        ${proj.final.map((f) => `<div class="row">${reportLinks(`/api/projects/${p.id}/report.{f}?leaf=${f.id}`, `Route to ${esc(f.title)}`)}</div>`).join("")}
      </div>
      <label class="field" style="margin-top:12px">Notes (shown in the reports)<textarea id="proj-notes" rows="3">${esc(p.notes || "")}</textarea></label>
      <div class="row" style="margin-top:12px"><span class="spacer"></span><button class="btn danger small" id="proj-del">Delete project</button></div>
    </div>`;
  $("#proj-title", app).addEventListener("input", (e) => saveField("title", e.target.value || "Untitled project"));
  $("#proj-notes", app).addEventListener("input", (e) => saveField("notes", e.target.value));
  $("#proj-add", app).onchange = (e) => e.target.value && change(app, "POST", `/api/projects/${p.id}/experiments`, { experiment_id: Number(e.target.value) });
  $("#proj-new", app).onclick = async () => {
    const d = await change(app, "POST", `/api/projects/${p.id}/new`, { title: "New experiment" });
    if (d?.experiment_id) location.hash = `#/exp/${d.experiment_id}/plan`;
  };
  $$("[data-branch]", app).forEach((b) => (b.onclick = async () => {
    const r = rows.find((x) => x.product_id === Number(b.dataset.branch));
    const out = await branchFrom({ id: r.product_id, name: r.product }, r.remaining_g ?? r.isolated_g);
    if (out) location.hash = `#/exp/${out.experiment.id}/plan`;
  }));
  $$("[data-remove]", app).forEach((b) => (b.onclick = () => change(app, "DELETE", `/api/projects/${p.id}/experiments/${b.dataset.remove}`)));
  $("#proj-del", app).onclick = async () => {
    if (!confirm(`Delete the project “${p.title}”? Its experiments are kept.`)) return;
    await api("DELETE", `/api/projects/${p.id}`);
    refreshSidebar();
    location.hash = "#/";
  };
}
