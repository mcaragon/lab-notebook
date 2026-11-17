/* Procedure & log: procedure rows next to the log (side by side on wide screens, interleaved on phones).
   New log entries attach to the current procedure row. Log actions are structured (what, how much) and the server
   writes the sentence. */
import { $, $$, api, esc, fmtDur, clockTime, isoWithOffset, localDateTimeValue, parseDuration, preserveFocus, toast } from "./util.js";
import { state, mutate, expId, multiStep, labelOf, reagentById } from "./state.js";

const wide = window.matchMedia("(min-width: 1000px)");
wide.addEventListener("change", () => state.data && renderProcedure($("#sec-procedure")));
const editing = new Set();      // procedure rows in edit mode
let editingEntry = null;
let composer = { action: null, values: {} };
let chipsOpen = false;   // phone: action chips collapsed by default
const chipsHidden = () => !wide.matches && !chipsOpen && !composer.action;

export function renderProcedure(root) {
  preserveFocus(root, () => draw(root));
}

function draw(root) {
  const d = state.data;
  const proc = d.procedure;
  if (!state.currentProc && proc.length) state.currentProc = (proc.find((p) => !p.done_at) || proc[proc.length - 1]).id;
  const isWide = wide.matches;
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Procedure &amp; log</h2><span class="spacer"></span>
      <span class="hint">Type <b>@</b> in a step to insert a chemical with its amount. New log entries attach to the highlighted step.</span></div>
    <div class="pl ${isWide ? "wide" : "narrow"}">
      <div class="pl-proc">
        <ol class="proc-list">${proc.map((p, i) => procRow(p, i, !isWide)).join("")}</ol>
        <div class="proc-add"><textarea id="proc-new" rows="2" data-key="proc-new" placeholder="Add a step… (Enter to add, Shift+Enter for a new line, @ for chemicals)"></textarea>
          <button class="btn" id="proc-add-btn">Add step</button></div>
        ${!isWide ? orphanLog() : ""}
      </div>
      ${isWide ? `<div class="pl-log">${composerHtml()}<ol class="log-list">${d.entries.slice().reverse().map(entryRow).join("") || '<li class="empty">No entries yet.</li>'}</ol></div>` : ""}
    </div>
    ${!isWide ? `<div class="composer-phone">${composerHtml()}</div>` : ""}
  </div>`;
  bind(root);
}

function procRow(p, i, nested) {
  const cur = state.currentProc === p.id;
  const step = multiStep() ? state.data.steps.findIndex((s) => s.id === p.step_id) : -1;
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
            ${multiStep() ? `<select data-pstep="${p.id}" aria-label="Reaction step">${state.data.steps.map((s, j) =>
              `<option value="${s.id}" ${s.id === p.step_id ? "selected" : ""}>Step ${j + 1}${s.title ? ": " + esc(s.title) : ""}</option>`).join("")}</select>` : ""}
            <button class="btn icon" data-move="${p.id}" data-dir="-1" title="Move up" aria-label="Move up">↑</button>
            <button class="btn icon" data-move="${p.id}" data-dir="1" title="Move down" aria-label="Move down">↓</button>
            <span class="spacer"></span>
            <button class="btn small danger" data-pdel="${p.id}">Delete</button>
            <button class="btn small primary" data-pdone-edit="${p.id}">Done</button>
          </div>`
        : `<div class="proc-view" data-pselect="${p.id}">${p.html || '<span class="muted">(empty)</span>'}
            ${p.notes ? `<div class="proc-note">Note: ${esc(p.notes)}</div>` : ""}
            <div class="proc-meta">${step >= 0 ? `<span class="badge">step ${step + 1}</span>` : ""}
              ${p.done_at ? `<span class="small muted">done ${esc(clockTime(p.done_at))}</span>` : ""}
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
  return rest.length ? `<h4 class="log-h">Other log entries</h4><ol class="log-list">${rest.slice().reverse().map(entryRow).join("")}</ol>` : "";
}

function entryRow(e) {
  if (editingEntry === e.id) {
    const d = new Date(e.ts);
    return `<li class="entry editing" data-eid="${e.id}">
      <input type="datetime-local" step="1" class="e-ts" value="${isNaN(d) ? "" : localDateTimeValue(d)}" aria-label="Time">
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
  const acts = state.config.actions;
  const cur = state.data.procedure.findIndex((p) => p.id === state.currentProc);
  return `<div class="composer" id="composer">
    <form class="quick" id="quick-form" autocomplete="off">
      <input id="quick-text" data-key="quick-text" placeholder="Quick observation… (Enter)" aria-label="Quick observation">
      <button class="btn">Log</button>
      ${!wide.matches ? `<button type="button" class="btn" id="chips-toggle" aria-expanded="${!chipsHidden()}">${chipsHidden() ? "Actions…" : "Less"}</button>` : ""}
    </form>
    <div class="action-chips ${chipsHidden() ? "hidden" : ""}">${Object.entries(acts).filter(([k]) => !["observation"].includes(k)).map(([k, a]) =>
      `<button type="button" class="chip ${composer.action === k ? "on" : ""}" data-action="${k}">${esc(a.label)}</button>`).join("")}</div>
    ${composer.action ? actionForm(composer.action) : ""}
    <div class="hint ${chipsHidden() ? "hidden" : ""}">${cur >= 0 ? `Logging to procedure step ${cur + 1}. Tap a step to change.` : "Tip: add procedure steps to group the log."}</div>
  </div>`;
}

function chemOptions() {
  return state.data.reagents.filter((r) => r.role !== "product").map((r) => `<option value="${esc(labelOf(r))}">`).join("");
}

function actionForm(key) {
  const a = state.config.actions[key];
  const v = composer.values;
  const fields = a.fields.map((f) => {
    const id = `af-${f.name}`;
    const val = v[f.name] ?? "";
    let input;
    if (f.type === "select") {
      input = `<select id="${id}" data-af="${f.name}">${f.name === "unit" || f.name === "mode" || f.name === "stage" ? "" : '<option value=""></option>'}${f.options.map((o) =>
        `<option ${String(val) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    } else if (f.type === "chem") {
      input = `<input id="${id}" data-af="${f.name}" list="chem-list" value="${esc(val)}" placeholder="chemical from the table, or type a name">`;
    } else if (f.type === "product") {
      const prods = state.data.reagents.filter((r) => r.role === "product");
      input = `<select id="${id}" data-af="${f.name}">${prods.map((r) => `<option value="${r.id}" ${String(val) === String(r.id) ? "selected" : ""}>${esc(labelOf(r))}</option>`).join("")}</select>`;
    } else {
      const list = f.suggest ? `list="sg-${f.name}"` : "";
      input = `<input id="${id}" data-af="${f.name}" value="${esc(val)}" ${f.type === "number" ? 'inputmode="decimal"' : ""} ${list}
        placeholder="${f.type === "duration" ? "e.g. 10 min" : ""}">${f.suggest ? `<datalist id="sg-${f.name}">${f.suggest.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>` : ""}`;
    }
    return `<label class="field af-${f.type} ${f.name === "text" ? "wide" : ""}"><span>${esc(f.label)}</span>${input}</label>`;
  }).join("");
  const timer = a.timer ? `<label class="inline small timer-opt"><input type="checkbox" id="af-timer" ${v.__timer ? "checked" : ""}> Start a timer</label>` : "";
  return `<form class="action-form" id="action-form" autocomplete="off">
    <datalist id="chem-list">${chemOptions()}</datalist>
    <div class="af-grid">${fields}</div>
    <div class="row">${timer}<span class="spacer"></span><button type="button" class="btn" id="af-cancel">Cancel</button>
      <button class="btn primary">Log ${esc(a.label.toLowerCase())}</button></div>
  </form>`;
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
  if (r.form !== "neat" || ["solvent", "workup"].includes(r.role) || (r.mp != null && r.mp < 25)) return "mL";
  return "g";
}

function timerDefaults(key, v) {
  if (key === "add") return ["portionwise", "dropwise", "via syringe", "via cannula"].includes(v.mode) || !!v.over;
  return !!v.duration;
}

async function submitAction(form) {
  const key = composer.action;
  const a = state.config.actions[key];
  const data = {};
  for (const f of a.fields) {
    const el = $(`[data-af="${f.name}"]`, form);
    let val = el?.value?.trim() ?? "";
    if (f.required && !val) { toast(`Enter “${f.label}”.`, true); el?.focus(); return; }
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
  const body = { action: key, data, procedure_id: state.currentProc || null, step_id: currentStepId() };
  if ($("#af-timer", form)?.checked) {
    const chem = data.chem?.reagent_id ? labelOf(reagentById(data.chem.reagent_id)) : data.chem?.name;
    const dur = parseDuration(data.over || data.duration);
    const label = key === "add" ? `Addition of ${chem || "reagent"}` : key === "stir" ? "Stirring"
      : `${data.verb || "Heating"}${data.temp ? " " + data.temp : ""}`.replace(/ to$/, "");
    body.start_timer = dur && key !== "add" ? { label, kind: "countdown", duration_s: dur } : { label, kind: "stopwatch" };
    if (dur && key !== "add" && "Notification" in window && Notification.permission === "default" && window.isSecureContext) Notification.requestPermission().catch(() => {});
  }
  try {
    await mutate("POST", `/api/experiments/${expId()}/entries`, body);
    composer = { action: null, values: {} };
    renderProcedure($("#sec-procedure"));
  } catch { /* toast shown */ }
}

// ------------------------------------------------------------------------------------------- events
function bind(root) {
  // quick observation
  $("#quick-form", root).onsubmit = async (e) => {
    e.preventDefault();
    const t = $("#quick-text", root).value.trim();
    if (!t) return;
    await mutate("POST", `/api/experiments/${expId()}/entries`, { action: "observation", data: { text: t }, procedure_id: state.currentProc || null });
    const q = $("#quick-text");
    if (q) { q.value = ""; q.focus(); }
  };
  const ct = $("#chips-toggle", root);
  if (ct) ct.onclick = () => {
    const open = chipsHidden();
    chipsOpen = open;
    if (!open) composer = { action: null, values: {} };
    renderProcedure(root);
  };
  $$("[data-action]", root).forEach((b) => (b.onclick = () => {
    composer = composer.action === b.dataset.action ? { action: null, values: {} } : { action: b.dataset.action, values: {} };
    if (composer.action === "add") composer.values = { unit: "g", mode: "in one portion" };
    renderProcedure(root);
    $("#action-form [data-af]", root)?.focus();
  }));
  const form = $("#action-form", root);
  if (form) {
    form.addEventListener("input", (e) => {
      const f = e.target.dataset.af;
      if (!f) return;
      composer.values[f] = e.target.value;
      if (f === "chem" && composer.action === "add" && $('[data-af="unit"]', form)) {
        const u = defaultUnit(e.target.value);
        $('[data-af="unit"]', form).value = u;
        composer.values.unit = u;
      }
      const t = $("#af-timer", form);
      if (t && ["mode", "over", "duration"].includes(f)) { t.checked = timerDefaults(composer.action, composer.values); composer.values.__timer = t.checked; }
    });
    form.addEventListener("change", (e) => { if (e.target.dataset.af) composer.values[e.target.dataset.af] = e.target.value;
      if (e.target.id === "af-timer") composer.values.__timer = e.target.checked;
      const t = $("#af-timer", form);
      if (t && ["mode"].includes(e.target.dataset.af)) { t.checked = timerDefaults(composer.action, composer.values); composer.values.__timer = t.checked; } });
    form.onsubmit = (e) => { e.preventDefault(); submitAction(form); };
    $("#af-cancel", form).onclick = () => { composer = { action: null, values: {} }; renderProcedure(root); };
  }
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
    t.addEventListener("change", () => mutate("PUT", `/api/procedure/${t.dataset.ptext}`, { text: t.value }));
  });
  $$("[data-pnotes]", root).forEach((t) => t.addEventListener("change", () =>
    mutate("PUT", `/api/procedure/${t.dataset.pnotes}`, { notes: t.value.trim() || null })));
  $$("[data-pstep]", root).forEach((s) => s.addEventListener("change", () =>
    mutate("PUT", `/api/procedure/${s.dataset.pstep}`, { step_id: Number(s.value) })));
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
      mutate("DELETE", `/api/procedure/${b.dataset.pdel}`);
    }
  }));
  $$("[data-move]", root).forEach((b) => (b.onclick = () => {
    const ids = state.data.procedure.map((p) => p.id);
    const i = ids.indexOf(Number(b.dataset.move)), j = i + Number(b.dataset.dir);
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    mutate("PUT", `/api/experiments/${expId()}/procedure/order`, ids);
  }));
  const nw = $("#proc-new", root);
  mentions(nw);
  const addProc = async () => {
    const text = nw.value.trim();
    if (!text) return;
    const body = { text };
    if (multiStep()) body.step_id = currentStepId();
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
    $(".e-cancel", li).onclick = () => { editingEntry = null; renderProcedure(root); };
    $(".e-del", li).onclick = () => { if (confirm("Delete this entry?")) { editingEntry = null; mutate("DELETE", `/api/entries/${id}`); } };
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
      if (Object.keys(body).length) await mutate("PUT", `/api/entries/${id}`, body);
      else renderProcedure(root);
    };
  });
}

// ------------------------------------------------------------------------------------------- @ mentions
function mentions(textarea) {
  if (!textarea) return;
  const box = document.createElement("ul");
  box.className = "ac-list mention-list hidden";
  textarea.insertAdjacentElement("afterend", box);
  let items = [], active = 0, start = -1;
  const close = () => { box.classList.add("hidden"); delete textarea.dataset.mentionOpen; start = -1; };
  const show = () => {
    box.innerHTML = items.map((r, i) => `<li class="${i === active ? "active" : ""}" data-i="${i}">${esc(r.name)}${r.label ? ` <span class="sub">${esc(r.label)}</span>` : ""}</li>`).join("");
    box.classList.toggle("hidden", !items.length);
    if (items.length) textarea.dataset.mentionOpen = "1"; else delete textarea.dataset.mentionOpen;
  };
  const insert = (r) => {
    const name = labelOf(r);
    const token = /\s/.test(name) ? `@{${name}}` : `@${name}`;
    const caret = textarea.selectionStart;
    textarea.value = textarea.value.slice(0, start) + token + " " + textarea.value.slice(caret);
    const pos = start + token.length + 1;
    textarea.setSelectionRange(pos, pos);
    close();
    textarea.focus();
  };
  textarea.addEventListener("input", () => {
    const caret = textarea.selectionStart;
    const m = textarea.value.slice(0, caret).match(/@\{?([^@{}\n]*)$/);
    if (!m) return close();
    start = caret - m[0].length;
    const q = m[1].toLowerCase();
    items = state.data.reagents.filter((r) => [r.name, r.label, r.formula].some((x) => (x || "").toLowerCase().includes(q))).slice(0, 8);
    active = 0;
    show();
  });
  textarea.addEventListener("keydown", (e) => {
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
  textarea.addEventListener("blur", () => setTimeout(close, 150));
}
