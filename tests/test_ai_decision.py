from __future__ import annotations

from advisor.ai.decision_agent import DecisionAgent
from advisor.config import Settings


def _item(ticker="AAPL", action="buy", edge=0.01, score=0.5, prob=0.6, news=0.1):
    return {
        "prediction": {
            "ticker": ticker,
            "name": ticker,
            "sector": "Tech",
            "score": score,
            "probability_up": prob,
            "expected_return": edge + 0.001,
            "confidence": 0.6,
            "factors": {
                "news_factor": news,
                "meta_label_prob": 0.6,
                "ic_spearman": 0.05,
                "ir_proxy": 0.5,
                "earnings_blackout": 0.0,
            },
            "reasons": ["test"],
            "risks": [],
        },
        "plan": {
            "action": action,
            "edge_net_pct": edge,
            "position_pct": 0.05,
            "stop_pct": 0.02,
            "invalidation": "x",
        },
    }


def test_local_agent_approves_strong_buy():
    agent = DecisionAgent(Settings(ai_provider="local", ai_enabled=True))
    d = agent.decide(
        market={"regime": "risk_on", "regime_score": 1.0},
        news={"headlines": [], "ticker_stories": []},
        item=_item(),
    )
    assert d.action in {"buy", "hold"}
    assert d.provider == "local"
    assert d.ticker == "AAPL"


def test_local_agent_avoids_governance_shock():
    agent = DecisionAgent(Settings(ai_provider="local", ai_enabled=True))
    item = _item(ticker="NVDA", edge=0.004, score=0.2, prob=0.52, news=-0.55)
    news = {
        "ticker_stories": [
            {
                "ticker": "NVDA",
                "headline": "CEO scandal and cheating allegations",
                "governance": True,
                "factor": -0.55,
            }
        ]
    }
    d = agent.decide(market={"regime": "risk_off"}, news=news, item=item)
    assert d.action == "avoid"
    assert d.approve_trade is False
