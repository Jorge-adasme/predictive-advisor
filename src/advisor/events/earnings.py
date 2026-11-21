from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from advisor.config import Settings, get_settings


@dataclass
class EarningsInfo:
    ticker: str
    next_earnings: str | None
    days_to_earnings: float | None
    in_blackout: bool
    blackout_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EarningsCalendar:
    """Calendario de earnings (Yahoo) + ventana de blackout."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache_path = self.settings.data_dir / "earnings_cache.json"
        self.ttl_sec = int(getattr(self.settings, "earnings_cache_ttl_sec", 43200))
        self.before = int(getattr(self.settings, "earnings_blackout_before", 2))
        self.after = int(getattr(self.settings, "earnings_blackout_after", 1))

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(payload["as_of"])
            if (datetime.now(timezone.utc) - ts).total_seconds() <= self.ttl_sec:
                return payload
        except Exception:
            return None
        return None

    def _write_cache(self, rows: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"as_of": datetime.now(timezone.utc).isoformat(), "tickers": rows}
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fetch_next_date(self, ticker: str) -> datetime | None:
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            # Prefer get_earnings_dates
            try:
                df = t.get_earnings_dates(limit=8)
            except Exception:
                df = None
            now = datetime.now(timezone.utc)
            if df is not None and not df.empty:
                idx = df.index
                dates: list[datetime] = []
                for d in idx:
                    ts = pd_to_utc(d)
                    if ts is not None:
                        dates.append(ts)
                future = [d for d in dates if d >= now - timedelta(days=self.after)]
                if future:
                    return min(future)
                if dates:
                    return max(dates)

            cal = getattr(t, "calendar", None)
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date") or cal.get("earningsDate")
                if isinstance(raw, (list, tuple)) and raw:
                    return pd_to_utc(raw[0])
        except Exception:
            return None
        return None

    def snapshot(self, tickers: Iterable[str], use_cache: bool = True) -> dict[str, EarningsInfo]:
        tickers_list = list(dict.fromkeys(tickers))
        cached_rows: dict[str, Any] = {}
        if use_cache:
            cached = self._read_cache()
            if cached:
                cached_rows = cached.get("tickers") or {}

        now = datetime.now(timezone.utc)
        out: dict[str, EarningsInfo] = {}
        fresh: dict[str, Any] = dict(cached_rows)

        skip = {"SPY", "QQQ", "IWM", "DIA", "VTI", "VOO"}
        for ticker in tickers_list:
            if ticker in skip:
                out[ticker] = EarningsInfo(
                    ticker=ticker,
                    next_earnings=None,
                    days_to_earnings=None,
                    in_blackout=False,
                    blackout_reason="ETF: sin earnings",
                )
                continue
            next_dt = None
            if ticker in cached_rows and cached_rows[ticker].get("next_earnings"):
                next_dt = datetime.fromisoformat(cached_rows[ticker]["next_earnings"])
            else:
                next_dt = self._fetch_next_date(ticker)
                fresh[ticker] = {
                    "next_earnings": next_dt.isoformat() if next_dt else None,
                }

            if next_dt is None:
                out[ticker] = EarningsInfo(
                    ticker=ticker,
                    next_earnings=None,
                    days_to_earnings=None,
                    in_blackout=False,
                )
                continue

            delta_days = (next_dt - now).total_seconds() / 86400.0
            in_before = 0 <= delta_days <= self.before
            in_after = -self.after <= delta_days < 0
            in_blackout = in_before or in_after
            reason = ""
            if in_before:
                reason = f"Earnings en {delta_days:.1f}d (blackout −{self.before}d)."
            elif in_after:
                reason = f"Earnings hace {-delta_days:.1f}d (blackout +{self.after}d)."

            out[ticker] = EarningsInfo(
                ticker=ticker,
                next_earnings=next_dt.isoformat(),
                days_to_earnings=float(delta_days),
                in_blackout=in_blackout,
                blackout_reason=reason,
            )

        self._write_cache(fresh)
        return out


def pd_to_utc(value: Any) -> datetime | None:
    try:
        import pandas as pd

        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        try:
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        return None
