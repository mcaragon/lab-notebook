"""Problem reports sent from the app: stored in the notebook, read by admins, replies shown to the reporter."""
import base64

from fastapi.testclient import TestClient

from test_auth import other

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def test_report_flow(client):
    f = other(client)
    body = {"kind": "bug", "title": "Yield stays at 0%", "body": "After weighing the product the yield is 0.",
            "steps": "1. Bench\n2. Product mass 0.9 g", "expected": "About 85%", "page": "#/exp/3/results",
            "version": "0.7.2", "user_agent": "Firefox", "screen": "390×844", "theme": "dark",
            "screenshot": f"data:image/png;base64,{PNG}"}
    r = f.post("/api/feedback", json=body)
    assert r.status_code == 201
    fid = r.json()["id"]
    # the admin sees it, with who sent it and the device details
    assert client.get("/api/feedback/unseen").json()["new_reports"] == 1
    inbox = client.get("/api/admin/feedback").json()
    (rep,) = inbox["reports"]
    assert rep["username"] == "friend" and rep["user_agent"] == "Firefox" and rep["has_image"]
    assert inbox["counts"]["new"] == 1
    shot = client.get(f"/api/feedback/{fid}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"
    # other users see neither the report nor its screenshot; only admins reach the inbox
    stranger = other(client, "stranger")
    assert stranger.get(f"/api/feedback/{fid}/screenshot").status_code == 404
    assert stranger.get("/api/feedback/mine").json()["reports"] == []
    assert f.get("/api/admin/feedback").status_code == 403
    # the admin replies and resolves it; the reporter sees the reply once
    d = client.put(f"/api/admin/feedback/{fid}", json={"status": "resolved", "reply": "Fixed in 0.7.3, thanks!"}).json()
    assert d["report"]["status"] == "resolved" and d["counts"]["resolved"] == 1
    assert f.get("/api/feedback/unseen").json() == {"replies": 1}
    mine = f.get("/api/feedback/mine").json()["reports"]
    assert mine[0]["reply"] == "Fixed in 0.7.3, thanks!" and "user_agent" not in mine[0]
    assert f.get("/api/feedback/unseen").json() == {"replies": 0}
    assert client.get("/api/admin/feedback", params={"status": "active"}).json()["reports"] == []
    assert client.delete(f"/api/admin/feedback/{fid}").status_code == 204
    assert f.get("/api/feedback/mine").json()["reports"] == []


def test_report_validation(client):
    assert client.post("/api/feedback", json={"title": "", "body": "x"}).status_code == 400
    assert client.post("/api/feedback", json={"title": "x", "body": "y", "kind": "spam"}).status_code == 422
    fake = base64.b64encode(b"<svg onload=alert(1)>").decode()
    r = client.post("/api/feedback", json={"title": "x", "body": "y", "screenshot": f"data:image/png;base64,{fake}"})
    assert r.status_code == 400  # content is checked, not just the declared type
    r = client.post("/api/feedback", json={"title": "x", "body": "y", "screenshot": "data:image/svg+xml;base64,PHN2Zz4="})
    assert r.status_code == 400
    assert TestClient(client.app, headers={"X-Requested-With": "x"}).post(
        "/api/feedback", json={"title": "x", "body": "y"}).status_code == 401
    for _ in range(25):
        assert client.post("/api/feedback", json={"title": "x", "body": "y"}).status_code == 201
    assert client.post("/api/feedback", json={"title": "x", "body": "y"}).status_code == 429
