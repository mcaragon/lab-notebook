/* Side panels of the Plan tab: "At a glance" and the experiment-wide hazard summary. */
import { esc, fmt, fmtDur, ghsImg, GHS_NAMES, hCode, hText, nfpaDiamond } from "./util.js";
import { state, labelOf, multiStep, nowServer } from "./state.js";

const ROLE = { reactant: "Starting material", reagent: "Reagent", catalyst: "Catalyst", solvent: "Solvent", workup: "Workup", product: "Product" };

export function renderGlance(root) {
  const d = state.data;
  const exp = d.experiment;
  const rs = d.reagents;
  const lim = rs.find((r) => r.calc?.is_limiting);
  const prods = rs.filter((r) => r.role === "product");
  const inputs = rs.filter((r) => !["product"].includes(r.role));
  const measured = inputs.filter((r) => r.actual_value != null).length;
  const pct = inputs.length ? Math.round((measured / inputs.length) * 100) : 0;
  const scale = lim?.calc?.used_mmol;
  const byRole = {};
  rs.forEach((r) => { byRole[r.role] = (byRole[r.role] || 0) + 1; });
  const elapsed = exp.started_at ? ((exp.ended_at ? Date.parse(exp.ended_at) : nowServer()) - Date.parse(exp.started_at)) / 1000 : null;
  const prod = prods.find((r) => r.calc?.theoretical_mass_g != null) || prods[0];
  const c = prod?.calc || {};
  root.innerHTML = `<div class="panel widget glance">
    <div class="w-h"><h3>At a glance</h3></div>
    <div class="kpis">
      <div class="kpi k-scale"><span class="k-l">Scale</span><span class="k-v">${scale != null ? fmt(scale) : "–"}<small> mmol</small></span>
        <span class="k-s">${lim ? esc(labelOf(lim)) + " limiting" : "no limiting reagent yet"}</span></div>
      <div class="kpi k-theo"><span class="k-l">Theoretical</span><span class="k-v">${c.theoretical_mass_g != null ? fmt(c.theoretical_mass_g) : "–"}<small> g</small></span>
        <span class="k-s">${prod ? esc(labelOf(prod)) : "add a product"}</span></div>
      <div class="kpi k-yield"><span class="k-l">${c.percent_yield != null ? "Yield" : "Expected"}</span>
        <span class="k-v">${c.percent_yield != null ? c.percent_yield.toFixed(1) : c.expected_yield_pct != null ? fmt(c.expected_yield_pct, 2) : "–"}<small> %</small></span>
        <span class="k-s">${c.percent_yield != null ? `${fmt(c.isolated_mass_g)} g isolated` : c.expected_mass_g != null ? `${fmt(c.expected_mass_g)} g expected` : "literature value not set"}</span></div>
      <div class="kpi k-time"><span class="k-l">${exp.ended_at ? "Duration" : "Running"}</span><span class="k-v mono" ${exp.started_at ? `data-since="${esc(exp.started_at)}" data-until="${esc(exp.ended_at || "")}"` : ""}>${elapsed != null ? fmtDur(elapsed) : "–"}</span>
        <span class="k-s">${exp.started_at ? new Date(exp.started_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "not started"}</span></div>
    </div>
    <div class="meter" title="${measured} of ${inputs.length} chemicals measured"><span style="width:${pct}%"></span></div>
    <div class="k-s">${measured} of ${inputs.length} chemicals measured${multiStep() ? ` · ${d.steps.length} steps` : ""}</div>
    <div class="role-tags">${Object.entries(byRole).map(([k, n]) => `<span class="tag role-${k}">${n} ${esc(ROLE[k] || k)}${n > 1 && k !== "workup" ? "s" : ""}</span>`).join("")}</div>
  </div>`;
}

export function renderHazards(root) {
  const rs = state.data.reagents;
  const pics = new Map();
  rs.forEach((r) => (r.pictograms || []).forEach((p) => { if (!pics.has(p)) pics.set(p, []); pics.get(p).push(labelOf(r)); }));
  const danger = rs.filter((r) => r.signal_word === "Danger").map(labelOf);
  const forbidden = rs.filter((r) => r.extra_hazards?.dot?.forbidden).map(labelOf);
  const alerts = new Map();
  rs.forEach((r) => (r.extra_hazards?.alerts || []).forEach((a) => { if (!alerts.has(a)) alerts.set(a, []); alerts.get(a).push(labelOf(r)); }));
  const flam = rs.filter((r) => r.flash_point != null).sort((a, b) => a.flash_point - b.flash_point).slice(0, 3);
  const codes = new Map();
  rs.forEach((r) => (r.hazard_statements || []).filter((h) => /^\s*(EU)?H\d{3}/.test(h)).forEach((h) => {
    const k = hCode(hText(h)); if (!codes.has(k)) codes.set(k, hText(h));
  }));
  const severe = [...codes.entries()].filter(([k]) => /^H(2[0-4]\d|300|301|310|311|314|318|330|331|340|350|360|370|372)/.test(k));
  const worstNfpa = rs.map((r) => r.extra_hazards?.nfpa).filter(Boolean)
    .reduce((m, n) => ({ health: Math.max(m.health, n.health), fire: Math.max(m.fire, n.fire), instability: Math.max(m.instability, n.instability) }),
      { health: 0, fire: 0, instability: 0 });
  const anyNfpa = rs.some((r) => r.extra_hazards?.nfpa);
  root.innerHTML = `<div class="panel widget hazards-w">
    <div class="w-h"><h3>Hazard summary</h3>${danger.length ? `<span class="tag t-bad">${danger.length} Danger</span>` : ""}</div>
    ${forbidden.length ? `<div class="alert-box">⚠ DOT-forbidden: <b>${forbidden.map(esc).join(", ")}</b></div>` : ""}
    ${pics.size ? `<div class="pics">${[...pics.entries()].map(([p, who]) => `<div class="pic" title="${esc(GHS_NAMES[p] || p)}: ${esc(who.join(", "))}">
      ${ghsImg(p)}<span>${esc(GHS_NAMES[p] || p)}</span><b>${who.length}</b></div>`).join("")}</div>` : '<p class="hint">No GHS pictograms.</p>'}
    ${anyNfpa ? `<div class="nfpa-row">${nfpaDiamond(worstNfpa, 34)}<span class="hint">Worst NFPA 704 ratings across all chemicals</span></div>` : ""}
    ${alerts.size ? `<div class="w-sub">Reactivity</div><div class="tags">${[...alerts.entries()].map(([a, who]) =>
      `<span class="tag t-warn" title="${esc(who.join(", "))}">${esc(a)}</span>`).join("")}</div>` : ""}
    ${flam.length ? `<div class="w-sub">Lowest flash points</div><ul class="mini">${flam.map((r) =>
      `<li><span>${esc(labelOf(r))}</span><b>${fmt(r.flash_point, 3)} °C</b></li>`).join("")}</ul>` : ""}
    ${severe.length ? `<div class="w-sub">Severe hazards</div><ul class="mini codes">${severe.slice(0, 8).map(([k, t]) =>
      `<li title="${esc(t)}"><b>${esc(k)}</b><span>${esc(t.replace(/^[^:]*:\s*/, ""))}</span></li>`).join("")}</ul>` : ""}
  </div>`;
}
