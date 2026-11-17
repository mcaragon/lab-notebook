/* Lab Notebook frontend: vanilla JS, no build step. Hash routes: #/ (list), #/exp/<id>/<tab>. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const app = $("#app");

const state = { config: null, data: null, tab: "overview", open: new Set(), pubchemOk: null };

const TABS = [
  ["overview", "Overview"], ["reagents", "Reagents"], ["procedure", "Procedure"], ["log", "Log"],
  ["results", "Results"], ["report", "Report"],
];
const ROLE_LABELS = { reactant: "Reactant", reagent: "Reagent", catalyst: "Catalyst", solvent: "Solvent",
  product: "Product", other: "Other" };
const FORM_LABELS = { neat: "Neat / pure", solution: "Solution (molarity)", wt: "Solution (wt %)" };
const STATUS_LABELS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };
const CHEM_FIELDS = [
  ["name", "Name", "text"], ["cas", "CAS", "text"], ["formula", "Formula", "text"],
  ["mw", "Molar mass (g/mol)", "num"], ["density", "Density (g/mL)", "num"], ["bp", "bp (°C)", "num"],
  ["mp", "mp (°C)", "num"], ["flash_point", "Flash point (°C)", "num"], ["refractive_index", "n<sub>D</sub>", "num"],
  ["smiles", "SMILES", "text"],
];
const SOURCE_PROPS = new Set(["bp", "mp", "density", "flash_point", "refractive_index"]);

// ------------------------------------------------------------------------------------------- helpers
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(v, sig = 3) {
  if (v === null || v === undefined || v === "" || !isFinite(v)) return "";
  const f = Number(v);
  if (f === 0) return "0";
  const decimals = Math.max(0, sig - 1 - Math.floor(Math.log10(Math.abs(f))));
  return f.toFixed(Math.min(decimals, 8));
}
const fixed = (v, d) => (v === null || v === undefined || v === "" ? "" : Number(v).toFixed(d));

/** Parse a number typed by the user; accepts a decimal comma. Returns null for empty, NaN for invalid. */
function parseNum(s) {
  s = String(s ?? "").trim().replace(",", ".");
  if (s === "") return null;
  const f = Number(s);
  return isFinite(f) ? f : NaN;
}

let toastTimer;
function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), error ? 6000 : 2500);
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    let msg = data?.detail ?? `HTTP ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new Error(msg);
  }
  return data;
}

function debounce(fn, ms) {
  let t, last;
  const d = (...args) => { last = args; clearTimeout(t); t = setTimeout(() => { t = null; fn(...last); }, ms); };
  d.flush = () => { if (t) { clearTimeout(t); t = null; return fn(...last); } };
  return d;
}

function localDateTimeValue(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtTime(ts) {
  const d = new Date(ts);
  if (isNaN(d)) return esc(ts);
  const today = new Date().toDateString() === d.toDateString();
  return d.toLocaleString(undefined, today ? { hour: "2-digit", minute: "2-digit" }
    : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const ghsImg = (code) => `<img class="ghs" src="/api/pubchem/ghs/${esc(code)}.svg" alt="${esc(code)}" title="${esc(code)}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'badge',textContent:'${esc(code)}'}))">`;

// ------------------------------------------------------------------------------------------- PubChem status
async function checkHealth() {
  const el = $("#pubchem-status");
  try {
    const h = await api("GET", "/api/health");
    state.pubchemOk = h.pubchem.reachable;
    el.textContent = h.pubchem.reachable ? "PubChem Local connected" : "PubChem Local offline";
    el.className = "pill " + (h.pubchem.reachable ? "ok" : "bad");
    el.title = h.pubchem.reachable ? h.pubchem.url : `${h.pubchem.error}\nManual entry still works.`;
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
    state.tab = TABS.some(([k]) => k === parts[2]) ? parts[2] : "overview";
    if (!state.data || state.data.experiment.id !== id) {
      await flushExp.flush();
      state.open.clear();
      try {
        state.data = await api("GET", `/api/experiments/${id}`);
      } catch (e) {
        app.innerHTML = `<div class="panel">Could not load the experiment: ${esc(e.message)} <a href="#/">Back</a></div>`;
        return;
      }
    }
    renderExperiment();
  } else {
    await flushExp.flush();
    state.data = null;
    renderList();
  }
}

// ------------------------------------------------------------------------------------------- experiment list
async function renderList() {
  document.title = "Lab Notebook";
  app.innerHTML = `<div class="panel"><div class="row"><h2 style="margin:0">Experiments</h2><span class="spacer"></span>
    <button class="btn primary" id="new-exp">+ New experiment</button></div><div id="list" class="empty">Loading…</div></div>`;
  $("#new-exp").onclick = async () => {
    try {
      const d = await api("POST", "/api/experiments", { title: "New experiment" });
      state.data = d;
      location.hash = `#/exp/${d.experiment.id}/overview`;
    } catch (e) { toast(e.message, true); }
  };
  try {
    const { experiments } = await api("GET", "/api/experiments");
    const list = $("#list");
    if (!experiments.length) {
      list.innerHTML = "No experiments yet. Create one to start planning.";
      return;
    }
    list.className = "";
    list.innerHTML = `<ul class="exp-list">${experiments.map((e) => `<li><a href="#/exp/${e.id}/overview">
      <span class="title">${esc(e.title)}</span>
      <span class="muted small">${esc(e.course || "")}</span>
      <span class="muted small">${esc(e.date || "")}</span>
      <span class="status ${esc(e.status)}">${esc(STATUS_LABELS[e.status] || e.status)}</span>
      <span class="muted small">${e.n_reagents} chemicals</span></a></li>`).join("")}</ul>`;
  } catch (e) {
    $("#list").textContent = "Could not load experiments: " + e.message;
  }
}

// ------------------------------------------------------------------------------------------- experiment view
function renderExperiment() {
  const { experiment: exp } = state.data;
  document.title = `${exp.title} · Lab Notebook`;
  app.innerHTML = `
    <div class="exp-head">
      <a href="#/" class="btn icon" title="All experiments">←</a>
      <input class="title" id="exp-title" value="${esc(exp.title)}" aria-label="Title">
      <select id="exp-status" aria-label="Status">${Object.entries(STATUS_LABELS).map(([k, v]) =>
        `<option value="${k}" ${exp.status === k ? "selected" : ""}>${v}</option>`).join("")}</select>
      <span class="saved" id="saved"></span>
    </div>
    <nav class="tabs">${TABS.map(([k, v]) =>
      `<button data-tab="${k}" class="${state.tab === k ? "active" : ""}">${v}</button>`).join("")}</nav>
    <section id="tab"></section>`;
  $("#exp-title").addEventListener("input", (e) => saveExp({ title: e.target.value || "Untitled experiment" }));
  $("#exp-status").addEventListener("change", (e) => saveExp({ status: e.target.value }, true));
  $$(".tabs button").forEach((b) => (b.onclick = () => (location.hash = `#/exp/${exp.id}/${b.dataset.tab}`)));
  ({ overview: renderOverview, reagents: renderReagents, procedure: renderProcedure, log: renderLog,
    results: renderResults, report: renderReport })[state.tab]();
}

const pendingExp = {};
let pendingExpId = null;
const flushExp = debounce(async () => {
  const body = { ...pendingExp }, id = pendingExpId;
  Object.keys(pendingExp).forEach((k) => delete pendingExp[k]);
  if (!id || !Object.keys(body).length) return;
  try {
    const { experiment } = await api("PUT", `/api/experiments/${id}`, body);
    if (state.data?.experiment.id === id) {
      // keep local edits typed while the request was in flight
      state.data.experiment = { ...experiment, ...pendingExp };
      const s = $("#saved");
      if (s) s.textContent = "Saved";
    }
  } catch (e) { toast("Not saved: " + e.message, true); }
}, 700);

function saveExp(fields, now = false) {
  const id = state.data.experiment.id;
  if (pendingExpId !== id) flushExp.flush();
  pendingExpId = id;
  Object.assign(pendingExp, fields);
  Object.assign(state.data.experiment, fields);
  const s = $("#saved");
  if (s) s.textContent = "Saving…";
  flushExp();
  if (now) flushExp.flush();
}

function sectionField(key, label, hint, rows = 6) {
  const exp = state.data.experiment;
  return `<label class="field">${esc(label)}${hint ? ` <span class="small">${esc(hint)}</span>` : ""}
    <textarea data-section="${key}" rows="${rows}">${esc(exp[key] || "")}</textarea></label>`;
}

function bindSections(root = app) {
  $$("textarea[data-section]", root).forEach((t) =>
    t.addEventListener("input", () => saveExp({ [t.dataset.section]: t.value })));
}

function renderOverview() {
  const exp = state.data.experiment;
  $("#tab").innerHTML = `
    <div class="panel"><div class="grid wide">
      <label class="field">Date<input type="date" id="f-date" value="${esc(exp.date || "")}"></label>
      <label class="field">Author<input id="f-author" value="${esc(exp.author || "")}"></label>
      <label class="field">Course / lab<input id="f-course" value="${esc(exp.course || "")}"></label>
    </div></div>
    <div class="panel">
      ${sectionField("objective", "Objective", "What is the purpose of this experiment?", 4)}
      <div style="height:12px"></div>
      ${sectionField("reaction_scheme", "Reaction", "Reaction equation, mechanism notes, conditions (Markdown)", 4)}
    </div>
    <div class="panel row">
      <button class="btn" id="dup">Duplicate as new plan</button>
      <span class="spacer"></span>
      <button class="btn danger" id="del">Delete experiment</button>
    </div>`;
  [["f-date", "date"], ["f-author", "author"], ["f-course", "course"]].forEach(([id, k]) =>
    $("#" + id).addEventListener("input", (e) => saveExp({ [k]: e.target.value })));
  bindSections();
  $("#dup").onclick = async () => {
    try {
      const d = await api("POST", `/api/experiments/${exp.id}/duplicate`);
      state.data = d;
      location.hash = `#/exp/${d.experiment.id}/overview`;
      toast("Copied. Amounts are kept; isolated yields, results and the log are not.");
    } catch (e) { toast(e.message, true); }
  };
  $("#del").onclick = async () => {
    if (!confirm(`Delete “${exp.title}” with all its reagents and log entries? This cannot be undone.`)) return;
    try {
      await api("DELETE", `/api/experiments/${exp.id}`);
      location.hash = "#/";
    } catch (e) { toast(e.message, true); }
  };
}

function renderProcedure() {
  $("#tab").innerHTML = `<div class="panel">
    ${sectionField("procedure", "Procedure", "Planned or performed steps. Markdown: 1. numbered lists, **bold**, …", 18)}
    <p class="small muted">Record what happens during the experiment in the <a href="#/exp/${state.data.experiment.id}/log">Log</a>; each entry is timestamped.</p>
  </div>`;
  bindSections();
}

// ------------------------------------------------------------------------------------------- reagents
function renderReagents() {
  $("#tab").innerHTML = `
    <div class="panel">
      <div class="add-row">
        <div class="ac"><input id="add-q" placeholder="Add chemical: name, CAS, formula or SMILES" autocomplete="off"
          aria-label="Chemical"><ul id="ac-list" class="hidden" role="listbox"></ul></div>
        <select id="add-role" aria-label="Role">${state.config.roles.map((r) =>
          `<option value="${r}">${ROLE_LABELS[r]}</option>`).join("")}</select>
        <button class="btn primary" id="add-btn">Add</button>
      </div>
      <div id="rt"></div>
      <p class="small muted">Type a mass, volume, mmol or equivalents; the other columns are calculated.
        <b>Bold</b> = entered, <span style="color:var(--computed)">blue</span> = calculated. Equivalents are relative to the
        reference (●). The limiting reactant is marked. Click a name for details, forms (solutions, purity) and data sources.</p>
    </div>
    <div class="panel"><h2>Products</h2><div id="pt"></div></div>`;
  setupAutocomplete();
  drawReagentTables();
}

function setupAutocomplete() {
  const input = $("#add-q"), list = $("#ac-list");
  let items = [], active = -1, chosen = null, seq = 0;
  const close = () => { list.classList.add("hidden"); active = -1; };
  const show = () => {
    list.innerHTML = items.map((s, i) => `<li role="option" data-i="${i}" class="${i === active ? "active" : ""}">
      ${esc(s.name)} <span class="sub">CID ${s.cid}</span></li>`).join("");
    list.classList.toggle("hidden", !items.length);
  };
  const fetchSuggestions = debounce(async () => {
    const q = input.value.trim();
    const my = ++seq;
    if (q.length < 2) { items = []; close(); return; }
    try {
      const { suggestions } = await api("GET", `/api/pubchem/autocomplete?q=${encodeURIComponent(q)}&limit=10`);
      if (my !== seq) return;
      items = suggestions;
      active = -1;
      show();
    } catch { items = []; close(); }
  }, 180);
  input.addEventListener("input", () => { chosen = null; fetchSuggestions(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && items.length) { active = (active + 1) % items.length; show(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && items.length) { active = (active - 1 + items.length) % items.length; show(); e.preventDefault(); }
    else if (e.key === "Escape") close();
    else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && !list.classList.contains("hidden")) pick(items[active]);
      else add();
    }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); pick(items[Number(li.dataset.i)]); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
  function pick(s) { chosen = s; input.value = s.name; close(); add(); }
  async function add() {
    const q = input.value.trim();
    if (!q) return;
    seq++;
    close();
    const role = $("#add-role").value;
    const body = chosen ? { cid: chosen.cid, role } : { query: q, role };
    $("#add-btn").disabled = true;
    try {
      const d = await api("POST", `/api/experiments/${state.data.experiment.id}/reagents`, body);
      state.data = d;
      if (d.warning) { toast(d.warning, true); state.open.add(d.reagent_id); }
      input.value = "";
      chosen = null;
      drawReagentTables();
      input.focus();
    } catch (e) { toast(e.message, true); }
    finally { $("#add-btn").disabled = false; }
  }
  $("#add-btn").onclick = add;
}

function amountInput(r, field, value, digits) {
  const c = r.calc || {};
  const entered = r.basis === field;
  const disabled = field === "equiv" && r.id === state.data.stoich.reference_id && !entered;
  // a typed value is shown as typed; calculated ones are rounded
  const shown = entered ? String(r.basis_value) : value == null ? "" : digits ? fixed(value, digits) : fmt(value, 4);
  return `<input class="amt ${entered ? "entered" : "computed"}" inputmode="decimal" data-rid="${r.id}" data-amt="${field}"
    data-key="amt-${r.id}-${field}" value="${esc(shown)}"
    ${disabled ? "disabled title='Reference reagent: 1 equiv'" : ""} aria-label="${field}">`;
}

function nameCell(r) {
  const c = r.calc || {};
  const sub = [r.cas, r.formula].filter(Boolean).map(esc).join(" · ");
  const form = r.form === "solution" && r.concentration_m ? `${fmt(r.concentration_m)} M`
    : r.form === "wt" && r.wt_percent ? `${fmt(r.wt_percent)} wt%`
    : r.purity && r.purity < 100 ? `${fmt(r.purity)}%` : "";
  return `<button class="linklike cname" data-toggle="${r.id}">${esc(r.name || "?")}</button>
    ${form ? `<span class="badge">${esc(form)}</span>` : ""}
    ${c.is_limiting ? '<span class="badge lim">limiting</span>' : ""}
    <div class="sub">${sub} ${(r.pictograms || []).map(ghsImg).join("")}</div>
    ${(c.warnings || []).length ? `<div class="warnings">⚠ ${c.warnings.map(esc).join(" ")}</div>` : ""}`;
}

function roleSelect(r) {
  return `<select class="role" data-rid="${r.id}" data-field="role" data-key="role-${r.id}" aria-label="Role">${
    state.config.roles.map((x) => `<option value="${x}" ${r.role === x ? "selected" : ""}>${ROLE_LABELS[x]}</option>`).join("")}</select>`;
}

function drawReagentTables() {
  const act = document.activeElement;
  const focus = act?.dataset?.key;
  // text typed into the focused field that has not been committed yet survives the re-render
  const typed = focus && act.tagName === "INPUT" && act.value !== act.defaultValue ? act.value : null;
  const reagents = state.data.reagents;
  const inputs = reagents.filter((r) => r.role !== "product");
  const products = reagents.filter((r) => r.role === "product");
  const refId = state.data.stoich.reference_id;

  $("#rt").innerHTML = !inputs.length ? `<div class="empty">No chemicals yet.</div>` : `<div class="table-wrap"><table class="rt">
    <thead><tr><th title="Reference for equivalents">Ref</th><th>Compound</th><th>Role</th><th class="num">MW</th>
      <th class="num">Mass (g)</th><th class="num">Volume (mL)</th><th class="num">mmol</th><th class="num">equiv</th>
      <th class="num">bp / mp (°C)</th><th></th></tr></thead>
    <tbody>${inputs.map((r) => `
      <tr class="${r.calc?.is_limiting ? "limiting" : ""}">
        <td><input type="radio" name="ref" data-ref="${r.id}" ${r.id === refId ? "checked" : ""} title="Use as reference (1 equiv)"></td>
        <td>${nameCell(r)}</td>
        <td>${roleSelect(r)}</td>
        <td class="num">${fixed(r.mw, 2)}</td>
        <td class="num">${amountInput(r, "mass", r.calc?.mass_g)}</td>
        <td class="num">${amountInput(r, "volume", r.calc?.volume_ml)}</td>
        <td class="num">${amountInput(r, "mmol", r.calc?.mmol)}</td>
        <td class="num">${amountInput(r, "equiv", r.calc?.equiv, 2)}</td>
        <td class="num small">${[r.bp, r.mp].map((v) => (v === null || v === undefined ? "–" : fixed(v, 0))).join(" / ")}</td>
        <td><button class="btn icon danger" data-del="${r.id}" title="Remove">✕</button></td>
      </tr>${state.open.has(r.id) ? `<tr class="detail"><td colspan="10">${detailPanel(r)}</td></tr>` : ""}`).join("")}
    </tbody></table></div>`;

  $("#pt").innerHTML = !products.length
    ? `<div class="empty">Add the product with role “Product” to calculate the theoretical and percent yield.</div>`
    : `<div class="table-wrap"><table class="rt">
    <thead><tr><th>Compound</th><th>Role</th><th class="num">MW</th><th class="num" title="Stoichiometric coefficient">Coef.</th>
      <th class="num">Theoretical yield</th><th class="num">Isolated (g)</th><th class="num">mmol</th><th class="num">Yield</th><th></th></tr></thead>
    <tbody>${products.map((r) => {
      const c = r.calc || {};
      return `<tr>
        <td>${nameCell(r)}</td><td>${roleSelect(r)}</td>
        <td class="num">${fixed(r.mw, 2)}</td>
        <td class="num"><input class="amt" style="width:56px" inputmode="decimal" data-rid="${r.id}" data-field="coefficient" data-num="1"
          data-key="coef-${r.id}" value="${esc(r.coefficient ?? 1)}"></td>
        <td class="num">${c.theoretical_mass_g != null ? `${fmt(c.theoretical_mass_g)} g<div class="sub">${fmt(c.theoretical_mmol)} mmol</div>` : "–"}</td>
        <td class="num"><input class="amt entered" inputmode="decimal" data-rid="${r.id}" data-field="actual_mass_g" data-num="1"
          data-key="act-${r.id}" value="${r.actual_mass_g == null ? "" : esc(r.actual_mass_g)}" aria-label="Isolated mass (g)"></td>
        <td class="num">${fmt(c.mmol)}</td>
        <td class="num"><b>${c.percent_yield != null ? c.percent_yield.toFixed(1) + " %" : "–"}</b></td>
        <td><button class="btn icon danger" data-del="${r.id}" title="Remove">✕</button></td>
      </tr>${state.open.has(r.id) ? `<tr class="detail"><td colspan="9">${detailPanel(r)}</td></tr>` : ""}`;
    }).join("")}</tbody></table></div>`;

  bindReagentEvents();
  if (focus) {
    const el = $(`[data-key="${CSS.escape(focus)}"]`);
    if (el) {
      if (typed !== null) el.value = typed;
      el.focus();
      if (typed === null && el.select && el.classList.contains("amt")) el.select();
    }
  }
}

function srcBadge(r, k) {
  const s = (r.sources || {})[k];
  if (!s) return "";
  const revert = s === "manual" && r.cid ? ` <button class="linklike small" data-revert="${r.id}" data-field="${k}" title="Restore the PubChem value">↺</button>` : "";
  return `<span class="src ${s}" title="${s === "pubchem" ? "From PubChem Local" : "Entered or edited by you"}">${s === "pubchem" ? "PubChem" : "edited"}</span>${revert}`;
}

function detailPanel(r) {
  const formFields = r.form === "solution"
    ? numField(r, "concentration_m", "Concentration (M)") + numField(r, "solution_density", "Solution density (g/mL), optional")
    : r.form === "wt"
      ? numField(r, "wt_percent", "Weight percent (%)") + numField(r, "solution_density", "Solution density (g/mL)")
      : numField(r, "purity", "Purity (%)", "100");
  return `<div class="detail-grid"><div>
    <div class="grid">
      ${CHEM_FIELDS.map(([k, label, type]) => `<label class="field"><span>${label} ${srcBadge(r, k)}
        ${SOURCE_PROPS.has(k) && r.cid ? `<button class="linklike small" data-sources="${r.cid}" data-prop="${k}" data-rid="${r.id}">sources</button>` : ""}</span>
        <input data-rid="${r.id}" data-field="${k}" ${type === "num" ? 'data-num="1" inputmode="decimal"' : ""} data-key="d-${r.id}-${k}"
          value="${esc(r[k] ?? "")}"></label>`).join("")}
    </div>
    <div class="sources" id="src-${r.id}"></div>
    <div class="grid" style="margin-top:10px">
      <label class="field">Form<select data-rid="${r.id}" data-field="form" data-key="d-${r.id}-form">${state.config.forms.map((f) =>
        `<option value="${f}" ${r.form === f ? "selected" : ""}>${FORM_LABELS[f]}</option>`).join("")}</select></label>
      ${formFields}
      ${r.role !== "product" ? numField(r, "coefficient", "Stoich. coefficient", "1") : ""}
    </div>
    <label class="field" style="margin-top:10px">Notes (grade, supplier, lot, …)
      <input data-rid="${r.id}" data-field="notes" data-key="d-${r.id}-notes" value="${esc(r.notes || "")}"></label>
    ${r.cid ? `<div class="row small" style="margin-top:10px"><button class="btn" data-revert="${r.id}">↺ Reload all values from PubChem Local</button>
      <a href="${esc(r.pubchem_url || `https://pubchem.ncbi.nlm.nih.gov/compound/${r.cid}`)}" target="_blank" rel="noopener">PubChem CID ${r.cid}</a></div>` : ""}
  </div><div>
    ${r.cid ? `<img class="struct" src="/api/pubchem/compound/${r.cid}/structure.svg?width=280&height=200" alt="Structure of ${esc(r.name)}" onerror="this.remove()">` : ""}
    ${r.signal_word ? `<div><b class="${r.signal_word === "Danger" ? "warnings" : ""}">${esc(r.signal_word)}</b> ${(r.pictograms || []).map(ghsImg).join("")}</div>` : ""}
    ${(r.hazard_statements || []).length ? `<ul class="hz">${r.hazard_statements.map((h) => `<li>${esc(h.replace(/\s*\[[^\]]*\]\s*$/, ""))}</li>`).join("")}</ul>`
      : '<div class="small muted">No GHS hazard data.</div>'}
  </div></div>`;
}

function numField(r, k, label, placeholder = "") {
  return `<label class="field">${esc(label)}<input data-rid="${r.id}" data-field="${k}" data-num="1" inputmode="decimal"
    data-key="d-${r.id}-${k}" value="${esc(r[k] ?? "")}" placeholder="${esc(placeholder)}"></label>`;
}

async function updateReagent(rid, body) {
  try {
    state.data = await api("PUT", `/api/reagents/${rid}`, body);
    drawReagentTables();
  } catch (e) { toast(e.message, true); drawReagentTables(); }
}

function bindReagentEvents() {
  const tab = $("#tab");
  $$("[data-toggle]", tab).forEach((b) => (b.onclick = () => {
    const id = Number(b.dataset.toggle);
    state.open.has(id) ? state.open.delete(id) : state.open.add(id);
    drawReagentTables();
  }));
  $$("[data-del]", tab).forEach((b) => (b.onclick = async () => {
    const r = state.data.reagents.find((x) => x.id === Number(b.dataset.del));
    if (!confirm(`Remove ${r?.name || "this chemical"}?`)) return;
    try { state.data = await api("DELETE", `/api/reagents/${b.dataset.del}`); drawReagentTables(); }
    catch (e) { toast(e.message, true); }
  }));
  $$("[data-ref]", tab).forEach((b) => (b.onchange = () => updateReagent(Number(b.dataset.ref), { is_reference: true })));
  $$("input[data-amt]", tab).forEach((inp) => inp.addEventListener("change", () => {
    const v = parseNum(inp.value);
    const rid = Number(inp.dataset.rid);
    const r = state.data.reagents.find((x) => x.id === rid);
    if (Number.isNaN(v) || (v !== null && v < 0)) { toast("Enter a positive number.", true); drawReagentTables(); return; }
    if (v === null) {
      if (r.basis === inp.dataset.amt) updateReagent(rid, { basis: null, basis_value: null });
      else drawReagentTables();
      return;
    }
    updateReagent(rid, { basis: inp.dataset.amt, basis_value: v });
  }));
  $$("[data-field]", tab).forEach((inp) => inp.addEventListener("change", () => {
    const rid = Number(inp.dataset.rid);
    let v = inp.value;
    if (inp.dataset.num) {
      v = parseNum(v);
      if (Number.isNaN(v)) { toast("Enter a number.", true); drawReagentTables(); return; }
    } else if (inp.tagName !== "SELECT") {
      v = v.trim() || null;
    }
    updateReagent(rid, { [inp.dataset.field]: v });
  }));
  $$("[data-revert]", tab).forEach((b) => (b.onclick = async () => {
    const body = b.dataset.field ? { fields: [b.dataset.field] } : {};
    if (!b.dataset.field && !confirm("Replace all chemical data of this row (including your edits) with the PubChem Local values?")) return;
    try { state.data = await api("POST", `/api/reagents/${b.dataset.revert}/refresh`, body); drawReagentTables(); }
    catch (e) { toast(e.message, true); }
  }));
  $$("[data-sources]", tab).forEach((b) => (b.onclick = async (e) => {
    e.preventDefault();
    const box = $(`#src-${b.dataset.rid}`);
    box.textContent = "Loading sources…";
    try {
      const { properties } = await api("GET", `/api/pubchem/compound/${b.dataset.sources}/sources`);
      const p = properties[b.dataset.prop];
      if (!p) { box.textContent = "PubChem Local has no source values for this property."; return; }
      box.innerHTML = `<b>${esc(b.dataset.prop)}</b>: median ${fmt(p.value, 4)} ${esc(p.unit || "")} of ${p.n} standard-condition values
        (range ${fmt(p.min, 4)}–${fmt(p.max, 4)}). <button class="linklike" onclick="this.parentElement.innerHTML=''">hide</button>
        <table>${(p.sources || []).map((s) => `<tr class="${s.standard ? "" : "muted"}"><td>${esc(s.raw)}</td><td>${esc(s.source)}</td>
          <td>${s.standard ? "" : "excluded"}</td></tr>`).join("")}</table>`;
    } catch (err) { box.textContent = err.message; }
  }));
}

// ------------------------------------------------------------------------------------------- log
const QUICK = ["Started addition", "Addition complete", "Heating to reflux", "Color change", "Precipitate formed",
  "Gas evolution", "TLC taken", "Reaction quenched", "Workup started", "Product isolated"];
const UNITS = ["°C", "g", "mg", "mL", "min", "h", "Rf", "%", "mmHg", "pH"];

function renderLog() {
  $("#tab").innerHTML = `<div class="panel">
    <form class="log-form" id="log-form" autocomplete="off">
      <select id="l-kind" aria-label="Type"><option value="observation">Observation</option><option value="note">Note</option>
        <option value="measurement">Measurement</option></select>
      <input class="text" id="l-text" placeholder="What happened?" aria-label="Entry">
      <input id="l-value" placeholder="Value" inputmode="decimal" aria-label="Value">
      <input id="l-unit" placeholder="Unit" list="units" aria-label="Unit">
      <button class="btn primary">Add</button>
      <datalist id="units">${UNITS.map((u) => `<option value="${esc(u)}">`).join("")}</datalist>
    </form>
    <div class="quick">${QUICK.map((q) => `<button class="btn" data-quick="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <ul class="log-list" id="log-list"></ul>
  </div>`;
  $("#log-form").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("#l-text").value.trim(), value = $("#l-value").value.trim();
    if (!text && !value) return;
    await addEntry({ kind: $("#l-kind").value, text, value: value || null, unit: $("#l-unit").value.trim() || null });
    $("#l-text").value = $("#l-value").value = "";
    $("#l-text").focus();
  };
  $$("[data-quick]").forEach((b) => (b.onclick = () => {
    $("#l-text").value = b.dataset.quick;
    $("#l-text").focus();
  }));
  drawLog();
}

async function addEntry(body) {
  try {
    const { entry } = await api("POST", `/api/experiments/${state.data.experiment.id}/entries`, body);
    state.data.entries.push(entry);
    drawLog();
  } catch (e) { toast(e.message, true); }
}

function drawLog() {
  const list = $("#log-list");
  const entries = [...state.data.entries].sort((a, b) => (a.ts < b.ts ? 1 : -1));
  list.innerHTML = !entries.length ? `<li class="empty" style="display:block">No entries yet. Everything you add is timestamped.</li>`
    : entries.map((e) => `<li data-eid="${e.id}">
      <span class="small muted" title="${esc(e.ts)}">${fmtTime(e.ts)}</span>
      <span class="kind ${esc(e.kind)}">${esc(e.kind)}</span>
      <span class="lt">${esc(e.text)} ${e.value ? `<b>${esc(e.value)} ${esc(e.unit || "")}</b>` : ""}</span>
      <span class="row"><button class="btn icon" data-edit="${e.id}" title="Edit">✎</button>
        <button class="btn icon danger" data-edel="${e.id}" title="Delete">✕</button></span></li>`).join("");
  $$("[data-edel]", list).forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this entry?")) return;
    try {
      await api("DELETE", `/api/entries/${b.dataset.edel}`);
      state.data.entries = state.data.entries.filter((e) => e.id !== Number(b.dataset.edel));
      drawLog();
    } catch (e) { toast(e.message, true); }
  }));
  $$("[data-edit]", list).forEach((b) => (b.onclick = () => editEntry(Number(b.dataset.edit))));
}

function editEntry(id) {
  const e = state.data.entries.find((x) => x.id === id);
  const li = $(`li[data-eid="${id}"]`);
  const d = new Date(e.ts);
  li.innerHTML = `<input type="datetime-local" class="e-ts" value="${isNaN(d) ? "" : localDateTimeValue(d)}">
    <select class="e-kind">${["observation", "note", "measurement"].map((k) => `<option ${e.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select>
    <span class="lt row"><input class="e-text" style="flex:1" value="${esc(e.text)}"><input class="e-value" style="width:80px" value="${esc(e.value || "")}">
      <input class="e-unit" style="width:64px" list="units" value="${esc(e.unit || "")}"></span>
    <span class="row"><button class="btn primary e-save">Save</button><button class="btn e-cancel">Cancel</button></span>`;
  $(".e-cancel", li).onclick = drawLog;
  $(".e-save", li).onclick = async () => {
    const tsVal = $(".e-ts", li).value;
    const body = { kind: $(".e-kind", li).value, text: $(".e-text", li).value.trim(),
      value: $(".e-value", li).value.trim() || null, unit: $(".e-unit", li).value.trim() || null };
    if (tsVal) body.ts = isoWithOffset(new Date(tsVal));
    try {
      const { entry } = await api("PUT", `/api/entries/${id}`, body);
      Object.assign(e, entry);
      drawLog();
    } catch (err) { toast(err.message, true); }
  };
}

function isoWithOffset(d) {
  const off = -d.getTimezoneOffset(), sign = off >= 0 ? "+" : "-", p = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${localDateTimeValue(d)}:00${sign}${p(off / 60)}:${p(off % 60)}`;
}

// ------------------------------------------------------------------------------------------- results
function renderResults() {
  const products = state.data.reagents.filter((r) => r.role === "product");
  $("#tab").innerHTML = `<div class="panel"><h2>Yield</h2>${!products.length
    ? `<div class="empty">No product yet. Add it on the <a href="#/exp/${state.data.experiment.id}/reagents">Reagents</a> tab with role “Product”.</div>`
    : products.map((r) => {
      const c = r.calc || {};
      return `<div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)"><b style="min-width:180px">${esc(r.name)}</b>
        <span>Theoretical: ${c.theoretical_mass_g != null ? `${fmt(c.theoretical_mass_g)} g (${fmt(c.theoretical_mmol)} mmol)` : "–"}</span>
        <label class="row">Isolated <input class="amt" style="width:90px" inputmode="decimal" data-actual="${r.id}" value="${r.actual_mass_g ?? ""}"> g</label>
        <b>${c.percent_yield != null ? c.percent_yield.toFixed(1) + " %" : ""}</b></div>`;
    }).join("")}</div>
    <div class="panel">
      ${sectionField("results", "Results", "Characterization: appearance, mp, TLC Rf, IR/NMR peaks, … (Markdown)", 8)}
      <div style="height:12px"></div>${sectionField("discussion", "Discussion", "", 8)}
      <div style="height:12px"></div>${sectionField("conclusion", "Conclusion", "", 4)}
      <div style="height:12px"></div>${sectionField("references", "References", "PubChem citations for every linked chemical are added to the report automatically.", 4)}
    </div>`;
  bindSections();
  $$("[data-actual]").forEach((inp) => inp.addEventListener("change", async () => {
    const v = parseNum(inp.value);
    if (Number.isNaN(v)) { toast("Enter a number.", true); return; }
    try {
      state.data = await api("PUT", `/api/reagents/${inp.dataset.actual}`, { actual_mass_g: v });
      renderResults();
    } catch (e) { toast(e.message, true); }
  }));
}

// ------------------------------------------------------------------------------------------- report
function renderReport() {
  const id = state.data.experiment.id;
  $("#tab").innerHTML = `<div class="panel row">
      <a class="btn primary" href="/api/experiments/${id}/report.pdf" target="_blank" rel="noopener">⬇ PDF</a>
      <a class="btn" href="/api/experiments/${id}/report.md?download=true">⬇ Markdown</a>
      <a class="btn" href="/api/experiments/${id}/report.html" target="_blank" rel="noopener">Open print view</a>
      <span class="spacer"></span><button class="btn" id="reload">↻ Refresh preview</button>
    </div>
    <iframe class="preview" id="preview" title="Report preview" src="/api/experiments/${id}/report.html"></iframe>`;
  $("#reload").onclick = () => ($("#preview").src = $("#preview").src);
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
  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", (e) => {
    if (Object.keys(pendingExp).length) { e.preventDefault(); e.returnValue = ""; }
  });
  route();
})();
