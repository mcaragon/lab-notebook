"""Stockroom: the chemicals an account has on hand, one entry per container (bottle, bag, ampoule).

A container keeps the compound data (filled from PubChem Local when it is added, editable like a reagent row), where
it came from (supplier, catalogue number, grade, purity, lot), how much was bought (g or mL) and for what price, and
where it is kept. Corrections (spills, a stocktake recount) are recorded with a reason.

What is left is derived, never stored: quantity + corrections − used, where *used* comes from the measured amounts of
reagent rows drawn from the container and *reserved* from planned amounts of experiments that are not completed (see
``docs/stockroom-plan.md``). Each account has its own stockroom.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from . import auth

STATUSES = ("in_use", "empty", "disposed")
UNITS = ("g", "mL")
CURRENCIES = ("USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "CNY", "INR", "SEK", "NOK", "DKK", "PLN", "CZK",
              "NZD", "BRL", "MXN", "ZAR", "KRW", "SGD")
CHEM = ["cid", "pubchem_url", "name", "iupac_name", "cas", "formula", "smiles", "label", "mw", "density", "bp", "mp",
        "flash_point", "refractive_index", "signal_word", "pictograms", "hazard_statements", "sources",
        "extra_hazards", "hazard_notes"]
FIELDS = CHEM + ["form", "purity", "concentration_m", "wt_percent", "solution_density", "supplier", "catalog_no",
                 "grade", "lot", "quantity", "unit", "price", "location", "received_at", "opened_at", "expires_at",
                 "low_threshold", "status", "notes"]
EXPIRING_DAYS = 30


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def derive(item: dict, corrections: float = 0.0, used: float = 0.0, reserved: float = 0.0,
           today: Optional[date] = None) -> dict:
    """Amount left, price per unit, value left and flags of a container."""
    q = _num(item.get("quantity"))
    price = _num(item.get("price"))
    left = (q or 0.0) + corrections - used if q is not None else None
    unit_price = price / q if price is not None and q else None
    today = today or date.today()
    exp = None
    try:
        exp = date.fromisoformat((item.get("expires_at") or "")[:10]) if item.get("expires_at") else None
    except ValueError:
        pass
    threshold = _num(item.get("low_threshold"))
    active = item.get("status", "in_use") == "in_use"
    return {
        "corrections": corrections, "used": used, "reserved": reserved,
        "left": left, "available": left - reserved if left is not None else None,
        "fraction_left": max(0.0, min(1.0, left / q)) if left is not None and q else None,
        "unit_price": unit_price,
        "value_left": max(left, 0.0) * unit_price if left is not None and unit_price is not None else None,
        "low": bool(active and left is not None and ((threshold is not None and left <= threshold) or left <= 0)),
        "expired": bool(exp and exp < today),
        "expiring": bool(exp and today <= exp <= today + timedelta(days=EXPIRING_DAYS)),
    }


class Stockroom:
    def __init__(self, store: Any):
        self.store = store

    def conn(self):
        return self.store.conn()

    # containers ---------------------------------------------------------------------------------------
    def get(self, item_id: int) -> Optional[dict]:
        return self.store.get("stock_items", item_id)

    def items(self, owner: int) -> list[dict]:
        return self.store.list("stock_items", "owner_id = ?", (owner,),
                               order="LOWER(COALESCE(label, name)), status = 'in_use' DESC, id")

    def create(self, owner: int, data: dict) -> int:
        vals = {k: v for k, v in data.items() if k in FIELDS}
        vals.setdefault("name", "Unnamed")
        if vals.get("unit") not in UNITS:
            vals["unit"] = "g"
        if vals.get("status") not in STATUSES:
            vals["status"] = "in_use"
        now = auth.ts()
        return self.store.insert("stock_items", vals, owner_id=owner, created_at=now, updated_at=now)

    def update(self, item_id: int, data: dict) -> None:
        vals = {k: v for k, v in data.items() if k in FIELDS}
        if "unit" in vals and vals["unit"] not in UNITS:
            raise ValueError("The unit must be g or mL.")
        if "status" in vals and vals["status"] not in STATUSES:
            raise ValueError("Unknown status.")
        vals["updated_at"] = auth.ts()
        self.store.update("stock_items", item_id, vals)

    def delete(self, item_id: int) -> None:
        self.store.delete("stock_items", item_id)  # reagent rows keep their data; their link is cleared

    def duplicate(self, item_id: int) -> int:
        """The next container of the same thing: same compound and source, a fresh amount, no lot or dates."""
        it = self.get(item_id)
        data = {k: it.get(k) for k in FIELDS if k not in ("lot", "received_at", "opened_at", "expires_at", "status")}
        data["received_at"] = date.today().isoformat()
        return self.create(it["owner_id"], data)

    # corrections --------------------------------------------------------------------------------------
    def adjust(self, item_id: int, delta: float, reason: str, user_id: Optional[int]) -> int:
        with self.conn() as c:
            aid = c.execute("INSERT INTO stock_adjustments (item_id, ts, delta, reason, user_id) VALUES (?, ?, ?, ?, ?)",
                            (item_id, auth.ts(), delta, (reason or "").strip()[:200] or None, user_id)).lastrowid
            c.execute("UPDATE stock_items SET updated_at = ? WHERE id = ?", (auth.ts(), item_id))
        return aid

    def adjustments(self, item_id: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT a.id, a.ts, a.delta, a.reason, u.username FROM stock_adjustments a "
                "LEFT JOIN users u ON u.id = a.user_id WHERE a.item_id = ? ORDER BY a.ts, a.id", (item_id,))]

    def delete_adjustment(self, item_id: int, adj_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM stock_adjustments WHERE id = ? AND item_id = ?", (adj_id, item_id))

    def correction_totals(self, owner: int) -> dict[int, float]:
        with self.conn() as c:
            return {r[0]: r[1] for r in c.execute(
                "SELECT a.item_id, SUM(a.delta) FROM stock_adjustments a JOIN stock_items i ON i.id = a.item_id "
                "WHERE i.owner_id = ? GROUP BY a.item_id", (owner,))}

    def set_to(self, item_id: int, left_now: float, actual: float, reason: str, user_id: Optional[int]) -> Optional[int]:
        """Stocktake: record the correction that makes 'left' equal to what was found."""
        delta = actual - left_now
        if abs(delta) < 1e-9:
            return None
        return self.adjust(item_id, delta, reason or "Stocktake", user_id)


# ---------------------------------------------------------------------------------------------- use in experiments
# Fields a reagent row takes from the container it is drawn from
SOURCE_FIELDS = ["supplier", "grade", "lot", "purity", "form", "concentration_m", "wt_percent", "solution_density"]


def _in_unit(unit: str, grams: Optional[float], ml: Optional[float], density: Optional[float]) -> Optional[float]:
    """An amount in the container's unit (g or mL), converting with the density when needed."""
    if unit == "g":
        if grams is not None:
            return grams
        return ml * density if ml is not None and density else None
    if ml is not None:
        return ml
    return grams / density if grams is not None and density else None


def amount_for(item: dict, reagent: dict, calc: dict, log_use: dict, completed: bool) -> Optional[dict]:
    """How much of ``item`` a linked reagent row takes, in the item's unit.

    - measured (the row's actual amount, or for solvents and workup materials the volumes logged in extractions,
      washes and quenches): ``{"kind": "used", "amount"}``
    - otherwise its planned amount: ``{"kind": "reserved", "amount"}``, but only while the experiment is not
      completed (completing it releases the reservation)
    Returns None when there is nothing to count; ``amount`` is None when it cannot be converted (no density)."""
    unit = item.get("unit") or "g"
    density = _num(item.get("density")) if (item.get("form") or "neat") == "neat" else _num(item.get("solution_density"))
    density = density or _num(reagent.get("density"))
    if reagent.get("actual_value") is not None:
        return {"kind": "used", "amount": _in_unit(unit, calc.get("act_mass_g"), calc.get("act_volume_ml"), density)}
    if log_use:
        grams = log_use.get("g")
        ml = log_use.get("mL")
        return {"kind": "used", "amount": _in_unit(unit, grams, ml, density)}
    if completed:
        return None
    if calc.get("mass_g") is None and calc.get("volume_ml") is None:
        return None
    return {"kind": "reserved", "amount": _in_unit(unit, calc.get("mass_g"), calc.get("volume_ml"), density)}
