"""Projects: experiments linked by material (a starting material taken from another experiment's product), branching
routes, what is left of a product, overall yields and project reports."""
import pytest


def experiment(client, title, sm, product, sm_mmol, product_g, product_mw=None):
    d = client.post("/api/experiments", json={"title": title}).json()
    eid = d["experiment"]["id"]
    client.post(f"/api/experiments/{eid}/reagents", json={"query": sm, "basis": "mmol", "basis_value": sm_mmol})
    body = {"query": product, "role": "product", "actual_mass_g": product_g}
    if product_mw:
        body["mw"] = product_mw
    d = client.post(f"/api/experiments/{eid}/reagents", json=body).json()
    return eid, d["reagent_id"]


def take(client, exp_id, product_id, mass):
    """Use a portion of another experiment's product as a starting material."""
    r = client.post(f"/api/experiments/{exp_id}/reagents",
                    json={"source_reagent_id": product_id, "basis": "mass", "basis_value": mass})
    assert r.status_code == 201, r.text
    return r.json()


def test_link_by_product_and_route_info(client):
    e1, p1 = experiment(client, "Reduction", "benzaldehyde", "benzyl alcohol", 10, 0.865)      # 80 %
    # products of other experiments can be found to use them as starting materials
    found = client.get("/api/products", params={"q": "benzyl", "exclude": e1 + 100}).json()["products"]
    assert found[0]["id"] == p1 and found[0]["remaining_g"] == pytest.approx(0.865)
    e2 = client.post("/api/experiments", json={"title": "Oxidation"}).json()["experiment"]["id"]
    d = take(client, e2, p1, 0.8)
    sm = next(r for r in d["reagents"] if r["source_reagent_id"] == p1)
    assert sm["name"] == "Benzyl Alcohol" and sm["basis_value"] == 0.8 and sm["is_reference"]
    assert d["route"]["sources"][0]["experiment_id"] == e1 and d["route"]["sources"][0]["taken_g"] == 0.8
    # the parent sees where its product went and what is left
    r1 = client.get(f"/api/experiments/{e1}").json()["route"]
    assert r1["uses"] == [{"experiment_id": e2, "experiment": "Oxidation", "status": "planned", "product_id": p1,
                           "taken_g": 0.8}]
    assert r1["products"][0]["remaining_g"] == pytest.approx(0.065)
    # a product of the same experiment cannot be its own starting material
    assert client.post(f"/api/experiments/{e1}/reagents", json={"source_reagent_id": p1}).status_code == 400


def test_branching_project(client):
    # one aldehyde batch split over three reactions, each continued once: a branched route
    e1, p1 = experiment(client, "Batch", "benzaldehyde", "benzyl alcohol", 20, 1.73)           # 80 %
    d = client.post(f"/api/reagents/{p1}/branch", json={"mass_g": 0.5, "title": "Branch A"}).json()
    a = d["experiment"]["id"]
    pid = d["project_ids"][0]
    assert d["route"]["sources"][0]["taken_g"] == 0.5
    proj = client.get(f"/api/projects/{pid}").json()
    assert proj["project"]["title"] == "Route from Benzyl Alcohol"
    assert [e["id"] for e in proj["experiments"]] == [e1, a]
    b = client.post(f"/api/reagents/{p1}/branch", json={"mass_g": 0.4, "title": "Branch B"}).json()["experiment"]["id"]
    # without an amount, a branch takes what is left
    c = client.post(f"/api/reagents/{p1}/branch", json={"title": "Branch C"}).json()
    assert c["reagents"][0]["basis_value"] == pytest.approx(0.83)
    c = c["experiment"]["id"]
    # branch A gets a product, which is continued in a further experiment
    pa = client.post(f"/api/experiments/{a}/reagents", json={"query": "benzaldehyde", "role": "product",
                                                             "actual_mass_g": 0.392}).json()["reagent_id"]  # ~80 %
    a2 = client.post(f"/api/reagents/{pa}/branch", json={"mass_g": 0.3}).json()["experiment"]["id"]
    proj = client.get(f"/api/projects/{pid}").json()
    by = {r["id"]: r for r in proj["summary"]}
    assert by[e1]["col"] == 0 and {by[x]["col"] for x in (a, b, c)} == {1} and by[a2]["col"] == 2
    assert by[e1]["used_g"] == pytest.approx(1.73) and by[e1]["remaining_g"] == pytest.approx(0)
    assert sorted(by[e1]["children"]) == sorted([a, b, c])
    assert by[a]["yield"] == pytest.approx(80, abs=0.5)
    assert by[a]["overall_yield"] == pytest.approx(64, abs=0.5) and by[a]["lls"] == 2
    assert proj["branches"] is True
    assert {f["id"] for f in proj["final"]} == {b, c, a2}
    svg = proj["map_svg"]
    assert svg.startswith("<svg") and svg.count('class="rm-node"') == 5 and "0.500 g" in svg
    assert f'href="#/exp/{a2}/plan"' in svg
    # the experiment knows its project
    assert client.get(f"/api/experiments/{a2}").json()["projects"] == [{"id": pid, "title": "Route from Benzyl Alcohol"}]


def test_convergent_route(client):
    e1, p1 = experiment(client, "Left half", "benzaldehyde", "benzyl alcohol", 10, 0.865)
    e2, p2 = experiment(client, "Right half", "benzyl alcohol", "benzaldehyde", 10, 0.85)
    e3 = client.post("/api/experiments", json={"title": "Coupling"}).json()["experiment"]["id"]
    take(client, e3, p1, 0.5)
    take(client, e3, p2, 0.5)
    pid = client.post("/api/projects", json={"title": "Convergent", "experiment_ids": [e1, e2, e3]}).json()["project"]["id"]
    proj = client.get(f"/api/projects/{pid}").json()
    by = {r["id"]: r for r in proj["summary"]}
    assert by[e3]["col"] == 1 and sorted(f["id"] for f in by[e3]["from"]) == [e1, e2]
    assert proj["map_svg"].count("rm-edge") >= 2 and "rm-edge extra" in proj["map_svg"]


def test_project_crud_and_reports(client):
    e1, p1 = experiment(client, "Reduction", "benzaldehyde", "benzyl alcohol", 10, 0.865)      # 80 %
    e2 = client.post("/api/experiments", json={"title": "Oxidation"}).json()["experiment"]["id"]
    take(client, e2, p1, 0.865)
    client.post(f"/api/experiments/{e2}/reagents", json={"query": "benzaldehyde", "role": "product",
                                                         "actual_mass_g": 0.637})                # 75 %
    d = client.post("/api/projects", json={"title": "Round trip", "notes": "Two days",
                                           "experiment_ids": [e1, e2]}).json()
    pid = d["project"]["id"]
    # the first experiment's overall yield is its own; its starting material is listed and drawn on the map
    assert [r["overall_yield"] for r in d["summary"]] == [pytest.approx(80.0, abs=0.1), pytest.approx(60.0, abs=0.1)]
    assert [(f["id"], f["title"]) for f in d["summary"][0]["from"]] == [(None, "Benzaldehyde")]
    assert d["summary"][1]["from"][0]["id"] == e1
    assert "Starting material" in d["map_svg"] and d["map_svg"].count('class="rm-node rm-start"') == 1
    md = client.get(f"/api/projects/{pid}/report.md").text
    assert md.startswith("# Round trip") and "## Route" in md and "## Experiments" in md
    assert "## 1. Reduction" in md and "## 2. Oxidation" in md and "### Reagents" in md
    assert "**Overall yield:** 60.0% over 2 steps" in md
    # chapters use the project's compound numbers
    chapter2 = md.split("## 2. Oxidation", 1)[1]
    assert "Benzyl Alcohol (**2**)" in chapter2 and "Benzaldehyde (**1**)" in chapter2
    leaf = client.get(f"/api/projects/{pid}/report.md", params={"leaf": e2}).text
    assert leaf.startswith("# Round trip — route to Oxidation")
    html = client.get(f"/api/projects/{pid}/report.html").text
    assert "Round trip" in html and html.count('class="chapter"') == 2 and "route-map" in html
    assert client.get(f"/api/projects/{pid}/report.md", params={"leaf": 9999}).status_code == 404
    # new unlinked experiment, remove, add back
    d = client.post(f"/api/projects/{pid}/new", json={"title": "Side trial"}).json()
    assert d["experiment_id"] in [e["id"] for e in d["experiments"]]
    d = client.delete(f"/api/projects/{pid}/experiments/{d['experiment_id']}").json()
    assert [e["id"] for e in d["experiments"]] == [e1, e2]
    assert len(client.get("/api/projects").json()["projects"]) == 1
    pytest.importorskip("weasyprint")
    pdf = client.get(f"/api/projects/{pid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/experiments/{e1}").status_code == 200  # experiments are kept


def test_shared_starting_material_nine_targets(client):
    """One aldehyde batch, three Henry reactions with different nitroalkanes, each reduced and then halogenated three
    ways: nine targets from one starting material, each experiment with its own amounts and yield."""
    first = client.post("/api/experiments", json={"title": "Henry A"}).json()["experiment"]["id"]
    ald = client.post(f"/api/experiments/{first}/reagents", json={
        "query": "benzaldehyde", "basis": "mass", "basis_value": 5.0, "lot": "MKCD123", "supplier": "Acme",
        "is_reference": True}).json()["reagent_id"]
    client.post(f"/api/experiments/{first}/reagents", json={"name": "Nitromethane", "mw": 61.04, "basis": "equiv",
                                                            "basis_value": 5})
    # the other two Henry reactions start from the same batch, each with its own amount
    b = client.post(f"/api/reagents/{ald}/branch", json={"mass_g": 3.0, "title": "Henry B"}).json()
    pid = b["project_ids"][0]
    sm = b["reagents"][0]
    assert sm["lot"] == "MKCD123" and sm["supplier"] == "Acme" and sm["basis_value"] == 3.0
    assert sm["source_reagent_id"] is None and sm["is_reference"]
    c = client.post(f"/api/reagents/{ald}/branch", json={"mass_g": 2.0, "title": "Henry C", "project_id": pid}).json()
    henry = [first, b["experiment"]["id"], c["experiment"]["id"]]
    finals = []
    for i, h in enumerate(henry):
        p = client.post(f"/api/experiments/{h}/reagents", json={"name": f"Nitroalkene {i}", "role": "product",
                                                                "mw": 150, "actual_mass_g": 1.0}).json()["reagent_id"]
        red = client.post(f"/api/reagents/{p}/branch", json={"mass_g": 0.9, "title": f"Reduction {i}"}).json()
        amine = client.post(f"/api/experiments/{red['experiment']['id']}/reagents",
                            json={"name": f"Amine {i}", "role": "product", "mw": 120,
                                  "actual_mass_g": 0.5}).json()["reagent_id"]
        for x in ("I", "Br", "Cl"):
            finals.append(client.post(f"/api/reagents/{amine}/branch",
                                      json={"mass_g": 0.15, "title": f"{x}-{i}"}).json()["experiment"]["id"])
    proj = client.get(f"/api/projects/{pid}").json()
    assert len(proj["experiments"]) == 3 + 3 + 9 and {f["id"] for f in proj["final"]} == set(finals)
    (mat,) = proj["materials"]  # one batch, used three times
    assert mat["lot"] == "MKCD123" and [u["experiment_id"] for u in mat["uses"]] == henry
    assert [u["taken_g"] for u in mat["uses"]] == [5.0, 3.0, 2.0] and mat["used_g"] == pytest.approx(10.0)
    assert proj["map_svg"].count('class="rm-node rm-start"') == 1 and "10.0 g used in 3 experiments" in proj["map_svg"]
    # each Henry reaction keeps its own scale: same product mass, different yields
    by = {r["id"]: r for r in proj["summary"]}
    assert by[henry[0]]["yield"] != by[henry[1]]["yield"]
    # amount on hand: what is left of the batch
    d = client.put(f"/api/projects/{pid}/materials", json={"key": mat["key"], "on_hand_g": 25}).json()
    assert d["materials"][0]["left_g"] == pytest.approx(15.0) and "15.0 g left" in d["map_svg"]
    d = client.put(f"/api/projects/{pid}/materials", json={"key": mat["key"], "on_hand_g": None}).json()
    assert d["materials"][0]["on_hand_g"] is None
    # a different lot is a different batch
    other = client.post(f"/api/reagents/{ald}/branch", json={"mass_g": 1.0, "title": "Henry D"}).json()
    client.put(f"/api/reagents/{other['reagents'][0]['id']}", json={"lot": "NEW-LOT"})
    assert len(client.get(f"/api/projects/{pid}").json()["materials"]) == 2
    md = client.get(f"/api/projects/{pid}/report.md").text
    assert "## Starting materials" in md and "MKCD123" in md
