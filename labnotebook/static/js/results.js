/* Results (yields and write-up), references (rows) and report export. */
import { $, $$, esc, fmt, preserveFocus } from "./util.js";
import { state, mutate, expId } from "./state.js";
import { sectionField, bindSections } from "./expfields.js";

export function renderResults(root) {
  if (root.dataset.drawn) { updateYields(root); return; }
  root.dataset.drawn = "1";
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Results</h2></div>
    <div id="yields"></div>
    <div id="costs"></div>
    ${sectionField("results", "Results", "Characterization: appearance, mp, TLC, IR/NMR data (Markdown)", 6)}
    <div class="gap"></div>${sectionField("discussion", "Discussion", "", 6)}
    <div class="gap"></div>${sectionField("conclusion", "Conclusion", "", 3)}
  </div>`;
  bindSections(root);
  updateYields(root);
}

export const money = (v, cur) => {
  if (v == null) return "–";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: cur || "USD",
      maximumFractionDigits: v !== 0 && Math.abs(v) < 1 ? 4 : 2 }).format(v);
  } catch { return v.toFixed(2); }
};

function costPanel(d) {
  const c = d.cost;
  if (!c || !c.inputs.length) return "";
  const cur = d.currency;
  const p = c.product || {};
  const src = (x) => (!x.source ? "" : x.source.kind === "stock" ? `📦 ${esc([x.source.supplier, x.source.lot ? `lot ${x.source.lot}` : ""].filter(Boolean).join(" · ") || "stockroom")}`
    : `<a href="#/exp/${x.source.experiment_id}/results">⇢ from an earlier step</a>`);
  const rows = [...c.inputs].sort((a, b) => (b.cost ?? -1) - (a.cost ?? -1));
  return `<h3 class="cost-h">Cost</h3>
    <div class="cost-kpis">
      <div class="kpi"><span class="k-l">Experiment</span><span class="k-v">${c.total != null ? money(c.total, cur) : "–"}</span>
        <span class="k-s">${c.complete ? (c.estimated ? "estimated from planned amounts" : "from measured amounts") : `incomplete: ${c.unpriced.length} without a price`}</span></div>
      <div class="kpi"><span class="k-l">${esc(p.name || "Product")}</span><span class="k-v">${p.cost_per_g != null ? `${c.complete ? "" : "≥ "}${money(p.cost_per_g, cur)}<small>/g</small>` : "–"}</span>
        <span class="k-s">${p.cost_per_g != null ? `${p.crude ? "crude mass" : `${fmt(p.mass_g)} g isolated`}${p.cost_per_mmol != null ? ` · ${money(p.cost_per_mmol, cur)}/mmol` : ""}` : "enter the isolated mass"}</span></div>
    </div>
    <table class="cost-table"><thead><tr><th>Input</th><th>Source</th><th class="num">Amount</th><th class="num">Price</th><th class="num">Cost</th><th>Share</th></tr></thead>
      <tbody>${rows.map((x) => `<tr class="${x.cost == null ? "unpriced" : ""}">
        <td>${esc(x.name)}</td><td class="sub">${src(x)}</td>
        <td class="num">${x.amount != null ? `${fmt(x.amount)} ${esc(x.unit)}${x.estimated ? ' <span class="tag" title="Planned amount: nothing measured yet">planned</span>' : ""}` : "–"}</td>
        <td class="num">${x.unit_price != null ? `${money(x.unit_price, cur)}/${esc(x.unit)}` : "–"}</td>
        <td class="num">${x.cost != null ? money(x.cost, cur) : `<span class="sub">${esc(x.why || "no price")}</span>`}</td>
        <td>${x.share != null ? `<span class="share"><span style="width:${Math.round(x.share * 100)}%"></span></span> ${Math.round(x.share * 100)}%` : ""}</td></tr>`).join("")}</tbody></table>
    ${!c.complete ? `<p class="hint">Link the inputs without a price to stockroom containers (📦 chip on the reagent row) to complete the cost.</p>` : ""}`;
}

function updateYields(root) {
  const d = state.data;
  const cbox = $("#costs", root);
  if (cbox) cbox.innerHTML = costPanel(d);
  const rows = d.reagents.filter((r) => r.role === "product").map((r) => ({ r }));
  const box = $("#yields", root);
  if (!rows.length) {
    box.innerHTML = `<p class="empty">Add the product under Reagents → Products to calculate yields.</p>`;
    return;
  }
  box.innerHTML = `<div class="yield-cards">${rows.map(({ r }) => {
    const c = r.calc || {};
    const ref = d.refs.findIndex((x) => x.id === r.expected_ref_id);
    return `<div class="ycard">
      <div class="ytitle"><b>${esc(r.name)}</b></div>
      <dl>
        <dt>Theoretical</dt><dd>${c.theoretical_mass_g != null ? `${fmt(c.theoretical_mass_g)} g <span class="sub">${fmt(c.theoretical_mmol)} mmol</span>` : "–"}</dd>
        <dt>Expected</dt><dd>${c.expected_yield_pct != null ? `${c.expected_yield_pct}%${ref >= 0 ? ` [${ref + 1}]` : ""}${c.expected_mass_g != null ? ` <span class="sub">${fmt(c.expected_mass_g)} g</span>` : ""}` : "–"}</dd>
        <dt>Crude</dt><dd>${c.crude_mass_g != null ? `${fmt(c.crude_mass_g)} g${c.crude_percent != null ? ` <span class="sub">${c.crude_percent.toFixed(0)}%</span>` : ""}` : "–"}</dd>
        <dt>Isolated</dt><dd>${c.isolated_mass_g != null ? `${fmt(c.isolated_mass_g)} g${c.isolated_mmol != null ? ` <span class="sub">${fmt(c.isolated_mmol)} mmol</span>` : ""}` : "–"}</dd>
        <dt>Actual yield</dt><dd class="yield">${c.percent_yield != null ? c.percent_yield.toFixed(1) + "%" : "–"}</dd>
      </dl></div>`;
  }).join("")}</div>
  <p class="hint">Enter masses in Reagents → Products, or log “Product mass” while working. The theoretical yield uses the actual amounts of the starting materials.</p>`;
}

// ------------------------------------------------------------------------------------------- references
const REF_FIELDS = [["authors", "Authors", "Smith, J.; Doe, A."], ["title", "Title", ""], ["source", "Journal / book", "J. Org. Chem."],
  ["year", "Year", ""], ["volume", "Volume", ""], ["pages", "Pages", ""], ["doi", "DOI", "10.1021/…"], ["url", "URL", ""]];
const openRefs = new Set();

export function renderRefs(root) {
  preserveFocus(root, () => {
    const refs = state.data.refs;
    root.innerHTML = `<div class="panel">
      <div class="row sec-head"><h2>References</h2><span class="spacer"></span>
        <span class="hint">PubChem citations for linked chemicals are added to the report after these.</span></div>
      <ol class="refs">${refs.map((r, i) => refRow(r, i)).join("")}</ol>
      <div class="row"><input id="ref-new" class="grow" data-key="ref-new" placeholder="Add a reference: paste a citation or a DOI, or type a source (e.g. Lab manual, exp. 7)">
        <button class="btn" id="ref-add">Add</button></div>
    </div>`;
    bindRefs(root);
  });
}

function summary(r) {
  if (!["authors", "title", "source", "doi", "url"].some((k) => r[k])) return esc(r.text || "(empty)");
  const src = [r.source && esc(r.source), r.year && `<b>${esc(r.year)}</b>`, r.volume && `<i>${esc(r.volume)}</i>`, r.pages && esc(r.pages)]
    .filter(Boolean).join(", ");
  return [r.authors && esc(r.authors), r.title && esc(r.title), src, r.doi ? `DOI: ${esc(r.doi)}` : r.url && esc(r.url), r.text && esc(r.text)]
    .filter(Boolean).join(". ");
}

function refRow(r, i) {
  const open = openRefs.has(r.id);
  return `<li class="ref" data-ref="${r.id}">
    <div class="row"><span class="ref-sum grow">${summary(r)}</span>
      <button class="btn icon" data-ref-edit="${r.id}" title="Edit fields" aria-label="Edit reference ${i + 1}">✎</button>
      <button class="btn icon" data-ref-move="${r.id}" data-dir="-1" title="Move up" aria-label="Move up">↑</button>
      <button class="btn icon danger" data-ref-del="${r.id}" title="Delete" aria-label="Delete reference ${i + 1}">✕</button></div>
    ${open ? `<div class="grid ref-grid">${REF_FIELDS.map(([k, label, ph]) => `<label class="field"><span>${label}</span>
      <input data-rfield="${k}" data-key="rf-${r.id}-${k}" value="${esc(r[k] || "")}" placeholder="${esc(ph)}"></label>`).join("")}
      <label class="field wide"><span>Free text / note</span><input data-rfield="text" data-key="rf-${r.id}-text" value="${esc(r.text || "")}"></label></div>` : ""}
  </li>`;
}

function bindRefs(root) {
  const add = async () => {
    const v = $("#ref-new", root).value.trim();
    if (!v) return;
    const doi = v.match(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)?(10\.\d{4,9}\/\S+)$/i);
    await mutate("POST", `/api/experiments/${expId()}/refs`, doi ? { doi: doi[1] } : { text: v });
    const again = $("#ref-new");
    if (again) { again.value = ""; again.focus(); }
  };
  $("#ref-add", root).onclick = add;
  $("#ref-new", root).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  $$("[data-ref-edit]", root).forEach((b) => (b.onclick = () => {
    const id = Number(b.dataset.refEdit);
    openRefs.has(id) ? openRefs.delete(id) : openRefs.add(id);
    renderRefs(root);
  }));
  $$("[data-ref-del]", root).forEach((b) => (b.onclick = () => { if (confirm("Delete this reference?")) mutate("DELETE", `/api/refs/${b.dataset.refDel}`); }));
  $$("[data-ref-move]", root).forEach((b) => (b.onclick = () => {
    const ids = state.data.refs.map((r) => r.id);
    const i = ids.indexOf(Number(b.dataset.refMove)), j = i + Number(b.dataset.dir);
    if (j < 0) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    mutate("PUT", `/api/experiments/${expId()}/refs/order`, ids);
  }));
  $$("[data-rfield]", root).forEach((inp) => inp.addEventListener("change", () => {
    const id = inp.closest("[data-ref]").dataset.ref;
    mutate("PUT", `/api/refs/${id}`, { [inp.dataset.rfield]: inp.value.trim() || null });
  }));
}

// ------------------------------------------------------------------------------------------- report
export function renderReport(root) {
  const id = expId();
  let withCosts = false;  // off by default
  const q = (extra = "") => { const p = [extra, withCosts ? "costs=true" : ""].filter(Boolean).join("&"); return p ? `?${p}` : ""; };
  root.innerHTML = `<div class="panel">
    <div class="row sec-head"><h2>Report</h2><span class="spacer"></span>
      <label class="inline small" title="Adds a cost section (prices from the stockroom)"><input type="checkbox" id="rep-costs"> Include costs</label>
      <a class="btn primary" data-rep="pdf" target="_blank" rel="noopener">⬇ PDF</a>
      <a class="btn" data-rep="md">⬇ Markdown</a>
      <a class="btn" data-rep="html" target="_blank" rel="noopener">Print view</a>
      <button class="btn" id="rep-preview">Show preview</button></div>
    <div id="rep-box"></div></div>`;
  const links = () => {
    $$("[data-rep]", root).forEach((a) => {
      const f = a.dataset.rep;
      a.href = `/api/experiments/${id}/report.${f}${q(f === "md" ? "download=true" : "")}`;
    });
    const frame = $("#rep-box iframe", root);
    if (frame) frame.src = `/api/experiments/${id}/report.html${q()}`;
  };
  links();
  $("#rep-costs", root).onchange = (e) => { withCosts = e.target.checked; links(); };
  $("#rep-preview", root).onclick = () => {
    const box = $("#rep-box", root);
    if (box.firstChild) { box.firstChild.src = box.firstChild.src; return; }
    box.innerHTML = `<iframe class="preview" title="Report preview" src="/api/experiments/${id}/report.html${q()}"></iframe>`;
    $("#rep-preview", root).textContent = "↻ Refresh preview";
  };
}
