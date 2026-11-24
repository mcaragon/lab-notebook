/* Bench tab: reagent checklist, procedure and log.
   Procedure rows are grouped into phases (setup, reaction, workup, purification, analysis and the experiment's own);
   phases without rows are hidden. Procedure rows sit next to the log on wide screens (each log entry belongs to the procedure step that was
   highlighted when it was logged); on phones the entries are listed under their step. The log runs oldest to
   newest, like the procedure, with the composer underneath. */
import { $, $$, esc, fmt, fmtDur, clockTime, isoWithOffset, localDateTimeValue, parseDuration, parseNum, preserveFocus, toast } from "./util.js";
import { state, mutate, expId, multiStage, labelOf, reagentById } from "./state.js";
import { resizer } from "./resize.js";

const wide = window.matchMedia("(min-width: 1000px)");
wide.addEventListener("change", () => state.data && state.tab === "bench" && renderProcedure($("#sec-procedure")));
const editing = new Set();      // procedure rows in edit mode
let addPhase = null;            // phase new procedure rows go to (default: that of the current row)
let editingEntry = null;
let composer = { action: null, values: {} };
let checklistOpen = !window.matchMedia("(max-width: 700px)").matches;
let chipsOpen = false;   // phones: the action chips stay folded until asked for
const chipsHidden = () => !wide.matches && !chipsOpen && !composer.action;

// Timer is a composer action handled by the client (it creates a timer, which logs its own start)
const TIMER_ACTION = {
  label: "Timer",
  fields: [
    { name: "label", label: "What (type @ for a chemical)", type: "text", required: true, mention: true,
      suggest: ["Addition of ", "Stirring", "Reflux", "Heating", "Cooling", "Drying", "Crystallization"] },
    { name: "kind", label: "Type", type: "select", options: ["stopwatch", "countdown"] },
    { name: "duration", label: "Countdown (e.g. 30 min)", type: "duration" },
  ],
};
const actionsCfg = () => ({ ...state.config.actions, timer: TIMER_ACTION });
const ACTION_ORDER = ["add", "weigh", "timer", "observation", "temperature", "stir", "quench", "extract", "wash", "dry",
  "filter", "concentrate", "tlc", "purify", "isolate", "measure", "note"];

/** Open the composer on an action (used by the bench bar). */
export function openComposer(action) {
  composer = { action, values: action === "add" ? { unit: "g", mode: "in one portion" } : action === "timer" ? { kind: "stopwatch" } : {} };
  renderProcedure($("#sec-procedure"));
  const first = $("#action-form [data-af]");
  first?.scrollIntoView({ behavior: "smooth", block: "center" });
  first?.focus({ preventScroll: true });
}

export function focusQuickLog() {
  const q = $("#quick-text");
  q?.scrollIntoView({ behavior: "smooth", block: "center" });
  q?.focus({ preventScroll: true });
}

// ------------------------------------------------------------------------------------------- checklist
export function renderChecklist(root) {
  preserveFocus(root, () => {
    const d = state.data;
    const rows = d.reagents.filter((r) => r.role !== "product");
    const prods = d.reagents.filter((r) => r.role === "product");
    if (!rows.length && !prods.length) {
      root.innerHTML = `<div class="panel empty">Add reagents on the <a href="#/exp/${expId()}/plan">Plan</a> tab first.</div>`;
      return;
    }
    const done = rows.filter((r) => r.actual_value != null).length;
    const stepName = (r) => (multiStage() && r.role !== "product" ? `<span class="badge">stage ${d.steps.findIndex((s) => s.id === r.step_id) + 1}</span>` : "");
    root.innerHTML = `<div class="panel checklist">
      <button class="row cl-head linklike" id="cl-toggle" aria-expanded="${checklistOpen}">
        <h2>Reagents</h2><span class="hint">${done} of ${rows.length} measured · type what you actually weighed or measured</span>
        <span class="spacer"></span><span aria-hidden="true">${checklistOpen ? "▾" : "▸"}</span></button>
      ${checklistOpen ? `<div class="cl-grid">${rows.map((r) => clRow(r, stepName(r))).join("")}
        ${prods.map((r) => clProduct(r, stepName(r))).join("")}</div>` : ""}
    </div>`;
    $("#cl-toggle", root).onclick = () => { checklistOpen = !checklistOpen; renderChecklist(root); };
    $$("input[data-cl-actual]", root).forEach((inp) => inp.addEventListener("change", () => {
      const v = parseNum(inp.value);
      if (Number.isNaN(v) || (v !== null && v < 0)) { toast("Enter a positive number.", true); renderChecklist(root); return; }
      mutate("PUT", `/api/reagents/${inp.dataset.clActual}`, { actual_basis: v === null ? null : inp.dataset.unit, actual_value: v }).catch(() => {});
    }));
    $$("[data-cl-unit]", root).forEach((b) => (b.onclick = () => {
      const r = reagentById(b.dataset.clUnit);
      const next = b.dataset.unit === "volume" ? "mass" : "volume";
      if (r.actual_value != null) mutate("PUT", `/api/reagents/${r.id}`, { actual_basis: next }).catch(() => {});
      else { b.dataset.unit = next; b.textContent = next === "volume" ? "mL" : "g"; b.previousElementSibling.dataset.unit = next; }
    }));
    $$("input[data-cl-iso]", root).forEach((inp) => inp.addEventListener("change", () => {
      const v = parseNum(inp.value);
      if (Number.isNaN(v)) { toast("Enter a number.", true); return; }
      mutate("PUT", `/api/reagents/${inp.dataset.clIso}`, { actual_mass_g: v }).catch(() => {});
    }));
  });
}

function plannedText(r) {
  const c = r.calc || {};
  const liquid = r.form !== "neat" || ["solvent", "workup"].includes(r.role) || r.basis === "volume";
  const amt = liquid && c.volume_ml != null ? `${fmt(c.volume_ml)} mL` : c.mass_g != null ? `${fmt(c.mass_g)} g` : c.volume_ml != null ? `${fmt(c.volume_ml)} mL` : "";
  const extra = [c.mmol != null && !["solvent", "workup"].includes(r.role) ? `${fmt(c.mmol)} mmol` : "",
    c.equiv != null && !["solvent", "workup"].includes(r.role) ? `${fmt(c.equiv, 2)} eq` : ""].filter(Boolean).join(" · ");
  return amt ? `${amt}${extra ? ` <span class="sub">${extra}</span>` : ""}` : '<span class="sub">no plan</span>';
}

function clRow(r, step) {
  const c = r.calc || {};
  const liquid = r.form !== "neat" || ["solvent", "workup"].includes(r.role) || (r.mp != null && r.mp < 25);
  const unit = r.actual_basis || (r.basis === "mass" ? "mass" : r.basis === "volume" ? "volume" : liquid ? "volume" : "mass");
  const dev = c.deviation_pct;
  return `<div class="cl-row role-${esc(r.role)} ${r.actual_value != null ? "measured" : ""}">
    <span class="cl-check" aria-hidden="true">${r.actual_value != null ? "✓" : "○"}</span>
    <span class="cl-name">${esc(r.name)} ${step}${r.stock ? `<span class="cl-stock">📦 ${esc(r.stock.supplier || "stockroom")}${r.stock.lot ? ` · lot ${esc(r.stock.lot)}` : ""}${r.stock.location ? ` · ${esc(r.stock.location)}` : ""}</span>` : ""}</span>
    <span class="cl-plan">${plannedText(r)}</span>
    <span class="cl-act"><span class="act-in"><input class="amt entered" inputmode="decimal" data-cl-actual="${r.id}" data-unit="${unit}" data-key="cl-${r.id}"
      value="${r.actual_value == null ? "" : esc(r.actual_value)}" placeholder="actual" aria-label="Actual amount of ${esc(r.name)}">
      <button class="unit-btn" data-cl-unit="${r.id}" data-unit="${unit}" title="Switch between g and mL">${unit === "volume" ? "mL" : "g"}</button></span>
      ${dev != null ? `<span class="dev ${Math.abs(dev) < 0.05 ? "" : dev < 0 ? "neg" : "pos"}">${dev >= 0 ? "+" : ""}${dev.toFixed(1)}%</span>` : ""}</span>
  </div>`;
}

function clProduct(r, step) {
  const c = r.calc || {};
  return `<div class="cl-row prod role-product ${r.actual_mass_g != null ? "measured" : ""}">
    <span class="cl-check" aria-hidden="true">${r.actual_mass_g != null ? "✓" : "○"}</span>
    <span class="cl-name">${esc(r.name)} <span class="badge">product</span> ${step}</span>
    <span class="cl-plan">${c.theoretical_mass_g != null ? `theor. ${fmt(c.theoretical_mass_g)} g` : ""}</span>
    <span class="cl-act"><span class="act-in"><input class="amt entered" inputmode="decimal" data-cl-iso="${r.id}" data-key="cliso-${r.id}"
      value="${r.actual_mass_g ?? ""}" placeholder="isolated" aria-label="Isolated mass of ${esc(r.name)}"><span class="unit-btn">g</span></span>
      ${c.percent_yield != null ? `<span class="yield">${c.percent_yield.toFixed(1)}%</span>` : ""}</span>
  </div>`;
}

// ------------------------------------------------------------------------------------------- procedure & log
export function renderProcedure(root) {
  preserveFocus(root, () => draw(root));
}

function draw(root) {
  const d = state.data;
  const proc = d.procedure;
  if (!state.currentProc && proc.length) state.currentProc = (proc.find((p) => !p.done_at) || proc[proc.length - 1]).id;
  const isWide = wide.matches;
  const logBox = $(".pl-log .log-scroll", root);
  const atBottom = !logBox || logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;
  // Keep each pane where the reader left it across the redraw (the log still follows new entries when at the bottom).
  const procTop = $(".pl-proc", root)?.scrollTop || 0, logTop = logBox?.scrollTop || 0;
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Procedure &amp; log</h2><span class="spacer"></span>
      <span class="hint">Tap a step to make it current; new log entries attach to it. Type <b>@</b> for a chemical.</span></div>
    <div class="pl ${isWide ? "wide" : "narrow"}">
      <div class="pl-proc">
        ${phaseLists(proc, !isWide)}
        <div class="proc-add"><textarea id="proc-new" rows="2" data-key="proc-new" placeholder="Add a step… (Enter to add, Shift+Enter for a new line, @ for chemicals)"></textarea>
          <div class="proc-add-side"><select id="proc-phase" data-key="proc-phase" aria-label="Phase of the new step">
            ${d.phases.map((ph) => `<option value="${esc(ph.key)}" ${ph.key === newRowPhase() ? "selected" : ""}>${esc(ph.label)}</option>`).join("")}
            <option value="__new">New phase…</option></select>
          <button class="btn" id="proc-add-btn">Add step</button></div></div>
        ${!isWide ? orphanLog() : ""}
      </div>
      ${isWide ? resizer("--log-w", "next", 280, 900, "Resize the log") : ""}
      ${isWide ? `<div class="pl-log"><div class="log-scroll"><ol class="log-list">${d.entries.map(entryRow).join("") || '<li class="empty">No entries yet. Everything you log is timestamped.</li>'}</ol></div>
        ${composerHtml()}</div>` : ""}
    </div>
    ${!isWide ? `<div class="composer-phone">${composerHtml()}</div>` : ""}
  </div>`;
  bind(root);
  const box = $(".pl-log .log-scroll", root);
  if (box) box.scrollTop = atBottom ? box.scrollHeight : logTop;
  const pp = $(".pl-proc", root);
  if (pp) pp.scrollTop = procTop;
}

/** Phase of a new procedure row: the one picked last, else the current row's, else Reaction. */
function newRowPhase() {
  const keys = state.data.phases.map((p) => p.key);
  if (addPhase && keys.includes(addPhase)) return addPhase;
  const cur = state.data.procedure.find((p) => p.id === state.currentProc);
  return cur?.phase || "reaction";
}

function phaseLists(proc, nested) {
  if (!proc.length && !state.data.phases.some((ph) => ph.custom)) return '<ol class="proc-list"></ol>';
  let n = 0;
  return state.data.phases.map((ph, k) => {
    const rows = proc.filter((p) => p.phase === ph.key);
    if (!rows.length && !ph.custom) return "";
    const start = n;
    n += rows.length;
    const tools = ph.custom ? `<span class="ph-tools">
      <button class="btn icon" data-ph-move="${esc(ph.key)}" data-dir="-1" title="Move phase up" aria-label="Move phase up" ${k === 0 ? "disabled" : ""}>↑</button>
      <button class="btn icon" data-ph-move="${esc(ph.key)}" data-dir="1" title="Move phase down" aria-label="Move phase down" ${k === state.data.phases.length - 1 ? "disabled" : ""}>↓</button>
      <button class="btn icon" data-ph-rename="${esc(ph.key)}" title="Rename phase" aria-label="Rename phase">✎</button>
      <button class="btn icon danger" data-ph-del="${esc(ph.key)}" title="Remove phase (its steps move to Reaction)" aria-label="Remove phase">✕</button></span>` : "";
    return `<div class="phase ph-${esc(ph.custom ? "custom" : ph.key)}" data-phase="${esc(ph.key)}">
      <h4 class="phase-h"><span>${esc(ph.label)}</span><span class="ph-count">${rows.length || ""}</span>${tools}</h4>
      ${rows.length ? `<ol class="proc-list" start="${start + 1}">${rows.map((p, i) => procRow(p, start + i, nested)).join("")}</ol>`
        : '<div class="ph-empty">No steps yet: pick this phase when you add one.</div>'}</div>`;
  }).join("");
}

function procRow(p, i, nested) {
  const cur = state.currentProc === p.id;
  const entries = state.data.entries.filter((e) => e.procedure_id === p.id);
  const ed = editing.has(p.id);
  return `<li class="proc ${cur ? "current" : ""} ${p.done_at ? "done" : ""}" data-pid="${p.id}">
    <div class="proc-main">
      <label class="chk" title="${p.done_at ? "Done " + esc(clockTime(p.done_at)) : "Mark done"}"><input type="checkbox" data-done="${p.id}" ${p.done_at ? "checked" : ""} aria-label="Step ${i + 1} done"></label>
      <span class="proc-no">${i + 1}</span>
      <div class="proc-body">
        ${ed ? `<textarea class="proc-text" data-ptext="${p.id}" data-key="pt-${p.id}" rows="2">${esc(p.text)}</textarea>
          <input class="proc-notes" data-pnotes="${p.id}" data-key="pn-${p.id}" value="${esc(p.notes || "")}" placeholder="Notes for this step (cautions, tips)">
          <div class="row small">
            <select data-pphase="${p.id}" aria-label="Phase">${state.data.phases.map((ph) =>
              `<option value="${esc(ph.key)}" ${ph.key === p.phase ? "selected" : ""}>${esc(ph.label)}</option>`).join("")}</select>
            <button class="btn icon" data-move="${p.id}" data-dir="-1" title="Move up" aria-label="Move up">↑</button>
            <button class="btn icon" data-move="${p.id}" data-dir="1" title="Move down" aria-label="Move down">↓</button>
            <span class="spacer"></span>
            <button class="btn small danger" data-pdel="${p.id}">Delete</button>
            <button class="btn small primary" data-pdone-edit="${p.id}">Done</button>
          </div>`
        : `<div class="proc-view" data-pselect="${p.id}">${p.html || '<span class="muted">(empty)</span>'}
            ${p.notes ? `<div class="proc-note">Note: ${esc(p.notes)}</div>` : ""}
            <div class="proc-meta">${p.done_at ? `<span class="small muted">done ${esc(clockTime(p.done_at))}</span>` : ""}
              ${!nested && entries.length ? `<span class="small muted">${entries.length} log ${entries.length === 1 ? "entry" : "entries"}</span>` : ""}</div>
          </div>`}
      </div>
      ${ed ? "" : `<button class="btn icon" data-pedit="${p.id}" title="Edit step" aria-label="Edit step ${i + 1}">✎</button>`}
    </div>
    ${nested && entries.length ? `<ol class="log-list nested">${entries.map(entryRow).join("")}</ol>` : ""}
  </li>`;
}

function orphanLog() {
  const ids = new Set(state.data.procedure.map((p) => p.id));
  const rest = state.data.entries.filter((e) => !e.procedure_id || !ids.has(e.procedure_id));
  return rest.length ? `<h4 class="log-h">Other log entries</h4><ol class="log-list">${rest.map(entryRow).join("")}</ol>` : "";
}

function entryRow(e) {
  if (editingEntry === e.id) {
    const dt = new Date(e.ts);
    return `<li class="entry editing" data-eid="${e.id}">
      <input type="datetime-local" step="1" class="e-ts" value="${isNaN(dt) ? "" : localDateTimeValue(dt)}" aria-label="Time">
      <input class="e-text grow" value="${esc(e.text)}" aria-label="Entry">
      <div class="row"><button class="btn small primary e-save">Save</button><button class="btn small e-cancel">Cancel</button>
        <button class="btn small danger e-del">Delete</button></div></li>`;
  }
  const procNo = state.data.procedure.findIndex((p) => p.id === e.procedure_id);
  return `<li class="entry k-${esc(e.action || e.kind)}" data-eid="${e.id}">
    <span class="e-time" title="${esc(e.ts)}">${esc(clockTime(e.ts, true))}</span>
    <span class="e-tplus">${e.elapsed_s != null ? "T+" + fmtDur(e.elapsed_s) : ""}</span>
    <span class="e-text">${esc(e.text)}${e.value ? ` <b>${esc(e.value)} ${esc(e.unit || "")}</b>` : ""}
      ${procNo >= 0 && wide.matches ? `<span class="badge" title="Logged during procedure step ${procNo + 1}">§${procNo + 1}</span>` : ""}</span>
    <button class="btn icon e-edit" title="Edit" aria-label="Edit entry">✎</button>
  </li>`;
}

// ------------------------------------------------------------------------------------------- composer
function composerHtml() {
  const acts = actionsCfg();
  const cur = state.data.procedure.findIndex((p) => p.id === state.currentProc);
  return `<div class="composer" id="composer">
    <form class="quick" id="quick-form" autocomplete="off">
      <input id="quick-text" data-key="quick-text" data-mention="1" placeholder="Observation… (Enter to log, @ for a chemical)" aria-label="Quick observation">
      <button class="btn primary">Log</button>
      ${!wide.matches ? `<button type="button" class="btn" id="chips-toggle" aria-expanded="${!chipsHidden()}">${chipsHidden() ? "Actions…" : "Less"}</button>` : ""}
    </form>
    <div class="action-chips ${chipsHidden() ? "hidden" : ""}">${ACTION_ORDER.filter((k) => acts[k] && k !== "observation").map((k) =>
      `<button type="button" class="chip ${composer.action === k ? "on" : ""}" data-action="${k}">${esc(acts[k].label)}</button>`).join("")}</div>
    ${composer.action ? actionForm(composer.action) : ""}
    <div class="hint ${chipsHidden() ? "hidden" : ""}">${cur >= 0 ? `Logging to procedure step ${cur + 1}
      <span class="ph-chip">${esc(state.data.phases.find((ph) => ph.key === state.data.procedure[cur].phase)?.label || "")}</span>.`
      : "Add procedure steps to group the log."}</div>
  </div>`;
}

function actionForm(key) {
  const a = actionsCfg()[key];
  const v = composer.values;
  const fields = a.fields.map((f) => {
    const id = `af-${f.name}`;
    const val = v[f.name] ?? "";
    let input;
    if (f.type === "select") {
      const blank = ["unit", "mode", "stage", "kind", "verb", "method"].includes(f.name) ? "" : '<option value=""></option>';
      input = `<select id="${id}" data-af="${f.name}">${blank}${f.options.map((o) =>
        `<option ${String(val) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    } else if (f.type === "chem") {
      input = `<input id="${id}" data-af="${f.name}" data-chem="1" value="${esc(val)}" placeholder="chemical (type to search the table)">`;
    } else if (f.type === "product") {
      const prods = state.data.reagents.filter((r) => r.role === "product");
      input = `<select id="${id}" data-af="${f.name}">${prods.map((r) => `<option value="${r.id}" ${String(val) === String(r.id) ? "selected" : ""}>${esc(labelOf(r))}</option>`).join("")}</select>`;
    } else {
      const list = f.suggest ? `list="sg-${key}-${f.name}"` : "";
      const mention = f.mention || f.type === "text" ? 'data-mention="1"' : "";
      input = `<input id="${id}" data-af="${f.name}" value="${esc(val)}" ${f.type === "number" ? 'inputmode="decimal"' : ""} ${list} ${mention}
        placeholder="${f.type === "duration" ? "e.g. 10 min" : ""}">${f.suggest ? `<datalist id="sg-${key}-${f.name}">${f.suggest.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>` : ""}`;
    }
    const hide = key === "timer" && f.name === "duration" && v.kind !== "countdown";
    return `<label class="field af-${f.type} ${f.name === "text" || f.name === "label" ? "wide" : ""} ${hide ? "hidden" : ""}"><span>${esc(f.label)}</span>${input}</label>`;
  }).join("");
  const timer = a.timer ? `<label class="inline small timer-opt"><input type="checkbox" id="af-timer" ${v.__timer ? "checked" : ""}> Start a timer</label>` : "";
  const hint = key === "weigh" ? `<div class="hint">Sets the reagent's actual amount (shown in Reagents and used for the yield).</div>`
    : key === "add" ? `<div class="hint">With an amount in g or mL, the additions of a reagent add up to its actual amount (unless an “Amount used” entry exists).</div>` : "";
  return `<form class="action-form" id="action-form" autocomplete="off">
    <div class="af-grid">${fields}</div>${hint}
    <div class="row">${timer}<span class="spacer"></span><button type="button" class="btn" id="af-cancel">Cancel</button>
      <button class="btn primary">${key === "timer" ? "Start timer" : "Log " + esc(a.label.toLowerCase())}</button></div>
  </form>`;
}

// ------------------------------------------------------------------------------------------- phases
const putPhases = (list) => mutate("PUT", `/api/experiments/${expId()}`, { phases: list.map(({ key, label }) => ({ key, label })) });

async function newPhase() {
  const label = (prompt("Name of the new phase (e.g. Recrystallization, Preparation of the catalyst):") || "").trim();
  if (!label) return null;
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30) || "phase";
  const keys = new Set(state.data.phases.map((p) => p.key));
  let key = base, n = 2;
  while (keys.has(key) || ["setup", "reaction", "workup", "purification", "analysis"].includes(key)) key = `${base}-${n++}`;
  const list = [...state.data.phases];
  const at = list.findIndex((p) => p.key === "analysis");  // before Analysis; move it with the arrows
  list.splice(at < 0 ? list.length : at, 0, { key, label });
  await putPhases(list);
  return key;
}

function bindPhases(root) {
  const sel = $("#proc-phase", root);
  if (sel) sel.addEventListener("change", async () => {
    if (sel.value !== "__new") { addPhase = sel.value; return; }
    try {
      const key = await newPhase();
      if (key) addPhase = key;
    } catch { /* toast shown */ }
    renderProcedure($("#sec-procedure"));
    $("#proc-new")?.focus();
  });
  $$("[data-ph-move]", root).forEach((b) => (b.onclick = () => {
    const list = [...state.data.phases];
    const i = list.findIndex((p) => p.key === b.dataset.phMove), j = i + Number(b.dataset.dir);
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    putPhases(list).catch(() => {});
  }));
  $$("[data-ph-rename]", root).forEach((b) => (b.onclick = () => {
    const ph = state.data.phases.find((p) => p.key === b.dataset.phRename);
    const label = (prompt("Rename the phase:", ph.label) || "").trim();
    if (label && label !== ph.label) putPhases(state.data.phases.map((p) => (p.key === ph.key ? { ...p, label } : p))).catch(() => {});
  }));
  $$("[data-ph-del]", root).forEach((b) => (b.onclick = () => {
    const ph = state.data.phases.find((p) => p.key === b.dataset.phDel);
    const n = state.data.procedure.filter((p) => p.phase === ph.key).length;
    if (n && !confirm(`Remove the phase “${ph.label}”? Its ${n} step${n === 1 ? "" : "s"} move to Reaction.`)) return;
    putPhases(state.data.phases.filter((p) => p.key !== ph.key)).catch(() => {});
  }));
}

function findReagent(name) {
  const t = String(name || "").trim().toLowerCase();
  if (!t) return null;
  for (const key of ["label", "name", "formula", "cas"]) {
    const r = state.data.reagents.find((x) => (x[key] || "").trim().toLowerCase() === t);
    if (r) return r;
  }
  return null;
}

const currentStepId = () => {
  const p = state.data.procedure.find((x) => x.id === state.currentProc);
  return p?.step_id || state.data.steps[state.data.steps.length - 1].id;
};

async function resolveChem(name) {
  const r = findReagent(name);
  if (r) return { reagent_id: r.id };
  if (!name.trim()) return null;
  if (!confirm(`“${name}” is not in the reagent table. Add it to Workup & purification (with its PubChem hazards)?`)) return { name };
  const d = await mutate("POST", `/api/experiments/${expId()}/reagents`, { query: name, role: "workup", step_id: currentStepId() });
  if (d.warning) toast(d.warning, true);
  return { reagent_id: d.reagent_id };
}

function defaultUnit(chemName) {
  const r = findReagent(chemName);
  if (!r) return "mL";
  if (r.actual_basis) return r.actual_basis === "volume" ? "mL" : "g";
  if (r.basis === "mass") return "g";
  if (r.basis === "volume") return "mL";
  if (r.form !== "neat" || ["solvent", "workup"].includes(r.role) || (r.mp != null && r.mp < 25) || r.basis === "volume") return "mL";
  return "g";
}

function timerDefaults(key, v) {
  if (key === "add") return ["portionwise", "dropwise", "via syringe", "via cannula"].includes(v.mode) || !!v.over;
  return !!v.duration;
}

async function submitAction(form) {
  const key = composer.action;
  const a = actionsCfg()[key];
  const data = {};
  for (const f of a.fields) {
    const el = $(`[data-af="${f.name}"]`, form);
    if (el?.closest(".hidden")) continue;
    let val = el?.value?.trim() ?? "";
    if (f.required && !val) { toast(`Enter “${f.label.replace(/ \(.*/, "")}”.`, true); el?.focus(); return; }
    if (!val) continue;
    if (f.type === "number") {
      const n = Number(val.replace(",", "."));
      if (!isFinite(n)) { toast(`“${f.label}” must be a number.`, true); return; }
      val = n;
    }
    if (f.type === "chem") val = await resolveChem(val);
    if (f.type === "product") val = Number(val);
    data[f.name] = val;
  }
  try {
    if (key === "timer") {
      const body = { label: data.label, kind: data.kind || "stopwatch", procedure_id: state.currentProc || null };
      const r = findReagent(data.label.replace(/^Addition of\s+/i, ""));
      if (r) body.reagent_id = r.id;
      if (body.kind === "countdown") {
        body.duration_s = parseDuration(data.duration);
        if (!body.duration_s) { toast("Enter a countdown duration, e.g. 30 min.", true); return; }
        if ("Notification" in window && Notification.permission === "default" && window.isSecureContext) Notification.requestPermission().catch(() => {});
      }
      await mutate("POST", `/api/experiments/${expId()}/timers`, body);
    } else {
      const body = { action: key, data, procedure_id: state.currentProc || null, step_id: currentStepId() };
      if ($("#af-timer", form)?.checked) {
        const chem = data.chem?.reagent_id ? labelOf(reagentById(data.chem.reagent_id)) : data.chem?.name;
        const dur = parseDuration(data.over || data.duration);
        const label = key === "add" ? `Addition of ${chem || "reagent"}` : key === "stir" ? "Stirring"
          : `${data.verb || "Heating"}${data.temp ? " " + data.temp : ""}`.replace(/ to$/, "");
        body.start_timer = dur && key !== "add" ? { label, kind: "countdown", duration_s: dur } : { label, kind: "stopwatch" };
      }
      await mutate("POST", `/api/experiments/${expId()}/entries`, body);
    }
    composer = { action: null, values: {} };
    renderProcedure($("#sec-procedure"));
  } catch { /* toast shown */ }
}

// ------------------------------------------------------------------------------------------- events
function bind(root) {
  $("#quick-form", root).onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#quick-text", root);
    const t = q.value.trim();
    if (!t || q.dataset.mentionOpen) return;
    await mutate("POST", `/api/experiments/${expId()}/entries`, { action: "observation", data: { text: t }, procedure_id: state.currentProc || null });
    const again = $("#quick-text");
    if (again) { again.value = ""; again.focus(); }
  };
  const ct = $("#chips-toggle", root);
  if (ct) ct.onclick = () => {
    const open = chipsHidden();
    chipsOpen = open;
    if (!open) composer = { action: null, values: {} };
    renderProcedure(root);
  };
  $$("[data-action]", root).forEach((b) => (b.onclick = () => {
    if (composer.action === b.dataset.action) { composer = { action: null, values: {} }; renderProcedure(root); return; }
    openComposer(b.dataset.action);
  }));
  const form = $("#action-form", root);
  if (form) {
    form.addEventListener("input", (e) => {
      const f = e.target.dataset.af;
      if (!f) return;
      composer.values[f] = e.target.value;
      if (f === "chem" && ["add", "weigh", "quench"].includes(composer.action) && $('[data-af="unit"]', form)) {
        const u = defaultUnit(e.target.value);
        $('[data-af="unit"]', form).value = u;
        composer.values.unit = u;
      }
      const t = $("#af-timer", form);
      if (t && ["mode", "over", "duration"].includes(f)) { t.checked = timerDefaults(composer.action, composer.values); composer.values.__timer = t.checked; }
    });
    form.addEventListener("change", (e) => {
      if (e.target.dataset.af) composer.values[e.target.dataset.af] = e.target.value;
      if (e.target.id === "af-timer") composer.values.__timer = e.target.checked;
      if (e.target.dataset.af === "kind") $("#af-duration", form)?.closest("label").classList.toggle("hidden", e.target.value !== "countdown");
      const t = $("#af-timer", form);
      if (t && e.target.dataset.af === "mode") { t.checked = timerDefaults(composer.action, composer.values); composer.values.__timer = t.checked; }
    });
    form.onsubmit = (e) => { e.preventDefault(); if (!$("[data-mention-open]", form)) submitAction(form); };
    $("#af-cancel", form).onclick = () => { composer = { action: null, values: {} }; renderProcedure(root); };
  }
  $$("[data-chem]", root).forEach((inp) => chemPicker(inp));
  $$("input[data-mention]", root).forEach((inp) => mentions(inp, { plain: true }));
  // procedure rows
  $$("[data-pselect]", root).forEach((el) => (el.onclick = () => { state.currentProc = Number(el.dataset.pselect); renderProcedure(root); }));
  $$("[data-pedit]", root).forEach((b) => (b.onclick = () => {
    editing.add(Number(b.dataset.pedit));
    renderProcedure(root);
    $(`[data-ptext="${b.dataset.pedit}"]`, root)?.focus();
  }));
  $$("[data-pdone-edit]", root).forEach((b) => (b.onclick = () => { editing.delete(Number(b.dataset.pdoneEdit)); renderProcedure(root); }));
  $$("[data-ptext]", root).forEach((t) => {
    mentions(t);
    t.addEventListener("change", () => mutate("PUT", `/api/procedure/${t.dataset.ptext}`, { text: t.value }).catch(() => {}));
  });
  $$("[data-pnotes]", root).forEach((t) => {
    mentions(t, { plain: true });
    t.addEventListener("change", () => mutate("PUT", `/api/procedure/${t.dataset.pnotes}`, { notes: t.value.trim() || null }).catch(() => {}));
  });
  $$("[data-pphase]", root).forEach((s) => s.addEventListener("change", () =>
    mutate("PUT", `/api/procedure/${s.dataset.pphase}`, { phase: s.value }).catch(() => {})));
  bindPhases(root);
  $$("[data-done]", root).forEach((c) => c.addEventListener("change", async () => {
    const pid = Number(c.dataset.done);
    await mutate("PUT", `/api/procedure/${pid}`, { done: c.checked });
    if (c.checked) {  // move on to the next open step
      const next = state.data.procedure.find((p) => !p.done_at);
      state.currentProc = next ? next.id : pid;
      renderProcedure($("#sec-procedure"));
    }
  }));
  $$("[data-pdel]", root).forEach((b) => (b.onclick = () => {
    if (confirm("Delete this procedure step? Its log entries are kept.")) {
      editing.delete(Number(b.dataset.pdel));
      mutate("DELETE", `/api/procedure/${b.dataset.pdel}`).catch(() => {});
    }
  }));
  $$("[data-move]", root).forEach((b) => (b.onclick = () => {
    // moves within its phase (rows are ordered by phase, then position)
    const ids = state.data.procedure.map((p) => p.id);
    const i = ids.indexOf(Number(b.dataset.move)), j = i + Number(b.dataset.dir);
    if (j < 0 || j >= ids.length || state.data.procedure[i].phase !== state.data.procedure[j].phase) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    mutate("PUT", `/api/experiments/${expId()}/procedure/order`, ids).catch(() => {});
  }));
  const nw = $("#proc-new", root);
  mentions(nw);
  const addProc = async () => {
    const text = nw.value.trim();
    if (!text) return;
    const body = { text, phase: newRowPhase() };
    if (multiStage()) body.step_id = currentStepId();
    await mutate("POST", `/api/experiments/${expId()}/procedure`, body);
    const again = $("#proc-new");
    if (again) { again.value = ""; again.focus(); }
  };
  nw.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !nw.dataset.mentionOpen) { e.preventDefault(); addProc(); } });
  $("#proc-add-btn", root).onclick = addProc;
  // log entries
  $$(".entry .e-edit", root).forEach((b) => (b.onclick = () => { editingEntry = Number(b.closest(".entry").dataset.eid); renderProcedure(root); }));
  $$(".entry.editing", root).forEach((li) => {
    const id = Number(li.dataset.eid);
    mentions($(".e-text", li), { plain: true });
    $(".e-cancel", li).onclick = () => { editingEntry = null; renderProcedure(root); };
    $(".e-del", li).onclick = () => { if (confirm("Delete this entry?")) { editingEntry = null; mutate("DELETE", `/api/entries/${id}`).catch(() => {}); } };
    $(".e-save", li).onclick = async () => {
      const e = state.data.entries.find((x) => x.id === id);
      const body = {};
      const text = $(".e-text", li).value.trim();
      if (text !== e.text) body.text = text;
      const tsv = $(".e-ts", li).value;
      if (tsv) {
        const iso = isoWithOffset(new Date(tsv));
        if (new Date(iso).getTime() !== new Date(e.ts).getTime()) body.ts = iso;
      }
      editingEntry = null;
      if (Object.keys(body).length) await mutate("PUT", `/api/entries/${id}`, body).catch(() => {});
      else renderProcedure(root);
    };
  });
}

// ------------------------------------------------------------------------------------------- pickers
function dropdown(input) {
  const box = document.createElement("ul");
  box.className = "ac-list mention-list hidden";
  input.insertAdjacentElement("afterend", box);
  return box;
}

/** Chemical field of a log action: suggestions from the reagent table, any name allowed. */
function chemPicker(input) {
  const box = dropdown(input);
  let items = [], active = 0;
  const close = () => { box.classList.add("hidden"); delete input.dataset.mentionOpen; };
  const show = () => {
    box.innerHTML = items.map((r, i) => `<li class="${i === active ? "active" : ""}" data-i="${i}">${esc(r.name)}${r.label ? ` <span class="sub">${esc(r.label)}</span>` : ""}
      <span class="sub">${esc(r.role)}</span></li>`).join("");
    box.classList.toggle("hidden", !items.length);
    if (items.length) input.dataset.mentionOpen = "1"; else delete input.dataset.mentionOpen;
  };
  const pick = (r) => { input.value = labelOf(r); input.dispatchEvent(new Event("input", { bubbles: true })); close(); };
  const update = () => {
    const q = input.value.trim().toLowerCase();
    items = state.data.reagents.filter((r) => r.role !== "product" && (!q || [r.name, r.label, r.formula].some((x) => (x || "").toLowerCase().includes(q)))).slice(0, 10);
    active = 0;
    show();
  };
  input.addEventListener("focus", update);
  input.addEventListener("input", (e) => { if (e.isTrusted) update(); });
  input.addEventListener("keydown", (e) => {
    if (box.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") { active = (active + 1) % items.length; show(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; show(); e.preventDefault(); }
    else if (e.key === "Enter" || e.key === "Tab") { if (items[active]) { e.preventDefault(); pick(items[active]); } }
    else if (e.key === "Escape") close();
  });
  box.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); pick(items[Number(li.dataset.i)]); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
}

/** @ mentions. In procedure text they become @Name / @{Name} tokens (printed with amounts); with plain: true
    (log text, timer labels) the chemical's name is inserted as text. */
function mentions(el, { plain = false } = {}) {
  if (!el) return;
  const box = dropdown(el);
  let items = [], active = 0, start = -1;
  const close = () => { box.classList.add("hidden"); delete el.dataset.mentionOpen; start = -1; };
  const show = () => {
    box.innerHTML = items.map((r, i) => `<li class="${i === active ? "active" : ""}" data-i="${i}">${esc(r.name)}${r.label ? ` <span class="sub">${esc(r.label)}</span>` : ""}</li>`).join("");
    box.classList.toggle("hidden", !items.length);
    if (items.length) el.dataset.mentionOpen = "1"; else delete el.dataset.mentionOpen;
  };
  const insert = (r) => {
    const name = labelOf(r);
    const token = plain ? name : /\s/.test(name) ? `@{${name}}` : `@${name}`;
    const caret = el.selectionStart;
    el.value = el.value.slice(0, start) + token + " " + el.value.slice(caret);
    const pos = start + token.length + 1;
    el.setSelectionRange(pos, pos);
    close();
    el.focus();
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  el.addEventListener("input", (e) => {
    if (!e.isTrusted) return;
    const caret = el.selectionStart;
    const m = el.value.slice(0, caret).match(/@\{?([^@{}\n]*)$/);
    if (!m) return close();
    start = caret - m[0].length;
    const q = m[1].toLowerCase();
    const seen = new Set();  // the same chemical in several steps is listed once (mentions resolve by name)
    items = state.data.reagents.filter((r) => [r.name, r.label, r.formula].some((x) => (x || "").toLowerCase().includes(q)))
      .filter((r) => !seen.has(labelOf(r).toLowerCase()) && seen.add(labelOf(r).toLowerCase())).slice(0, 8);
    active = 0;
    show();
  });
  el.addEventListener("keydown", (e) => {
    if (box.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") { active = (active + 1) % items.length; show(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; show(); e.preventDefault(); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopImmediatePropagation(); insert(items[active]); }
    else if (e.key === "Escape") close();
  });
  box.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); insert(items[Number(li.dataset.i)]); }
  });
  el.addEventListener("blur", () => setTimeout(close, 150));
}
