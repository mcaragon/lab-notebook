"""Accounts: sign-in, sessions, access to other people's data, invites, demo limits and the admin routes."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import ADMIN_PASSWORD

PW = "a long enough password"


def other(client, username="friend", **kw):
    """A second signed-in browser for a new account."""
    app = client.app
    app.state.auth.create_user(username, PW, username.title(), **kw)
    c = TestClient(app, headers={"X-Requested-With": "test"})
    assert c.post("/api/auth/login", json={"username": username, "password": PW}).status_code == 200
    return c


def test_sign_in_required_and_header_check(client):
    anon = TestClient(client.app)
    assert anon.get("/api/experiments").status_code == 401
    assert anon.get("/api/health").json() == {"status": "ok"}  # health check works, without details
    st = anon.get("/api/auth/state").json()
    assert st["user"] is None and st["setup_needed"] is False
    # changes need the X-Requested-With header (a cross-site form cannot send it)
    assert anon.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 403
    r = anon.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD},
                  headers={"X-Requested-With": "x"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "secure" not in r.headers["set-cookie"].lower()  # plain http in tests ("auto")
    assert anon.get("/api/experiments").status_code == 200
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert anon.post("/api/auth/logout", headers={"X-Requested-With": "x"}).status_code == 200
    assert anon.get("/api/experiments").status_code == 401


def test_users_only_see_their_own_data(client):
    d = client.post("/api/experiments", json={"title": "Mine"}).json()
    eid, sid = d["experiment"]["id"], d["steps"][0]["id"]
    rid = client.post(f"/api/experiments/{eid}/reagents", json={"query": "benzyl alcohol", "role": "product",
                                                                "actual_mass_g": 1.0}).json()["reagent_id"]
    pid = client.post("/api/projects", json={"title": "My route", "experiment_ids": [eid]}).json()["project"]["id"]
    f = other(client)
    assert f.get("/api/experiments").json()["experiments"] == []
    assert f.get("/api/projects").json()["projects"] == []
    for method, path, body in [("GET", f"/api/experiments/{eid}", None), ("PUT", f"/api/experiments/{eid}", {"title": "x"}),
                               ("DELETE", f"/api/experiments/{eid}", None), ("PUT", f"/api/reagents/{rid}", {"name": "x"}),
                               ("GET", f"/api/reagents/{rid}/structure.svg", None),
                               ("POST", f"/api/steps/{sid}/conditions", {"temperature": "0"}),
                               ("GET", f"/api/experiments/{eid}/report.md", None), ("GET", f"/api/projects/{pid}", None),
                               ("POST", f"/api/reagents/{rid}/branch", {}),
                               ("POST", f"/api/experiments/{eid}/duplicate", None)]:
        assert f.request(method, path, json=body).status_code == 404, (method, path)
    # cannot link to or find someone else's product
    mine = f.post("/api/experiments", json={"title": "Friend's"}).json()["experiment"]["id"]
    assert f.post(f"/api/experiments/{mine}/reagents", json={"source_reagent_id": rid}).status_code == 404
    assert f.get("/api/products", params={"q": "benzyl"}).json()["products"] == []
    assert f.post("/api/projects", json={"title": "x", "experiment_ids": [eid]}).status_code == 404
    # the friend's own work gets their name as author; the admin does not see it in their list
    assert f.get(f"/api/experiments/{mine}").json()["experiment"]["author"] == "Friend"  # their own name
    assert [e["id"] for e in client.get("/api/experiments").json()["experiments"]] == [eid]


def test_throttling_and_disabled_accounts(client):
    anon = TestClient(client.app, headers={"X-Requested-With": "x"})
    client.app.state.auth.create_user("bob", PW)
    for _ in range(8):
        assert anon.post("/api/auth/login", json={"username": "bob", "password": "wrong password!"}).status_code == 401
    r = anon.post("/api/auth/login", json={"username": "bob", "password": PW})
    assert r.status_code == 429 and "Too many" in r.json()["detail"]
    f = other(client, "carol")
    uid = next(u["id"] for u in client.get("/api/admin/overview").json()["users"] if u["username"] == "carol")
    assert client.put(f"/api/admin/users/{uid}", json={"active": False}).status_code == 200
    assert f.get("/api/experiments").status_code == 401  # signed out everywhere
    r = TestClient(client.app, headers={"X-Requested-With": "x"}).post(
        "/api/auth/login", json={"username": "carol", "password": PW})
    assert r.status_code == 403 and "disabled" in r.json()["detail"]


def test_invites_demo_limits_and_expiry(client):
    inv = client.post("/api/admin/invites", json={"note": "for Sam", "demo": True, "max_experiments": 2,
                                                  "account_days": 14, "valid_days": 3}).json()
    anon = TestClient(client.app, headers={"X-Requested-With": "x"})
    assert anon.get(f"/api/auth/invite/{inv['token']}").json()["max_experiments"] == 2
    assert anon.post(f"/api/auth/invite/{inv['token']}", json={"username": "sam", "password": "short"}).status_code == 400
    r = anon.post(f"/api/auth/invite/{inv['token']}", json={"username": "sam", "password": PW, "display_name": "Sam"})
    assert r.status_code == 200 and r.json()["user"]["demo"] is True and r.json()["user"]["expires_at"]
    assert anon.get(f"/api/auth/invite/{inv['token']}").status_code == 404  # one use only
    assert anon.post("/api/experiments", json={}).status_code == 201
    assert anon.post("/api/experiments", json={}).status_code == 201
    r = anon.post("/api/experiments", json={})
    assert r.status_code == 403 and "limited to 2" in r.json()["detail"]
    ov = client.get("/api/admin/overview").json()
    sam = next(u for u in ov["users"] if u["username"] == "sam")
    assert sam["n_experiments"] == 2 and ov["invites"][0]["status"] == "used" and ov["invites"][0]["used_by"] == "sam"
    # reset the demo data, then let the account expire
    assert client.post(f"/api/admin/users/{sam['id']}/reset").status_code == 200
    assert anon.get("/api/experiments").json()["experiments"] == []
    assert client.put(f"/api/admin/users/{sam['id']}", json={"expires_at": "2020-01-01"}).status_code == 200
    assert anon.get("/api/experiments").status_code == 401


def test_admin_routes(client):
    f = other(client)
    assert f.get("/api/admin/overview").status_code == 403
    assert f.post("/api/admin/invites", json={}).status_code == 403
    r = client.post("/api/admin/users", json={"username": "dana", "password": PW, "display_name": "Dana",
                                              "demo": True, "max_experiments": 5, "expires_at": "2099-01-31"})
    assert r.status_code == 201 and r.json()["user"]["max_experiments"] == 5
    assert client.post("/api/admin/users", json={"username": "dana", "password": PW}).status_code == 409
    dana = r.json()["user"]["id"]
    assert client.post(f"/api/admin/users/{dana}/password", json={"password": "another long password"}).status_code == 200
    me = client.get("/api/auth/state").json()["user"]
    assert client.delete(f"/api/admin/users/{me['id']}").status_code == 400            # not yourself
    assert client.put(f"/api/admin/users/{me['id']}", json={"role": "user"}).status_code == 400  # last admin
    f.post("/api/experiments", json={"title": "Friend's work"})
    fid = next(u["id"] for u in client.get("/api/admin/overview").json()["users"] if u["username"] == "friend")
    exp = client.get(f"/api/admin/users/{fid}/export.json").json()
    assert exp["experiments"][0]["experiment"]["title"] == "Friend's work"
    backup = client.get("/api/admin/backup.sqlite")
    assert backup.status_code == 200 and backup.content.startswith(b"SQLite format 3")
    assert client.delete(f"/api/admin/users/{dana}").status_code == 204
    # changing your own password signs out your other sessions
    assert client.post("/api/auth/password", json={"current": "nope", "new": PW}).status_code == 403
    assert f.post("/api/auth/password", json={"current": PW, "new": "a new long password"}).status_code == 200


def test_first_start_setup_code(tmp_path, capsys):
    from conftest import mock_pubchem
    import httpx
    from labnotebook.app import create_app
    from labnotebook.config import Settings
    from labnotebook.pubchem import PubChemClient
    # an old single-user notebook: its data goes to the admin created at setup
    from labnotebook import db
    store = db.Store(tmp_path / "notebook.sqlite")
    old = store.create_experiment({"title": "Before accounts"})
    app = create_app(Settings(data_dir=tmp_path, pubchem_url="http://pubchem.test", pubchem_timeout=2,
                              lab_name="", author=""),
                     PubChemClient("http://pubchem.test", transport=httpx.MockTransport(mock_pubchem)))
    code = app.state.auth.setup_code
    assert code and code in capsys.readouterr().out
    c = TestClient(app, headers={"X-Requested-With": "x"})
    assert c.get("/api/auth/state").json()["setup_needed"] is True
    assert c.post("/api/auth/setup", json={"code": "WRONG", "username": "boss", "password": PW}).status_code == 403
    r = c.post("/api/auth/setup", json={"code": code, "username": "boss", "password": PW, "display_name": "Boss"})
    assert r.status_code == 200 and r.json()["user"]["is_admin"]
    assert [e["id"] for e in c.get("/api/experiments").json()["experiments"]] == [old]
    assert c.post("/api/auth/setup", json={"code": code, "username": "x", "password": PW}).status_code == 409
    with sqlite3.connect(tmp_path / "notebook.sqlite") as con:
        assert con.execute("SELECT password_hash FROM users").fetchone()[0].startswith("scrypt$")


def test_markdown_in_reports_is_safe(client):
    eid = client.post("/api/experiments", json={"title": "x", "objective": "<script>alert(1)</script> "
                                                "[click](javascript:alert(1))"}).json()["experiment"]["id"]
    html = client.get(f"/api/experiments/{eid}/report.html").text
    assert "<script>alert" not in html and "javascript:" not in html and "&lt;script&gt;" in html
