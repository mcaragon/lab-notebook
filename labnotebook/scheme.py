"""Reaction scheme layout and procedure mentions, shared by the app and the report.

The scheme is a row of segments: structures (joined by "+") and arrows. Each arrow carries the step's reagents and
catalysts above it and its solvents, atmosphere and condition stages below it, following the usual organic chemistry
convention. With ``scheme_style`` "lettered" (or "auto" when the text is long) the arrows show (a), (b), ... and the
conditions are listed under the scheme instead.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .actions import fmt_temp


def _fmt(v: Any, sig: int = 3) -> str:
    from .report import fmt  # local import: report imports this module

    return fmt(v, sig)


def label(r: dict) -> str:
    return (r.get("label") or r.get("name") or "?").strip()


def _reagent_text(r: dict, c: dict) -> str:
    """'NaBH4 (0.5 equiv)', 'Pd(PPh3)4 (5 mol%)'."""
    s = label(r)
    eq = c.get("act_equiv") if c.get("act_equiv") is not None else c.get("equiv")
    if eq is not None and r.get("role") in ("reagent", "reactant"):
        s += f" ({_fmt(eq, 2)} equiv)"
    elif eq is not None and r.get("role") == "catalyst":
        s += f" ({_fmt(eq * 100, 2)} mol%)"
    if r.get("form") == "solution" and r.get("concentration_m"):
        s += f" ({_fmt(r['concentration_m'])} M)" if "(" not in s else ""
    return s


def conditions_text(step: dict) -> str:
    """Condition stages: '0 °C, 15 min; then rt, 2 h'."""
    stages = []
    for k in step.get("conditions") or []:
        parts = [p for p in (fmt_temp(k.get("temperature")), (k.get("duration") or "").strip(),
                             (k.get("note") or "").strip()) if p]
        if parts:
            stages.append(", ".join(parts))
    return "; then ".join(stages)


def build(bundle: dict, calc: dict, style: Optional[str] = None) -> dict:
    """Scheme layout.

    Returns ``{"segments": [...], "lettered": bool, "legend": [(letter, text)], "numbers": {reagent_id: n}}``.
    Segment types: ``{"type": "mols", "mols": [{"reagent", "number", "yield"}]}`` and
    ``{"type": "arrow", "letter", "above": [str], "below": [str], "step_id", "step_no"}``.
    """
    steps = bundle["steps"]
    reagents = bundle["reagents"]
    rows = calc["rows"]
    by_step = {s["id"]: [r for r in reagents if r.get("step_id") == s["id"]] for s in steps}
    numbers: dict[int, int] = {}
    segments: list[dict] = []
    arrows: list[dict] = []

    by_ident: dict[Any, int] = {}

    def ident(r: dict) -> Any:
        return r.get("cid") or (r.get("smiles") or "").strip() or (r.get("name") or "").strip().lower() or r["id"]

    def mol(r: dict, with_yield: bool = False) -> dict:
        """Number compounds in order of appearance; the same compound keeps its number."""
        if r["id"] not in numbers:
            src = r.get("source_reagent_id")
            n = numbers.get(src) or by_ident.get(ident(r)) or (max(numbers.values(), default=0) + 1)
            numbers[r["id"]] = n
            by_ident.setdefault(ident(r), n)
        c = rows.get(r["id"], {})
        return {"reagent": r, "number": numbers[r["id"]],
                "yield": c.get("percent_yield") if with_yield else None}

    prev_products: list[dict] = []
    for i, s in enumerate(steps):
        rs = by_step[s["id"]]
        pos = lambda r: r.get("scheme_pos") or "auto"  # noqa: E731
        reactants = [r for r in rs if r.get("role") == "reactant" and pos(r) != "hidden"]
        carried = [r for r in reactants if r.get("source_reagent_id")
                   and any(p["id"] == r["source_reagent_id"] for p in prev_products)]
        if i == 0 or not prev_products:
            left = [r for r in reactants if pos(r) in ("auto", "structure")]
            if left:
                segments.append({"type": "mols", "mols": [mol(r) for r in left]})
            extra_above = [r for r in reactants if pos(r) == "above"]
            extra_below = [r for r in reactants if pos(r) == "below"]
        else:
            for r in carried:  # the previous product continues the chain under the same number
                if r["source_reagent_id"] in numbers:
                    numbers.setdefault(r["id"], numbers[r["source_reagent_id"]])
            others = [r for r in reactants if r not in carried]
            extra_above = [r for r in others if pos(r) in ("auto", "above", "structure")]
            extra_below = [r for r in others if pos(r) == "below"]
        above, below = [], []
        for r in extra_above:
            above.append(_reagent_text(r, rows.get(r["id"], {})))
        for r in rs:
            p, role = pos(r), r.get("role")
            if role in ("reactant", "product", "workup") or p == "hidden":
                continue
            target = (above if role in ("reagent", "catalyst") else below) if p == "auto" else \
                (above if p == "above" else below)
            target.append(label(r) if role == "solvent" else _reagent_text(r, rows.get(r["id"], {})))
        for r in extra_below:
            below.append(_reagent_text(r, rows.get(r["id"], {})))
        if s.get("atmosphere"):
            below.append(s["atmosphere"])
        cond = conditions_text(s)
        if cond:
            below.append(cond)
        arrow = {"type": "arrow", "letter": chr(ord("a") + i), "above": above, "below": below,
                 "step_id": s["id"], "step_no": i + 1}
        segments.append(arrow)
        arrows.append(arrow)
        products = [r for r in rs if r.get("role") == "product" and pos(r) != "hidden"]
        if products:
            segments.append({"type": "mols", "mols": [mol(r, with_yield=True) for r in products]})
        prev_products = products

    style = style or bundle["experiment"].get("scheme_style") or "auto"
    longest = max((len(", ".join(a["above"])) for a in arrows), default=0)
    longest = max([longest] + [len(", ".join(a["below"])) for a in arrows])
    lettered = style == "lettered" or (style == "auto" and (longest > 34 or len(arrows) > 2))
    legend = [(a["letter"], ", ".join(a["above"] + a["below"])) for a in arrows] if lettered else []
    return {"segments": segments, "lettered": lettered, "legend": legend, "numbers": numbers,
            "empty": not any(seg["type"] == "mols" for seg in segments)}


# ------------------------------------------------------------------------------------------- mentions
MENTION = re.compile(r"@\{([^}]+)\}|@([A-Za-z0-9][\w\-()+,.]*[\w)])")


def find_reagent(token: str, reagents: list[dict]) -> Optional[dict]:
    t = token.strip().lower()
    for key in ("label", "name", "formula", "cas"):
        for r in reagents:
            if (r.get(key) or "").strip().lower() == t:
                return r
    return None


def amount_phrase(r: dict, c: dict) -> str:
    """'0.189 g, 5.00 mmol' using actual amounts when entered."""
    from .report import fmt

    act = c.get("act_mmol") is not None or c.get("act_mass_g") is not None or c.get("act_volume_ml") is not None
    mass = c.get("act_mass_g") if act else c.get("mass_g")
    vol = c.get("act_volume_ml") if act else c.get("volume_ml")
    mmol = c.get("act_mmol") if act else c.get("mmol")
    parts = []
    liquid = r.get("form") != "neat" or (r.get("basis") == "volume" or r.get("actual_basis") == "volume")
    if r.get("role") == "solvent":
        if vol is not None:
            parts.append(f"{fmt(vol)} mL")
    else:
        if liquid and vol is not None:
            parts.append(f"{fmt(vol)} mL")
        elif mass is not None:
            parts.append(f"{fmt(mass)} g")
        if mmol is not None:
            parts.append(f"{fmt(mmol)} mmol")
        eq = c.get("act_equiv") if act and c.get("act_equiv") is not None else c.get("equiv")
        if eq is not None and r.get("role") in ("reagent", "catalyst", "reactant") and abs(eq - 1) > 1e-9:
            parts.append(f"{fmt(eq, 3)} equiv")
    return ", ".join(parts)


def render_mentions(text: str, reagents: list[dict], rows: dict, mode: str = "text") -> str:
    """Replace @Name / @{Name with spaces} by 'Name (amounts)'. ``mode`` "html" escapes and bolds the name."""
    import html as _html

    out, last = [], 0
    for m in MENTION.finditer(text or ""):
        token = m.group(1) or m.group(2)
        r = find_reagent(token, reagents)
        if not r and m.group(2):  # '@NaBH4,' -> try without trailing punctuation
            trimmed = token.rstrip(".,)")
            r = find_reagent(trimmed, reagents)
            if r:
                m_end = m.start() + 1 + len(trimmed)
            else:
                m_end = m.end()
        else:
            m_end = m.end()
        seg = text[last:m.start()]
        out.append(_html.escape(seg) if mode == "html" else seg)
        if r:
            phr = amount_phrase(r, rows.get(r["id"], {}))
            name = label(r)
            if mode == "html":
                out.append(f'<span class="mention"><b>{_html.escape(name)}</b>'
                           + (f" ({_html.escape(phr)})" if phr else "") + "</span>")
            else:
                out.append(name + (f" ({phr})" if phr else ""))
        else:
            raw = text[m.start():m_end]
            out.append(_html.escape(raw) if mode == "html" else raw)
        last = m_end
    tail = (text or "")[last:]
    out.append(_html.escape(tail) if mode == "html" else tail)
    return "".join(out)
