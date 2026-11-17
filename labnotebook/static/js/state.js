/* Application state and the single mutation path: every change goes to the server, which returns the full
   experiment; the page then re-renders from it. */
import { api, toast } from "./util.js";

export const state = {
  config: null,
  data: null,          // full experiment detail from the server
  clockOffset: 0,      // server time - client time (ms), so T+ is right even if the device clock is off
  open: new Set(),     // expanded reagent rows
  currentProc: null,   // procedure row new log entries attach to
  renderers: [],       // functions re-run after every change
};

export function setData(d) {
  state.data = d;
  if (d.server_time) state.clockOffset = Date.parse(d.server_time) - Date.now();
  if (state.currentProc && !d.procedure.some((p) => p.id === state.currentProc)) state.currentProc = null;
  for (const r of state.renderers) r();
}

export async function mutate(method, path, body) {
  try {
    const d = await api(method, path, body);
    if (d && d.experiment) setData(d);
    return d;
  } catch (e) {
    toast(e.message, true);
    throw e;
  }
}

export const expId = () => state.data?.experiment.id;
export const nowServer = () => Date.now() + state.clockOffset;
export const reagentById = (id) => state.data?.reagents.find((r) => r.id === Number(id));
export const labelOf = (r) => (r?.label || r?.name || "?");
export const multiStep = () => (state.data?.steps.length || 0) > 1;
