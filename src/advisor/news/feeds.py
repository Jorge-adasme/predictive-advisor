from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

import httpx

RSS_FEEDS = [
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC Top", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("CNBC World", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Fed Press", "https://www.federalreserve.gov/feeds/press_all.xml"),
]


@dataclass
class RawHeadline:
    title: str
    summary: str
    source: str
    url: str
    published: datetime | None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
        except Exception:
            return None


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_rss(xml_text: str, source: str) -> list[RawHeadline]:
    out: list[RawHeadline] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out

    items = [el for el in root.iter() if _local(el.tag) in {"item", "entry"}]
    for item in items[:25]:
        title = ""
        summary = ""
        link = ""
        published = None
        for child in list(item):
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                title = text
            elif name in {"description", "summary", "content"}:
                summary = re_strip_html(text)
            elif name == "link":
                link = text or (child.attrib.get("href") or link)
            elif name in {"pubDate", "published", "updated", "date"}:
                published = _parse_date(text) or published
        if title:
            out.append(
                RawHeadline(
                    title=title,
                    summary=summary,
                    source=source,
                    url=link,
                    published=published,
                )
            )
    return out


def re_strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def fetch_rss_headlines(timeout: float = 8.0) -> list[RawHeadline]:
    headlines: list[RawHeadline] = []
    headers = {"User-Agent": "predictive-advisor/0.2 (+research; non-commercial)"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for source, url in RSS_FEEDS:
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                headlines.extend(parse_rss(resp.text, source))
            except Exception:
                continue
    return headlines


def fetch_yahoo_ticker_news(tickers: Iterable[str], limit_per: int = 4) -> list[RawHeadline]:
    """Noticias por ticker vía yfinance (best-effort)."""
    out: list[RawHeadline] = []
    try:
        import yfinance as yf
    except Exception:
        return out

    for ticker in list(tickers)[:20]:
        try:
            items = yf.Ticker(ticker).news or []
        except Exception:
            continue
        for item in items[:limit_per]:
            content = item.get("content") if isinstance(item.get("content"), dict) else {}
            title = (
                item.get("title")
                or content.get("title")
                or ""
            )
            summary = item.get("summary") or content.get("summary") or ""
            link = ""
            if isinstance(item.get("link"), str):
                link = item["link"]
            elif isinstance(content.get("clickThroughUrl"), dict):
                link = content["clickThroughUrl"].get("url") or ""
            pub = None
            ts = item.get("providerPublishTime") or content.get("pubDate")
            if isinstance(ts, (int, float)):
                pub = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                pub = _parse_date(ts)
            if title:
                out.append(
                    RawHeadline(
                        title=f"[{ticker}] {title}",
                        summary=str(summary),
                        source=f"Yahoo:{ticker}",
                        url=str(link),
                        published=pub,
                    )
                )
    return out
