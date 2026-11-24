/* Stockroom: the chemicals on hand, one entry per container, with amounts, prices and locations. Containers are
   grouped by compound; a container opens to edit it, record corrections (spill, stocktake) or mark it empty. */
import { $, $$, api, autocomplete, esc, fmt, ghsImg, parseNum, toast } from "./util.js";
import { state } from "./state.js";

const STATUS = { in_use: "In use", empty: "Empty", disposed: "Disposed" };
const FORMS = { neat: "Neat / pure", solution: "Solution (M)", wt: "Solution (wt %)" };
let data = null;
let filter = "in_use";
let query = "";
let openId = null;
let adding = false;
let detail = null;   // {item, adjustments} of the open container

const money = (v, digits) => {
  if (v == null) return "–";
  const cur = data?.currency || "USD";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: cur, maximumFractionDigits: digits ?? (v !== 0 && Math.abs(v) < 1 ? 4 : 2) }).format(v);
  } catch { return `${v.toFixed(2)} ${cur}`; }
};
const amt = (v, unit) => (v == null ? "–" : `${fmt(v, 4)} ${unit}`);
const day = (v) => (v ? new Date(v + (v.length === 10 ? "T12:00:00" : "")).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");

export async function renderStockroom(app) {
  document.title = "Stockroom · Lab Notebook";
  try { data = await api("GET", "/api/stockroom"); }
  catch (e) { app.innerHTML = `<div class="panel">Could not load the stockroom: ${esc(e.message)}</div>`; return; }
  if (openId) detail = await api("GET", `/api/stockroom/${openId}`).catch(() => null);
  draw(app);
}

async function reload(app, open = openId) {
  openId = open;
  data = await api("GET", "/api/stockroom");
  detail = openId ? await api("GET", `/api/stockroom/${openId}`).catch(() => null) : null;
  draw(app);
}

function shown() {
  const q = query.trim().toLowerCase();
  return data.items.filter((i) => {
    if (filter === "in_use" && i.status !== "in_use") return false;
    if (filter === "low" && !(i.status === "in_use" && i.low)) return false;
    if (filter === "expiring" && !(i.status === "in_use" && (i.expiring || i.expired))) return false;
    if (filter === "gone" && i.status === "in_use") return false;
    if (!q) return true;
    return [i.name, i.label, i.cas, i.formula, i.supplier, i.lot, i.location, i.catalog_no].some((v) => (v || "").toLowerCase().includes(q));
  });
}

function groups(items) {
  const by = new Map();
  for (const i of items) {
    const k = i.cid ? `cid:${i.cid}` : `name:${(i.name || "").toLowerCase()}`;
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(i);
  }
  return [...by.values()];
}

function thumb(i) {
  return i.cid || i.smiles ? `<img class="thumb struct" src="/api/stockroom/${i.id}/structure.svg?width=120&height=84&v=${i.cid || 0}" alt="" loading="lazy"
    onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb none'}))">` : '<div class="thumb none"></div>';
}

function containerRow(i) {
  const pct = i.fraction_left != null ? Math.round(i.fraction_left * 100) : null;
  const flags = [i.status !== "in_use" ? `<span class="tag">${STATUS[i.status]}</span>` : "",
    i.status === "in_use" && i.low ? '<span class="tag t-warn">low</span>' : "",
    i.expired ? '<span class="tag t-bad">expired</span>' : i.expiring ? '<span class="tag t-warn">expires soon</span>' : ""].join("");
  const form = i.form === "solution" && i.concentration_m ? `${fmt(i.concentration_m)} M` : i.form === "wt" && i.wt_percent ? `${fmt(i.wt_percent)} wt%`
    : i.purity ? `${fmt(i.purity)}%` : "";
  return `<div class="st-row ${openId === i.id ? "open" : ""} ${i.status !== "in_use" ? "gone" : ""}" data-id="${i.id}" tabindex="0" role="button" aria-expanded="${openId === i.id}">
    <div class="st-src"><b>${esc(i.supplier || "Unknown supplier")}</b>${form ? ` <span class="badge">${esc(form)}</span>` : ""}${flags}
      <div class="sub">${esc([i.grade, i.catalog_no ? `#${i.catalog_no}` : "", i.lot ? `lot ${i.lot}` : ""].filter(Boolean).join(" · ") || "–")}</div></div>
    <div class="st-left" data-label="Left">
      <div class="st-bar ${i.low ? "low" : ""}"><span style="width:${pct ?? 0}%"></span></div>
      <div><b>${amt(i.left, i.unit)}</b> <span class="sub">of ${amt(i.quantity, i.unit)}</span></div>
      ${i.reserved ? `<div class="sub">${amt(i.reserved, i.unit)} reserved</div>` : ""}</div>
    <div class="st-price num" data-label="Price">${i.price != null ? `${money(i.price)}<div class="sub">${money(i.unit_price)}/${esc(i.unit)}</div>` : '<span class="sub">no price</span>'}</div>
    <div class="st-value num" data-label="Value left">${money(i.value_left)}</div>
    <div class="st-loc" data-label="Location">${esc(i.location || "–")}${i.expires_at ? `<div class="sub">expires ${esc(day(i.expires_at))}</div>` : ""}</div>
  </div>${openId === i.id && detail ? detailPanel(detail) : ""}`;
}

function groupBlock(items) {
  const i0 = items[0];
  const units = [...new Set(items.map((i) => i.unit))];
  const total = units.length === 1 ? items.filter((i) => i.status === "in_use").reduce((s, i) => s + Math.max(i.left || 0, 0), 0) : null;
  return `<section class="st-group">
    <div class="st-head">${thumb(i0)}
      <div class="grow"><b class="st-name">${esc(i0.label || i0.name)}</b>${i0.label && i0.label !== i0.name ? ` <span class="sub">${esc(i0.name)}</span>` : ""}
        <div class="sub">${esc([i0.cas, i0.formula, i0.mw ? `${fmt(i0.mw, 5)} g/mol` : ""].filter(Boolean).join(" · "))}</div></div>
      <div class="st-haz">${(i0.pictograms || []).map((p) => ghsImg(p)).join("")}</div>
      <div class="st-total num">${total != null ? `<b>${amt(total, units[0])}</b><div class="sub">${items.length} container${items.length === 1 ? "" : "s"}</div>` : ""}</div>
    </div>
    ${items.map(containerRow).join("")}
  </section>`;
}

function field(name, label, value, { type = "text", step, placeholder = "", list } = {}) {
  return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" ${step ? `step="${step}"` : ""} value="${esc(value ?? "")}"
    placeholder="${esc(placeholder)}" ${list ? `list="${list}"` : ""} autocomplete="off"></label>`;
}

function itemFields(i) {
  return `<div class="st-form">
    ${field("quantity", `Amount bought`, i.quantity, { type: "number", step: "any" })}
    <label class="field"><span>Unit</span><select name="unit">${["g", "mL"].map((u) => `<option ${i.unit === u ? "selected" : ""}>${u}</option>`).join("")}</select></label>
    ${field("price", `Price paid (${esc(data.currency)})`, i.price, { type: "number", step: "any", placeholder: "total, incl. shipping if you like" })}
    ${field("supplier", "Supplier", i.supplier, { list: "st-suppliers" })}
    ${field("catalog_no", "Catalogue no.", i.catalog_no)}
    ${field("grade", "Grade", i.grade, { placeholder: "e.g. ReagentPlus, ACS" })}
    ${field("lot", "Lot", i.lot)}
    <label class="field"><span>Form</span><select name="form">${Object.entries(FORMS).map(([k, v]) => `<option value="${k}" ${(i.form || "neat") === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    ${(i.form || "neat") === "solution" ? field("concentration_m", "Concentration (M)", i.concentration_m, { type: "number", step: "any" })
      : (i.form || "neat") === "wt" ? field("wt_percent", "Weight percent", i.wt_percent, { type: "number", step: "any" })
      : field("purity", "Purity (%)", i.purity, { type: "number", step: "any", placeholder: "100" })}
    ${field("location", "Location", i.location, { list: "st-locations", placeholder: "e.g. Flammables cabinet, shelf 2" })}
    ${field("received_at", "Received", (i.received_at || "").slice(0, 10), { type: "date" })}
    ${field("opened_at", "Opened", (i.opened_at || "").slice(0, 10), { type: "date" })}
    ${field("expires_at", "Expires", (i.expires_at || "").slice(0, 10), { type: "date" })}
    ${field("low_threshold", `Warn below (${esc(i.unit || "g")})`, i.low_threshold, { type: "number", step: "any" })}
    <label class="field wide"><span>Notes</span><input name="notes" value="${esc(i.notes || "")}"></label>
  </div>`;
}

function detailPanel(d) {
  const i = d.item;
  return `<div class="st-detail" data-detail="${i.id}">
    <div class="st-detail-grid"><form class="st-edit" id="st-edit">${itemFields(i)}</form>
      <div class="st-side">
        <h4>Amount</h4>
        <dl class="st-dl"><dt>Bought</dt><dd>${amt(i.quantity, i.unit)}</dd>
          <dt>Corrections</dt><dd>${i.corrections ? `${i.corrections > 0 ? "+" : ""}${amt(i.corrections, i.unit)}` : "–"}</dd>
          <dt>Used in experiments</dt><dd>${i.used ? amt(i.used, i.unit) : "–"}</dd>
          <dt>Left</dt><dd><b>${amt(i.left, i.unit)}</b></dd>
          <dt>Reserved (planned)</dt><dd>${i.reserved ? amt(i.reserved, i.unit) : "–"}</dd></dl>
        <form class="row st-adjust" id="st-adjust">
          <select name="mode" aria-label="Kind of correction"><option value="delta">Change by</option><option value="actual">Amount found</option></select>
          <input name="value" inputmode="decimal" placeholder="${esc(i.unit)}" aria-label="Amount" required>
          <input name="reason" class="grow" placeholder="Reason (spill, recount…)" aria-label="Reason">
          <button class="btn small">Record</button></form>
        ${d.adjustments.length ? `<ul class="mini st-adj">${d.adjustments.map((a) => `<li><span>${esc(day(a.ts.slice(0, 10)))} · ${esc(a.reason || "correction")}</span>
          <b>${a.delta > 0 ? "+" : ""}${amt(a.delta, i.unit)}</b><button class="btn icon" data-adj-del="${a.id}" title="Remove this correction" aria-label="Remove">✕</button></li>`).join("")}</ul>` : ""}
        ${(i.uses || []).length ? `<h4>Used in experiments</h4><ul class="mini st-uses">${i.uses.map((u) => `<li>
          <a href="#/exp/${u.experiment_id}/plan">${esc(u.experiment)}</a>${u.kind === "reserved" ? '<span class="tag" title="Planned amount: not used yet">reserved</span>' : ""}
          <b>${u.amount == null ? "?" : amt(u.amount, i.unit)}</b></li>`).join("")}</ul>
          ${i.unconverted ? `<p class="hint">⚠ ${i.unconverted} amount(s) could not be converted to ${esc(i.unit)}: enter the density.</p>` : ""}` : ""}
        <div class="row st-actions">
          <button class="btn small" data-dup="${i.id}" title="Add another container of the same thing">Duplicate</button>
          ${i.status === "in_use" ? `<button class="btn small" data-status="empty">Mark empty</button><button class="btn small" data-status="disposed">Disposed</button>`
            : `<button class="btn small" data-status="in_use">Back in use</button>`}
          <span class="spacer"></span><button class="btn small danger" data-del="${i.id}">Delete</button></div>
      </div></div></div>`;
}

function addPanel() {
  const blank = { unit: "g", form: "neat" };
  return `<div class="panel st-add"><div class="row sec-head"><h2>Add a container</h2><span class="spacer"></span>
      <button class="btn icon" id="st-add-x" aria-label="Close">✕</button></div>
    <form id="st-add-form">
      <label class="field wide"><span>Chemical (name, CAS, formula or SMILES; filled in from PubChem Local)</span>
        <input id="st-q" name="query" required placeholder="e.g. benzaldehyde, 100-52-7, or 2.5 M n-BuLi in hexanes"></label>
      ${itemFields(blank)}
      <div class="row"><span class="spacer"></span><button class="btn primary">Add to stockroom</button></div>
    </form></div>`;
}

function draw(app) {
  const s = data.summary;
  const items = shown();
  const suppliers = [...new Set(data.items.map((i) => i.supplier).filter(Boolean))];
  const locations = [...new Set(data.items.map((i) => i.location).filter(Boolean))];
  const curOpts = ["USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "CNY", "INR", "SEK", "NOK", "DKK", "PLN", "CZK", "NZD", "BRL", "MXN", "ZAR", "KRW", "SGD"];
  app.innerHTML = `<div class="home stockroom">
    <div class="page-head"><div><h1>Stockroom</h1><p class="hint">The chemicals you have on hand: one entry per bottle, with amounts, prices and where it is.</p></div>
      <span class="spacer"></span>
      <label class="inline small">Currency <select id="st-cur">${curOpts.map((c) => `<option ${c === data.currency ? "selected" : ""}>${c}</option>`).join("")}</select></label>
      <button class="btn primary" id="st-add">＋ Add container</button></div>
    <div class="stat-row">
      <div class="stat"><span class="k-l">Containers</span><b>${s.containers}</b><span class="sub">${s.compounds} compound${s.compounds === 1 ? "" : "s"}</span></div>
      <div class="stat s-completed"><span class="k-l">Value on hand</span><b>${money(s.value, 0)}</b><span class="sub">${s.unpriced ? `${s.unpriced} without a price` : "all priced"}</span></div>
      <div class="stat s-in_progress"><span class="k-l">Low stock</span><b>${s.low}</b></div>
      <div class="stat s-planned"><span class="k-l">Expiring / expired</span><b>${s.expiring + s.expired}</b></div>
    </div>
    ${adding ? addPanel() : ""}
    <div class="row st-tools">
      <input id="st-search" class="grow" placeholder="Search name, CAS, supplier, lot, location" value="${esc(query)}" aria-label="Search the stockroom">
      ${[["in_use", "In use"], ["low", `Low (${s.low})`], ["expiring", `Expiring (${s.expiring + s.expired})`], ["gone", "Empty & disposed"], ["all", "All"]]
        .map(([k, v]) => `<button class="chip ${filter === k ? "on" : ""}" data-filter="${k}">${v}</button>`).join("")}
    </div>
    <div class="st-list">${items.length ? '<div class="st-cols" aria-hidden="true"><span>Container</span><span>Left</span><span class="num">Price</span><span class="num">Value left</span><span>Location</span></div>' + groups(items).map(groupBlock).join("")
      : `<div class="panel empty">${data.items.length ? "Nothing matches." : "No chemicals yet. <b>＋ Add container</b> to start your stockroom."}</div>`}</div>
    <datalist id="st-suppliers">${suppliers.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>
    <datalist id="st-locations">${locations.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>
  </div>`;
  bind(app);
}

const formValues = (form) => {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.name === "mode") continue;
    if (el.type === "number") {
      const v = parseNum(el.value);
      out[el.name] = Number.isNaN(v) ? undefined : v;
    } else out[el.name] = el.value.trim() || null;
  }
  return out;
};

function bind(app) {
  $("#st-cur", app).onchange = async (e) => {
    try {
      const d = await api("PUT", "/api/account", { currency: e.target.value });
      state.user = d.user;
      await reload(app);
    } catch (err) { toast(err.message, true); }
  };
  $("#st-add", app).onclick = () => { adding = true; draw(app); $("#st-q")?.focus(); };
  const s = $("#st-search", app);
  s.addEventListener("input", () => { query = s.value; const pos = s.selectionStart; draw(app); const n = $("#st-search", app); n.focus(); n.setSelectionRange(pos, pos); });
  $$("[data-filter]", app).forEach((b) => (b.onclick = () => { filter = b.dataset.filter; draw(app); }));
  $$(".st-row", app).forEach((row) => {
    const open = async () => {
      const id = Number(row.dataset.id);
      if (openId === id) { openId = null; detail = null; draw(app); return; }
      try { detail = await api("GET", `/api/stockroom/${id}`); openId = id; draw(app); }
      catch (e) { toast(e.message, true); }
    };
    row.onclick = open;
    row.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  });
  // adding
  const af = $("#st-add-form", app);
  if (af) {
    $("#st-add-x", app).onclick = () => { adding = false; draw(app); };
    let chosen = null;
    const q = $("#st-q", af);
    autocomplete(q, async (text) => {
      try {
        const res = await api("GET", `/api/pubchem/autocomplete?q=${encodeURIComponent(text)}&limit=8`);
        return res.suggestions.map((x) => ({ label: x.name, sub: `CID ${x.cid}`, cid: x.cid }));
      } catch { return []; }
    }, (item) => { chosen = item; q.value = item.label; }, { minChars: 2 });
    q.addEventListener("input", () => { chosen = null; });
    af.querySelector('select[name="form"]').onchange = (e) => {
      const keep = formValues(af);
      adding = true; draw(app);
      const f2 = $("#st-add-form", app);
      Object.entries({ ...keep, form: e.target.value }).forEach(([k, v]) => { const el = f2.elements[k]; if (el && v != null) el.value = v; });
    };
    af.onsubmit = async (e) => {
      e.preventDefault();
      const body = formValues(af);
      if (!body.query) { toast("Enter the chemical.", true); return; }
      if (chosen?.cid) { body.cid = chosen.cid; delete body.query; }
      Object.keys(body).forEach((k) => body[k] == null && delete body[k]);
      try {
        const d = await api("POST", "/api/stockroom", body);
        if (d.warning) toast(d.warning, true); else toast(`Added ${d.item.name}.`);
        adding = false; filter = filter === "gone" ? "in_use" : filter;
        await reload(app, d.item.id);
      } catch (err) { toast(err.message, true); }
    };
  }
  // the open container
  const ed = $("#st-edit", app);
  if (ed) {
    const id = openId;
    ed.addEventListener("click", (e) => e.stopPropagation());
    $$("input, select", ed).forEach((el) => el.addEventListener("change", async () => {
      let v = el.value;
      if (el.type === "number") { v = parseNum(v); if (Number.isNaN(v)) { toast("Enter a number.", true); return; } }
      else v = v.trim() || null;
      try {
        await api("PUT", `/api/stockroom/${id}`, { [el.name]: v });
        await reload(app);
      } catch (err) { toast(err.message, true); }
    }));
    const adj = $("#st-adjust", app);
    adj.onsubmit = async (e) => {
      e.preventDefault();
      const v = parseNum(adj.elements.value.value);
      if (v == null || Number.isNaN(v)) { toast("Enter an amount.", true); return; }
      const body = adj.elements.mode.value === "actual" ? { actual: v } : { delta: v };
      body.reason = adj.elements.reason.value.trim() || null;
      try { await api("POST", `/api/stockroom/${id}/adjust`, body); await reload(app); }
      catch (err) { toast(err.message, true); }
    };
    $$("[data-adj-del]", app).forEach((b) => (b.onclick = async () => {
      try { await api("DELETE", `/api/stockroom/${id}/adjustments/${b.dataset.adjDel}`); await reload(app); }
      catch (err) { toast(err.message, true); }
    }));
    $$("[data-status]", app).forEach((b) => (b.onclick = async () => {
      try { await api("PUT", `/api/stockroom/${id}`, { status: b.dataset.status }); await reload(app); }
      catch (err) { toast(err.message, true); }
    }));
    $$("[data-dup]", app).forEach((b) => (b.onclick = async () => {
      try { const d = await api("POST", `/api/stockroom/${id}/duplicate`); toast("Added another container: enter its amount and price."); await reload(app, d.item.id); }
      catch (err) { toast(err.message, true); }
    }));
    $$("[data-del]", app).forEach((b) => (b.onclick = async () => {
      const it = detail.item;
      if (!confirm(`Delete this container of ${it.name}${it.supplier ? ` (${it.supplier})` : ""}? Experiments that used it keep their amounts.`)) return;
      try { await api("DELETE", `/api/stockroom/${id}`); await reload(app, null); }
      catch (err) { toast(err.message, true); }
    }));
    $(".st-detail", app).addEventListener("click", (e) => e.stopPropagation());
  }
}
