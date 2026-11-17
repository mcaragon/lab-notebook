import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from labnotebook.app import create_app
from labnotebook.config import Settings
from labnotebook.pubchem import PubChemClient

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN_PASSWORD = "correct horse battery"
RECORDED = json.loads((FIXTURES / "pubchem.json").read_text())


def mock_pubchem(request: httpx.Request) -> httpx.Response:
    """Serves recorded PubChem Local responses."""
    path, q = request.url.path, request.url.params
    if path == "/api/health":
        return httpx.Response(200, json=RECORDED["health"])
    if path == "/api/lookup":
        rec = RECORDED.get("lookup:" + q["q"].lower())
        return httpx.Response(200, json=rec) if rec else httpx.Response(404, json={"detail": "Not found"})
    if path == "/api/autocomplete":
        return httpx.Response(200, json=RECORDED["autocomplete:benz"])
    if path.startswith("/api/compound/"):
        parts = path.split("/")
        cid = parts[3]
        if path.endswith("/safety-summary"):
            rec = RECORDED.get("safety:" + cid)
            return httpx.Response(200, json=rec) if rec else httpx.Response(404)
        if path.endswith("/lab"):
            rec = RECORDED.get("lab:" + cid)
            return httpx.Response(200, json=rec) if rec else httpx.Response(404)
        if path.endswith("/structure.svg"):
            return httpx.Response(200, content=(FIXTURES / "structure_240.svg").read_bytes(),
                                  headers={"content-type": "image/svg+xml"})
        rec = RECORDED.get("compound:" + cid)
        return httpx.Response(200, json=rec) if rec else httpx.Response(404)
    if path.startswith("/static/ghs/"):
        return httpx.Response(200, content=(FIXTURES / "GHS07.svg").read_bytes(),
                              headers={"content-type": "image/svg+xml"})
    return httpx.Response(404)


def offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _client(tmp_path, handler):
    settings = Settings(data_dir=tmp_path, pubchem_url="http://pubchem.test", pubchem_timeout=2, lab_name="Test Lab",
                        author="A. Chemist")
    pc = PubChemClient(settings.pubchem_url, transport=httpx.MockTransport(handler))
    app = create_app(settings, pc)
    if not app.state.auth.has_users():
        app.state.auth.create_user("admin", ADMIN_PASSWORD, "A. Admin", role="admin")
    c = TestClient(app, headers={"X-Requested-With": "test"})
    assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
    return c


@pytest.fixture
def client(tmp_path):
    return _client(tmp_path, mock_pubchem)


@pytest.fixture
def offline_client(tmp_path):
    return _client(tmp_path, offline)
