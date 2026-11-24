"""Costs: inputs priced from stockroom containers, product cost per gram, costs inherited along a project route."""
import pytest

from labnotebook.costs import money


def item(client, **body):
    return client.post("/api/stockroom", json=body).json()["item"]["id"]


def run(client, title, uses, product_g=None, product="Product P"):
    """An experiment drawing ``uses`` [(container, grams measured)] with an isolated product."""
    eid = client.post("/api/experiments", json={"title": title}).json()["experiment"]["id"]
    for iid, g in uses:
        rid = client.post(f"/api/experiments/{eid}/reagents", json={"stock_item_id": iid}).json()["reagent_id"]
        client.put(f"/api/reagents/{rid}", json={"actual_basis": "mass", "actual_value": g})
    pid = client.post(f"/api/experiments/{eid}/reagents", json={"name": product, "role": "product", "mw": 150,
                                                                "actual_mass_g": product_g}).json()["reagent_id"]
    return eid, pid


def test_three_runs_of_one_experiment(client):
    """100 g of reagent A for $250; runs using 5.4, 4.9 and 5.7 g."""
    a = item(client, name="Reagent A", mw=100, quantity=100, unit="g", price=250, supplier="Sigma")
    runs = [run(client, f"Run {i}", [(a, g)], product_g=p) for i, (g, p) in enumerate([(5.4, 2.0), (4.9, 2.1), (5.7, 1.9)], 1)]
    totals = []
    for eid, _ in runs:
        c = client.get(f"/api/experiments/{eid}").json()["cost"]
        assert c["complete"] and not c["estimated"]
        totals.append(c["total"])
    assert totals == [pytest.approx(13.50), pytest.approx(12.25), pytest.approx(14.25)]
    c = client.get(f"/api/experiments/{runs[1][0]}").json()["cost"]
    assert c["inputs"][0]["unit_price"] == pytest.approx(2.5) and c["inputs"][0]["share"] == 1
    assert c["product"]["cost_per_g"] == pytest.approx(12.25 / 2.1)
    assert client.get(f"/api/stockroom/{a}").json()["item"]["left"] == pytest.approx(84.0)


def test_route_inherits_costs_and_flags_missing_prices(client):
    a = item(client, name="A", mw=100, quantity=100, unit="g", price=250)   # $2.50/g
    b = item(client, name="B", mw=100, quantity=100, unit="g", price=100)   # $1.00/g
    e1, p1 = run(client, "Step 1", [(a, 16)], product_g=10)                 # $40 → $4.00/g
    e2 = client.post(f"/api/reagents/{p1}/branch", json={"mass_g": 6}).json()["experiment"]["id"]
    rid = next(r["id"] for r in client.get(f"/api/experiments/{e2}").json()["reagents"])
    client.put(f"/api/reagents/{rid}", json={"actual_basis": "mass", "actual_value": 6})
    rb = client.post(f"/api/experiments/{e2}/reagents", json={"stock_item_id": b}).json()["reagent_id"]
    client.put(f"/api/reagents/{rb}", json={"actual_basis": "mass", "actual_value": 18})
    client.post(f"/api/experiments/{e2}/reagents", json={"name": "Q", "role": "product", "mw": 150, "actual_mass_g": 5})
    c = client.get(f"/api/experiments/{e2}").json()["cost"]
    inherited = next(x for x in c["inputs"] if x["source"]["kind"] == "product")
    assert inherited["unit_price"] == pytest.approx(4.0) and inherited["cost"] == pytest.approx(24.0)
    assert c["total"] == pytest.approx(42.0) and c["product"]["cost_per_g"] == pytest.approx(8.40) and c["complete"]
    # the project shows each step's cost per gram, on the map too
    pid = client.get(f"/api/experiments/{e2}").json()["projects"][0]["id"]
    proj = client.get(f"/api/projects/{pid}").json()
    by = {r["id"]: r for r in proj["summary"]}
    assert by[e1]["cost"]["per_g"] == pytest.approx(4.0) and by[e2]["cost"]["per_g"] == pytest.approx(8.4)
    assert "$8.40/g" in proj["map_svg"] and proj["currency"] == "USD"
    # an input without a price: the total is incomplete and says which; nothing counts as free
    client.post(f"/api/experiments/{e2}/reagents", json={"name": "Celite", "role": "workup", "basis": "mass",
                                                         "basis_value": 2})
    c = client.get(f"/api/experiments/{e2}").json()["cost"]
    assert not c["complete"] and c["unpriced"] == ["Celite"] and c["total"] == pytest.approx(42.0)
    assert next(x for x in c["inputs"] if x["name"] == "Celite")["why"] == "not from the stockroom"
    assert "≥$8.40/g" in client.get(f"/api/projects/{pid}").json()["map_svg"]


def test_planned_amounts_give_an_estimate(client):
    a = item(client, name="A", mw=100, quantity=50, unit="g", price=100)
    eid = client.post("/api/experiments", json={}).json()["experiment"]["id"]
    client.post(f"/api/experiments/{eid}/reagents", json={"stock_item_id": a, "basis": "mass", "basis_value": 3})
    c = client.get(f"/api/experiments/{eid}").json()["cost"]
    assert c["total"] == pytest.approx(6.0) and c["estimated"] and c["inputs"][0]["estimated"]


def test_money():
    assert money(13.5) == "$13.50" and money(0.0248, "EUR") == "€0.0248" and money(1250, "SEK") == "1,250.00 SEK"
    assert money(1500, "JPY") == "¥1,500" and money(None) == ""


def test_reports_include_costs_only_when_asked(client):
    a = item(client, name="A", mw=100, quantity=100, unit="g", price=250, supplier="Sigma", lot="L1")
    e1, p1 = run(client, "Step 1", [(a, 16)], product_g=10)
    md = client.get(f"/api/experiments/{e1}/report.md").text
    assert "Cost" not in md and "$" not in md
    md = client.get(f"/api/experiments/{e1}/report.md", params={"costs": True}).text
    assert "### Cost" in md or "## Cost" in md
    assert "$40.00" in md and "$4.00/g" in md and "Sigma, lot L1" in md
    html = client.get(f"/api/experiments/{e1}/report.html", params={"costs": True}).text
    assert 'class="cost"' in html and "$40.00" in html
    e2 = client.post(f"/api/reagents/{p1}/branch", json={"mass_g": 6}).json()
    pid = e2["project_ids"][0]
    md = client.get(f"/api/projects/{pid}/report.md", params={"costs": True}).text
    assert "Cost/g" in md and "$4.00" in md
    assert "Cost/g" not in client.get(f"/api/projects/{pid}/report.md").text
