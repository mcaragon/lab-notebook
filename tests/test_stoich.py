import pytest

from labnotebook.stoich import compute


def row(id, **kw):
    base = dict(id=id, role="reactant", form="neat", coefficient=1)
    base.update(kw)
    return base


def test_mass_volume_mmol_neat():
    # 1.061 g benzaldehyde (106.12 g/mol, 1.046 g/mL) = 10.0 mmol, 1.014 mL
    res = compute([row(1, mw=106.12, density=1.046, basis="mass", basis_value=1.0612)])
    r = res["rows"][1]
    assert r["mmol"] == pytest.approx(10.0)
    assert r["volume_ml"] == pytest.approx(1.0612 / 1.046)
    assert r["equiv"] == pytest.approx(1.0)
    assert r["is_limiting"]


def test_volume_basis_and_purity():
    # 2 mL of 98 % pure liquid
    res = compute([row(1, mw=100.0, density=0.8, purity=98, basis="volume", basis_value=2)])
    r = res["rows"][1]
    assert r["mass_g"] == pytest.approx(1.6)
    assert r["mmol"] == pytest.approx(1.6 * 0.98 / 100 * 1000)


def test_mmol_basis_with_purity_back_calculates_mass():
    res = compute([row(1, mw=100.0, purity=50, basis="mmol", basis_value=10)])
    assert res["rows"][1]["mass_g"] == pytest.approx(2.0)
    assert res["rows"][1]["volume_ml"] is None


def test_equivalents_relative_to_reference():
    rows = [
        row(1, mw=106.12, basis="mmol", basis_value=10),
        row(2, role="reagent", mw=37.83, basis="equiv", basis_value=0.5),
    ]
    res = compute(rows)
    assert res["reference_id"] == 1
    assert res["rows"][2]["mmol"] == pytest.approx(5.0)
    assert res["rows"][2]["mass_g"] == pytest.approx(5.0 * 37.83 / 1000)


def test_marked_reference_overrides_first_reactant():
    rows = [row(1, mw=100, basis="mmol", basis_value=10), row(2, mw=50, basis="mmol", basis_value=5, is_reference=True)]
    res = compute(rows)
    assert res["reference_id"] == 2
    assert res["rows"][1]["equiv"] == pytest.approx(2.0)


def test_molar_solution():
    # 2.5 M n-BuLi: 4 mL = 10 mmol; mass needs the solution density
    rows = [row(1, mw=100, basis="mmol", basis_value=10),
            row(2, role="reagent", form="solution", mw=64.06, concentration_m=2.5, basis="equiv", basis_value=1.0)]
    r = compute(rows)["rows"][2]
    assert r["volume_ml"] == pytest.approx(4.0)
    assert r["mass_g"] is None
    rows[1]["solution_density"] = 0.68
    r = compute(rows)["rows"][2]
    assert r["mass_g"] == pytest.approx(4.0 * 0.68)


def test_molar_solution_volume_basis():
    r = compute([row(1, form="solution", concentration_m=2.0, basis="volume", basis_value=5)])["rows"][1]
    assert r["mmol"] == pytest.approx(10.0)


def test_wt_percent_solution():
    # 37 wt% HCl (36.46 g/mol), density 1.19: 10 mL = 11.9 g solution = 4.403 g HCl = 120.8 mmol
    r = compute([row(1, role="reagent", form="wt", mw=36.46, wt_percent=37, solution_density=1.19,
                     basis="volume", basis_value=10)])["rows"][1]
    assert r["mass_g"] == pytest.approx(11.9)
    assert r["mmol"] == pytest.approx(11.9 * 0.37 / 36.46 * 1000)


def test_limiting_reagent_uses_coefficients():
    rows = [row(1, mw=100, basis="mmol", basis_value=10, coefficient=1),
            row(2, mw=100, basis="mmol", basis_value=15, coefficient=2),  # 7.5 per coefficient: limiting
            row(3, role="reagent", mw=100, basis="mmol", basis_value=1)]  # reagents never limit
    res = compute(rows)
    assert res["limiting_id"] == 2
    assert res["rows"][2]["is_limiting"] and not res["rows"][1]["is_limiting"]


def test_theoretical_and_percent_yield():
    rows = [row(1, mw=106.12, basis="mmol", basis_value=10),
            row(2, role="product", mw=108.14, actual_mass_g=0.865)]
    p = compute(rows)["rows"][2]
    assert p["theoretical_mmol"] == pytest.approx(10.0)
    assert p["theoretical_mass_g"] == pytest.approx(1.0814)
    assert p["percent_yield"] == pytest.approx(0.865 / 1.0814 * 100)
    assert p["mmol"] == pytest.approx(0.865 / 108.14 * 1000)


def test_missing_data_gives_warnings_not_errors():
    rows = [row(1, basis="mass", basis_value=1.0),  # no MW
            row(2, role="reagent", basis="equiv", basis_value=2),
            row(3, role="product")]
    res = compute(rows)
    assert res["rows"][1]["mmol"] is None and res["rows"][1]["warnings"]
    assert res["rows"][2]["mmol"] is None and res["rows"][2]["warnings"]
    assert res["rows"][3]["theoretical_mmol"] is None


def test_garbage_values_are_ignored():
    res = compute([row(1, mw="abc", density=-1, basis="mass", basis_value="nan")])
    assert res["rows"][1]["mass_g"] is None


def test_solvent_volume_only():
    r = compute([row(1, role="solvent", mw=32.04, density=0.791, basis="volume", basis_value=20)])
    assert r["rows"][1]["mass_g"] == pytest.approx(15.82)
    assert r["limiting_id"] is None


def test_solids_get_no_calculated_volume():
    rows = [row(1, mw=100, basis="mmol", basis_value=10),
            row(2, role="reagent", mw=37.83, density=1.07, mp=400, basis="equiv", basis_value=0.5)]
    r = compute(rows)["rows"][2]
    assert r["mass_g"] == pytest.approx(0.18915) and r["volume_ml"] is None
    rows[1]["mp"] = -26  # liquid
    assert compute(rows)["rows"][2]["volume_ml"] == pytest.approx(0.18915 / 1.07)
