"""What an experiment cost, and what its product costs per gram.

- An input drawn from a stockroom container costs its amount × the container's price per g or mL. The amount is the
  measured one (the row's actual amount, or for solvents and workup materials the volumes logged in extractions,
  washes and quenches); without a measurement the planned amount is used and the cost is marked *estimated*.
- An input taken from another experiment's product inherits that product's cost per gram (so costs add up along a
  project's route); the part of a product nobody took keeps its value.
- Inputs that are neither (not linked to a container) have no price: the total is then *incomplete* and lists them.
  Nothing is silently treated as free.
- Product cost per gram = experiment cost ÷ isolated mass (crude mass if nothing was isolated yet, marked).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from . import stockroom

INPUT_ROLES = ("reactant", "reagent", "catalyst", "solvent", "workup")


def _measured(item: dict, reagent: dict, calc: dict, log_use: dict) -> tuple[Optional[float], bool]:
    """(amount in the container's unit, measured?) for a row drawn from ``item``."""
    unit = item.get("unit") or "g"
    density = stockroom._num(item.get("density")) if (item.get("form") or "neat") == "neat" \
        else stockroom._num(item.get("solution_density"))
    density = density or stockroom._num(reagent.get("density"))
    if reagent.get("actual_value") is not None:
        return stockroom._in_unit(unit, calc.get("act_mass_g"), calc.get("act_volume_ml"), density), True
    if log_use and (log_use.get("g") or log_use.get("mL")):
        return stockroom._in_unit(unit, log_use.get("g"), log_use.get("mL"), density), True
    return stockroom._in_unit(unit, calc.get("mass_g"), calc.get("volume_ml"), density), False


def _grams(calc: dict) -> tuple[Optional[float], bool]:
    if calc.get("act_mass_g") is not None:
        return calc["act_mass_g"], True
    return calc.get("mass_g"), False


class Costs:
    """Costs of an account's experiments. ``bundle_of(id)`` gives an experiment with ``calc`` and ``log_use``;
    ``experiment_of(reagent_id)`` the experiment a product belongs to (None if it isn't the account's)."""

    def __init__(self, items: dict[int, dict], bundle_of: Callable[[int], Optional[dict]],
                 experiment_of: Callable[[int], Optional[int]]):
        self.items = items
        self.bundle_of = bundle_of
        self.experiment_of = experiment_of
        self.memo: dict[int, dict] = {}
        self.busy: set[int] = set()

    def product_cost_per_g(self, product_id: int, exp_id: int) -> tuple[Optional[float], bool, bool]:
        """(cost per g, estimated, complete) of a product, from the experiment that made it."""
        c = self.experiment(exp_id)
        if not c or c["product"] is None or c["product"]["id"] != product_id:
            return None, False, False
        return c["product"]["cost_per_g"], c["estimated"], c["complete"]

    def experiment(self, exp_id: int) -> Optional[dict]:
        if exp_id in self.memo:
            return self.memo[exp_id]
        if exp_id in self.busy:  # a cycle of links: stop here
            return None
        self.busy.add(exp_id)
        try:
            b = self.bundle_of(exp_id)
            out = self._compute(b) if b else None
        finally:
            self.busy.discard(exp_id)
        self.memo[exp_id] = out
        return out

    def _compute(self, b: dict) -> dict:
        calc, log_use = b["calc"]["rows"], b["log_use"]
        own = {r["id"] for r in b["reagents"]}
        inputs, unpriced = [], []
        for r in b["reagents"]:
            if r.get("role") not in INPUT_ROLES:
                continue
            c = calc.get(r["id"], {})
            line = {"reagent_id": r["id"], "name": r.get("label") or r.get("name"), "role": r.get("role"),
                    "amount": None, "unit": None, "unit_price": None, "cost": None, "estimated": False, "source": None}
            it = self.items.get(r.get("stock_item_id"))
            src = r.get("source_reagent_id")
            if it is not None:
                q, price = stockroom._num(it.get("quantity")), stockroom._num(it.get("price"))
                amount, measured = _measured(it, r, c, log_use.get(r["id"], {}))
                line.update(amount=amount, unit=it.get("unit") or "g", estimated=not measured,
                            source={"kind": "stock", "id": it["id"], "supplier": it.get("supplier"), "lot": it.get("lot")})
                if price is not None and q:
                    line["unit_price"] = price / q
                    line["cost"] = amount * line["unit_price"] if amount is not None else None
            elif src and src not in own:
                parent = self.experiment_of(src)
                grams, measured = _grams(c)
                line.update(amount=grams, unit="g", estimated=not measured,
                            source={"kind": "product", "experiment_id": parent, "product_id": src})
                if parent is not None:
                    per_g, est, complete = self.product_cost_per_g(src, parent)
                    if per_g is not None:
                        line["unit_price"] = per_g
                        line["cost"] = grams * per_g if grams is not None else None
                        line["estimated"] = line["estimated"] or est
                        line["inherited_incomplete"] = not complete
            if line["cost"] is None:
                if line["amount"] is None and line["unit_price"] is not None:
                    line["why"] = "no amount"
                elif it is not None and line["unit_price"] is None:
                    line["why"] = "container has no price"
                elif src and src not in own:
                    line["why"] = "the product it came from has no cost yet"
                else:
                    line["why"] = "not from the stockroom"
                unpriced.append(line["name"])
            inputs.append(line)
        total = sum(x["cost"] for x in inputs if x["cost"] is not None)
        for x in inputs:
            x["share"] = x["cost"] / total if x["cost"] is not None and total else None
        prods = [r for r in b["reagents"] if r.get("role") == "product"]
        product = None
        if prods:
            p = prods[0]
            pc = calc.get(p["id"], {})
            mass = pc.get("isolated_mass_g")
            crude = mass is None and pc.get("crude_mass_g") is not None
            mass = mass if mass is not None else pc.get("crude_mass_g")
            mmol = pc.get("isolated_mmol")
            product = {"id": p["id"], "name": p.get("label") or p.get("name"), "mass_g": mass, "crude": crude,
                       "cost_per_g": total / mass if mass and total else None,
                       "cost_per_mmol": total / mmol if mmol and total and not crude else None}
        priced = [x for x in inputs if x["cost"] is not None]
        return {"inputs": inputs, "total": total if priced else None, "unpriced": unpriced,
                "complete": not unpriced and not any(x.get("inherited_incomplete") for x in inputs),
                "estimated": any(x["estimated"] for x in priced), "product": product}


SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹", "KRW": "₩", "CAD": "CA$",
           "AUD": "A$", "NZD": "NZ$", "SGD": "S$", "BRL": "R$", "MXN": "MX$", "CHF": "CHF ", "ZAR": "R "}


def money(v: Optional[float], currency: str = "USD") -> str:
    """'$13.50', '€0.0248' (small unit prices keep more digits), '1 250 SEK'."""
    if v is None:
        return ""
    digits = 4 if v and abs(v) < 1 else 2
    if currency in ("JPY", "KRW") and abs(v) >= 1:
        digits = 0
    num = f"{v:,.{digits}f}"
    sym = SYMBOLS.get(currency)
    return f"{sym}{num}" if sym else f"{num} {currency}"
