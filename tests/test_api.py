import pytest


def new_exp(client, **kw):
    r = client.post("/api/experiments", json={"title": "NaBH4 reduction of benzaldehyde", **kw})
    assert r.status_code == 201
    d = r.json()
    return d["experiment"]["id"], d["steps"][0]["id"]


def add(client, exp_id, **body):
    r = client.post(f"/api/experiments/{exp_id}/reagents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def rows(d):
    return {r["id"]: r for r in d["reagents"]}


def test_health_and_config(client, offline_client):
    h = client.get("/api/health").json()
    assert h["pubchem"]["reachable"] is True
    assert h["pubchem"]["datasets"]["lcss"] is True
    assert offline_client.get("/api/health").json()["pubchem"]["reachable"] is False
    cfg = client.get("/api/config").json()
    assert "workup" in cfg["roles"] and "extract" in cfg["actions"]


def test_experiment_crud(client):
    exp_id, _ = new_exp(client)
    d = client.get(f"/api/experiments/{exp_id}").json()
    assert d["experiment"]["author"] == "A. Chemist"  # default from AUTHOR_NAME
    assert len(d["steps"]) == 1 and d["scheme_html"]
    r = client.put(f"/api/experiments/{exp_id}", json={"objective": "Reduce", "status": "in_progress"})
    assert r.json()["experiment"]["objective"] == "Reduce"
    assert client.put(f"/api/experiments/{exp_id}", json={"status": "bogus"}).status_code == 422
    assert client.delete(f"/api/experiments/{exp_id}").status_code == 204
    assert client.get(f"/api/experiments/{exp_id}").status_code == 404


def test_add_reagent_autofills_ghs_and_extra_hazards(client):
    exp_id, sid = new_exp(client)
    d = add(client, exp_id, query="methanol", role="solvent", step_id=sid)
    r = d["reagents"][0]
    assert r["cid"] == 887 and r["sources"]["mw"] == "pubchem"
    assert r["basis"] == "volume"  # solvents are measured by volume
    assert r["extra_hazards"]["dot"]["un"] == ["UN1230"]
    assert r["extra_hazards"]["nfpa"] == {"health": 1, "fire": 3, "instability": 0, "special": None}
    # Forbidden explosive: DOT data shown even though PubChem has it as extra data
    d = add(client, exp_id, query="628-86-4", role="reagent", step_id=sid)
    fulm = next(x for x in d["reagents"] if x["cid"] == 11022444)
    assert fulm["extra_hazards"]["dot"]["forbidden"] is True
    assert "Explosive" in fulm["extra_hazards"]["alerts"]


def test_solution_parsing_from_the_add_box(client):
    exp_id, sid = new_exp(client)
    d = add(client, exp_id, query="37% hydrochloric acid", role="workup", step_id=sid)
    r = d["reagents"][0]
    assert r["cid"] == 313 and r["form"] == "wt" and r["wt_percent"] == 37
    d = add(client, exp_id, query="2.5 M my reagent in hexanes", role="reagent", step_id=sid)
    r = next(x for x in d["reagents"] if x["id"] == d["reagent_id"])
    assert r["form"] == "solution" and r["concentration_m"] == 2.5 and "hexanes" in r["notes"]


def test_planned_actual_and_weigh_log(client):
    exp_id, sid = new_exp(client)
    ald = add(client, exp_id, query="benzaldehyde", step_id=sid)["reagent_id"]
    bh = add(client, exp_id, query="sodium borohydride", role="reagent", step_id=sid)["reagent_id"]
    prod = add(client, exp_id, query="benzyl alcohol", role="product", step_id=sid)["reagent_id"]
    client.put(f"/api/reagents/{ald}", json={"basis": "mass", "basis_value": 1.0612})
    client.put(f"/api/reagents/{bh}", json={"basis": "equiv", "basis_value": 0.5})
    d = client.put(f"/api/reagents/{ald}", json={"actual_basis": "mass", "actual_value": 1.0400}).json()
    r = rows(d)
    assert r[ald]["calc"]["act_mmol"] == pytest.approx(1.04 / 106.12 * 1000)
    assert r[ald]["calc"]["deviation_pct"] == pytest.approx((1.04 - 1.0612) / 1.0612 * 100)
    assert r[bh]["calc"]["mmol"] == pytest.approx(5.0)
    assert r[prod]["calc"]["theoretical_mmol"] == pytest.approx(1.04 / 106.12 * 1000)  # actual amount used
    weigh = [e for e in d["entries"] if e["action"] == "weigh"]
    assert len(weigh) == 1 and weigh[0]["text"] == "Benzaldehyde measured: 1.04 g"
    # a correction updates the same entry; clearing removes it
    d = client.put(f"/api/reagents/{ald}", json={"actual_value": 1.05}).json()
    assert [e["text"] for e in d["entries"] if e["action"] == "weigh"] == ["Benzaldehyde measured: 1.05 g"]
    d = client.put(f"/api/reagents/{ald}", json={"actual_value": None, "actual_basis": None}).json()
    assert not [e for e in d["entries"] if e["action"] == "weigh"]


def test_manual_override_and_refresh(client):
    exp_id, sid = new_exp(client)
    ald = add(client, exp_id, query="benzaldehyde", step_id=sid)["reagent_id"]
    d = client.put(f"/api/reagents/{ald}", json={"density": 1.044, "grade": "99%", "lot": "A1"}).json()
    r = rows(d)[ald]
    assert r["sources"]["density"] == "manual" and r["grade"] == "99%" and r["lot"] == "A1"
    d = client.post(f"/api/reagents/{ald}/refresh", json={"fields": ["density"]}).json()
    r = rows(d)[ald]
    assert r["sources"]["density"] == "pubchem" and r["density"] == 1.046


def test_unknown_and_offline_reagents_allow_manual_entry(client, offline_client):
    exp_id, sid = new_exp(client)
    d = add(client, exp_id, query="my secret intermediate", mw=250.3, step_id=sid)
    assert "not found" in d["warning"]
    r = d["reagents"][0]
    assert r["name"] == "my secret intermediate" and r["mw"] == 250.3 and r["sources"]["mw"] == "manual"
    exp2, sid2 = new_exp(offline_client)
    d = add(offline_client, exp2, query="benzaldehyde", step_id=sid2)
    assert "unavailable" in d["warning"]
    assert offline_client.get("/api/pubchem/autocomplete?q=benz").status_code == 503
    assert offline_client.get(f"/api/reagents/{d['reagent_id']}/structure.svg").status_code == 404


def test_steps_carry_product_and_conditions(client):
    exp_id, s1 = new_exp(client)
    add(client, exp_id, query="benzaldehyde", step_id=s1, basis="mmol", basis_value=10)
    prod = add(client, exp_id, query="benzyl alcohol", role="product", step_id=s1)["reagent_id"]
    client.put(f"/api/reagents/{prod}", json={"actual_mass_g": 0.9})
    client.post(f"/api/steps/{s1}/conditions", json={"temperature": "0", "duration": "15 min"})
    d = client.post(f"/api/steps/{s1}/conditions", json={"temperature": "rt", "duration": "2 h"}).json()
    assert [k["temperature"] for k in d["steps"][0]["conditions"]] == ["0", "rt"]
    d = client.post(f"/api/experiments/{exp_id}/steps", json={"title": "Oxidation"}).json()
    s2 = d["step_id"]
    carried = [r for r in d["reagents"] if r["step_id"] == s2]
    assert len(carried) == 1 and carried[0]["source_reagent_id"] == prod
    assert carried[0]["basis_value"] == 0.9 and carried[0]["is_reference"]
    # deleting a step removes its reagents; the last step cannot be deleted
    d = client.delete(f"/api/steps/{s2}").json()
    assert len(d["steps"]) == 1 and all(r["step_id"] == s1 for r in d["reagents"])
    assert client.delete(f"/api/steps/{s1}").status_code == 400


def test_procedure_mentions_done_and_order(client):
    exp_id, sid = new_exp(client)
    ald = add(client, exp_id, query="benzaldehyde", step_id=sid, basis="mass", basis_value=1.06)["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/procedure",
                    json={"text": "Dissolve @Benzaldehyde in MeOH.", "notes": "dry MeOH"}).json()
    p1 = d["procedure"][0]
    assert "<b>Benzaldehyde</b> (1.06 g, 9.99 mmol)" in p1["html"]
    d = client.post(f"/api/experiments/{exp_id}/procedure", json={"text": "Add @{Sodium borohydride}."}).json()
    p2 = d["procedure"][1]
    assert "@{Sodium borohydride}" in p2["html"]  # unknown mention stays as typed
    d = client.put(f"/api/procedure/{p1['id']}", json={"done": True}).json()
    assert d["procedure"][0]["done_at"]
    assert [e["text"] for e in d["entries"]] == ["Procedure step 1 completed"]
    d = client.put(f"/api/procedure/{p1['id']}", json={"done": False}).json()
    assert d["entries"] == [] and d["procedure"][0]["done_at"] is None
    d = client.put(f"/api/experiments/{exp_id}/procedure/order", json=[p2["id"], p1["id"]]).json()
    assert [p["id"] for p in d["procedure"]] == [p2["id"], p1["id"]]
    assert ald


def test_log_actions_clock_and_timers(client):
    exp_id, sid = new_exp(client)
    bh = add(client, exp_id, query="sodium borohydride", role="reagent", step_id=sid)["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/start").json()
    assert d["experiment"]["started_at"] and d["experiment"]["status"] == "in_progress"
    d = client.post(f"/api/experiments/{exp_id}/entries", json={
        "action": "add", "data": {"chem": {"reagent_id": bh}, "amount": 0.19, "unit": "g", "mode": "portionwise",
                                  "over": "10 min"},
        "start_timer": {"label": "Addition of NaBH4"}}).json()
    e = next(x for x in d["entries"] if x["action"] == "add")
    assert e["text"] == "Sodium borohydride (0.19 g) added portionwise over 10 min"
    assert e["elapsed_s"] is not None and e["elapsed_s"] >= 0
    tid = d["timers"][0]["id"]
    assert d["timers"][0]["start_entry_id"] == e["id"]
    d = client.post(f"/api/timers/{tid}/stop").json()
    assert d["timers"][0]["stopped_at"]
    assert d["entries"][-1]["text"].startswith("Addition of NaBH4: complete (")
    # extraction with a chemical typed by name, usage is tallied
    dcm = add(client, exp_id, query="methanol", role="workup", step_id=sid)["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/entries", json={
        "action": "extract", "data": {"chem": {"reagent_id": dcm}, "n": 4, "volume": 25}}).json()
    assert d["entries"][-1]["text"] == "Extracted with Methanol (4 × 25 mL)"
    assert rows(d)[dcm]["usage"] == {"mL": 100}
    # countdown timer, observation, unknown action
    d = client.post(f"/api/experiments/{exp_id}/timers", json={"label": "Reflux", "kind": "countdown",
                                                                 "duration_s": 3600}).json()
    assert d["entries"][-1]["text"] == "Countdown started: Reflux (1:00:00)"
    d = client.post(f"/api/experiments/{exp_id}/entries", json={"action": "observation", "data": {"text": "Yellow"}}).json()
    assert d["entries"][-1]["text"] == "Yellow"
    assert client.post(f"/api/experiments/{exp_id}/entries", json={"action": "bogus"}).status_code == 422
    # editing: text override and time change recomputes T+
    eid = d["entries"][-1]["id"]
    d = client.put(f"/api/entries/{eid}", json={"text": "Pale yellow"}).json()
    assert next(x for x in d["entries"] if x["id"] == eid)["text"] == "Pale yellow"
    # ending stops running timers and logs the total
    d = client.post(f"/api/experiments/{exp_id}/end").json()
    assert all(t["stopped_at"] for t in d["timers"])
    assert d["entries"][-1]["text"].startswith("Experiment ended (total ")


def test_isolate_action_sets_product_mass(client):
    exp_id, sid = new_exp(client)
    add(client, exp_id, query="benzaldehyde", step_id=sid, basis="mmol", basis_value=10)
    prod = add(client, exp_id, query="benzyl alcohol", role="product", step_id=sid)["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/entries", json={
        "action": "isolate", "data": {"product": prod, "stage": "crude", "mass": 1.2}}).json()
    assert rows(d)[prod]["crude_mass_g"] == 1.2
    d = client.post(f"/api/experiments/{exp_id}/entries", json={
        "action": "isolate", "data": {"product": prod, "stage": "purified", "mass": 0.9, "appearance": "colorless oil"}}).json()
    r = rows(d)[prod]
    assert r["actual_mass_g"] == 0.9 and r["calc"]["percent_yield"] == pytest.approx(0.9 / 1.0814 * 100)
    assert d["entries"][-1]["text"] == "Benzyl Alcohol (purified): 0.9 g, colorless oil"


def test_references(client):
    exp_id, sid = new_exp(client)
    d = client.post(f"/api/experiments/{exp_id}/refs", json={"text": "Lab manual"}).json()
    d = client.post(f"/api/experiments/{exp_id}/refs", json={"authors": "Smith, J.", "doi": "10.1/x"}).json()
    r1, r2 = d["refs"]
    prod = add(client, exp_id, query="benzyl alcohol", role="product", step_id=sid)["reagent_id"]
    client.put(f"/api/reagents/{prod}", json={"expected_yield_pct": 90, "expected_ref_id": r2["id"]})
    d = client.put(f"/api/experiments/{exp_id}/refs/order", json=[r2["id"], r1["id"]]).json()
    assert [r["id"] for r in d["refs"]] == [r2["id"], r1["id"]]
    d = client.delete(f"/api/refs/{r2['id']}").json()
    assert rows(d)[prod]["expected_ref_id"] is None


def test_duplicate(client):
    exp_id, sid = new_exp(client, results="good")
    ald = add(client, exp_id, query="benzaldehyde", step_id=sid)["reagent_id"]
    client.put(f"/api/reagents/{ald}", json={"actual_basis": "mass", "actual_value": 1.0})
    client.post(f"/api/steps/{sid}/conditions", json={"temperature": "0"})
    client.post(f"/api/experiments/{exp_id}/procedure", json={"text": "Do it"})
    client.post(f"/api/experiments/{exp_id}/steps", json={})
    copy = client.post(f"/api/experiments/{exp_id}/duplicate").json()
    assert copy["experiment"]["title"].endswith("(copy)") and copy["experiment"]["results"] is None
    assert len(copy["steps"]) == 2 and copy["steps"][0]["conditions"][0]["temperature"] == "0"
    assert copy["reagents"][0]["actual_value"] is None and copy["reagents"][0]["cid"] == 240
    assert copy["procedure"][0]["text"] == "Do it" and copy["entries"] == []


def test_proxy_and_structures(client):
    assert client.get("/api/pubchem/autocomplete?q=benz").json()["suggestions"]
    assert client.get("/api/pubchem/autocomplete?q=2.5 M benz").json()["parsed"] == {"form": "solution",
                                                                                       "concentration_m": 2.5}
    assert client.get("/api/pubchem/lookup?q=nope").status_code == 404
    assert client.get("/api/pubchem/compound/240/sources").json()["properties"]["bp"]["sources"]
    assert client.get("/api/pubchem/ghs/evil.svg").status_code == 404
    exp_id, sid = new_exp(client)
    d = add(client, exp_id, query="benzaldehyde", step_id=sid)
    r = client.get(f"/api/reagents/{d['reagent_id']}/structure.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")
    # a hand-entered compound without CID or SMILES has no structure
    d = add(client, exp_id, name="Mystery", step_id=sid)
    assert client.get(f"/api/reagents/{d['reagent_id']}/structure.svg").status_code == 404


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Lab Notebook" in r.text
    for f in ("main.js", "state.js", "reagents.js", "procedure.js", "bench.js", "reaction.js", "results.js"):
        assert client.get(f"/static/js/{f}").status_code == 200
