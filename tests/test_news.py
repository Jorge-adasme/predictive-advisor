from __future__ import annotations

from advisor.news.feeds import parse_rss
from advisor.news.sentiment import (
    detect_sectors,
    detect_tickers,
    is_governance_risk,
    score_text,
    urgency_score,
)
from advisor.news.engine import NewsPulse


def test_score_text_positive_and_negative():
    assert score_text("Markets rally on strong growth and rate cut hopes") > 0
    assert score_text("War fears and crash panic hit stocks") < 0
    # no false positive: war⊂forward, miss⊂dismissed
    assert abs(score_text("Looking forward after the analyst dismissed rumors")) < 0.35


def test_urgency_and_sectors():
    assert urgency_score("Breaking: emergency default risk") > 0
    secs = detect_sectors("Oil and OPEC cut crude supply")
    assert "Energy" in secs


def test_detect_tickers():
    found = detect_tickers("Apple and Nvidia lead AI chip boom", universe=["AAPL", "NVDA", "JPM"])
    assert "AAPL" in found and "NVDA" in found


def test_parse_rss_basic():
    xml = """<?xml version='1.0'?>
    <rss><channel>
      <item>
        <title>Fed signals rate cut</title>
        <description>Markets rally on dovish tone</description>
        <link>https://example.com/1</link>
        <pubDate>Tue, 18 Nov 2025 12:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    items = parse_rss(xml, "Test")
    assert len(items) == 1
    assert "Fed" in items[0].title


def test_news_pulse_factor_blend():
    pulse = NewsPulse(
        as_of="2025-01-01T00:00:00+00:00",
        market_sentiment=0.2,
        market_urgency=0.1,
        regime_bias=0.1,
        by_sector={"Tech": 0.5},
        by_ticker={"AAPL": 0.8},
    )
    f = pulse.factor_for("AAPL", "Tech")
    assert f > 0.4


def test_governance_scandal_detected():
    assert is_governance_risk("NVIDIA CEO scandal and cheating allegations rock the company")
    assert score_text("CEO fraud investigation and lawsuit") < 0
