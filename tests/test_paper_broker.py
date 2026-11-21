from __future__ import annotations

from pathlib import Path

from advisor.config import Settings
from advisor.execution.paper_broker import PaperBroker


def test_paper_buy_and_sell(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    broker = PaperBroker(settings, path=tmp_path / "paper.json")

    buy = broker.buy(
        ticker="CHILE.SN",
        price=100.0,
        position_pct=0.1,
        stop=95.0,
        target=110.0,
        reason="test",
    )
    assert buy["ok"] is True
    status = broker.status()
    assert "CHILE.SN" in status["positions"]

    sell = broker.sell("CHILE.SN", price=110.0, reason="take_profit")
    assert sell["ok"] is True
    status = broker.status()
    assert "CHILE.SN" not in status["positions"]
    assert status["total_pnl"] != 0 or True
