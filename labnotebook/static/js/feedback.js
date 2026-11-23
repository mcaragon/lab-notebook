/* "Report a problem": a form inside the app. Reports are stored in this Lab Notebook (nothing is sent anywhere) and
   read by its admins in the Feedback inbox of the admin dashboard; their replies show under "My reports". */
import { $, $$, api, esc, toast } from "./util.js";
import { state } from "./state.js";

const KINDS = [["bug", "🐞 Something's wrong"], ["idea", "💡 Idea"], ["question", "❓ Question"]];
const STATUS = { new: "New", open: "Looking into it", resolved: "Resolved", wontfix: "Won't fix" };
let shot = null;          // screenshot as a data URL
let kind = "bug";
let tab = "new";

const when = (v) => (v ? new Date(v).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

function close() {
  $("#fb-modal")?.remove();
  document.removeEventListener("keydown", onKey);
  document.removeEventListener("paste", onPaste);
}
function onKey(e) { if (e.key === "Escape") close(); }

/** Downscale big images so a screenshot stays well under the 3 MB limit. */
async function readImage(file) {
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw new Error("Use a PNG, JPEG or WebP image.");
  const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const max = 1800;
  if (file.size < 1.5e6 && img.width <= max && img.height <= max) return url;
  const k = Math.min(1, max / Math.max(img.width, img.height));
  const c = document.createElement("canvas");
  c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

async function setShot(file) {
  try {
    shot = await readImage(file);
    const box = $("#fb-shot-box");
    if (box) box.innerHTML = `<img src="${shot}" alt="Screenshot to send"><button type="button" class="btn small" id="fb-shot-x">Remove</button>`;
    $("#fb-shot-x")?.addEventListener("click", () => { shot = null; drawForm(); });
  } catch (e) { toast(e.message, true); }
}

function onPaste(e) {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item && tab === "new") { e.preventDefault(); setShot(item.getAsFile()); }
}

function context() {
  return {
    page: location.hash || "#/", version: state.config?.version || "", user_agent: navigator.userAgent,
    screen: `${window.innerWidth}×${window.innerHeight}`,
    theme: document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark (auto)" : "light (auto)"),
  };
}

function drawForm() {
  const ctx = context();
  $("#fb-body").innerHTML = `<form id="fb-form" class="fb-form" novalidate>
    <div class="fb-kinds" role="radiogroup" aria-label="Kind of report">${KINDS.map(([k, label]) =>
      `<button type="button" role="radio" aria-checked="${k === kind}" class="chip ${k === kind ? "on" : ""}" data-kind="${k}">${label}</button>`).join("")}</div>
    <label class="field"><span>Title</span><input id="fb-title" maxlength="140" required
      placeholder="${kind === "bug" ? "e.g. Yield stays at 0% after entering the product mass" : kind === "idea" ? "e.g. Let me copy a procedure from another experiment" : "e.g. How do I record a reagent added in two portions?"}"></label>
    <label class="field"><span>${kind === "bug" ? "What happened?" : kind === "idea" ? "What would help, and when would you use it?" : "Your question"}</span>
      <textarea id="fb-body-text" rows="4" maxlength="8000" required></textarea></label>
    ${kind === "bug" ? `<div class="fb-two">
      <label class="field"><span>Steps to get there <i>(optional)</i></span><textarea id="fb-steps" rows="3" maxlength="8000" placeholder="1. Bench tab&#10;2. Product mass 0.9 g&#10;3. Results tab"></textarea></label>
      <label class="field"><span>What did you expect? <i>(optional)</i></span><textarea id="fb-expected" rows="3" maxlength="4000"></textarea></label></div>` : ""}
    <div class="field"><span>Screenshot <i>(optional: choose a file, or paste with Ctrl+V)</i></span>
      <div id="fb-shot-box" class="fb-shot">${shot ? `<img src="${shot}" alt="Screenshot to send"><button type="button" class="btn small" id="fb-shot-x">Remove</button>`
        : `<input type="file" id="fb-file" accept="image/png,image/jpeg,image/webp">`}</div></div>
    <p class="hint">Sent along: this page (<code>${esc(ctx.page)}</code>), version ${esc(ctx.version)}, your browser and screen size.
      Reports stay in this Lab Notebook; only its admins read them. Please don't include passwords.</p>
    <div class="row"><span class="spacer"></span><button type="button" class="btn" id="fb-cancel">Cancel</button>
      <button class="btn primary" id="fb-send">Send report</button></div>
  </form>`;
  $$("[data-kind]").forEach((b) => (b.onclick = () => {
    const keep = { t: $("#fb-title").value, b: $("#fb-body-text").value };
    kind = b.dataset.kind; drawForm();
    $("#fb-title").value = keep.t; $("#fb-body-text").value = keep.b;
  }));
  $("#fb-file")?.addEventListener("change", (e) => e.target.files[0] && setShot(e.target.files[0]));
  $("#fb-shot-x")?.addEventListener("click", () => { shot = null; drawForm(); });
  $("#fb-cancel").onclick = close;
  $("#fb-form").onsubmit = async (e) => {
    e.preventDefault();
    const title = $("#fb-title").value.trim(), body = $("#fb-body-text").value.trim();
    if (!title || !body) { toast("Add a title and a description.", true); ($("#fb-title").value.trim() ? $("#fb-body-text") : $("#fb-title")).focus(); return; }
    const btn = $("#fb-send");
    btn.disabled = true; btn.textContent = "Sending…";
    try {
      await api("POST", "/api/feedback", { kind, title, body, steps: $("#fb-steps")?.value || null,
        expected: $("#fb-expected")?.value || null, screenshot: shot, ...context() });
      shot = null;
      toast("Thanks! Your report was sent.");
      tab = "mine"; drawTabs(); drawMine();
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = "Send report"; }
  };
  $("#fb-title").focus();
}

async function drawMine() {
  const box = $("#fb-body");
  box.innerHTML = '<p class="hint">Loading…</p>';
  let reports = [];
  try { reports = (await api("GET", "/api/feedback/mine")).reports; } catch (e) { box.textContent = e.message; return; }
  window.dispatchEvent(new Event("feedback-seen"));
  box.innerHTML = reports.length ? `<ul class="fb-list">${reports.map((r) => `<li>
      <div class="row"><b>${esc(r.title)}</b><span class="tag fb-${esc(r.status)}">${esc(STATUS[r.status] || r.status)}</span>
        <span class="spacer"></span><span class="sub">${esc(when(r.created_at))}</span></div>
      <div class="sub fb-text">${esc(r.body)}</div>
      ${r.reply ? `<div class="fb-reply"><span class="sub">Reply · ${esc(when(r.replied_at))}</span><div>${esc(r.reply)}</div></div>` : ""}
    </li>`).join("")}</ul>` : '<p class="empty">You haven\'t sent any reports yet.</p>';
}

function drawTabs() {
  $$("#fb-modal [data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
}

/** Open the report form (or the list of the user's reports). */
export function openFeedback(which = "new") {
  close();
  tab = which;
  document.body.insertAdjacentHTML("beforeend", `<div class="modal-backdrop" id="fb-modal" role="presentation">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="fb-h">
      <div class="modal-head"><h2 id="fb-h">Report a problem</h2>
        <nav class="tabs small-tabs"><a href="#" data-tab="new">New report</a><a href="#" data-tab="mine">My reports</a></nav>
        <span class="spacer"></span><button class="btn icon" id="fb-close" aria-label="Close">✕</button></div>
      <div id="fb-body" class="modal-body"></div>
    </div></div>`);
  $("#fb-close").onclick = close;
  $("#fb-modal").addEventListener("mousedown", (e) => { if (e.target.id === "fb-modal") close(); });
  $$("#fb-modal [data-tab]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault(); tab = a.dataset.tab; drawTabs(); tab === "new" ? drawForm() : drawMine();
  }));
  document.addEventListener("keydown", onKey);
  document.addEventListener("paste", onPaste);
  drawTabs();
  tab === "new" ? drawForm() : drawMine();
}
