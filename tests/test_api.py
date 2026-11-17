def new_exp(client, **kw):
    r = client.post("/api/experiments", json={"title": "NaBH4 reduction of benzaldehyde", **kw})
    assert r.status_code == 201
    return r.json()["experiment"]["id"]


def test_health_and_config(client, offline_client):
    h = client.get("/api/health").json()
    assert h["pubchem"]["reachable"] is True
    assert h["pubchem"]["datasets"]["lcss"] is True
    h = offline_client.get("/api/health").json()
    assert h["status"] == "ok" and h["pubchem"]["reachable"] is False
    cfg = client.get("/api/config").json()
    assert "reactant" in cfg["roles"]


def test_experiment_crud(client):
    exp_id = new_exp(client)
    d = client.get(f"/api/experiments/{exp_id}").json()
    assert d["experiment"]["author"] == "A. Chemist"  # default from AUTHOR_NAME
    assert d["experiment"]["status"] == "planned"
    r = client.put(f"/api/experiments/{exp_id}", json={"procedure": "1. Dissolve", "status": "in_progress"})
    assert r.json()["experiment"]["procedure"] == "1. Dissolve"
    assert client.put(f"/api/experiments/{exp_id}", json={"status": "bogus"}).status_code == 422
    assert len(client.get("/api/experiments").json()["experiments"]) == 1
    assert client.delete(f"/api/experiments/{exp_id}").status_code == 204
    assert client.get(f"/api/experiments/{exp_id}").status_code == 404


def test_add_reagent_autofills_from_pubchem(client):
    exp_id = new_exp(client)
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzaldehyde"}).json()
    assert d["warning"] is None
    r = d["reagents"][0]
    assert r["cid"] == 240 and r["mw"] == 106.12 and r["density"] == 1.046
    assert r["sources"]["mw"] == "pubchem"
    assert "GHS07" in r["pictograms"]

    # by CID (autocomplete pick)
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"cid": 4311764, "role": "reagent"}).json()
    assert d["reagents"][1]["name"].lower() == "sodium borohydride"


def test_reagent_table_calculation_and_overrides(client):
    exp_id = new_exp(client)
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzaldehyde"}).json()
    ald = d["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "sodium borohydride", "role": "reagent"}).json()
    bh = d["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "methanol", "role": "solvent"}).json()
    meoh = d["reagent_id"]
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzyl alcohol", "role": "product"}).json()
    prod = d["reagent_id"]
    assert next(r for r in d["reagents"] if r["id"] == meoh)["basis"] == "volume"  # solvents default to volume

    client.put(f"/api/reagents/{ald}", json={"basis": "mmol", "basis_value": 10})
    client.put(f"/api/reagents/{bh}", json={"basis": "equiv", "basis_value": 0.5})
    client.put(f"/api/reagents/{meoh}", json={"basis_value": 20})
    d = client.put(f"/api/reagents/{prod}", json={"actual_mass_g": 0.9}).json()
    rows = {r["id"]: r for r in d["reagents"]}
    assert rows[ald]["calc"]["is_limiting"]
    assert abs(rows[ald]["calc"]["mass_g"] - 1.0612) < 1e-6
    assert abs(rows[bh]["calc"]["mmol"] - 5.0) < 1e-9
    assert abs(rows[meoh]["calc"]["mass_g"] - 20 * 0.7907) < 1e-6
    assert abs(rows[prod]["calc"]["percent_yield"] - 0.9 / 1.0814 * 100) < 1e-6

    # manual override is tracked, and can be reverted
    d = client.put(f"/api/reagents/{ald}", json={"density": 1.044}).json()
    r = next(x for x in d["reagents"] if x["id"] == ald)
    assert r["sources"]["density"] == "manual" and r["density"] == 1.044
    d = client.post(f"/api/reagents/{ald}/refresh", json={"fields": ["density"]}).json()
    r = next(x for x in d["reagents"] if x["id"] == ald)
    assert r["sources"]["density"] == "pubchem" and r["density"] == 1.046

    # reference switch
    d = client.put(f"/api/reagents/{bh}", json={"is_reference": True}).json()
    assert d["stoich"]["reference_id"] == bh
    assert sum(r["is_reference"] for r in d["reagents"]) == 1

    # reorder and delete
    d = client.put(f"/api/experiments/{exp_id}/reagents/order", json=[prod, meoh, bh, ald]).json()
    assert [r["id"] for r in d["reagents"]] == [prod, meoh, bh, ald]
    d = client.delete(f"/api/reagents/{meoh}").json()
    assert len(d["reagents"]) == 3


def test_unknown_and_offline_reagents_allow_manual_entry(client, offline_client):
    exp_id = new_exp(client)
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "my secret intermediate", "mw": 250.3}).json()
    assert "not found" in d["warning"]
    r = d["reagents"][0]
    assert r["name"] == "my secret intermediate" and r["mw"] == 250.3 and r["sources"]["mw"] == "manual"

    exp2 = new_exp(offline_client)
    d = offline_client.post(f"/api/experiments/{exp2}/reagents", json={"query": "benzaldehyde"}).json()
    assert "unavailable" in d["warning"]
    assert d["reagents"][0]["name"] == "benzaldehyde"
    assert offline_client.get("/api/pubchem/autocomplete?q=benz").status_code == 503


def test_entries(client):
    exp_id = new_exp(client)
    e = client.post(f"/api/experiments/{exp_id}/entries", json={"kind": "observation", "text": "Solution turned yellow"})
    assert e.status_code == 201
    eid = e.json()["entry"]["id"]
    assert e.json()["entry"]["ts"]
    client.post(f"/api/experiments/{exp_id}/entries",
                json={"kind": "measurement", "text": "mp", "value": "-15", "unit": "°C", "ts": "2026-01-01T10:00:00+01:00"})
    u = client.put(f"/api/entries/{eid}", json={"text": "Solution turned pale yellow"}).json()["entry"]
    assert u["text"] == "Solution turned pale yellow"
    entries = client.get(f"/api/experiments/{exp_id}").json()["entries"]
    assert [x["text"] for x in entries] == ["mp", "Solution turned pale yellow"]  # sorted by time
    assert client.delete(f"/api/entries/{eid}").status_code == 204


def test_duplicate(client):
    exp_id = new_exp(client, results="good")
    d = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzyl alcohol", "role": "product",
                                                                  "actual_mass_g": 1.0}).json()
    client.post(f"/api/experiments/{exp_id}/entries", json={"text": "x"})
    copy = client.post(f"/api/experiments/{exp_id}/duplicate").json()
    assert copy["experiment"]["title"].endswith("(copy)")
    assert copy["experiment"]["results"] is None
    assert copy["reagents"][0]["actual_mass_g"] is None and copy["reagents"][0]["cid"] == 244
    assert copy["entries"] == []


def test_proxy_endpoints(client):
    assert client.get("/api/pubchem/autocomplete?q=benz").json()["suggestions"]
    assert client.get("/api/pubchem/lookup?q=benzaldehyde").json()["cid"] == 240
    assert client.get("/api/pubchem/lookup?q=nope").status_code == 404
    src = client.get("/api/pubchem/compound/240/sources").json()["properties"]
    assert src["bp"]["sources"]
    r = client.get("/api/pubchem/compound/240/structure.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")
    assert client.get("/api/pubchem/ghs/GHS07.svg").status_code == 200
    assert client.get("/api/pubchem/ghs/evil.svg").status_code == 404


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Lab Notebook" in r.text
    assert client.get("/static/app.js").status_code == 200
