from __future__ import annotations

from datetime import datetime, timezone

import httpx

from advisor.news.feeds import RawHeadline


def fetch_newsapi_headlines(
    api_key: str,
    *,
    query: str = (
        '(stocks OR equities OR "federal reserve" OR inflation OR recession '
        "OR tariffs OR geopolitics OR OPEC OR earnings)"
    ),
    page_size: int = 40,
    timeout: float = 10.0,
) -> list[RawHeadline]:
    """NewsAPI.org (opcional). Requiere ADVISOR_NEWSAPI_KEY."""
    if not api_key:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
    }
    headers = {"X-Api-Key": api_key}
    out: list[RawHeadline] = []
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(url, params=params)
            if resp.status_code != 200:
                return out
            payload = resp.json()
    except Exception:
        return out

    for art in payload.get("articles") or []:
        title = (art.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue
        summary = (art.get("description") or art.get("content") or "").strip()
        source = ((art.get("source") or {}).get("name")) or "NewsAPI"
        link = art.get("url") or ""
        published = None
        if art.get("publishedAt"):
            try:
                published = datetime.fromisoformat(
                    art["publishedAt"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except Exception:
                published = None
        out.append(
            RawHeadline(
                title=title,
                summary=summary,
                source=f"NewsAPI:{source}",
                url=link,
                published=published,
            )
        )
    return out
