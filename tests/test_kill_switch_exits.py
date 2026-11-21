from __future__ import annotations

from advisor.config import Settings
from advisor.execution.autopilot import Autopilot


class _FakeBroker:
    def __init__(self):
        self.sold: list[tuple[str, str]] = []

    def sell(self, ticker, price, reason, fraction=1.0):
        self.sold.append((ticker, reason))
        return {"ok": True, "ticker": ticker, "price": price, "reason": reason}


class _FakeTrails:
    def remove(self, ticker):
        return None


def test_close_losers_only():
    settings = Settings(halt_close_losers=True, halt_flatten_all=False)
    bot = Autopilot(settings=settings, mode="paper")
    broker = _FakeBroker()
    bot.broker = broker
    bot.trails = _FakeTrails()

    portfolio = {
        "positions": {
            "LOSER": {"qty": 10, "entry_price": 100, "last_price": 90},
            "WINNER": {"qty": 5, "entry_price": 50, "last_price": 60},
        }
    }
    actions = bot._close_positions_for_kill_switch(
        portfolio, {"LOSER": 90.0, "WINNER": 60.0}, losers_only=True
    )
    assert len(actions) == 1
    assert actions[0]["ticker"] == "LOSER"
    assert broker.sold == [("LOSER", "kill_switch_loser")]


def test_flatten_all():
    settings = Settings(halt_flatten_all=True)
    bot = Autopilot(settings=settings, mode="paper")
    broker = _FakeBroker()
    bot.broker = broker
    bot.trails = _FakeTrails()

    portfolio = {
        "positions": {
            "A": {"qty": 1, "entry_price": 10, "last_price": 9},
            "B": {"qty": 1, "entry_price": 10, "last_price": 11},
        }
    }
    actions = bot._close_positions_for_kill_switch(
        portfolio, {}, losers_only=False
    )
    assert {a["ticker"] for a in actions} == {"A", "B"}
    assert all(r == "kill_switch_flatten" for _, r in broker.sold)
