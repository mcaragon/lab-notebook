/* Reaction section: live scheme plus the step editor (title, atmosphere, condition stages). */
import { $, $$, esc, preserveFocus } from "./util.js";
import { state, mutate, expId, multiStep } from "./state.js";

const TEMPS = ["−78", "0", "rt", "reflux"];
const ATMOS = ["", "N₂", "Ar", "air", "H₂ (1 atm)", "O₂"];

export function renderReaction(root) {
  preserveFocus(root, () => draw(root));
}

function draw(root) {
  const d = state.data;
  const style = d.experiment.scheme_style || "auto";
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Reaction</h2><span class="spacer"></span>
      <label class="inline small">Scheme style <select id="scheme-style" data-key="scheme-style">
        ${[["auto", "Automatic"], ["inline", "Conditions on arrows"], ["lettered", "Lettered (a), (b)…"]].map(([k, v]) =>
          `<option value="${k}" ${style === k ? "selected" : ""}>${v}</option>`).join("")}</select></label></div>
    <div class="scheme-paper">${d.scheme_html.includes("<figure") || d.scheme_html.includes('class="arrow"')
      ? d.scheme_html : '<div class="empty">Add starting materials and products in Reagents to draw the scheme.</div>'}</div>
    <div class="steps">${d.steps.map((s, i) => stepCard(s, i)).join("")}</div>
    <button class="btn" id="add-step">+ Add step</button>
    <span class="hint">A new step starts from the previous step's product.</span>
  </div>`;
  bind(root);
}

function stepCard(s, i) {
  const n = state.data.steps.length;
  return `<div class="step-card" data-step="${s.id}">
    <div class="row step-title">
      <span class="step-no">${n > 1 ? `Step ${i + 1}` : "Conditions"}</span>
      ${n > 1 ? `<input class="grow" placeholder="Step name (e.g. Reduction)" data-sfield="title" data-key="st-${s.id}-title" value="${esc(s.title || "")}">` : ""}
      <label class="inline small">Atmosphere <input list="atmos" class="w-sm" data-sfield="atmosphere" data-key="st-${s.id}-atm" value="${esc(s.atmosphere || "")}"></label>
      ${n > 1 ? `<button class="btn icon danger" data-del-step="${s.id}" title="Delete step ${i + 1}" aria-label="Delete step">✕</button>` : ""}
    </div>
    <div class="stages">
      ${s.conditions.map((k, j) => `<div class="stage" data-cond="${k.id}">
        <span class="stage-no">${j === 0 ? "" : "then"}</span>
        <input class="w-sm" placeholder="Temp (°C, rt)" data-cfield="temperature" data-key="c-${k.id}-t" value="${esc(k.temperature || "")}" list="temps" aria-label="Temperature">
        <input class="w-sm" placeholder="Time (e.g. 2 h)" data-cfield="duration" data-key="c-${k.id}-d" value="${esc(k.duration || "")}" aria-label="Time">
        <input class="grow" placeholder="Note (e.g. dropwise addition)" data-cfield="note" data-key="c-${k.id}-n" value="${esc(k.note || "")}" aria-label="Note">
        <button class="btn icon" data-del-cond="${k.id}" title="Remove stage" aria-label="Remove stage">✕</button>
      </div>`).join("")}
      <div class="row quick-temps"><span class="hint">Add stage:</span>
        ${TEMPS.map((t) => `<button class="chip" data-add-cond="${s.id}" data-temp="${t}">${t === "rt" || t === "reflux" ? t : t + " °C"}</button>`).join("")}
        <button class="chip" data-add-cond="${s.id}" data-temp="">other…</button></div>
    </div>
    ${multiStep() ? `<input class="w-full step-notes" placeholder="Notes for this step (shown in the report)" data-sfield="notes" data-key="st-${s.id}-notes" value="${esc(s.notes || "")}">` : ""}
  </div>`;
}

function bind(root) {
  if (!$("#atmos")) {
    document.body.insertAdjacentHTML("beforeend",
      `<datalist id="atmos">${ATMOS.map((a) => `<option value="${a}">`).join("")}</datalist>
       <datalist id="temps">${["−78", "−40", "0", "rt", "40", "60", "80", "reflux"].map((a) => `<option value="${a}">`).join("")}</datalist>`);
  }
  $("#scheme-style", root).onchange = (e) =>
    mutate("PUT", `/api/experiments/${expId()}`, { scheme_style: e.target.value })
      .then(() => mutate("GET", `/api/experiments/${expId()}`));
  $("#add-step", root).onclick = () => mutate("POST", `/api/experiments/${expId()}/steps`, {});
  $$("[data-sfield]", root).forEach((inp) => inp.addEventListener("change", () => {
    const sid = inp.closest("[data-step]").dataset.step;
    mutate("PUT", `/api/steps/${sid}`, { [inp.dataset.sfield]: inp.value.trim() || null });
  }));
  $$("[data-cfield]", root).forEach((inp) => inp.addEventListener("change", () => {
    const cid = inp.closest("[data-cond]").dataset.cond;
    mutate("PUT", `/api/conditions/${cid}`, { [inp.dataset.cfield]: inp.value.trim() || null });
  }));
  $$("[data-del-cond]", root).forEach((b) => (b.onclick = () => mutate("DELETE", `/api/conditions/${b.dataset.delCond}`)));
  $$("[data-add-cond]", root).forEach((b) => (b.onclick = async () => {
    await mutate("POST", `/api/steps/${b.dataset.addCond}/conditions`, { temperature: b.dataset.temp || null });
    const card = $(`[data-step="${b.dataset.addCond}"]`, root);
    const last = [...card.querySelectorAll(".stage")].pop();
    last?.querySelector(b.dataset.temp ? "[data-cfield=duration]" : "[data-cfield=temperature]")?.focus();
  }));
  $$("[data-del-step]", root).forEach((b) => (b.onclick = () => {
    if (confirm("Delete this step with its reagents and conditions?")) mutate("DELETE", `/api/steps/${b.dataset.delStep}`);
  }));
}
