/* Application state and the single mutation path: every change goes to the server, which returns the full
   experiment; the page then re-renders the parts whose data changed, in the open tab only. */
import { api, toast } from "./util.js";

export const state = {
  user: null,          // the signed-in account ({id, username, display_name, is_admin, demo, ...})
  config: null,
  data: null,          // full experiment detail from the server
  clockOffset: 0,      // server time - client time (ms), so T+ is right even if the device clock is off
  open: new Set(),     // expanded reagent rows
  currentProc: null,   // procedure row new log entries attach to
  tab: "plan",         // open workspace
  renderers: [],       // {tab, sig: () => string, render: () => void, last}
};

/** Register a part of the page. `tab` is the workspace it lives in ("*" = always visible). */
export function addRenderer(tab, sig, render) {
  state.renderers.push({ tab, sig, render, last: null });
}

/** Re-render visible parts whose data signature changed (force: re-render all visible parts). */
export function refresh(force = false) {
  for (const r of state.renderers) {
    if (r.tab !== "*" && r.tab !== state.tab) continue;
    const sig = r.sig ? r.sig() : null;
    if (!force && sig !== null && sig === r.last) continue;
    r.last = sig;
    r.render();
  }
}

export function setData(d, force = false) {
  state.data = d;
  if (d.server_time) state.clockOffset = Date.parse(d.server_time) - Date.now();
  if (state.currentProc && !d.procedure.some((p) => p.id === state.currentProc)) state.currentProc = null;
  refresh(force);
}

/** Send a change; when the server answers with the full experiment, re-render from it. */
export async function mutate(method, path, body) {
  try {
    const d = await api(method, path, body);
    if (d && d.experiment && d.steps) setData(d);
    return d;
  } catch (e) {
    toast(e.message, true);
    throw e;
  }
}

/** JSON signature of parts of the experiment, for change detection. */
export const sigOf = (...parts) => JSON.stringify(parts);

export const expId = () => state.data?.experiment.id;
export const nowServer = () => Date.now() + state.clockOffset;
export const reagentById = (id) => state.data?.reagents.find((r) => r.id === Number(id));
export const labelOf = (r) => (r?.label || r?.name || "?");
/** A one-pot reaction in several stages. */
export const multiStage = () => (state.data?.steps.length || 0) > 1;
