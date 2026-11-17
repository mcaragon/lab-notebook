import pytest


def experiment(client, title, sm, product, sm_mmol, product_g):
    d = client.post("/api/experiments", json={"title": title}).json()
    eid, sid = d["experiment"]["id"], d["steps"][0]["id"]
    client.post(f"/api/experiments/{eid}/reagents", json={"query": sm, "step_id": sid, "basis": "mmol",
                                                         "basis_value": sm_mmol})
    client.post(f"/api/experiments/{eid}/reagents", json={"query": product, "role": "product", "step_id": sid,
                                                         "actual_mass_g": product_g})
    return eid


def test_link_existing_experiments_after_the_fact(client):
    # two experiments done separately: benzaldehyde -> benzyl alcohol, then benzyl alcohol -> benzaldehyde
    e1 = experiment(client, "Reduction", "benzaldehyde", "benzyl alcohol", 10, 0.865)      # 80 %
    e2 = experiment(client, "Oxidation", "benzyl alcohol", "benzaldehyde", 8, 0.637)       # 75 %
    d = client.post("/api/sequences", json={"title": "Round trip", "experiment_ids": [e1, e2]}).json()
    sid = d["sequence"]["id"]
    assert [e["id"] for e in d["experiments"]] == [e1, e2]
    assert d["experiments"][1]["linked"] is True  # matched by compound, no explicit link needed
    assert [r["yield"] for r in d["summary"]] == [pytest.approx(80.0, abs=0.1), pytest.approx(75.0, abs=0.1)]
    assert d["overall_yield"] == pytest.approx(60.0, abs=0.1)
    assert 'class="arrow"' in d["scheme_html"]
    # experiment shows its sequence
    assert client.get(f"/api/experiments/{e1}").json()["sequences"] == [{"id": sid, "title": "Round trip"}]
    # reorder, remove, add back
    d = client.put(f"/api/sequences/{sid}/order", json=[e2, e1]).json()
    assert [e["id"] for e in d["experiments"]] == [e2, e1]
    d = client.delete(f"/api/sequences/{sid}/experiments/{e2}").json()
    assert [e["id"] for e in d["experiments"]] == [e1]
    d = client.post(f"/api/sequences/{sid}/experiments", json={"experiment_id": e2}).json()
    assert [e["id"] for e in d["experiments"]] == [e1, e2]
    assert len(client.get("/api/sequences").json()["sequences"]) == 1


def test_next_experiment_starts_from_last_product(client):
    e1 = experiment(client, "Reduction", "benzaldehyde", "benzyl alcohol", 10, 0.9)
    sid = client.post("/api/sequences", json={"title": "Route", "experiment_ids": [e1]}).json()["sequence"]["id"]
    d = client.post(f"/api/sequences/{sid}/next", json={}).json()
    e2 = d["experiment_id"]
    assert [e["id"] for e in d["experiments"]] == [e1, e2]
    exp2 = client.get(f"/api/experiments/{e2}").json()
    sm = exp2["reagents"][0]
    assert sm["name"] == "Benzyl Alcohol" and sm["role"] == "reactant" and sm["basis_value"] == 0.9
    assert exp2["experiment"]["title"] == "Route: step 2"
    assert d["experiments"][1]["linked"] is True


def test_sequence_reports(client):
    e1 = experiment(client, "Reduction", "benzaldehyde", "benzyl alcohol", 10, 0.865)
    e2 = experiment(client, "Oxidation", "benzyl alcohol", "benzaldehyde", 8, 0.637)
    sid = client.post("/api/sequences", json={"title": "Round trip", "notes": "Two days",
                                              "experiment_ids": [e1, e2]}).json()["sequence"]["id"]
    md = client.get(f"/api/sequences/{sid}/report.md").text
    assert md.startswith("# Round trip") and "## Route" in md
    assert "## 1. Reduction" in md and "## 2. Oxidation" in md and "### Reagents" in md
    assert "**Overall yield:** 60.0% over 2 steps" in md
    # chapters use the route's compound numbers and arrow letters
    chapter2 = md.split("## 2. Oxidation", 1)[1]
    assert "Benzyl Alcohol (**2**)" in chapter2 and "Benzaldehyde (**1**)" in chapter2
    html = client.get(f"/api/sequences/{sid}/report.html").text
    assert "Round trip" in html and html.count('class="chapter"') == 2
    pytest.importorskip("weasyprint")
    pdf = client.get(f"/api/sequences/{sid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.delete(f"/api/sequences/{sid}").status_code == 204
    assert client.get(f"/api/experiments/{e1}").status_code == 200  # experiments are kept
