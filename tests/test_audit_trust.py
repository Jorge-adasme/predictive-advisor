from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from advisor.api.app import app
from advisor.config import Settings
from advisor.portfolio.audit import AuditLog, PerformanceStats, SystemStatus

client = TestClient(app)


def test_audit_log_roundtrip(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    log = AuditLog(settings, path=tmp_path / "audit_log.jsonl")
    row = log.record("analyze", summary="test", payload={"n": 1}, source="unit")
    assert row["event"] == "analyze"
    rows = log.list_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["summary"] == "test"


def test_performance_stats_empty():
    stats = PerformanceStats().from_portfolio(
        {
            "equity": 10000,
            "equity_start": 10000,
            "daily_pnl": 0,
            "total_pnl": 0,
            "positions": {},
            "closed": [],
            "open_positions": 0,
            "halted": False,
        }
    )
    assert stats["n_closed"] == 0
    assert stats["win_rate"] == 0
    assert stats["exposure_pct"] == 0


def test_performance_stats_with_trades():
    stats = PerformanceStats().from_portfolio(
        {
            "equity": 11000,
            "equity_start": 10000,
            "daily_pnl": -50,
            "total_pnl": 1000,
            "open_positions": 1,
            "halted": False,
            "positions": {"AAPL": {"qty": 10, "last_price": 100, "sector": "Tech"}},
            "closed": [
                {"pnl": 200},
                {"pnl": -50},
                {"pnl": 100},
            ],
        }
    )
    assert stats["n_closed"] == 3
    assert abs(stats["win_rate"] - (2 / 3)) < 1e-3
    assert stats["expectancy"] != 0
    assert stats["sectors"]["Tech"] == 1


def test_system_status_ready():
    status = SystemStatus().build({"halted": False, "halt_reason": ""})
    assert "checks" in status
    assert status["version"] == "0.4.0"
    assert "disclaimer" in status


def test_api_system_audit_performance():
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["version"] == "0.4.0"

    s = client.get("/system/status?mode=paper")
    assert s.status_code == 200
    assert "checks" in s.json()

    p = client.get("/performance?mode=paper")
    assert p.status_code == 200
    assert "stats" in p.json()

    a = client.get("/audit?limit=10")
    assert a.status_code == 200
    assert "events" in a.json()


def test_dashboard_trust_fields():
    r = client.get("/dashboard?mode=paper")
    assert r.status_code == 200
    body = r.json()
    assert "performance" in body
    assert "system" in body
    assert "audit" in body
    assert "disclaimer" in body
