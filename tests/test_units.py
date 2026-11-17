"""Actions, hazards, scheme layout, mentions and the database migrations."""
import json
import sqlite3
from pathlib import Path

import pytest

from labnotebook import actions, db, hazards, scheme
from labnotebook.stoich import compute_experiment

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "pubchem.json").read_text())


@pytest.mark.parametrize("text,seconds", [("10 min", 600), ("1 h 30 min", 5400), ("90 s", 90), ("1.5 h", 5400),
                                          ("1:30", 90), ("1:00:00", 3600), ("5", 300), ("", None), ("soon", None)])
def test_parse_duration(text, seconds):
    assert actions.parse_duration(text) == seconds


def test_describe_actions():
    names = {1: "DCM", 2: "Brine", 3: "Product A"}.get
    d = actions.describe
    assert d("extract", {"chem": {"reagent_id": 1}, "n": 4, "volume": 25}, names) == "Extracted with DCM (4 × 25 mL)"
    assert d("wash", {"chem": {"reagent_id": 2}, "n": 2, "volume": 20}, names) == "Washed with Brine (2 × 20 mL)"
    assert d("quench", {"chem": {"name": "sat. NH4Cl"}, "amount": 10, "unit": "mL"}) == "Quenched with sat. NH4Cl (10 mL)"
    assert d("dry", {"chem": {"name": "MgSO4"}}) == "Dried over MgSO4"
    assert d("temperature", {"verb": "Cooled to", "temp": "-78"}) == "Cooled to −78 °C"
    assert d("temperature", {"verb": "Heated at reflux", "duration": "2 h"}) == "Heated at reflux for 2 h"
    assert d("stir", {"temp": "rt", "duration": "16 h"}) == "Stirred at rt for 16 h"
    assert d("tlc", {"eluent": "4:1 hexanes/EtOAc", "spots": "SM 0.55, P 0.25", "stain": "KMnO4"}) == \
        "TLC (4:1 hexanes/EtOAc): SM 0.55, P 0.25; visualized with KMnO4"
    assert d("purify", {"method": "flash column chromatography", "solvent": "10% EtOAc/hexanes"}) == \
        "Purified by flash column chromatography (10% EtOAc/hexanes)"
    assert d("isolate", {"product": 3, "stage": "crude", "mass": 1.2}, names) == "Product A (crude): 1.2 g"
    assert d("measure", {"quantity": "mp", "value": "102–104", "unit": "°C"}) == "mp: 102–104 °C"


def test_usage_totals():
    entries = [{"action": "extract", "data": {"chem": {"reagent_id": 1}, "n": 3, "volume": 20}},
               {"action": "wash", "data": {"chem": {"reagent_id": 1}, "volume": 10}},
               {"action": "quench", "data": {"chem": {"reagent_id": 2}, "amount": 500, "unit": "µL"}},
               {"action": "observation", "data": {"text": "x"}}]
    assert actions.usage(entries) == {1: {"mL": 70}, 2: {"mL": 0.5}}


def test_extra_hazards_extraction():
    meoh = hazards.extract(FIXTURES["safety:887"])
    assert meoh["dot"]["un"] == ["UN1230"] and meoh["dot"]["packing_groups"] == ["II"]
    assert "Class 3 Flammable and combustible liquid" in meoh["dot"]["classes"]
    assert not meoh["dot"]["forbidden"]
    fulm = hazards.extract(FIXTURES["safety:11022444"])
    assert fulm["dot"]["forbidden"] and fulm["alerts"] == ["Explosive"]
    assert hazards.summary_lines(fulm)[0] == "DOT: forbidden for transport"
    assert hazards.parse_nfpa("3-2-2-W") == {"health": 3, "fire": 2, "instability": 2, "special": "W"}
    assert hazards.extract(None) == {} and hazards.extract({"sections": []}) == {}


def _bundle(style="auto"):
    steps = [{"id": 1, "conditions": [{"temperature": "0", "duration": "15 min"}, {"temperature": "rt", "duration": "2 h"}],
              "atmosphere": "N₂"},
             {"id": 2, "conditions": [{"temperature": "rt", "duration": "16 h"}]}]
    r = lambda **k: {"form": "neat", "coefficient": 1, "scheme_pos": "auto", **k}  # noqa: E731
    reagents = [
        r(id=1, step_id=1, role="reactant", name="Benzaldehyde", cid=240, mw=106.12, basis="mmol", basis_value=10),
        r(id=2, step_id=1, role="reagent", name="Sodium borohydride", label="NaBH4", mw=37.83, basis="equiv", basis_value=0.5),
        r(id=3, step_id=1, role="solvent", name="Methanol", label="MeOH"),
        r(id=4, step_id=1, role="product", name="Benzyl alcohol", cid=244, mw=108.14, actual_mass_g=0.9),
        r(id=5, step_id=2, role="reactant", name="Benzyl alcohol", cid=244, mw=108.14, source_reagent_id=4,
          basis="mass", basis_value=0.9),
        r(id=6, step_id=2, role="reagent", name="Manganese dioxide", label="MnO2", mw=86.94, basis="equiv", basis_value=10),
        r(id=7, step_id=2, role="catalyst", name="Pd", label="Pd/C", mw=106.4, basis="equiv", basis_value=0.05),
        r(id=8, step_id=2, role="product", name="Benzaldehyde", cid=240, mw=106.12),
    ]
    return {"experiment": {"scheme_style": style}, "steps": steps, "reagents": reagents, "entries": [], "refs": []}


def _two_reactions(style="auto"):
    """The bundle as two experiments: reduction, then oxidation of its product."""
    b = _bundle(style)
    rx = [{"id": i, "stages": [s], "reagents": [r for r in b["reagents"] if r["step_id"] == s["id"]]}
          for i, s in enumerate(b["steps"], 1)]
    rows = compute_experiment(b["steps"][:1], rx[0]["reagents"], db.stoich_rows)["rows"]
    rows.update(compute_experiment(b["steps"][1:], rx[1]["reagents"], db.stoich_rows)["rows"])
    return rx, rows


def test_scheme_route_of_two_experiments():
    rx, rows = _two_reactions()
    sch = scheme.build(rx, rows)
    kinds = [s["type"] for s in sch["segments"]]
    assert kinds == ["mols", "arrow", "mols", "arrow", "mols"]
    a1, a2 = sch["segments"][1], sch["segments"][3]
    assert a1["above"] == ["NaBH4 (0.50 equiv)"]
    assert a1["below"] == ["MeOH", "N₂", "0 °C, 15 min; then rt, 2 h"]
    assert a2["above"] == ["MnO2 (10 equiv)", "Pd/C (5.0 mol%)"]
    # benzaldehyde keeps number 1 when it reappears; the carried alcohol keeps 2
    assert [m["number"] for m in sch["segments"][0]["mols"]] == [1]
    assert [m["number"] for m in sch["segments"][2]["mols"]] == [2]
    assert [m["number"] for m in sch["segments"][4]["mols"]] == [1]
    assert sch["segments"][2]["mols"][0]["yield"] == pytest.approx(0.9 / 1.0814 * 100)
    assert sch["lettered"]  # long text -> lettered automatically
    assert sch["legend"][0] == ("a", "NaBH4 (0.50 equiv), MeOH, N₂, 0 °C, 15 min; then rt, 2 h")
    assert not scheme.build(rx, rows, "inline")["lettered"]
    # a later experiment keeps the numbers of compounds seen before (idents)
    first = scheme.build(rx[:1], rows)
    second = scheme.build(rx[1:], rows, numbers=first["numbers"], idents=first["idents"])
    assert [m["number"] for s in second["segments"] if s["type"] == "mols" for m in s["mols"]] == [2, 1]


def test_scheme_one_pot_stages():
    """One experiment, two stages: one arrow with numbered lines; a reactant of stage 2 is written on the arrow."""
    stages = [{"id": 1, "conditions": [{"temperature": "reflux", "duration": "1 h"}]},
              {"id": 2, "conditions": [{"temperature": "0"}]}]
    r = lambda **k: {"form": "neat", "coefficient": 1, "scheme_pos": "auto", **k}  # noqa: E731
    reagents = [r(id=1, step_id=1, role="reactant", name="Bromobenzene", cid=7961, mw=157.0, basis="mmol", basis_value=10),
                r(id=2, step_id=1, role="reagent", name="Magnesium", label="Mg", mw=24.3, basis="equiv", basis_value=1.2),
                r(id=3, step_id=1, role="solvent", name="Tetrahydrofuran", label="THF"),
                r(id=4, step_id=2, role="reactant", name="Benzaldehyde", label="PhCHO", cid=240, mw=106.1,
                  basis="equiv", basis_value=0.9),
                r(id=5, step_id=2, role="product", name="Benzhydrol", cid=7037, mw=184.2)]
    b = {"experiment": {"scheme_style": "inline"}, "steps": stages, "reagents": reagents}
    sch = scheme.build_experiment(b, compute_experiment(stages, reagents, db.stoich_rows))
    assert [s["type"] for s in sch["segments"]] == ["mols", "arrow", "mols"]
    arrow = sch["segments"][1]
    assert arrow["stacked"]
    assert arrow["above"] == ["1. Mg (1.2 equiv), THF, reflux, 1 h"]
    assert arrow["below"] == ["2. PhCHO (0.90 equiv), 0 °C"]
    assert [m["reagent"]["name"] for m in sch["segments"][0]["mols"]] == ["Bromobenzene"]


def test_scheme_positions():
    b = _bundle("inline")
    b["steps"] = b["steps"][:1]
    b["reagents"] = [r for r in b["reagents"] if r["step_id"] == 1]
    b["reagents"][1]["scheme_pos"] = "below"
    b["reagents"][2]["scheme_pos"] = "hidden"
    calc = compute_experiment(b["steps"], b["reagents"], db.stoich_rows)
    a1 = scheme.build_experiment(b, calc)["segments"][1]
    assert a1["above"] == [] and a1["below"][0] == "NaBH4 (0.50 equiv)" and "MeOH" not in a1["below"]


def test_guess_phase():
    assert db.guess_phase("Quench with sat. NH4Cl and extract with DCM (3 × 20 mL)") == "workup"
    assert db.guess_phase("Purify by flash column chromatography") == "purification"
    assert db.guess_phase("Record the 1H NMR spectrum") == "analysis"
    assert db.guess_phase("Flame-dry a 100 mL flask under N2") == "setup"
    assert db.guess_phase("Add NaBH4 in portions over 10 min") == "reaction"


def test_mentions():
    b = _bundle()
    b["reagents"] = [r for r in b["reagents"] if r["step_id"] == 1]
    rows = compute_experiment(b["steps"], b["reagents"], db.stoich_rows)["rows"]
    rs = b["reagents"]
    assert scheme.render_mentions("Add @NaBH4, then stir.", rs, rows) == \
        "Add NaBH4 (0.189 g, 5.00 mmol, 0.500 equiv), then stir."
    assert scheme.render_mentions("Dissolve @{Benzaldehyde} in @MeOH", rs, rows) == \
        "Dissolve Benzaldehyde (1.06 g, 10.0 mmol) in MeOH"
    assert scheme.render_mentions("email me@home", rs, rows) == "email me@home"
    assert "&lt;b&gt;" in scheme.render_mentions("<b>@NaBH4", rs, rows, mode="html")


def test_split_procedure():
    assert db.split_procedure("1. Dissolve A\n   in B\n2. Add C\n\nStir") == ["Dissolve A in B", "Add C", "Stir"]


V1_SCHEMA = """
CREATE TABLE experiments (id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', date TEXT, author TEXT, course TEXT,
  status TEXT NOT NULL DEFAULT 'planned', objective TEXT, reaction_scheme TEXT, procedure TEXT, results TEXT,
  discussion TEXT, conclusion TEXT, "references" TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE reagents (id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0, cid INTEGER, pubchem_url TEXT, name TEXT, iupac_name TEXT, cas TEXT, formula TEXT,
  smiles TEXT, mw REAL, density REAL, bp REAL, mp REAL, flash_point REAL, refractive_index REAL, signal_word TEXT,
  pictograms TEXT, hazard_statements TEXT, sources TEXT, role TEXT NOT NULL DEFAULT 'reactant',
  form TEXT NOT NULL DEFAULT 'neat', purity REAL, concentration_m REAL, wt_percent REAL, solution_density REAL,
  coefficient REAL NOT NULL DEFAULT 1, basis TEXT, basis_value REAL, is_reference INTEGER NOT NULL DEFAULT 0,
  actual_mass_g REAL, notes TEXT);
CREATE INDEX reagents_exp ON reagents(experiment_id, position);
CREATE TABLE entries (id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  ts TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'note', text TEXT NOT NULL DEFAULT '', value TEXT, unit TEXT);
CREATE INDEX entries_exp ON entries(experiment_id, ts);
PRAGMA user_version = 1;
"""


def test_migration_from_v1(tmp_path):
    path = tmp_path / "notebook.sqlite"
    c = sqlite3.connect(path)
    c.executescript(V1_SCHEMA)
    c.execute("INSERT INTO experiments (id, title, reaction_scheme, procedure, \"references\", created_at, updated_at) "
              "VALUES (1, 'Old', 'A -> B', '1. Dissolve A\n2. Add B', 'Lab manual\nSmith 2020', 'x', 'x')")
    c.execute("INSERT INTO reagents (experiment_id, name, role, mw, actual_mass_g, notes) VALUES (1, 'A', 'reactant', 100, NULL, 'lot 5')")
    c.execute("INSERT INTO reagents (experiment_id, name, role) VALUES (1, 'Celite', 'other')")
    c.execute("INSERT INTO entries (experiment_id, ts, kind, text) VALUES (1, '2026-01-01T10:00:00+00:00', 'observation', 'Yellow')")
    c.commit()
    c.close()
    store = db.Store(path)
    b = store.bundle(1)
    assert len(b["steps"]) == 1 and b["steps"][0]["notes"] == "A -> B"
    assert all(r["step_id"] == b["steps"][0]["id"] for r in b["reagents"])
    assert [r["role"] for r in b["reagents"]] == ["reactant", "workup"]
    assert b["reagents"][0]["notes"] == "lot 5"
    assert [p["text"] for p in b["procedure"]] == ["Dissolve A", "Add B"]
    assert [r["text"] for r in b["refs"]] == ["Lab manual", "Smith 2020"]
    assert b["entries"][0]["action"] == "observation"
    with sqlite3.connect(path) as c2:
        assert c2.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    db.Store(path)  # opening again is a no-op


def test_migration_v2_splits_multistep_experiments(tmp_path):
    """A v2 multi-step experiment becomes one experiment per step, linked by the intermediate, in a project."""
    path = tmp_path / "notebook.sqlite"
    store = db.Store(path)
    eid = store.create_experiment({"title": "Two steps", "objective": "Make C"})
    s1 = store.list("steps", "experiment_id = ?", (eid,))[0]["id"]
    s2 = store.insert("steps", {"title": "Oxidation"}, experiment_id=eid)
    store.update_experiment(eid, {"started_at": "2026-01-01T10:00:00+00:00", "ended_at": "2026-01-01T15:00:00+00:00"})
    a = store.add_reagent(eid, {"name": "A", "role": "reactant", "step_id": s1, "mw": 100, "basis": "mmol", "basis_value": 10})
    b = store.add_reagent(eid, {"name": "B", "role": "product", "step_id": s1, "mw": 100, "actual_mass_g": 0.8})
    store.add_reagent(eid, {"name": "B", "role": "reactant", "step_id": s2, "mw": 100, "source_reagent_id": b,
                            "basis": "mass", "basis_value": 0.8})
    store.add_reagent(eid, {"name": "C", "role": "product", "step_id": s2, "mw": 100, "actual_mass_g": 0.4})
    store.insert("procedure", {"text": "Dissolve A.", "step_id": s1}, experiment_id=eid)
    store.insert("procedure", {"text": "Extract with DCM.", "step_id": s1}, experiment_id=eid)
    p3 = store.insert("procedure", {"text": "Oxidize B.", "step_id": s2}, experiment_id=eid)
    store.insert("entries", {"ts": "2026-01-01T10:05:00+00:00", "action": "note", "text": "step 1 note", "step_id": s1},
                 experiment_id=eid)
    store.insert("entries", {"ts": "2026-01-01T13:00:00+00:00", "action": "note", "text": "step 2 note",
                             "procedure_id": p3}, experiment_id=eid)
    store.insert("entries", {"ts": "2026-01-01T13:30:00+00:00", "action": "note", "text": "after it"},
                 experiment_id=eid)
    store.insert("refs", {"text": "Org. Synth."}, experiment_id=eid)
    # make it look like a v2 database: no phase columns, sequences instead of projects
    with sqlite3.connect(path) as c:
        c.executescript("""
            DROP TABLE project_items; DROP TABLE projects;
            ALTER TABLE procedure DROP COLUMN phase; ALTER TABLE experiments DROP COLUMN phases;
            CREATE TABLE sequences (id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', notes TEXT,
              scheme_style TEXT NOT NULL DEFAULT 'auto', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE sequence_items (id INTEGER PRIMARY KEY,
              sequence_id INTEGER NOT NULL REFERENCES sequences(id) ON DELETE CASCADE,
              experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
              position INTEGER NOT NULL DEFAULT 0, UNIQUE (sequence_id, experiment_id));
            PRAGMA user_version = 2;""")
    store = db.Store(path)
    exps = store.list_experiments()
    assert sorted(e["title"] for e in exps) == ["Two steps — step 1", "Two steps — step 2: Oxidation"]
    new = next(e["id"] for e in exps if e["id"] != eid)
    b1, b2 = store.bundle(eid), store.bundle(new)
    assert [r["name"] for r in b1["reagents"]] == ["A", "B"] and [r["name"] for r in b2["reagents"]] == ["B", "C"]
    assert b2["reagents"][0]["source_reagent_id"] == b  # linked to the first experiment's product
    assert [p["text"] for p in b1["procedure"]] == ["Dissolve A.", "Extract with DCM."]
    assert [p["phase"] for p in b1["procedure"]] == ["reaction", "workup"]
    assert [e["text"] for e in b1["entries"]] == ["step 1 note"]
    assert [e["text"] for e in b2["entries"]] == ["step 2 note", "after it"]
    assert b2["experiment"]["started_at"] == "2026-01-01T13:00:00+00:00" and b2["entries"][1]["elapsed_s"] == 1800
    assert [r["text"] for r in b2["refs"]] == ["Org. Synth."] and b2["experiment"]["objective"] == "Make C"
    projs = store.list_projects()
    assert len(projs) == 1 and [e["id"] for e in projs[0]["experiments"]] == [eid, new]
    db.Store(path)  # opening again is a no-op
    assert len(store.list_experiments()) == 2 and a


def test_pair_procedure_log():
    from labnotebook.report import pair_procedure_log
    procedure = [{"id": 1, "n": 1}, {"id": 2, "n": 2}]
    log = [{"id": 10, "procedure_id": None, "text": "weighed"},
           {"id": 11, "procedure_id": 1, "text": "dissolved"},
           {"id": 12, "procedure_id": None, "text": "timer done"},   # joins step 1 (the step in progress)
           {"id": 13, "procedure_id": 2, "text": "added"}]
    rows = pair_procedure_log(procedure, log)
    assert [r["p"]["id"] if r["p"] else None for r in rows] == [None, 1, 2]
    assert [[e["id"] for e in r["entries"]] for r in rows] == [[10], [11, 12], [13]]


def test_ghs_statements_drop_not_classified_lines():
    from labnotebook.report import ghs_statements, hazard_info
    st = ["H225: Highly Flammable liquid and vapor [Danger Flammable liquids]", "Not Classified",
          "Reported as not meeting GHS hazard criteria by 1866 of 1876 companies (only 0.5% companies provided GHS "
          "information). For more detailed information, please visit ECHA C&L website."]
    real, nc = ghs_statements(st)
    assert real == ["H225: Highly Flammable liquid and vapor"] and nc
    assert hazard_info({"hazard_statements": st})["codes"] == ["H225"]
    assert not hazard_info({"hazard_statements": st})["not_classified"]  # has real H-statements
    h = hazard_info({"hazard_statements": st[1:]})
    assert h["codes"] == [] and h["not_classified"]


def test_actual_from_log():
    e = lambda action, rid, amount, unit, i: {"id": i, "action": action, "data": {"chem": {"reagent_id": rid}, "amount": amount, "unit": unit}}  # noqa: E731
    entries = [e("add", 1, 0.10, "g", 1), e("add", 1, 95, "mg", 2), e("add", 2, 5, "mL", 3), e("add", 2, 1, "g", 4)]
    assert actions.actual_from_log(entries, 1) == (pytest.approx(0.195), "g")
    assert actions.actual_from_log(entries, 2) == (5.0, "mL")     # mixed units: the first unit counts
    entries.append(e("weigh", 1, 0.2, "g", 5))
    assert actions.actual_from_log(entries, 1) == (0.2, "g")       # an "Amount used" entry wins
    entries.append({"id": 6, "action": "weigh", "data": {"reagent_id": 3, "value": 2.5, "unit": "mL"}})  # old format
    assert actions.actual_from_log(entries, 3) == (2.5, "mL")
    assert actions.actual_from_log(entries, 9) is None
