"""Stoichiometry for the reagent table.

Every row has one *basis*: the quantity the user typed (mass, volume, mmol or equivalents). All other quantities are
derived from it. Units: mass in g, volume in mL, amount in mmol, molar mass in g/mol, density in g/mL (= g/cm³),
concentration in mol/L (= mmol/mL), purity and wt% in percent.

Forms:
  * ``neat``: the pure substance (optionally with a purity < 100 %). Mass and volume are of the material as weighed
    or measured; ``density`` is the density of the substance.
  * ``solution``: a solution of known molarity (e.g. 2.0 M n-BuLi in hexanes). Volume is of the solution; mass needs
    ``solution_density``.
  * ``wt``: a solution of known weight percent (e.g. 37 % HCl). Mass is of the solution; volume needs
    ``solution_density``.

A neat compound that is solid at room temperature (melting point above 25 °C) gets no calculated volume; a volume
typed for it is still used.

Each row has a *planned* amount (the basis above) and, once weighed or measured, an *actual* amount
(``actual_basis`` "mass" or "volume" with ``actual_value``). Wherever an actual amount exists it is the one used:
the limiting reagent, the theoretical yield and the percent yield are based on what really went into the flask.

Equivalents are relative to the reference row (``is_reference``) or, if none is marked, to the first reactant with
a known amount. The limiting reagent is the reactant with the smallest mmol / coefficient. Reagents, catalysts and
solvents never limit the yield.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ROLES = ("reactant", "reagent", "catalyst", "solvent", "workup", "product")
# Roles that take part in the reaction (stoichiometry); solvents and workup materials only have amounts
REACTION_ROLES = ("reactant", "reagent", "catalyst")
FORMS = ("neat", "solution", "wt")
BASES = ("mass", "volume", "mmol", "equiv")
SOLID_ABOVE_C = 25.0


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _pos(v: Any) -> Optional[float]:
    f = _num(v)
    return f if f is not None and f > 0 else None


@dataclass
class RowResult:
    id: Any
    # planned
    mass_g: Optional[float] = None
    volume_ml: Optional[float] = None
    mmol: Optional[float] = None
    equiv: Optional[float] = None
    # actual (weighed / measured)
    act_mass_g: Optional[float] = None
    act_volume_ml: Optional[float] = None
    act_mmol: Optional[float] = None
    act_equiv: Optional[float] = None
    deviation_pct: Optional[float] = None
    used_mmol: Optional[float] = None  # actual if known, else planned
    is_limiting: bool = False
    # products
    theoretical_mmol: Optional[float] = None
    theoretical_mass_g: Optional[float] = None
    isolated_mass_g: Optional[float] = None
    isolated_mmol: Optional[float] = None
    percent_yield: Optional[float] = None
    crude_mass_g: Optional[float] = None
    crude_percent: Optional[float] = None
    expected_yield_pct: Optional[float] = None
    expected_mass_g: Optional[float] = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class _Row:
    """Conversion helpers for one reagent row."""

    def __init__(self, r: dict):
        self.r = r
        self.form = r.get("form") or "neat"
        self.mw = _pos(r.get("mw"))
        self.density = _pos(r.get("density"))
        purity = _pos(r.get("purity"))
        self.purity = min(purity, 100.0) / 100.0 if purity else 1.0
        self.molarity = _pos(r.get("concentration_m"))
        wt = _pos(r.get("wt_percent"))
        self.wt = min(wt, 100.0) / 100.0 if wt else None
        self.sol_density = _pos(r.get("solution_density"))
        mp = _num(r.get("mp"))
        self.solid = self.form == "neat" and mp is not None and mp > SOLID_ABOVE_C

    # Mass of material (neat substance or solution) <-> volume
    def mass_to_volume(self, mass: float) -> Optional[float]:
        if self.solid:
            return None
        d = self.density if self.form == "neat" else self.sol_density
        return mass / d if d else None

    def volume_to_mass(self, vol: float) -> Optional[float]:
        d = self.density if self.form == "neat" else self.sol_density
        return vol * d if d else None

    # Material -> mmol of the compound
    def mass_to_mmol(self, mass: float) -> Optional[float]:
        if self.form == "solution":
            vol = self.mass_to_volume(mass)
            return self.volume_to_mmol(vol) if vol is not None else None
        if not self.mw:
            return None
        frac = self.purity if self.form == "neat" else self.wt
        return mass * frac / self.mw * 1000 if frac else None

    def volume_to_mmol(self, vol: float) -> Optional[float]:
        if self.form == "solution":
            return vol * self.molarity if self.molarity else None
        mass = self.volume_to_mass(vol)
        return self.mass_to_mmol(mass) if mass is not None else None

    # mmol of the compound -> material
    def mmol_to_mass(self, mmol: float) -> Optional[float]:
        if self.form == "solution":
            vol = self.mmol_to_volume(mmol)
            return self.volume_to_mass(vol) if vol is not None else None
        if not self.mw:
            return None
        frac = self.purity if self.form == "neat" else self.wt
        return mmol * self.mw / 1000 / frac if frac else None

    def mmol_to_volume(self, mmol: float) -> Optional[float]:
        if self.form == "solution":
            return mmol / self.molarity if self.molarity else None
        mass = self.mmol_to_mass(mmol)
        return self.mass_to_volume(mass) if mass is not None else None


def _missing_hint(row: _Row, need: str) -> str:
    if row.form == "solution":
        if need == "mass":
            return "Enter the solution density to convert between mass and volume."
        return "Enter the molarity of the solution."
    if row.form == "wt":
        if need == "volume":
            return "Enter the solution density to convert between mass and volume."
        if not row.wt:
            return "Enter the weight percent of the solution."
        return "Enter the molar mass."
    if need == "volume":
        return "Enter a density to calculate the volume."
    return "Enter the molar mass."


def _amounts(h: "_Row", basis: Optional[str], val: Optional[float]) -> tuple:
    """(mass, volume, mmol) from an absolute basis."""
    if basis == "mass" and val is not None:
        return val, h.mass_to_volume(val), h.mass_to_mmol(val)
    if basis == "volume" and val is not None:
        return h.volume_to_mass(val), val, h.volume_to_mmol(val)
    if basis == "mmol" and val is not None:
        return None, None, val
    return None, None, None


def compute(rows: list[dict]) -> dict:
    """Compute the reagent table of one reaction step.

    ``rows`` are dicts with keys: id, role, form, mw, density, mp, purity, concentration_m, wt_percent,
    solution_density, coefficient, basis, basis_value, is_reference, actual_basis, actual_value, and for products
    actual_mass_g (isolated, purified), crude_mass_g and expected_yield_pct.

    Returns ``{"rows": {id: RowResult dict}, "reference_id", "limiting_id", "reference_mmol"}``.
    """
    results: dict[Any, RowResult] = {}
    helpers: dict[Any, _Row] = {}
    products = [r for r in rows if r.get("role") == "product"]
    inputs = [r for r in rows if r.get("role") != "product"]

    for r in inputs:
        rid = r.get("id")
        h = helpers[rid] = _Row(r)
        res = results[rid] = RowResult(id=rid)
        res.mass_g, res.volume_ml, res.mmol = _amounts(h, r.get("basis"), _pos(r.get("basis_value")))
        if r.get("basis") == "mass":
            res.mass_g = _pos(r.get("basis_value"))
        abasis = r.get("actual_basis") if r.get("actual_basis") in ("mass", "volume") else None
        res.act_mass_g, res.act_volume_ml, res.act_mmol = _amounts(h, abasis, _pos(r.get("actual_value")))

    # Reference: the marked row, else the first reactant with an amount
    ref_id = next((r.get("id") for r in inputs if r.get("is_reference")), None)
    if ref_id is None:
        ref_id = next((r.get("id") for r in inputs if r.get("role") == "reactant"
                       and (results[r.get("id")].mmol or results[r.get("id")].act_mmol)), None)
    ref_mmol = results[ref_id].mmol if ref_id is not None else None
    if ref_id is not None and not ref_mmol:
        ref_row = next(r for r in inputs if r.get("id") == ref_id)
        if ref_row.get("basis") == "equiv":
            results[ref_id].warnings.append("The reference row needs a mass, volume or mmol, not equivalents.")

    for r in inputs:
        rid = r.get("id")
        res, h = results[rid], helpers[rid]
        if r.get("basis") == "equiv" and rid != ref_id:
            val = _pos(r.get("basis_value"))
            if val is not None:
                if ref_mmol:
                    res.mmol = val * ref_mmol
                else:
                    res.warnings.append("Equivalents need a reference reagent with a known amount.")
        if res.mmol is not None:
            if res.mass_g is None:
                res.mass_g = h.mmol_to_mass(res.mmol)
            if res.volume_ml is None:
                res.volume_ml = h.mmol_to_volume(res.mmol)
        elif (r.get("basis") in ("mass", "volume") and _pos(r.get("basis_value"))
              and r.get("role") in REACTION_ROLES):
            res.warnings.append(_missing_hint(h, "mmol"))
        if res.act_mmol is None and r.get("actual_basis") and _pos(r.get("actual_value")) \
                and r.get("role") in REACTION_ROLES and not res.warnings:
            res.warnings.append(_missing_hint(h, "mmol"))
        res.used_mmol = res.act_mmol if res.act_mmol is not None else res.mmol
        if res.mmol and res.act_mmol:
            res.deviation_pct = (res.act_mmol - res.mmol) / res.mmol * 100
        elif res.mass_g and res.act_mass_g:
            res.deviation_pct = (res.act_mass_g - res.mass_g) / res.mass_g * 100
        elif res.volume_ml and res.act_volume_ml:
            res.deviation_pct = (res.act_volume_ml - res.volume_ml) / res.volume_ml * 100

    ref_used = results[ref_id].used_mmol if ref_id is not None else None
    for r in inputs:
        res = results[r.get("id")]
        if ref_mmol and res.mmol is not None:
            res.equiv = res.mmol / ref_mmol
        if ref_used and res.act_mmol is not None:
            res.act_equiv = res.act_mmol / ref_used

    # Limiting reactant: from actual amounts where known
    lim_id, lim_ratio = None, None
    for r in inputs:
        if r.get("role") != "reactant":
            continue
        mmol = results[r.get("id")].used_mmol
        coef = _pos(r.get("coefficient")) or 1.0
        if mmol:
            ratio = mmol / coef
            if lim_ratio is None or ratio < lim_ratio:
                lim_id, lim_ratio = r.get("id"), ratio
    if lim_id is not None:
        results[lim_id].is_limiting = True

    # Products: theoretical, expected, crude and isolated yield
    for r in products:
        rid = r.get("id")
        h = helpers[rid] = _Row(r)
        res = results[rid] = RowResult(id=rid)
        coef = _pos(r.get("coefficient")) or 1.0
        if lim_ratio is not None:
            res.theoretical_mmol = lim_ratio * coef
            if h.mw:
                res.theoretical_mass_g = res.theoretical_mmol * h.mw / 1000
            else:
                res.warnings.append("Enter the molar mass of the product to calculate the theoretical yield.")
        res.expected_yield_pct = _pos(r.get("expected_yield_pct"))
        if res.expected_yield_pct and res.theoretical_mass_g:
            res.expected_mass_g = res.theoretical_mass_g * res.expected_yield_pct / 100
        crude = _pos(r.get("crude_mass_g"))
        if crude is not None:
            res.crude_mass_g = crude
            if res.theoretical_mass_g:
                res.crude_percent = crude / res.theoretical_mass_g * 100
        actual = _pos(r.get("actual_mass_g"))
        if actual is not None:
            res.isolated_mass_g = actual
            if h.mw:
                res.isolated_mmol = actual * h.purity / h.mw * 1000
            if res.theoretical_mass_g:
                res.percent_yield = actual * h.purity / res.theoretical_mass_g * 100

    return {
        "rows": {k: v.as_dict() for k, v in results.items()},
        "reference_id": ref_id,
        "reference_mmol": ref_mmol,
        "limiting_id": lim_id,
    }


def compute_experiment(steps: list[dict], reagents: list[dict], stoich_rows) -> dict:
    """The reagent table of one experiment: one reaction, whatever its number of one-pot stages.

    All stages share one reference (equivalents are relative to it) and one limiting reactant; a reactant added in a
    later stage limits the yield like any other. ``steps`` is kept for the call signature (stages need no separate
    calculation).

    Returns ``{"rows", "reference_id", "reference_mmol", "limiting_id", "yield"}``; ``yield`` is that of the first
    product with a yield.
    """
    rows = stoich_rows(reagents)
    res = compute(rows)
    yields = [res["rows"][r["id"]]["percent_yield"] for r in rows
              if r.get("role") == "product" and res["rows"][r["id"]]["percent_yield"] is not None]
    return {**res, "yield": yields[0] if yields else None}
