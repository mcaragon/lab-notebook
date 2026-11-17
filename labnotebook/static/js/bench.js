/* Bench bar: experiment clock (T+), running timers and countdowns, alerts and screen wake lock. */
import { $, $$, esc, fmtDur, toast } from "./util.js";
import { state, mutate, expId, nowServer } from "./state.js";
import { openComposer, focusQuickLog } from "./procedure.js";

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
    </div>`;
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
    </div>`;
  }
  bind(root);
  tick();
  manageWakeLock();
}

function timerChip(t) {
  const cd = t.kind === "countdown" && t.duration_s;
  return `<div class="timer ${cd ? "countdown" : ""}" data-timer="${t.id}">
    <span class="t-label" title="${esc(t.label)}">${cd ? "⏳ " : "⏱ "}${esc(t.label)}</span>
    <span class="t-val" data-since="${esc(t.started_at)}" ${cd ? `data-dur="${t.duration_s}" data-tid="${t.id}"` : ""}>0:00</span>
    <button class="t-stop" data-stop="${t.id}" title="${cd ? "Done (logs the time)" : "Stop and log the duration"}">${cd ? "Done" : "Stop"}</button>
    <button class="t-cancel" data-cancel="${t.id}" title="Discard this timer (nothing logged)" aria-label="Discard ${esc(t.label)}">✕</button>
  </div>`;
}

/** Switch to the Bench tab, then run fn once it is visible. */
function onBench(fn) {
  const want = `#/exp/${expId()}/bench`;
  if (state.tab !== "bench") { location.hash = want; setTimeout(fn, 60); } else fn();
}

function bind(root) {
  $("#b-start", root)?.addEventListener("click", () => mutate("POST", `/api/experiments/${expId()}/start`));
  $("#b-end", root)?.addEventListener("click", () => {
    if (confirm("End the experiment? Running timers are stopped and logged.")) mutate("POST", `/api/experiments/${expId()}/end`);
  });
  $("#b-restart", root)?.addEventListener("click", () => {
    if (confirm("Reset the experiment clock? Existing log entries keep their T+ values.")) mutate("POST", `/api/experiments/${expId()}/restart`);
  });
  $("#b-log", root)?.addEventListener("click", () => onBench(focusQuickLog));
  $("#b-timer", root)?.addEventListener("click", () => onBench(() => openComposer("timer")));
  $$("[data-stop]", root).forEach((b) => (b.onclick = () => mutate("POST", `/api/timers/${b.dataset.stop}/stop`).catch(() => {})));
  $$("[data-cancel]", root).forEach((b) => (b.onclick = () => {
    if (confirm("Discard this timer without logging it?")) mutate("DELETE", `/api/timers/${b.dataset.cancel}`).catch(() => {});
  }));
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
