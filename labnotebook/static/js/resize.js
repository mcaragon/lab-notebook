/* Draggable dividers between panes. A divider is <div class="resizer" data-var="--name" data-side="prev|next|parent"
   data-min data-max>: dragging it sets the CSS variable --name to the width of the pane on that side, in px.
   Widths are remembered per browser; double-click resets a divider. One delegated listener serves every divider, so
   re-rendered panes need no setup. */
const KEY = "ln.panes";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const save = (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* private mode */ } };
const root = document.documentElement;

export function initResizers() {
  for (const [k, v] of Object.entries(load())) root.style.setProperty(k, `${v}px`);

  document.addEventListener("pointerdown", (e) => {
    const h = e.target.closest(".resizer");
    if (!h || e.button !== 0) return;
    const side = h.dataset.side || "prev";
    const pane = side === "parent" ? h.parentElement : side === "next" ? h.nextElementSibling : h.previousElementSibling;
    if (!pane) return;
    e.preventDefault();
    const dir = side === "next" ? -1 : 1;              // dragging right grows a pane on the left, shrinks one on the right
    const start = pane.getBoundingClientRect().width;
    const x0 = e.clientX;
    const min = Number(h.dataset.min || 180), max = Number(h.dataset.max || 900);
    let w = start;
    h.classList.add("dragging");
    document.body.classList.add("resizing");
    h.setPointerCapture(e.pointerId);
    const move = (ev) => {
      w = Math.round(Math.min(max, Math.max(min, start + dir * (ev.clientX - x0))));
      root.style.setProperty(h.dataset.var, `${w}px`);
    };
    const up = () => {
      h.removeEventListener("pointermove", move);
      h.removeEventListener("pointerup", up);
      h.removeEventListener("pointercancel", up);
      h.classList.remove("dragging");
      document.body.classList.remove("resizing");
      const v = load();
      v[h.dataset.var] = w;
      save(v);
    };
    h.addEventListener("pointermove", move);
    h.addEventListener("pointerup", up);
    h.addEventListener("pointercancel", up);
  });

  document.addEventListener("dblclick", (e) => {
    const h = e.target.closest(".resizer");
    if (!h) return;
    root.style.removeProperty(h.dataset.var);
    const v = load();
    delete v[h.dataset.var];
    save(v);
  });

  // keyboard: focus a divider and use the arrow keys
  document.addEventListener("keydown", (e) => {
    const h = e.target.closest?.(".resizer");
    if (!h || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    const side = h.dataset.side || "prev";
    const pane = side === "parent" ? h.parentElement : side === "next" ? h.nextElementSibling : h.previousElementSibling;
    const dir = (side === "next" ? -1 : 1) * (e.key === "ArrowRight" ? 1 : -1);
    const min = Number(h.dataset.min || 180), max = Number(h.dataset.max || 900);
    const w = Math.round(Math.min(max, Math.max(min, pane.getBoundingClientRect().width + dir * 20)));
    root.style.setProperty(h.dataset.var, `${w}px`);
    const v = load();
    v[h.dataset.var] = w;
    save(v);
  });
}

/** Markup for a divider. */
export const resizer = (cssVar, side, min, max, label) =>
  `<div class="resizer" role="separator" aria-orientation="vertical" tabindex="0" aria-label="${label}"
    title="Drag to resize · double-click to reset" data-var="${cssVar}" data-side="${side}" data-min="${min}" data-max="${max}"></div>`;
