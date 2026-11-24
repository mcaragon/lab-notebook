/* Reagents section, grouped by role (and by stage for a one-pot reaction in several stages). Planned and actual
   amounts, properties and hazards are on each row; the expandable detail panel edits chemical data, solution form,
   provenance and scheme placement. A starting material can be a portion of another experiment's product. */
import { $, $$, api, autocomplete, esc, fmt, fixed, ghsImg, hCode, hText, nfpaDiamond, parseNum, preserveFocus, toast } from "./util.js";
import { state, mutate, expId, multiStage } from "./state.js";

const GROUPS = [
  { key: "reactant", roles: ["reactant"], title: "Starting materials", add: "reactant",
    hint: "Compounds that end up in the product. The limiting one sets the theoretical yield." },
  { key: "reagent", roles: ["reagent", "catalyst"], title: "Reagents & catalysts", add: "reagent" },
  { key: "solvent", roles: ["solvent"], title: "Solvents", add: "solvent" },
  { key: "workup", roles: ["workup"], title: "Workup & purification", add: "workup",
    hint: "Quench, extraction, washing, drying and chromatography materials. Their hazards go into the report." },
  { key: "product", roles: ["product"], title: "Products", add: "product" },
];
const FORM_LABELS = { neat: "Neat / pure", solution: "Solution (molarity)", wt: "Solution (wt %)" };
const ROLE_LABELS = { reactant: "Starting material", reagent: "Reagent", catalyst: "Catalyst", solvent: "Solvent",
  workup: "Workup", product: "Product" };
const CHEM_FIELDS = [
  ["name", "Name", "text"], ["cas", "CAS", "text"], ["formula", "Formula", "text"], ["mw", "Molar mass (g/mol)", "num"],
  ["density", "Density (g/mL)", "num"], ["bp", "bp (°C)", "num"], ["mp", "mp (°C)", "num"],
  ["flash_point", "Flash point (°C)", "num"], ["refractive_index", "n<sub>D</sub>", "num"], ["smiles", "SMILES", "text"],
];
const SOURCE_PROPS = new Set(["bp", "mp", "density", "flash_point", "refractive_index"]);
const expandedHaz = new Set();

export function renderReagents(root) {
  preserveFocus(root, () => draw(root));
}

function draw(root) {
  const d = state.data;
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Reagents</h2><span class="spacer"></span>
      <span class="hint">Type an amount in any planned column; the rest is calculated. <b>Bold</b> = entered.
      Actual = what you weighed or measured; yields use it.</span></div>
    ${d.steps.map((s, i) => stageBlock(s, i)).join("")}
    ${multiStage() ? `<div class="step-block">${GROUPS.filter((g) => !STAGED.has(g.key)).map((g) =>
      groupBlock(lastStage(), g, d.reagents.filter((r) => g.roles.includes(r.role)), d.stoich)).join("")}</div>` : ""}
  </div>`;
  bind(root);
}

// With several one-pot stages, starting materials, reagents and solvents are listed per stage; workup materials and
// products once for the reaction.
const STAGED = new Set(["reactant", "reagent", "solvent"]);
const lastStage = () => state.data.steps[state.data.steps.length - 1];

function stageBlock(s, i) {
  const multi = multiStage();
  const ids = new Set(state.data.steps.map((x) => x.id));
  const rs = state.data.reagents.filter((r) => r.step_id === s.id || (i === 0 && !ids.has(r.step_id)));
  return `<div class="step-block ${multi ? "staged" : ""}" data-step="${s.id}">
    ${multi ? `<h3 class="step-h"><span class="stage-num">${i + 1}</span>Stage ${i + 1}${s.title ? `: ${esc(s.title)}` : ""}</h3>` : ""}
    ${GROUPS.filter((g) => !multi || STAGED.has(g.key)).map((g) => groupBlock(s, g, rs.filter((r) => g.roles.includes(r.role)), state.data.stoich)).join("")}
  </div>`;
}

function groupBlock(s, g, rows, st) {
  const isProd = g.key === "product";
  const head = isProd
    ? `<div class="rg-head prod"><span></span><span>Compound</span><span class="num">MW</span><span class="num">Coef.</span>
        <span class="num">Theoretical</span><span class="num">Expected</span><span class="num">Crude (g)</span>
        <span class="num">Isolated (g)</span><span class="num">Yield</span><span>Hazards</span><span></span></div>`
    : `<div class="rg-head"><span></span><span>Compound</span><span class="num">MW</span>
        <span class="num grp">Planned · g</span><span class="num">mL</span><span class="num">mmol</span><span class="num">equiv</span>
        <span class="num grp">Actual</span><span>Properties</span><span>Hazards</span><span></span></div>`;
  return `<div class="rgroup" data-group="${g.key}">
    <div class="rg-title"><h4>${g.title}</h4>${g.hint && !rows.length ? `<span class="hint">${g.hint}</span>` : ""}</div>
    ${rows.length ? head + rows.map((r) => (isProd ? productRow(r, st) : inputRow(r, st))).join("") : ""}
    <div class="add-row"><input class="add-q" data-step="${s.id}" data-role="${g.add}" data-key="add-${s.id}-${g.key}"
      placeholder="${isProd ? "Add product" : g.key === "solvent" ? "Add solvent (e.g. THF)" : g.key === "workup"
        ? "Add (e.g. sat. NH4Cl, MgSO4, DCM)" : g.key === "reactant" ? "Add: name, CAS, formula, SMILES, or the product of another experiment"
        : "Add: name, CAS, formula, SMILES, or e.g. 2.5 M n-BuLi in hexanes"}"
      autocomplete="off" aria-label="Add to ${g.title}"></div>
  </div>`;
}

function structThumb(r, w = 120, h = 84) {
  if (!r.cid && !r.smiles) return `<div class="thumb none"></div>`;
  const v = r.cid || encodeURIComponent(r.smiles || "").length;
  return `<img class="thumb struct" src="/api/reagents/${r.id}/structure.svg?width=${w}&height=${h}&v=${v}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb none'}))">`;
}

function compoundCell(r, st) {
  const c = r.calc || {};
  const sub = [r.cas, r.formula].filter(Boolean).map(esc).join(" · ");
  const form = r.form === "solution" && r.concentration_m ? `${fmt(r.concentration_m)} M`
    : r.form === "wt" && r.wt_percent ? `${fmt(r.wt_percent)} wt%`
    : r.purity && r.purity < 100 ? `${fmt(r.purity)}%` : "";
  const prov = [r.grade, r.supplier, r.lot ? `lot ${r.lot}` : ""].filter(Boolean).join(", ");
  const isRef = st.reference_id === r.id;
  return `<div class="cmp">
    <button class="linklike cname" data-toggle="${r.id}" aria-expanded="${state.open.has(r.id)}">${esc(r.name || "?")}</button>
    ${r.role === "catalyst" ? '<span class="badge">cat.</span>' : ""}
    ${form ? `<span class="badge">${esc(form)}</span>` : ""}
    ${c.is_limiting ? '<span class="badge lim">limiting</span>' : ""}
    ${isRef && r.role !== "product" && !["solvent", "workup"].includes(r.role) ? '<span class="badge ref" title="Equivalents are relative to this reagent">1 equiv ref.</span>' : ""}
    ${sourceBadge(r)}${stockChip(r)}
    <div class="sub">${sub}</div>
    ${prov ? `<div class="sub">${esc(prov)}</div>` : ""}
    ${r.notes ? `<div class="sub note">${esc(r.notes)}</div>` : ""}
    ${Object.keys(r.usage || {}).length && ["solvent", "workup"].includes(r.role) ? `<div class="sub">Used (log): ${Object.entries(r.usage).map(([u, v]) => `${fmt(v)} ${u}`).join(", ")}</div>` : ""}
    ${(c.warnings || []).length ? `<div class="warnings">⚠ ${c.warnings.map(esc).join(" ")}</div>` : ""}
  </div>`;
}

// ------------------------------------------------------------------------------------------- stockroom link
const money = (v) => {
  if (v == null) return "";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: state.user?.currency || "USD",
      maximumFractionDigits: v !== 0 && Math.abs(v) < 1 ? 4 : 2 }).format(v);
  } catch { return v.toFixed(2); }
};
const stockLine = (i) => [i.supplier || "unknown supplier", i.grade, i.purity ? `${fmt(i.purity)}%` : "", i.lot ? `lot ${i.lot}` : "",
  i.left != null ? `${fmt(i.left, 4)} ${i.unit} left` : "", i.unit_price != null ? `${money(i.unit_price)}/${i.unit}` : "", i.location]
  .filter(Boolean).join(" · ");

/** The container a row is drawn from, or a hint that the compound is in the stockroom. */
function stockChip(r) {
  if (r.role === "product") return "";
  if (r.stock) {
    const s = r.stock;
    return `<button class="badge stock ${s.low ? "low" : ""}" data-stock="${r.id}" title="Drawn from: ${esc(stockLine(s))}. Click to change.">📦 ${esc(s.supplier || "stockroom")}${s.lot ? ` · ${esc(s.lot)}` : ""}${s.left != null ? ` · ${esc(fmt(s.left, 3))} ${esc(s.unit)} left` : ""}</button>`;
  }
  return r.stock_count ? `<button class="badge stock add" data-stock="${r.id}" title="Pick the container this comes from">📦 in stock (${r.stock_count})</button>` : "";
}

async function openStockPicker(btn) {
  $$(".stock-pick").forEach((x) => x.remove());
  const r = state.data.reagents.find((x) => x.id === Number(btn.dataset.stock));
  const params = new URLSearchParams({ q: r.name || "", limit: "12" });
  if (r.cid) params.set("cid", r.cid);
  let items = [];
  try { items = (await api("GET", `/api/stockroom/match?${params}`)).items; } catch (e) { toast(e.message, true); return; }
  const box = document.createElement("div");
  box.className = "stock-pick menu-list";
  box.innerHTML = `${items.length ? items.map((i) => `<button data-pick="${i.id}" class="${r.stock_item_id === i.id ? "on" : ""}">
      <b>${esc(i.label || i.name)}</b><span class="sub">${esc(stockLine(i))}</span></button>`).join("")
      : '<span class="menu-note">No container of this compound in use.</span>'}
    ${r.stock_item_id ? '<button data-pick="">Not from the stockroom (unlink)</button>' : ""}
    <a href="#/stockroom" class="menu-note">Open the stockroom ↗</a>`;
  btn.insertAdjacentElement("afterend", box);
  const close = (e) => { if (!box.contains(e.target) && e.target !== btn) { box.remove(); document.removeEventListener("mousedown", close); } };
  setTimeout(() => document.addEventListener("mousedown", close), 0);
  $$("[data-pick]", box).forEach((b) => (b.onclick = () => {
    box.remove();
    const id = b.dataset.pick ? Number(b.dataset.pick) : null;
    if (id === r.stock_item_id) return;
    put(r.id, { stock_item_id: id });
  }));
}

function sourceBadge(r) {
  if (!r.source_reagent_id) return "";
  const s = (state.data.route?.sources || []).find((x) => x.reagent_id === r.id);
  if (!s) return "";
  if (s.missing) return '<span class="badge alert" title="The experiment this came from was deleted">source deleted</span>';
  return `<a class="badge link" href="#/exp/${s.experiment_id}/results" title="A portion of the product of “${esc(s.experiment)}”">from ${esc(s.experiment)}</a>`;
}

function amountInput(r, field, value, digits, st) {
  const entered = r.basis === field && r.basis_value != null;
  const disabled = field === "equiv" && st.reference_id === r.id && !entered;
  const shown = entered ? String(r.basis_value) : value == null ? "" : digits ? fixed(value, digits) : fmt(value, 4);
  return `<input class="amt ${entered ? "entered" : "computed"}" inputmode="decimal" data-rid="${r.id}" data-amt="${field}"
    data-key="amt-${r.id}-${field}" value="${esc(shown)}" ${disabled ? "disabled title='Reference reagent: 1 equiv'" : ""} aria-label="Planned ${field}">`;
}

const isLiquid = (r) => r.form !== "neat" || ["solvent", "workup"].includes(r.role)
  || (r.mp != null && r.mp < 25 && r.density) || r.basis === "volume";

function actualCell(r) {
  const c = r.calc || {};
  const unit = r.actual_basis || (r.basis === "mass" ? "mass" : r.basis === "volume" ? "volume" : isLiquid(r) ? "volume" : "mass");
  const dev = c.deviation_pct;
  const derived = r.actual_value != null ? [unit === "volume" && c.act_mass_g != null ? `${fmt(c.act_mass_g)} g` : "",
    unit === "mass" && c.act_volume_ml != null ? `${fmt(c.act_volume_ml)} mL` : "",
    c.act_mmol != null ? `${fmt(c.act_mmol)} mmol` : "", c.act_equiv != null ? `${fixed(c.act_equiv, 2)} eq` : ""].filter(Boolean).join(" · ") : "";
  return `<div class="actual">
    <div class="act-in"><input class="amt entered" inputmode="decimal" data-actual="${r.id}" data-unit="${unit}" data-key="act-${r.id}"
      value="${r.actual_value == null ? "" : esc(r.actual_value)}" placeholder="—" aria-label="Actual amount">
      <button class="unit-btn" data-unit-toggle="${r.id}" data-unit="${unit}" title="Switch between g and mL">${unit === "volume" ? "mL" : "g"}</button></div>
    ${dev != null ? `<span class="dev ${Math.abs(dev) < 0.05 ? "" : dev < 0 ? "neg" : "pos"}">${dev >= 0 ? "+" : ""}${dev.toFixed(1)}%</span>` : ""}
    ${derived ? `<div class="sub">${derived}</div>` : ""}
  </div>`;
}

function propsCell(r) {
  const v = (x, d = 0) => (x == null ? "–" : fixed(x, d));
  return `<div class="props">
    ${r.density ? `<div>d ${fmt(r.density)}</div>` : ""}
    <div>bp ${v(r.bp)} · mp ${v(r.mp)}</div>
  </div>`;
}

function hazardCell(r) {
  const x = r.extra_hazards || {};
  const dot = x.dot || {};
  // PubChem's GHS list also has "Not Classified" / "Reported as not meeting GHS hazard criteria…" lines: not H-statements
  const raw = r.hazard_statements || [];
  const hs = raw.filter((h) => /^\s*(EU)?H\d{3}/.test(h)).map(hText);
  const notClassified = !hs.length && raw.some((h) => /not classified|not meeting ghs/i.test(h));
  const uniq = [...new Map(hs.map((h) => [hCode(h), h])).values()];
  const open = expandedHaz.has(r.id);
  const shown = open ? uniq : uniq.slice(0, 3);
  const dotTxt = [...(dot.un || []), ...(dot.classes || []).filter((c) => !/forbidden/i.test(c)).map((c) => c.replace(/^(Class|Div)\s+([\d.]+).*/, "$1 $2")).slice(0, 2),
    (dot.packing_groups || []).length ? "PG " + dot.packing_groups.join("/") : ""].filter(Boolean);
  const none = !uniq.length && !notClassified && !r.signal_word && !(r.pictograms || []).length && !dot.classes && !x.nfpa && !(x.alerts || []).length && !r.hazard_notes;
  return `<div class="haz">
    <div class="haz-top">${(r.pictograms || []).map((p) => ghsImg(p)).join("")}
      ${x.nfpa ? nfpaDiamond(x.nfpa, 24) : ""}
      ${r.signal_word ? `<span class="sw ${r.signal_word.toLowerCase()}">${esc(r.signal_word)}</span>` : ""}
      ${r.flash_point != null ? `<span class="fp" title="Flash point">fp ${fixed(r.flash_point, 0)} °C</span>` : ""}</div>
    ${dot.forbidden ? `<div class="forbidden" title="${esc((dot.classes || []).join("; "))}">DOT: forbidden for transport</div>` : ""}
    ${dotTxt.length ? `<div class="sub" title="${esc((dot.classes || []).join("; "))}">DOT ${esc(dotTxt.join(" · "))}</div>` : ""}
    ${(x.alerts || []).length ? `<div>${x.alerts.map((a) => `<span class="badge alert">${esc(a)}</span>`).join("")}</div>` : ""}
    ${shown.length ? `<ul class="hz">${shown.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}
    ${uniq.length > 3 ? `<button class="linklike small" data-haz-more="${r.id}">${open ? "show less" : `+${uniq.length - 3} more`}</button>` : ""}
    ${notClassified ? '<div class="sub">Not classified (GHS)</div>' : ""}
    ${r.hazard_notes ? `<div class="sub note">${esc(r.hazard_notes)}</div>` : ""}
    ${none ? `<span class="sub">${r.cid ? "No hazard data in PubChem Local" : "—"}</span>` : ""}
  </div>`;
}

function inputRow(r, st) {
  const c = r.calc || {};
  const solv = ["solvent", "workup"].includes(r.role);
  const cls = ["rrow", c.is_limiting ? "limiting" : "", state.open.has(r.id) ? "open" : ""].join(" ");
  return `<div class="${cls}" data-rid="${r.id}">
    <div class="c-thumb">${structThumb(r)}</div>
    <div class="c-name">${compoundCell(r, st)}</div>
    <div class="c-mw num" data-label="MW">${fixed(r.mw, 2)}</div>
    <div class="c-mass num" data-label="g">${amountInput(r, "mass", c.mass_g, 0, st)}</div>
    <div class="c-vol num" data-label="mL">${amountInput(r, "volume", c.volume_ml, 0, st)}</div>
    <div class="c-mmol num" data-label="mmol">${solv ? "" : amountInput(r, "mmol", c.mmol, 0, st)}</div>
    <div class="c-eq num" data-label="equiv">${solv ? "" : amountInput(r, "equiv", c.equiv, 2, st)}</div>
    <div class="c-act" data-label="Actual">${actualCell(r)}</div>
    <div class="c-props" data-label="Properties">${propsCell(r)}</div>
    <div class="c-haz">${hazardCell(r)}</div>
    <div class="c-menu"><button class="btn icon danger" data-del="${r.id}" title="Remove ${esc(r.name)}" aria-label="Remove">✕</button></div>
  </div>${state.open.has(r.id) ? `<div class="rdetail">${detailPanel(r)}</div>` : ""}`;
}

function productRow(r, st) {
  const c = r.calc || {};
  const refs = state.data.refs;
  return `<div class="rrow prod ${state.open.has(r.id) ? "open" : ""}" data-rid="${r.id}">
    <div class="c-thumb">${structThumb(r)}</div>
    <div class="c-name">${compoundCell(r, st)}</div>
    <div class="c-mw num" data-label="MW">${fixed(r.mw, 2)}</div>
    <div class="num" data-label="Coef."><input class="amt sm" inputmode="decimal" data-field="coefficient" data-num="1" data-rid="${r.id}" data-key="coef-${r.id}" value="${esc(r.coefficient ?? 1)}" aria-label="Coefficient"></div>
    <div class="num" data-label="Theoretical">${c.theoretical_mass_g != null ? `${fmt(c.theoretical_mass_g)} g<div class="sub">${fmt(c.theoretical_mmol)} mmol</div>` : "–"}</div>
    <div class="num" data-label="Expected">
      <span class="pct-in"><input class="amt sm" inputmode="decimal" data-field="expected_yield_pct" data-num="1" data-rid="${r.id}" data-key="exp-${r.id}" value="${r.expected_yield_pct ?? ""}" placeholder="lit." aria-label="Expected yield %">%</span>
      ${refs.length ? `<select class="ref-sel" data-field="expected_ref_id" data-rid="${r.id}" data-num="1" data-key="expref-${r.id}" aria-label="Literature reference">
        <option value="">ref.</option>${refs.map((x, i) => `<option value="${x.id}" ${r.expected_ref_id === x.id ? "selected" : ""}>[${i + 1}]</option>`).join("")}</select>` : ""}
      ${c.expected_mass_g != null ? `<div class="sub">${fmt(c.expected_mass_g)} g</div>` : ""}</div>
    <div class="num" data-label="Crude (g)"><input class="amt" inputmode="decimal" data-field="crude_mass_g" data-num="1" data-rid="${r.id}" data-key="crude-${r.id}" value="${r.crude_mass_g ?? ""}" aria-label="Crude mass (g)">
      ${c.crude_percent != null ? `<div class="sub">${c.crude_percent.toFixed(0)}%</div>` : ""}</div>
    <div class="num" data-label="Isolated (g)"><input class="amt entered" inputmode="decimal" data-field="actual_mass_g" data-num="1" data-rid="${r.id}" data-key="iso-${r.id}" value="${r.actual_mass_g ?? ""}" aria-label="Isolated mass (g)">
      ${c.isolated_mmol != null ? `<div class="sub">${fmt(c.isolated_mmol)} mmol</div>` : ""}</div>
    <div class="num yield" data-label="Yield">${c.percent_yield != null ? c.percent_yield.toFixed(1) + "%" : "–"}</div>
    <div class="c-haz">${hazardCell(r)}</div>
    <div class="c-menu"><button class="btn icon danger" data-del="${r.id}" title="Remove ${esc(r.name)}" aria-label="Remove">✕</button></div>
  </div>${state.open.has(r.id) ? `<div class="rdetail">${detailPanel(r)}</div>` : ""}`;
}

function srcBadge(r, k) {
  const s = (r.sources || {})[k];
  if (!s) return "";
  const revert = s === "manual" && r.cid ? ` <button class="linklike small" data-revert="${r.id}" data-field="${k}" title="Restore the PubChem value">↺</button>` : "";
  return `<span class="src ${s}" title="${s === "pubchem" ? "From PubChem Local" : "Entered or edited by you"}">${s === "pubchem" ? "PubChem" : "edited"}</span>${revert}`;
}

function field(r, k, label, { num = false, placeholder = "", list = "" } = {}) {
  return `<label class="field"><span>${label}</span><input data-rid="${r.id}" data-field="${k}" ${num ? 'data-num="1" inputmode="decimal"' : ""}
    data-key="d-${r.id}-${k}" value="${esc(r[k] ?? "")}" placeholder="${esc(placeholder)}" ${list ? `list="${list}"` : ""}></label>`;
}

function detailPanel(r) {
  const x = r.extra_hazards || {};
  const dot = x.dot || {};
  const form = r.form === "solution"
    ? field(r, "concentration_m", "Concentration (M)", { num: true }) + field(r, "solution_density", "Solution density (g/mL)", { num: true, placeholder: "optional" })
    : r.form === "wt" ? field(r, "wt_percent", "Weight percent (%)", { num: true }) + field(r, "solution_density", "Solution density (g/mL)", { num: true })
    : field(r, "purity", "Purity (%)", { num: true, placeholder: "100" });
  const roles = r.role === "product" ? ["product"] : ["reactant", "reagent", "catalyst", "solvent", "workup", "product"];
  return `<div class="detail-grid"><div>
    <div class="grid">
      ${CHEM_FIELDS.map(([k, label, type]) => `<label class="field"><span>${label} ${srcBadge(r, k)}
        ${SOURCE_PROPS.has(k) && r.cid ? `<button class="linklike small" data-sources="${r.cid}" data-prop="${k}" data-rid="${r.id}">sources</button>` : ""}</span>
        <input data-rid="${r.id}" data-field="${k}" ${type === "num" ? 'data-num="1" inputmode="decimal"' : ""} data-key="d-${r.id}-${k}" value="${esc(r[k] ?? "")}"></label>`).join("")}
    </div>
    <div class="sources" id="src-${r.id}"></div>
    <h5>Amount</h5>
    <div class="grid">
      <label class="field"><span>Role</span><select data-rid="${r.id}" data-field="role" data-key="d-${r.id}-role">${roles.map((x) =>
        `<option value="${x}" ${r.role === x ? "selected" : ""}>${ROLE_LABELS[x]}</option>`).join("")}</select></label>
      <label class="field"><span>Form</span><select data-rid="${r.id}" data-field="form" data-key="d-${r.id}-form">${state.config.forms.map((f) =>
        `<option value="${f}" ${r.form === f ? "selected" : ""}>${FORM_LABELS[f]}</option>`).join("")}</select></label>
      ${form}
      ${r.role !== "product" ? field(r, "coefficient", "Stoich. coefficient", { num: true, placeholder: "1" }) : ""}
      ${r.role !== "product" && !["solvent", "workup"].includes(r.role) ? `<label class="field"><span>Reference</span>
        <button class="btn" data-ref="${r.id}">Use as 1 equiv</button></label>` : ""}
    </div>
    <h5>Provenance</h5>
    <div class="grid">
      ${field(r, "grade", "Grade", { placeholder: "e.g. ReagentPlus, 99%" })}${field(r, "supplier", "Supplier")}${field(r, "lot", "Lot number")}
    </div>
    <label class="field"><span>Notes (shown in the report)</span><input data-rid="${r.id}" data-field="notes" data-key="d-${r.id}-notes" value="${esc(r.notes || "")}"></label>
    <h5>Scheme</h5>
    <div class="grid">
      ${field(r, "label", "Short label", { placeholder: r.formula || "e.g. NaBH4" })}
      <label class="field"><span>Show in scheme</span><select data-rid="${r.id}" data-field="scheme_pos" data-key="d-${r.id}-sp">
        ${[["auto", "Automatic"], ["above", "Above the arrow"], ["below", "Below the arrow"], ["structure", "As a structure"], ["hidden", "Hidden"]].map(([k, v]) =>
          `<option value="${k}" ${(r.scheme_pos || "auto") === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    </div>
    <h5>Hazards</h5>
    <label class="field"><span>Additional hazard information (shown in the report)</span>
      <input data-rid="${r.id}" data-field="hazard_notes" data-key="d-${r.id}-hn" value="${esc(r.hazard_notes || "")}"
        placeholder="e.g. Primary explosive: friction and shock sensitive when dry"></label>
    ${r.cid ? `<div class="row small" style="margin-top:10px"><button class="btn" data-revert="${r.id}">↺ Reload all values from PubChem Local</button>
      <a href="${esc(r.pubchem_url || `https://pubchem.ncbi.nlm.nih.gov/compound/${r.cid}`)}" target="_blank" rel="noopener">PubChem CID ${r.cid}</a></div>` : ""}
  </div><div>
    ${r.cid || r.smiles ? `<img class="struct big" src="/api/reagents/${r.id}/structure.svg?width=300&height=220&v=${r.cid || 0}" alt="Structure of ${esc(r.name)}" onerror="this.remove()">` : ""}
    ${r.signal_word ? `<div><b>${esc(r.signal_word)}</b> ${(r.pictograms || []).map((p) => ghsImg(p)).join("")}</div>` : ""}
    ${(r.hazard_statements || []).length ? `<ul class="hz full">${r.hazard_statements.map((h) => `<li>${esc(hText(h))}</li>`).join("")}</ul>` : ""}
    ${dot.classes ? `<div class="small"><b>DOT</b> ${esc([...(dot.un || []), ...dot.classes, ...(dot.packing_groups || []).map((p) => "PG " + p)].join("; "))}
      ${(dot.placards || []).length ? `<br>Placards: ${esc(dot.placards.join("; "))}` : ""}</div>` : ""}
    ${x.nfpa ? `<div class="small row">${nfpaDiamond(x.nfpa, 40)} NFPA 704: health ${x.nfpa.health}, fire ${x.nfpa.fire}, instability ${x.nfpa.instability}${x.nfpa.special ? ", " + esc(x.nfpa.special) : ""}</div>` : ""}
  </div></div>`;
}

// ------------------------------------------------------------------------------------------- events
const put = (rid, body) => mutate("PUT", `/api/reagents/${rid}`, body).catch(() => renderReagents($("#sec-reagents")));

function bind(root) {
  $$(".add-q", root).forEach(setupAdd);
  $$("[data-stock]", root).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openStockPicker(b); }));
  $$("[data-toggle]", root).forEach((b) => (b.onclick = () => {
    const id = Number(b.dataset.toggle);
    state.open.has(id) ? state.open.delete(id) : state.open.add(id);
    renderReagents(root);
  }));
  $$("[data-haz-more]", root).forEach((b) => (b.onclick = () => {
    const id = Number(b.dataset.hazMore);
    expandedHaz.has(id) ? expandedHaz.delete(id) : expandedHaz.add(id);
    renderReagents(root);
  }));
  $$("[data-del]", root).forEach((b) => (b.onclick = () => {
    const r = state.data.reagents.find((x) => x.id === Number(b.dataset.del));
    if (confirm(`Remove ${r?.name || "this chemical"}?`)) mutate("DELETE", `/api/reagents/${b.dataset.del}`);
  }));
  $$("[data-ref]", root).forEach((b) => (b.onclick = () => put(b.dataset.ref, { is_reference: true })));
  $$("input[data-amt]", root).forEach((inp) => inp.addEventListener("change", () => {
    const v = parseNum(inp.value);
    const r = state.data.reagents.find((x) => x.id === Number(inp.dataset.rid));
    if (Number.isNaN(v) || (v !== null && v < 0)) { toast("Enter a positive number.", true); renderReagents(root); return; }
    if (v === null) {
      if (r.basis === inp.dataset.amt) put(r.id, { basis: null, basis_value: null });
      else renderReagents(root);
      return;
    }
    put(r.id, { basis: inp.dataset.amt, basis_value: v });
  }));
  $$("input[data-actual]", root).forEach((inp) => inp.addEventListener("change", () => {
    const v = parseNum(inp.value);
    if (Number.isNaN(v) || (v !== null && v < 0)) { toast("Enter a positive number.", true); renderReagents(root); return; }
    put(inp.dataset.actual, { actual_basis: v === null ? null : inp.dataset.unit, actual_value: v });
  }));
  $$("[data-unit-toggle]", root).forEach((b) => (b.onclick = () => {
    const r = state.data.reagents.find((x) => x.id === Number(b.dataset.unitToggle));
    const next = b.dataset.unit === "volume" ? "mass" : "volume";
    if (r.actual_value != null) put(r.id, { actual_basis: next });
    else { b.dataset.unit = next; b.textContent = next === "volume" ? "mL" : "g"; b.previousElementSibling.dataset.unit = next; }
  }));
  $$("[data-field]", root).forEach((inp) => {
    if (inp.tagName === "BUTTON") return;
    inp.addEventListener("change", () => {
      let v = inp.value;
      if (inp.dataset.num) {
        v = parseNum(v);
        if (Number.isNaN(v)) { toast("Enter a number.", true); renderReagents(root); return; }
      } else if (inp.tagName !== "SELECT") v = v.trim() || null;
      put(inp.dataset.rid, { [inp.dataset.field]: v });
    });
  });
  $$("[data-revert]", root).forEach((b) => (b.onclick = async () => {
    const body = b.dataset.field ? { fields: [b.dataset.field] } : {};
    if (!b.dataset.field && !confirm("Replace all chemical and hazard data of this row (including your edits) with the PubChem Local values?")) return;
    mutate("POST", `/api/reagents/${b.dataset.revert}/refresh`, body).catch(() => {});
  }));
  $$("[data-sources]", root).forEach((b) => (b.onclick = async (e) => {
    e.preventDefault();
    const box = $(`#src-${b.dataset.rid}`, root);
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

function setupAdd(input) {
  const stepId = Number(input.dataset.step);
  const role = input.dataset.role;
  let chosen = null;
  const ac = autocomplete(input, async (q) => {
    // products of other experiments can be used as starting materials: that links the experiments
    let local = [];
    if (role === "reactant") {
      try {
        const { products } = await api("GET", `/api/products?q=${encodeURIComponent(q)}&exclude=${expId()}&limit=5`);
        local = products.map((p) => ({ label: p.label || p.name, carry: p.id,
          sub: `product of ${p.experiment}${p.remaining_g != null ? ` · ${fmt(p.remaining_g)} g left` : ""}` }));
      } catch { /* ignore */ }
    }
    // containers in the stockroom come first: picking one fills the row and links it
    let stockItems = [];
    if (role !== "product") {
      try {
        stockItems = (await api("GET", `/api/stockroom/match?q=${encodeURIComponent(q)}&limit=6`)).items
          .map((i) => ({ label: `📦 ${i.label || i.name}`, sub: stockLine(i), stock: i.id }));
      } catch { /* ignore */ }
    }
    let remote = [];
    try {
      const res = await api("GET", `/api/pubchem/autocomplete?q=${encodeURIComponent(q)}&limit=8`);
      const parsed = res.parsed || {};
      const tag = parsed.concentration_m ? ` (${parsed.concentration_m} M solution)` : parsed.wt_percent ? ` (${parsed.wt_percent} wt%)` : "";
      remote = res.suggestions.map((s) => ({ label: s.name + tag, sub: `CID ${s.cid}`, cid: s.cid, parsed }));
    } catch { /* PubChem Local offline: typed names still work */ }
    return [...stockItems, ...local, ...remote];
  }, (item) => { chosen = item; add(); }, { minChars: 2 });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  input.addEventListener("input", () => { chosen = null; });
  async function add() {
    const q = input.value.trim();
    if (!q && !chosen) return;
    ac.cancel();
    let body;
    if (chosen?.stock) body = { stock_item_id: chosen.stock, role, step_id: stepId };
    else if (chosen?.carry) body = { source_reagent_id: chosen.carry, step_id: stepId };
    else if (chosen?.cid) body = { cid: chosen.cid, role, step_id: stepId, ...(chosen.parsed || {}) };
    else body = { query: q, role, step_id: stepId };
    if (role === "reagent" && /\b(cat\.?|catalyst)\b/i.test(q)) body.role = "catalyst";
    input.disabled = true;
    try {
      const d = await mutate("POST", `/api/experiments/${expId()}/reagents`, body);
      if (d.warning) { toast(d.warning, true); state.open.add(d.reagent_id); renderReagents($("#sec-reagents")); }
      chosen = null;
      const again = $(`.add-q[data-key="${input.dataset.key}"]`);
      if (again) { again.value = ""; again.focus(); }
    } catch { /* toast shown */ }
    finally { input.disabled = false; }
  }
}
