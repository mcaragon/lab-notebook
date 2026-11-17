"""Hazard data beyond GHS, extracted from PubChem Local's Laboratory Chemical Safety Summary.

Some chemicals have no GHS classification in PubChem but do have a US DOT transport classification, an NFPA 704
rating or reactivity alerts (e.g. primary explosives). These are kept per reagent as ``extra_hazards``:

    {"dot": {"un": [...], "classes": [...], "packing_groups": [...], "placards": [...], "forbidden": bool},
     "nfpa": {"health": 1, "fire": 3, "instability": 0, "special": "W"},
     "alerts": ["Explosive", ...]}
"""
from __future__ import annotations

import re
from typing import Any, Iterator, Optional

_CFR = re.compile(r"\s*\(49 eCFR[^)]*\)\s*")


def _entries(sections: list, heading: str) -> Iterator[dict]:
    for s in sections or []:
        if s.get("heading") == heading:
            yield from s.get("entries") or []
        yield from _entries(s.get("sections") or [], heading)


def _uniq(items) -> list:
    out: list = []
    for i in items:
        if i and i not in out:
            out.append(i)
    return out


def parse_nfpa(diamond: str) -> Optional[dict]:
    """'1-3-0' or '3-2-2-W' -> {health, fire, instability, special}."""
    m = re.match(r"\s*([0-4])\s*-\s*([0-4])\s*-\s*([0-4])(?:\s*-\s*(\S+))?", diamond or "")
    if not m:
        return None
    return {"health": int(m.group(1)), "fire": int(m.group(2)), "instability": int(m.group(3)),
            "special": m.group(4) or None}


def extract(summary: Optional[dict]) -> dict:
    """``extra_hazards`` from a ``/api/compound/{cid}/safety-summary`` response (empty dict if nothing)."""
    if not summary:
        return {}
    sections = summary.get("sections") or []
    out: dict[str, Any] = {}

    dot = list(_entries(sections, "DOT Hazard Classification"))
    if dot:
        un = _uniq(str(e.get("value")).strip() for e in dot if e.get("name") == "DOT ID (UN/NA Number)")
        classes = _uniq(_CFR.sub(" ", str(e.get("value"))).strip()
                        for e in dot if e.get("name") in ("Hazard Class/Division", "Hazard Class/Label Code(s)",
                                                          "Hazard Class", "Label Codes"))
        pgs = _uniq(m.group(1) for e in dot if e.get("name") == "Packing Group"
                    for m in [re.match(r"\s*PG\s*(I{1,3})\b", str(e.get("value")))] if m)
        placards = _uniq(str(e.get("value")).strip() for e in dot if e.get("name") == "Placard/Label(s)")
        forbidden = any("forbidden" in c.lower() for c in classes)
        out["dot"] = {"un": un, "classes": classes, "packing_groups": pgs, "placards": placards,
                      "forbidden": forbidden}

    for e in _entries(sections, "NFPA Hazard Classification"):
        if e.get("name") == "NFPA 704 Diamond":
            nfpa = parse_nfpa(str(e.get("value")))
            if nfpa:
                out["nfpa"] = nfpa
                break

    alerts = _uniq(a.strip() for e in _entries(sections, "Reactivity Alerts")
                   for a in re.split(r"[;,]", str(e.get("value") or "")))
    if alerts:
        out["alerts"] = alerts
    return out


def summary_lines(extra: Optional[dict]) -> list[str]:
    """Short human-readable lines for tables: 'DOT: FORBIDDEN', 'UN1230, Class 3, PG II', 'NFPA 1-3-0'."""
    if not extra:
        return []
    lines = []
    dot = extra.get("dot") or {}
    if dot:
        if dot.get("forbidden"):
            lines.append("DOT: forbidden for transport")
        parts = list(dot.get("un") or [])
        classes = [c for c in dot.get("classes") or [] if "forbidden" not in c.lower()]
        parts += classes[:2]
        if dot.get("packing_groups"):
            parts.append("PG " + "/".join(dot["packing_groups"]))
        if parts:
            lines.append("DOT: " + ", ".join(parts))
    nfpa = extra.get("nfpa")
    if nfpa:
        lines.append(f"NFPA 704: {nfpa['health']}-{nfpa['fire']}-{nfpa['instability']}"
                     + (f" {nfpa['special']}" if nfpa.get("special") else ""))
    if extra.get("alerts"):
        lines.append("Reactivity: " + ", ".join(extra["alerts"]))
    return lines
