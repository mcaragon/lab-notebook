/* Side panels of the Plan tab: "At a glance", the experiment-wide hazard summary and the route (where the starting
   materials came from, where the product went, branching, projects). */
import { $, $$, api, esc, fmt, fmtDur, ghsImg, GHS_NAMES, hCode, hText, nfpaDiamond, toast } from "./util.js";
import { state, labelOf, multiStage, nowServer } from "./state.js";
import { refreshSidebar } from "./sidebar.js";

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
    <div class="k-s">${measured} of ${inputs.length} chemicals measured${multiStage() ? ` · one-pot, ${d.steps.length} stages` : ""}</div>
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

// ------------------------------------------------------------------------------------------- route
const STATUS = { planned: "Planned", in_progress: "In progress", completed: "Completed" };

/** Ask for the portion of a product to use and start a new experiment from it. */
export async function branchFrom(product, remaining) {
  const def = remaining != null && remaining > 0 ? String(+remaining.toFixed(4)) : "";
  const v = prompt(`Branch from ${product.name}: how much do you take (g)?\nLeave empty to decide later.`, def);
  if (v === null) return null;
  const mass = v.trim() === "" ? null : Number(v.replace(",", "."));
  if (mass !== null && !(mass > 0)) { toast("Enter a mass in g.", true); return null; }
  try {
    const d = await api("POST", `/api/reagents/${product.id}/branch`, mass === null ? {} : { mass_g: mass });
    refreshSidebar();
    return d;
  } catch (e) { toast(e.message, true); return null; }
}

export function renderRoute(root) {
  const d = state.data;
  const rt = d.route || { sources: [], uses: [], products: [] };
  const prod = rt.products[0];
  root.innerHTML = `<div class="panel widget route-w">
    <div class="w-h"><h3>Route</h3>${d.projects.length ? "" : '<span class="tag">not in a project</span>'}</div>
    ${rt.sources.length ? `<div class="w-sub">Made from</div><ul class="mini links">${rt.sources.map((s) => `<li>
      <span>${esc(s.name)}${s.taken_g != null ? ` <span class="sub">${fmt(s.taken_g)} g</span>` : ""}</span>
      ${s.missing ? '<span class="sub">source deleted</span>' : `<a href="#/exp/${s.experiment_id}/results">${esc(s.experiment)}</a>`}</li>`).join("")}</ul>` : ""}
    ${prod ? `<div class="w-sub">Product</div>
      <div class="route-prod"><b>${esc(prod.name)}</b>
        <span class="sub">${prod.isolated_g != null ? `${fmt(prod.isolated_g)} g isolated` : "not isolated yet"}${prod.used_g != null ? ` · ${fmt(prod.used_g)} g used` : ""}</span>
        ${prod.remaining_g != null && prod.used_g != null ? `<span class="left ${prod.remaining_g < 0 ? "neg" : ""}">${fmt(prod.remaining_g)} g left</span>` : ""}</div>
      ${rt.uses.length ? `<ul class="mini links">${rt.uses.map((u) => `<li><a href="#/exp/${u.experiment_id}/plan">${esc(u.experiment)}</a>
        <span class="sub">${u.taken_g != null ? `${fmt(u.taken_g)} g · ` : ""}${esc(STATUS[u.status] || u.status)}</span></li>`).join("")}</ul>` : ""}
      <button class="btn small primary" id="branch-btn" title="New experiment that starts from a portion of this product">⑂ Branch from this product</button>`
    : `<p class="hint">Add the product under Reagents to continue the route from it.</p>`}
    <div class="w-sub">Projects</div>
    <div class="row seq-row">
      ${d.projects.map((q) => `<a class="chip" href="#/project/${q.id}">⇢ ${esc(q.title)}</a>`).join("")}
      <select id="proj-pick" aria-label="Add to a project"><option value="">Add to project…</option><option value="new">New project…</option></select>
    </div>
    <p class="hint">To link an experiment done earlier, add its product as a starting material: type its name under Reagents → Starting materials.</p>
  </div>`;
  const b = $("#branch-btn", root);
  if (b) b.onclick = async () => {
    const out = await branchFrom(prod, prod.remaining_g ?? prod.isolated_g);
    if (out) location.hash = `#/exp/${out.experiment.id}/plan`;
  };
  const pick = $("#proj-pick", root);
  api("GET", "/api/projects").then(({ projects }) => {
    const mine = new Set(d.projects.map((q) => q.id));
    pick.insertAdjacentHTML("beforeend", projects.filter((q) => !mine.has(q.id))
      .map((q) => `<option value="${q.id}">${esc(q.title)}</option>`).join(""));
  }).catch(() => {});
  pick.onchange = async () => {
    try {
      let id;
      if (pick.value === "new") {
        const title = prompt("Name of the new project:", d.experiment.title);
        if (!title) { pick.value = ""; return; }
        id = (await api("POST", "/api/projects", { title, experiment_ids: [d.experiment.id] })).project.id;
      } else if (pick.value) {
        id = (await api("POST", `/api/projects/${pick.value}/experiments`, { experiment_id: d.experiment.id })).project.id;
      }
      if (id) { state.data = null; refreshSidebar(); location.hash = `#/project/${id}`; }
    } catch (e) { toast(e.message, true); }
  };
}
