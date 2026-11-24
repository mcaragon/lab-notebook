"""Stockroom: containers with amounts and prices, corrections, privacy between accounts, currency."""
from datetime import date, timedelta

import pytest

from labnotebook.stockroom import derive
from test_auth import other


def add(client, **body):
    r = client.post("/api/stockroom", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_container_from_pubchem_with_price_and_amounts(client):
    d = add(client, query="benzaldehyde", quantity=100, unit="g", price=250, supplier="Sigma-Aldrich",
            grade="ReagentPlus", purity=99, lot="SHBK4471", location="Shelf B2", low_threshold=20)
    it = d["item"]
    assert it["name"] == "Benzaldehyde" and it["cid"] == 240 and it["mw"] and it["pictograms"]
    assert it["unit_price"] == pytest.approx(2.5) and it["left"] == 100 and it["value_left"] == pytest.approx(250)
    assert it["received_at"] and d["warning"] is None
    iid = it["id"]
    # a spill and a stocktake are recorded as corrections
    d = client.post(f"/api/stockroom/{iid}/adjust", json={"delta": -16, "reason": "Used before the notebook"}).json()
    assert d["item"]["left"] == pytest.approx(84) and d["item"]["value_left"] == pytest.approx(210)
    d = client.post(f"/api/stockroom/{iid}/adjust", json={"actual": 15, "reason": "Recount"}).json()
    assert d["item"]["left"] == pytest.approx(15) and d["item"]["low"]
    assert [a["delta"] for a in d["adjustments"]] == [-16, pytest.approx(-69)]
    assert d["adjustments"][1]["reason"] == "Recount" and d["adjustments"][1]["username"] == "admin"
    d = client.delete(f"/api/stockroom/{iid}/adjustments/{d['adjustments'][1]['id']}").json()
    assert d["item"]["left"] == pytest.approx(84)
    assert client.post(f"/api/stockroom/{iid}/adjust", json={}).status_code == 422
    # edits mark chemical data as entered by hand
    d = client.put(f"/api/stockroom/{iid}", json={"density": 1.05, "status": "in_use"}).json()
    assert d["item"]["sources"]["density"] == "manual"
    assert client.put(f"/api/stockroom/{iid}", json={"price": -1}).status_code == 422
    # the next bottle of the same thing
    dup = client.post(f"/api/stockroom/{iid}/duplicate").json()["item"]
    assert dup["supplier"] == "Sigma-Aldrich" and dup["lot"] is None and dup["left"] == 100 and dup["id"] != iid
    assert client.get(f"/api/stockroom/{iid}/structure.svg").status_code == 200


def test_list_summary_and_currency(client):
    add(client, query="methanol", quantity=1000, unit="mL", price=40, low_threshold=100)
    soon = (date.today() + timedelta(days=10)).isoformat()
    add(client, name="Old reagent", quantity=5, unit="g", expires_at=soon)
    gone = add(client, name="Finished", quantity=10, unit="g", price=5)["item"]["id"]
    client.put(f"/api/stockroom/{gone}", json={"status": "empty"})
    d = client.get("/api/stockroom").json()
    s = d["summary"]
    assert s["containers"] == 2 and s["value"] == pytest.approx(40) and s["unpriced"] == 1 and s["expiring"] == 1
    assert d["currency"] == "USD"
    r = client.put("/api/account", json={"currency": "eur"})
    assert r.json()["user"]["currency"] == "EUR" and client.get("/api/stockroom").json()["currency"] == "EUR"
    assert client.put("/api/account", json={"currency": "XYZ"}).status_code == 422


def test_stockrooms_are_private(client):
    iid = add(client, name="Mine", quantity=10, unit="g")["item"]["id"]
    f = other(client)
    assert f.get("/api/stockroom").json()["items"] == []
    for method, path, body in [("GET", f"/api/stockroom/{iid}", None), ("PUT", f"/api/stockroom/{iid}", {"name": "x"}),
                               ("DELETE", f"/api/stockroom/{iid}", None),
                               ("POST", f"/api/stockroom/{iid}/adjust", {"delta": -1}),
                               ("POST", f"/api/stockroom/{iid}/duplicate", None),
                               ("GET", f"/api/stockroom/{iid}/structure.svg", None)]:
        assert f.request(method, path, json=body).status_code == 404, (method, path)
    assert client.delete(f"/api/stockroom/{iid}").status_code == 204


def test_derive():
    today = date(2026, 1, 10)
    d = derive({"quantity": 100, "price": 250, "low_threshold": 10, "expires_at": "2026-01-05", "status": "in_use"},
               corrections=-5, used=80, reserved=10, today=today)
    assert d["left"] == 15 and d["available"] == 5 and d["value_left"] == pytest.approx(37.5)
    assert d["fraction_left"] == pytest.approx(.15) and d["expired"] and not d["expiring"] and not d["low"]
    assert derive({"quantity": None})["left"] is None and derive({"quantity": 5, "price": None})["unit_price"] is None
    assert derive({"quantity": 5, "status": "in_use"}, used=6)["low"]  # empty or overdrawn counts as low
