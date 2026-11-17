"""Sequences: separate experiments linked into one multi-step route.

Each experiment keeps its own clock, procedure and log. A sequence puts them in order; the overall scheme and yield
treat every step of every experiment as one chain. Where a starting material of an experiment is the product of the
previous experiment (same PubChem CID, SMILES or name), the chain continues through it, also when the experiments
were linked after the fact.
"""
from __future__ import annotations

from typing import Any, Optional

from . import db, stoich


def _ident(r: dict) -> Any:
    return r.get("cid") or (r.get("smiles") or "").strip() or (r.get("name") or "").strip().lower() or None


def combine(bundles: list[dict]) -> dict:
    """One bundle with the steps and reagents of all experiments, linked product -> starting material."""
    steps: list[dict] = []
    reagents: list[dict] = []
    prev_products: list[dict] = []
    for b in bundles:
        first_step = b["steps"][0]["id"] if b["steps"] else None
        for r in b["reagents"]:
            r = dict(r)
            if r.get("step_id") == first_step and r.get("role") == "reactant" and prev_products:
                src = r.get("source_reagent_id")
                if not any(p["id"] == src for p in prev_products):
                    match = next((p for p in prev_products if _ident(p) and _ident(p) == _ident(r)), None)
                    if match:
                        r["source_reagent_id"] = match["id"]
            reagents.append(r)
        steps.extend(b["steps"])
        if b["steps"]:
            last = b["steps"][-1]["id"]
            prods = [r for r in reagents if r.get("step_id") == last and r.get("role") == "product"]
            prev_products = prods or prev_products
    return {"experiment": {}, "steps": steps, "reagents": reagents, "entries": [], "refs": []}


def compute(bundles: list[dict]) -> tuple[dict, dict]:
    combined = combine(bundles)
    calc = stoich.compute_experiment(combined["steps"], combined["reagents"], db.stoich_rows)
    return combined, calc


def summary(bundles: list[dict], calc: dict) -> list[dict]:
    """One row per step: experiment, step number in the route, product and yield."""
    out, n = [], 0
    for b in bundles:
        for i, s in enumerate(b["steps"]):
            n += 1
            prods = [r for r in b["reagents"] if r.get("step_id") == s["id"] and r.get("role") == "product"]
            c = calc["rows"].get(prods[0]["id"], {}) if prods else {}
            out.append({"n": n, "experiment": b["experiment"], "step_in_exp": i + 1, "n_steps_exp": len(b["steps"]),
                        "step": s, "product": prods[0] if prods else None,
                        "yield": c.get("percent_yield"), "isolated_mass_g": c.get("isolated_mass_g")})
    return out


def overall_yield(rows: list[dict]) -> Optional[float]:
    if len(rows) < 2 or any(r["yield"] is None for r in rows):
        return None
    y = 1.0
    for r in rows:
        y *= r["yield"] / 100
    return y * 100
