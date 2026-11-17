/* Shared helpers. */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Number with `sig` significant figures, without scientific notation. */
export function fmt(v, sig = 3) {
  if (v === null || v === undefined || v === "" || !isFinite(v)) return "";
  const f = Number(v);
  if (f === 0) return "0";
  const decimals = Math.max(0, sig - 1 - Math.floor(Math.log10(Math.abs(f))));
  return f.toFixed(Math.min(decimals, 8));
}
export const fixed = (v, d) => (v === null || v === undefined || v === "" ? "" : Number(v).toFixed(d));

/** Parse a typed number (accepts a decimal comma). null for empty, NaN for invalid. */
export function parseNum(s) {
  s = String(s ?? "").trim().replace(",", ".");
  if (s === "") return null;
  const f = Number(s);
  return isFinite(f) ? f : NaN;
}

/** Seconds -> h:mm:ss (or m:ss under an hour when short=true). */
export function fmtDur(sec, short = false) {
  if (sec === null || sec === undefined || !isFinite(sec)) return "";
  const neg = sec < 0;
  let s = Math.abs(Math.round(sec));
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  const p = (n) => String(n).padStart(2, "0");
  return (neg ? "−" : "") + (h || !short ? `${h}:${p(m)}:${p(s)}` : `${m}:${p(s)}`);
}

/** '10 min', '1 h 30 min', '90 s', '1:30' -> seconds (bare number = minutes). */
export function parseDuration(text) {
  const s = String(text ?? "").trim().toLowerCase().replace(",", ".");
  if (!s) return null;
  if (/^\d+(:\d{1,2}){1,2}$/.test(s)) {
    const p = s.split(":").map(Number);
    return p.length === 2 ? p[0] * 60 + p[1] : p[0] * 3600 + p[1] * 60 + p[2];
  }
  let total = 0, found = false;
  for (const m of s.matchAll(/(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)\b/g)) {
    found = true;
    total += Number(m[1]) * (m[2].startsWith("h") ? 3600 : m[2].startsWith("m") ? 60 : 1);
  }
  if (found) return total;
  const n = Number(s);
  return isFinite(n) ? n * 60 : null;
}

export function fmtTemp(t) {
  const s = String(t ?? "").trim();
  if (!s) return "";
  if (/^[−-]?\d+([.,]\d+)?$/.test(s)) return s.replace("-", "−") + " °C";
  return s;
}

let toastTimer;
export function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), error ? 6000 : 2500);
}

export async function api(method, path, body) {
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

export function debounce(fn, ms) {
  let t, last;
  const d = (...args) => { last = args; clearTimeout(t); t = setTimeout(() => { t = null; fn(...last); }, ms); };
  d.flush = () => { if (t) { clearTimeout(t); t = null; return fn(...last); } };
  return d;
}

export function localDateTimeValue(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function isoWithOffset(d) {
  const off = -d.getTimezoneOffset(), sign = off >= 0 ? "+" : "-";
  const p = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${localDateTimeValue(d)}${sign}${p(off / 60)}:${p(off % 60)}`;
}

export function clockTime(ts, withSeconds = false) {
  const d = new Date(ts);
  if (isNaN(d)) return esc(ts);
  const opts = { hour: "2-digit", minute: "2-digit" };
  if (withSeconds) opts.second = "2-digit";
  const today = new Date().toDateString() === d.toDateString();
  if (!today) Object.assign(opts, { month: "short", day: "numeric" });
  return d.toLocaleString(undefined, opts);
}

export const GHS_NAMES = {
  GHS01: "Explosive", GHS02: "Flammable", GHS03: "Oxidizer", GHS04: "Compressed gas", GHS05: "Corrosive",
  GHS06: "Acute toxicity", GHS07: "Harmful / irritant", GHS08: "Health hazard", GHS09: "Environmental hazard",
};

export const ghsImg = (code, cls = "ghs") =>
  `<img class="${cls}" src="/api/pubchem/ghs/${esc(code)}.svg" alt="${esc(code)}" title="${esc(code)}: ${esc(GHS_NAMES[code] || "")}" loading="lazy"
    onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'badge',textContent:'${esc(code)}'}))">`;

/** 'H225: Highly flammable ... [Danger ...]' -> 'H225: Highly flammable ...' */
export const hText = (s) => String(s || "").replace(/\s*\[[^\]]*\]\s*$/, "");
export const hCode = (s) => (String(s || "").match(/^\s*((?:EU)?H\d{3}[A-Za-z+H\d]*)/) || [])[1] || s;

/** Small NFPA 704 diamond as inline SVG. */
export function nfpaDiamond(n, size = 30) {
  if (!n) return "";
  const t = (x, y, v, fill) => `<text x="${x}" y="${y}" font-size="9" font-weight="700" text-anchor="middle" fill="${fill}">${v ?? ""}</text>`;
  return `<svg class="nfpa" width="${size}" height="${size}" viewBox="0 0 40 40" role="img"
    aria-label="NFPA 704: health ${n.health}, fire ${n.fire}, instability ${n.instability}${n.special ? ", " + n.special : ""}">
    <title>NFPA 704 — health ${n.health}, fire ${n.fire}, instability ${n.instability}${n.special ? ", special " + n.special : ""}</title>
    <polygon points="20,1 29.5,10.5 20,20 10.5,10.5" fill="#d62728"/>
    <polygon points="10.5,10.5 20,20 10.5,29.5 1,20" fill="#1f62b0"/>
    <polygon points="29.5,10.5 39,20 29.5,29.5 20,20" fill="#f2c80f"/>
    <polygon points="20,20 29.5,29.5 20,39 10.5,29.5" fill="#fff" stroke="#999" stroke-width=".6"/>
    ${t(20, 14, n.fire, "#fff")}${t(10.5, 23, n.health, "#fff")}${t(29.5, 23, n.instability, "#000")}${t(20, 32.5, n.special || "", "#000")}
  </svg>`;
}

/** Keep focus, caret and uncommitted typing across a re-render of `root`. */
export function preserveFocus(root, renderFn) {
  const act = document.activeElement;
  const key = act && root.contains(act) ? act.dataset?.key : null;
  const typed = key && (act.tagName === "INPUT" || act.tagName === "TEXTAREA") && act.value !== act.defaultValue ? act.value : null;
  const sel = key && act.selectionStart !== undefined ? [act.selectionStart, act.selectionEnd] : null;
  renderFn();
  if (!key) return;
  const el = root.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (!el) return;
  if (typed !== null) el.value = typed;
  el.focus({ preventScroll: true });
  try { if (sel) el.setSelectionRange(...sel); } catch { /* not a text input */ }
}

/** Autocomplete dropdown on an input. `source(q)` returns [{label, sub, value}]. */
export function autocomplete(input, source, onPick, { minChars = 1, delay = 150 } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "ac";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const list = document.createElement("ul");
  list.className = "ac-list hidden";
  list.setAttribute("role", "listbox");
  wrap.appendChild(list);
  let items = [], active = -1, seq = 0;
  const close = () => { list.classList.add("hidden"); active = -1; };
  const show = () => {
    list.innerHTML = items.map((s, i) => `<li role="option" data-i="${i}" class="${i === active ? "active" : ""}">
      ${esc(s.label)}${s.sub ? ` <span class="sub">${esc(s.sub)}</span>` : ""}</li>`).join("");
    list.classList.toggle("hidden", !items.length);
  };
  const run = debounce(async () => {
    const q = input.value.trim();
    const my = ++seq;
    if (q.length < minChars) { items = []; close(); return; }
    try {
      const res = await source(q);
      if (my !== seq) return;
      items = res; active = -1; show();
    } catch { items = []; close(); }
  }, delay);
  input.addEventListener("input", run);
  input.addEventListener("focus", () => { if (minChars === 0) run(); });
  input.addEventListener("keydown", (e) => {
    const open = !list.classList.contains("hidden");
    if (e.key === "ArrowDown" && items.length) { active = (active + 1) % items.length; show(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && items.length) { active = (active - 1 + items.length) % items.length; show(); e.preventDefault(); }
    else if (e.key === "Escape") close();
    else if (e.key === "Enter" && open && active >= 0) { e.preventDefault(); e.stopImmediatePropagation(); const it = items[active]; seq++; close(); onPick(it); }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); seq++; const it = items[Number(li.dataset.i)]; close(); onPick(it); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
  return { close, cancel: () => { seq++; close(); } };
}
