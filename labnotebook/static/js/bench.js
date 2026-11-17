/* Bench bar: experiment clock (T+), running timers and countdowns, alerts and screen wake lock. */
import { $, $$, esc, fmtDur, parseDuration, toast } from "./util.js";
import { state, mutate, expId, nowServer, labelOf } from "./state.js";

const alerted = new Set();
let wakeLock = null;

export function renderBench(root) {
  const exp = state.data.experiment;
  const running = exp.started_at && !exp.ended_at;
  document.body.classList.toggle("running", !!running);
  const timers = state.data.timers.filter((t) => !t.stopped_at);
  if (!exp.started_at) {
    root.innerHTML = `<div class="bench-inner idle">
      <button class="btn primary" id="b-start">▶ Start experiment</button>
      <span class="hint">Starts the T+ clock. Every log entry records the time and T+.</span>
      <span class="spacer"></span>
      <button class="btn" id="b-timer">+ Timer</button>
    </div>${timerForm()}`;
  } else {
    root.innerHTML = `<div class="bench-inner">
      <div class="clock" title="Started ${esc(new Date(exp.started_at).toLocaleString())}">
        <span class="clock-label">T+</span><span class="clock-val" data-since="${esc(exp.started_at)}" data-until="${esc(exp.ended_at || "")}">0:00:00</span>
      </div>
      <div class="timers">${timers.map(timerChip).join("")}</div>
      <span class="spacer"></span>
      <button class="btn" id="b-timer">+ Timer</button>
      <button class="btn primary" id="b-log">✎ Log</button>
      ${running ? `<button class="btn" id="b-end" title="Stop the experiment clock">■ End</button>`
        : `<span class="small muted">Ended</span><button class="btn small" id="b-restart" title="Clear the clock to start again">Reset clock</button>`}
    </div>${timerForm()}`;
  }
  bind(root);
  tick();
  manageWakeLock();
}

function timerChip(t) {
  const cd = t.kind === "countdown" && t.duration_s;
  return `<div class="timer ${cd ? "countdown" : ""}" data-timer="${t.id}">
    <span class="t-label">${esc(t.label)}</span>
    <span class="t-val" data-since="${esc(t.started_at)}" ${cd ? `data-dur="${t.duration_s}" data-tid="${t.id}"` : ""}>0:00</span>
    <button class="t-stop" data-stop="${t.id}" title="${cd ? "Done" : "Stop and log the duration"}" aria-label="Stop ${esc(t.label)}">■</button>
    <button class="t-cancel" data-cancel="${t.id}" title="Discard this timer (nothing logged)" aria-label="Discard">✕</button>
  </div>`;
}

function timerForm() {
  const chems = state.data.reagents.filter((r) => r.role !== "product").map(labelOf);
  return `<form class="timer-form hidden" id="timer-form" autocomplete="off">
    <input id="tf-label" placeholder="What (e.g. Addition of NaBH4, Reflux)" list="tf-list" required aria-label="Timer label">
    <datalist id="tf-list">${["Reflux", "Stirring", "Addition", "Drying", "Crystallization", ...chems.map((c) => "Addition of " + c)]
      .map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
    <select id="tf-kind" aria-label="Timer type"><option value="stopwatch">Stopwatch</option><option value="countdown">Countdown</option></select>
    <input id="tf-dur" class="w-sm hidden" placeholder="e.g. 30 min" aria-label="Countdown duration">
    <button class="btn primary">Start</button><button type="button" class="btn" id="tf-close">Cancel</button>
  </form>`;
}

function bind(root) {
  $("#b-start", root)?.addEventListener("click", () => mutate("POST", `/api/experiments/${expId()}/start`));
  $("#b-end", root)?.addEventListener("click", () => {
    if (confirm("End the experiment? Running timers are stopped and logged.")) mutate("POST", `/api/experiments/${expId()}/end`);
  });
  $("#b-restart", root)?.addEventListener("click", () => {
    if (confirm("Reset the experiment clock? Existing log entries keep their T+ values.")) mutate("POST", `/api/experiments/${expId()}/restart`);
  });
  $("#b-log", root)?.addEventListener("click", () => {
    const composer = $("#composer");
    composer?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => $("#composer .action-chips button")?.focus(), 300);
  });
  const form = $("#timer-form", root);
  $("#b-timer", root)?.addEventListener("click", () => { form.classList.toggle("hidden"); $("#tf-label", root).focus(); });
  $("#tf-close", root)?.addEventListener("click", () => form.classList.add("hidden"));
  $("#tf-kind", root)?.addEventListener("change", (e) => $("#tf-dur", root).classList.toggle("hidden", e.target.value !== "countdown"));
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    const kind = $("#tf-kind", root).value;
    const body = { label: $("#tf-label", root).value.trim(), kind };
    if (kind === "countdown") {
      body.duration_s = parseDuration($("#tf-dur", root).value);
      if (!body.duration_s) { toast("Enter a duration, e.g. 30 min.", true); return; }
      askNotify();
    }
    startTimer(body);
  });
  $$("[data-stop]", root).forEach((b) => (b.onclick = () => mutate("POST", `/api/timers/${b.dataset.stop}/stop`)));
  $$("[data-cancel]", root).forEach((b) => (b.onclick = () => {
    if (confirm("Discard this timer without logging it?")) mutate("DELETE", `/api/timers/${b.dataset.cancel}`);
  }));
}

export function startTimer(body) {
  if (state.currentProc) body.procedure_id = state.currentProc;
  return mutate("POST", `/api/experiments/${expId()}/timers`, body);
}

// ------------------------------------------------------------------------------------------- ticking and alerts
function tick() {
  const now = nowServer();
  for (const el of $$("[data-since]")) {
    const since = Date.parse(el.dataset.since);
    const until = el.dataset.until ? Date.parse(el.dataset.until) : now;
    const elapsed = (until - since) / 1000;
    if (el.dataset.dur) {
      const left = Number(el.dataset.dur) - elapsed;
      el.textContent = left >= 0 ? fmtDur(left, true) : "+" + fmtDur(-left, true);
      const chip = el.closest(".timer");
      chip?.classList.toggle("overdue", left < 0);
      if (left < 0 && !alerted.has(el.dataset.tid)) {
        alerted.add(el.dataset.tid);
        alarm(chip?.querySelector(".t-label")?.textContent || "Timer");
      }
    } else {
      el.textContent = fmtDur(elapsed, el.classList.contains("t-val"));
    }
  }
}

export function startTicker() {
  setInterval(tick, 250);
}

function alarm(label) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880;
      o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.25, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.3);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.3);
    });
  } catch { /* no audio */ }
  navigator.vibrate?.([300, 150, 300, 150, 300]);
  toast(`⏰ ${label}: time is up`, true);
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification("Lab Notebook", { body: `${label}: time is up` }); } catch { /* not allowed here */ }
  }
}

function askNotify() {
  if ("Notification" in window && Notification.permission === "default" && window.isSecureContext) {
    Notification.requestPermission().catch(() => {});
  }
}

// Keep the phone screen on while an experiment runs (needs HTTPS or localhost)
async function manageWakeLock() {
  const exp = state.data?.experiment;
  const want = exp && exp.started_at && !exp.ended_at && document.visibilityState === "visible";
  if (want && !wakeLock && "wakeLock" in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => { wakeLock = null; });
    } catch { wakeLock = null; }
  } else if (!want && wakeLock) {
    wakeLock.release().catch(() => {});
    wakeLock = null;
  }
}
document.addEventListener("visibilitychange", () => { if (state.data) manageWakeLock(); });
