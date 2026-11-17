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

Equivalents are relative to the reference row (``is_reference``) or, if none is marked, to the first reactant with
a known amount. The limiting reagent is the reactant with the smallest mmol / coefficient. Reagents, catalysts and
solvents never limit the yield.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ROLES = ("reactant", "reagent", "catalyst", "solvent", "product", "other")
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
    mass_g: Optional[float] = None
    volume_ml: Optional[float] = None
    mmol: Optional[float] = None
    equiv: Optional[float] = None
    is_limiting: bool = False
    theoretical_mmol: Optional[float] = None
    theoretical_mass_g: Optional[float] = None
    percent_yield: Optional[float] = None
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


def compute(rows: list[dict]) -> dict:
    """Compute the reagent table.

    ``rows`` are dicts with keys: id, role, form, mw, density, mp, purity, concentration_m, wt_percent,
    solution_density, coefficient, basis, basis_value, is_reference, actual_mass_g.

    Returns ``{"rows": {id: RowResult dict}, "reference_id", "limiting_id", "reference_mmol"}``.
    """
    results: dict[Any, RowResult] = {}
    helpers: dict[Any, _Row] = {}

    # Pass 1: rows whose basis is an absolute quantity
    for r in rows:
        rid = r.get("id")
        h = helpers[rid] = _Row(r)
        res = results[rid] = RowResult(id=rid)
        basis = r.get("basis")
        val = _pos(r.get("basis_value"))
        if basis not in BASES or val is None:
            continue
        if basis == "mass":
            res.mass_g = val
            res.mmol = h.mass_to_mmol(val)
            res.volume_ml = h.mass_to_volume(val)
        elif basis == "volume":
            res.volume_ml = val
            res.mmol = h.volume_to_mmol(val)
            res.mass_g = h.volume_to_mass(val)
        elif basis == "mmol":
            res.mmol = val

    # Reference: the marked row, else the first reactant with an amount
    ref_id = next((r.get("id") for r in rows if r.get("is_reference")), None)
    if ref_id is None:
        ref_id = next((r.get("id") for r in rows
                       if r.get("role") == "reactant" and results[r.get("id")].mmol), None)
    ref_mmol = results[ref_id].mmol if ref_id is not None else None
    if ref_id is not None and not ref_mmol:
        ref_row = next(r for r in rows if r.get("id") == ref_id)
        if ref_row.get("basis") == "equiv":
            results[ref_id].warnings.append("The reference row needs a mass, volume or mmol, not equivalents.")

    # Pass 2: equivalents-based rows, then fill derived quantities
    for r in rows:
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
            if ref_mmol:
                res.equiv = res.mmol / ref_mmol
        elif r.get("basis") in ("mass", "volume") and _pos(r.get("basis_value")) and r.get("role") != "solvent":
            res.warnings.append(_missing_hint(h, "mmol"))

    # Limiting reactant
    lim_id, lim_ratio = None, None
    for r in rows:
        if r.get("role") != "reactant":
            continue
        mmol = results[r.get("id")].mmol
        coef = _pos(r.get("coefficient")) or 1.0
        if mmol:
            ratio = mmol / coef
            if lim_ratio is None or ratio < lim_ratio:
                lim_id, lim_ratio = r.get("id"), ratio
    if lim_id is not None:
        results[lim_id].is_limiting = True

    # Products: theoretical and percent yield
    for r in rows:
        if r.get("role") != "product":
            continue
        res, h = results[r.get("id")], helpers[r.get("id")]
        # A product's own basis is not a planned amount; the table shows the isolated amount instead
        res.mass_g = res.volume_ml = res.mmol = res.equiv = None
        res.warnings.clear()
        coef = _pos(r.get("coefficient")) or 1.0
        if lim_ratio is not None:
            res.theoretical_mmol = lim_ratio * coef
            if h.mw:
                res.theoretical_mass_g = res.theoretical_mmol * h.mw / 1000
            else:
                res.warnings.append("Enter the molar mass of the product to calculate the theoretical yield.")
        actual = _pos(r.get("actual_mass_g"))
        if actual is not None:
            res.mass_g = actual
            if h.mw:
                res.mmol = actual * h.purity / h.mw * 1000
                if ref_mmol:
                    res.equiv = res.mmol / ref_mmol
            if res.theoretical_mass_g:
                res.percent_yield = actual * h.purity / res.theoretical_mass_g * 100

    return {
        "rows": {k: v.as_dict() for k, v in results.items()},
        "reference_id": ref_id,
        "reference_mmol": ref_mmol,
        "limiting_id": lim_id,
    }
