"""Structured log actions.

Each action has a list of fields (served to the frontend, which builds its forms from them) and a sentence template.
The sentence is generated on the server so the log, the report and the Markdown export all read the same.

Field types: ``chem`` (a reagent of the experiment or a typed name), ``number``, ``text``, ``select`` (with
``options``), ``duration`` (free text such as "10 min"), ``product`` (a product of the experiment).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

AMOUNT_UNITS = ["g", "mg", "mL", "µL", "mmol", "equiv", "drops"]

ACTIONS: dict[str, dict] = {
    "add": {
        "label": "Add", "timer": True,
        "fields": [
            {"name": "chem", "label": "What", "type": "chem", "required": True},
            {"name": "amount", "label": "Amount", "type": "number"},
            {"name": "unit", "label": "Unit", "type": "select", "options": AMOUNT_UNITS},
            {"name": "mode", "label": "How", "type": "select",
             "options": ["in one portion", "portionwise", "dropwise", "via syringe", "via cannula", "as a solid"]},
            {"name": "over", "label": "Over", "type": "duration"},
            {"name": "temp", "label": "At (°C)", "type": "text"},
        ],
    },
    "weigh": {
        "label": "Amount used",
        "fields": [
            {"name": "chem", "label": "What", "type": "chem", "required": True},
            {"name": "amount", "label": "Amount", "type": "number", "required": True},
            {"name": "unit", "label": "Unit", "type": "select", "options": ["g", "mg", "mL", "µL"]},
        ],
    },
    "quench": {
        "label": "Quench",
        "fields": [
            {"name": "chem", "label": "With", "type": "chem", "required": True},
            {"name": "amount", "label": "Amount", "type": "number"},
            {"name": "unit", "label": "Unit", "type": "select", "options": AMOUNT_UNITS},
        ],
    },
    "extract": {
        "label": "Extract",
        "fields": [
            {"name": "chem", "label": "With", "type": "chem", "required": True},
            {"name": "n", "label": "Times", "type": "number"},
            {"name": "volume", "label": "Volume each (mL)", "type": "number"},
        ],
    },
    "wash": {
        "label": "Wash",
        "fields": [
            {"name": "chem", "label": "With", "type": "chem", "required": True},
            {"name": "n", "label": "Times", "type": "number"},
            {"name": "volume", "label": "Volume each (mL)", "type": "number"},
        ],
    },
    "dry": {
        "label": "Dry",
        "fields": [{"name": "chem", "label": "Over", "type": "chem", "required": True}],
    },
    "filter": {
        "label": "Filter",
        "fields": [{"name": "through", "label": "Through (optional)", "type": "text"},
                   {"name": "rinse", "label": "Rinsed with (optional)", "type": "chem"}],
    },
    "concentrate": {
        "label": "Concentrate",
        "fields": [{"name": "method", "label": "How", "type": "select",
                    "options": ["under reduced pressure", "by rotary evaporation", "under a stream of N₂",
                                "on a high-vacuum line"]}],
    },
    "temperature": {
        "label": "Heat / cool", "timer": True,
        "fields": [
            {"name": "verb", "label": "Action", "type": "select",
             "options": ["Cooled to", "Heated to", "Warmed to", "Heated at reflux", "Allowed to warm to"]},
            {"name": "temp", "label": "Temperature (°C or rt)", "type": "text"},
            {"name": "duration", "label": "For", "type": "duration"},
        ],
    },
    "stir": {
        "label": "Stir", "timer": True,
        "fields": [{"name": "temp", "label": "At (°C or rt)", "type": "text"},
                   {"name": "duration", "label": "For", "type": "duration"}],
    },
    "tlc": {
        "label": "TLC",
        "fields": [{"name": "eluent", "label": "Eluent", "type": "text"},
                   {"name": "spots", "label": "Spots (e.g. SM 0.55, product 0.25)", "type": "text"},
                   {"name": "stain", "label": "Visualization", "type": "text"}],
    },
    "purify": {
        "label": "Purify",
        "fields": [{"name": "method", "label": "Method", "type": "select",
                    "options": ["flash column chromatography", "recrystallization", "distillation",
                                "Kugelrohr distillation", "sublimation", "preparative TLC", "trituration"]},
                   {"name": "solvent", "label": "Eluent / solvent", "type": "text"}],
    },
    "isolate": {
        "label": "Product mass",
        "fields": [{"name": "product", "label": "Product", "type": "product", "required": True},
                   {"name": "stage", "label": "Stage", "type": "select", "options": ["purified", "crude"]},
                   {"name": "mass", "label": "Mass (g)", "type": "number", "required": True},
                   {"name": "appearance", "label": "Appearance", "type": "text"}],
    },
    "measure": {
        "label": "Measurement",
        "fields": [{"name": "quantity", "label": "Quantity", "type": "text", "required": True,
                    "suggest": ["mp", "bp", "Internal temperature", "pH", "Mass", "Volume", "Rf", "Pressure"]},
                   {"name": "value", "label": "Value", "type": "text", "required": True},
                   {"name": "unit", "label": "Unit", "type": "text",
                    "suggest": ["°C", "g", "mg", "mL", "mmHg", "mbar", "min", "h"]}],
    },
    "observation": {"label": "Observation",
                    "fields": [{"name": "text", "label": "Observation", "type": "text", "required": True}]},
    "note": {"label": "Note", "fields": [{"name": "text", "label": "Note", "type": "text", "required": True}]},
}
# Created by the app, not offered in the action picker
SYSTEM_ACTIONS = {"timer", "start", "end", "procedure"}
# Actions whose amount is the reagent's actual (measured) amount
AMOUNT_ACTIONS = ("add", "weigh")


def fmt_num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v or "")
    return f"{f:g}" if abs(f) >= 0.001 or f == 0 else f"{f:.2e}"


def fmt_temp(t: Any) -> str:
    """'0' -> '0 °C', '-78' -> '−78 °C', 'rt' / 'reflux' unchanged."""
    s = str(t or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"[−-]?\d+(?:[.,]\d+)?", s):
        return s.replace("-", "−") + " °C"
    if re.fullmatch(r"[−-]?\d+(?:[.,]\d+)?\s*(?:to|–|-)\s*[−-]?\d+(?:[.,]\d+)?", s):
        return s.replace("-", "–") + " °C"
    return s


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_duration(text: Any) -> Optional[float]:
    """'10 min', '1 h 30 min', '90 s', '1.5 h', '1:30', '1:30:00' -> seconds."""
    s = str(text or "").strip().lower().replace(",", ".")
    if not s:
        return None
    if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", s):
        parts = [int(p) for p in s.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)\b", s):
        found = True
        total += float(num) * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
    if found:
        return total
    try:
        return float(s) * 60  # a bare number is minutes
    except ValueError:
        return None


def _chem(data: dict, key: str, names: Callable[[Any], Optional[str]]) -> str:
    v = data.get(key)
    if isinstance(v, dict):
        return (names(v.get("reagent_id")) if v.get("reagent_id") else None) or v.get("name") or ""
    return str(v or "")


def _amount(data: dict) -> str:
    if data.get("amount") in (None, ""):
        return ""
    return f"{fmt_num(data['amount'])} {data.get('unit') or ''}".strip()


def _times(data: dict) -> str:
    n, vol = data.get("n"), data.get("volume")
    if n not in (None, "") and vol not in (None, ""):
        return f"{fmt_num(n)} × {fmt_num(vol)} mL"
    if vol not in (None, ""):
        return f"{fmt_num(vol)} mL"
    if n not in (None, ""):
        return f"{fmt_num(n)}×"
    return ""


def describe(action: str, data: dict, names: Callable[[Any], Optional[str]] = lambda _id: None) -> str:
    """Sentence for a log entry. ``names`` maps a reagent id to its display name."""
    d = data or {}
    if action == "add":
        what = _chem(d, "chem", names)
        amt = _amount(d)
        s = f"{what} ({amt}) added" if amt else f"{what} added"
        if d.get("mode"):
            s += f" {d['mode']}"
        if d.get("over"):
            s += f" over {d['over']}"
        if d.get("temp"):
            s += f" at {fmt_temp(d['temp'])}"
        return s
    if action == "quench":
        amt = _amount(d)
        return f"Quenched with {_chem(d, 'chem', names)}" + (f" ({amt})" if amt else "")
    if action in ("extract", "wash"):
        t = _times(d)
        verb = "Extracted" if action == "extract" else "Washed"
        return f"{verb} with {_chem(d, 'chem', names)}" + (f" ({t})" if t else "")
    if action == "dry":
        return f"Dried over {_chem(d, 'chem', names)}"
    if action == "filter":
        s = "Filtered" + (f" through {d['through']}" if d.get("through") else "")
        rinse = _chem(d, "rinse", names)
        return s + (f", rinsing with {rinse}" if rinse else "")
    if action == "concentrate":
        return f"Concentrated {d.get('method') or 'under reduced pressure'}"
    if action == "temperature":
        verb = d.get("verb") or "Heated to"
        s = verb if "reflux" in verb else f"{verb} {fmt_temp(d.get('temp'))}".strip()
        return s + (f" for {d['duration']}" if d.get("duration") else "")
    if action == "stir":
        s = "Stirred"
        if d.get("temp"):
            s += f" at {fmt_temp(d['temp'])}"
        return s + (f" for {d['duration']}" if d.get("duration") else "")
    if action == "tlc":
        s = "TLC" + (f" ({d['eluent']})" if d.get("eluent") else "")
        if d.get("spots"):
            s += f": {d['spots']}"
        if d.get("stain"):
            s += f"; visualized with {d['stain']}"
        return s
    if action == "purify":
        return f"Purified by {d.get('method') or 'chromatography'}" + (f" ({d['solvent']})" if d.get("solvent") else "")
    if action == "isolate":
        prod = names(d.get("product")) or "Product"
        s = f"{prod} ({d.get('stage') or 'purified'}): {fmt_num(d.get('mass'))} g"
        return s + (f", {d['appearance']}" if d.get("appearance") else "")
    if action == "measure":
        return f"{d.get('quantity') or 'Measurement'}: {d.get('value') or ''} {d.get('unit') or ''}".strip()
    if action == "weigh":
        what = _chem(d, "chem", names) if d.get("chem") else (names(d.get("reagent_id")) or "Reagent")
        amount = d.get("amount", d.get("value"))
        return f"{what} measured: {fmt_num(amount)} {d.get('unit') or ''}".strip()
    if action in ("observation", "note"):
        return str(d.get("text") or "")
    return str(d.get("text") or "")


# Volumes (mL) or masses (g) of each reagent consumed by log actions, for the reagent table and waste totals
def usage(entries: list[dict]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for e in entries:
        d = e.get("data") or {}
        if e.get("action") not in ("quench", "extract", "wash", "add", "filter"):
            continue
        key = "rinse" if e.get("action") == "filter" else "chem"
        chem = d.get(key)
        rid = chem.get("reagent_id") if isinstance(chem, dict) else None
        if not rid:
            continue
        u = out.setdefault(rid, {})
        if e["action"] in ("extract", "wash"):
            try:
                vol = float(d.get("volume") or 0) * float(d.get("n") or 1)
            except (TypeError, ValueError):
                vol = 0
            if vol:
                u["mL"] = u.get("mL", 0) + vol
        elif d.get("amount") not in (None, "") and d.get("unit") in ("mL", "g", "mg", "µL"):
            try:
                amt = float(d["amount"])
            except (TypeError, ValueError):
                continue
            unit = d["unit"]
            if unit == "mg":
                unit, amt = "g", amt / 1000
            if unit == "µL":
                unit, amt = "mL", amt / 1000
            u[unit] = u.get(unit, 0) + amt
    return out


def entry_reagent(e: dict) -> Optional[int]:
    """Reagent id an amount entry refers to (add / weigh)."""
    d = e.get("data") or {}
    chem = d.get("chem")
    rid = chem.get("reagent_id") if isinstance(chem, dict) else None
    return rid or d.get("reagent_id")


def entry_amount(e: dict) -> Optional[tuple[float, str]]:
    """(amount, 'g' | 'mL') of an amount entry, converting mg and µL; None for other units."""
    d = e.get("data") or {}
    amount = d.get("amount", d.get("value"))
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    unit = d.get("unit") or "g"
    if unit == "mg":
        return amount / 1000, "g"
    if unit in ("µL", "uL"):
        return amount / 1000, "mL"
    if unit in ("g", "mL"):
        return amount, unit
    return None


def actual_from_log(entries: list[dict], rid: int) -> Optional[tuple[float, str]]:
    """The actual amount of a reagent according to the log: the latest 'Amount used' entry, else the total of the
    'Add' entries (in the unit of the first one). None when the log has no amount for it."""
    mine = [e for e in entries if e.get("action") in AMOUNT_ACTIONS and entry_reagent(e) == rid]
    weighs = [e for e in mine if e["action"] == "weigh" and entry_amount(e)]
    if weighs:
        return entry_amount(weighs[-1])
    total, unit = 0.0, None
    for e in mine:
        a = entry_amount(e)
        if not a:
            continue
        if unit is None:
            unit = a[1]
        if a[1] == unit:
            total += a[0]
    return (total, unit) if unit else None
