from __future__ import annotations

from fastapi.testclient import TestClient

from advisor.api.app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_btg_status():
    response = client.get("/btg/status")
    assert response.status_code == 200
    body = response.json()
    assert "orders" in body


def test_dashboard():
    response = client.get("/dashboard?mode=paper")
    assert response.status_code == 200
    body = response.json()
    assert "headline" in body
    assert "positions" in body
    assert "movements" in body
