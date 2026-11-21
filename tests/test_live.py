from __future__ import annotations

from fastapi.testclient import TestClient

from advisor.api.app import app
from advisor.api.live import live_snapshot

client = TestClient(app)


def test_live_snapshot_shape():
    snap = live_snapshot("paper", refresh_marks=False)
    assert snap["live"] is True
    assert "headline" in snap
    assert "positions" in snap
    assert "server_ts" in snap
    assert snap["poll_sec"] >= 3


def test_live_endpoint():
    res = client.get("/live?mode=paper&marks=false")
    assert res.status_code == 200
    body = res.json()
    assert body["live"] is True
    assert "equity" in body["headline"]
