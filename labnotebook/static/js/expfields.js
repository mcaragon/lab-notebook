/* Autosaved experiment fields (title, metadata, text sections). */
import { $, $$, api, debounce, esc, toast } from "./util.js";
import { state, expId } from "./state.js";

const pendingExp = {};
let pendingExpId = null;
export const flushExp = debounce(async () => {
  const body = { ...pendingExp }, id = pendingExpId;
  Object.keys(pendingExp).forEach((k) => delete pendingExp[k]);
  if (!id || !Object.keys(body).length) return;
  try {
    const { experiment } = await api("PUT", `/api/experiments/${id}`, body);
    if (state.data?.experiment.id === id) {
      state.data.experiment = { ...experiment, ...pendingExp };
      const s = $("#saved");
      if (s) s.textContent = "Saved";
    }
  } catch (e) { toast("Not saved: " + e.message, true); }
}, 700);

export function saveExp(fields, now = false) {
  const id = expId();
  if (pendingExpId !== id) flushExp.flush();
  pendingExpId = id;
  Object.assign(pendingExp, fields);
  Object.assign(state.data.experiment, fields);
  const s = $("#saved");
  if (s) s.textContent = "Saving…";
  flushExp();
  if (now) flushExp.flush();
}

export function sectionField(key, label, hint = "", rows = 5) {
  const v = state.data.experiment[key] || "";
  return `<label class="field">${esc(label)}${hint ? ` <span class="hint">${esc(hint)}</span>` : ""}
    <textarea data-section="${key}" data-key="sec-${key}" rows="${rows}">${esc(v)}</textarea></label>`;
}

export function bindSections(root) {
  $$("textarea[data-section]", root).forEach((t) =>
    t.addEventListener("input", () => saveExp({ [t.dataset.section]: t.value })));
}


export const hasPendingExp = () => Object.keys(pendingExp).length > 0;
