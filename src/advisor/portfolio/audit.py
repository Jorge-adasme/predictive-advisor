from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from advisor.config import Settings, get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    """Bitácora append-only de eventos del sistema (confianza / compliance)."""

    def __init__(self, settings: Settings | None = None, path: Path | None = None):
        self.settings = settings or get_settings()
        self.path = path or (self.settings.data_dir / "audit_log.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def record(
        self,
        event: str,
        *,
        level: str = "info",
        summary: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "system",
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "ts": _now(),
            "event": event,
            "level": level,
            "source": source,
            "summary": summary,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return row

    def list_events(self, limit: int = 100, event: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if event and row.get("event") != event:
                    continue
                rows.append(row)
        return rows[-limit:]


class PerformanceStats:
    """Métricas simples de confiabilidad del paper/live local."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def from_portfolio(self, portfolio: dict[str, Any]) -> dict[str, Any]:
        closed = list(portfolio.get("closed") or [])
        pnls = [float(c.get("pnl") or 0) for c in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        n = len(pnls)
        win_rate = (len(wins) / n) if n else 0.0
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss) if n else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        equity = float(portfolio.get("equity") or 0)
        start = float(portfolio.get("equity_start") or equity or 1)
        total_return = ((equity / start) - 1.0) if start else 0.0
        daily = float(portfolio.get("daily_pnl") or 0)
        max_daily = float(self.settings.max_daily_loss_pct)
        daily_budget_left = max(0.0, (equity * max_daily) + daily) if equity else 0.0

        positions = portfolio.get("positions") or {}
        sectors: dict[str, int] = {}
        for t, p in positions.items():
            sec = str(p.get("sector") or "Unknown")
            sectors[sec] = sectors.get(sec, 0) + 1

        exposure = 0.0
        for p in positions.values():
            exposure += float(p.get("qty") or 0) * float(p.get("last_price") or p.get("entry_price") or 0)
        exposure_pct = (exposure / equity) if equity else 0.0

        return {
            "n_closed": n,
            "n_open": int(portfolio.get("open_positions") or len(positions)),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "profit_factor": round(min(profit_factor, 99.0), 2),
            "total_pnl": round(float(portfolio.get("total_pnl") or 0), 2),
            "total_return_pct": round(total_return, 4),
            "daily_pnl": round(daily, 2),
            "daily_loss_budget_left": round(daily_budget_left, 2),
            "max_daily_loss_pct": max_daily,
            "exposure_pct": round(exposure_pct, 4),
            "max_positions": self.settings.max_positions,
            "sectors": sectors,
            "halted": bool(portfolio.get("halted")),
            "as_of": _now(),
        }


class SystemStatus:
    """Checklist de preparación del sistema (confianza operativa)."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def build(self, portfolio: dict[str, Any] | None = None) -> dict[str, Any]:
        s = self.settings
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str, critical: bool = False) -> None:
            checks.append(
                {
                    "name": name,
                    "ok": ok,
                    "detail": detail,
                    "critical": critical,
                }
            )

        add(
            "config",
            True,
            f"broker={s.broker} · currency={s.base_currency} · horizon={s.horizon_days}d",
        )
        alpaca_keys = bool(s.alpaca_api_key and s.alpaca_secret_key)
        add(
            "alpaca_keys",
            alpaca_keys or s.broker != "alpaca",
            "API keys configuradas" if alpaca_keys else "Faltan ADVISOR_ALPACA_* (paper local OK)",
            critical=s.broker == "alpaca",
        )
        add(
            "ai_layer",
            bool(s.ai_enabled),
            f"provider={s.ai_provider} · gate={s.ai_gate_autopilot}",
        )
        add(
            "news",
            bool(s.news_enabled),
            f"lookback={s.news_lookback_days}d · weight={s.news_weight}",
        )
        add(
            "earnings_blackout",
            bool(s.earnings_enabled),
            f"before={s.earnings_blackout_before} · after={s.earnings_blackout_after}",
        )
        add(
            "risk_limits",
            True,
            (
                f"risk/trade={s.risk_per_trade:.2%} · max_pos={s.max_positions} · "
                f"daily_loss={s.max_daily_loss_pct:.0%} · min_edge={s.min_edge_net_pct:.2%}"
            ),
        )

        halted = bool((portfolio or {}).get("halted"))
        add(
            "kill_switch",
            not halted,
            (portfolio or {}).get("halt_reason") or "Operativo",
            critical=True,
        )

        # Freshness of news cache
        news_age = None
        news_path = s.data_dir / "news_cache.json"
        if news_path.exists():
            try:
                raw = json.loads(news_path.read_text(encoding="utf-8"))
                ts = raw.get("ts") or raw.get("as_of") or raw.get("cached_at")
                if ts:
                    news_age = ts
            except Exception:
                pass
        add(
            "news_cache",
            news_path.exists(),
            f"última={news_age or 'sin cache'}",
        )

        audit = AuditLog(s)
        last_events = audit.list_events(limit=5)
        add(
            "audit_log",
            True,
            f"{len(audit.list_events(limit=10_000))} eventos · último={last_events[-1]['event'] if last_events else '—'}",
        )
        add(
            "live_feed",
            bool(getattr(s, "live_enabled", True)),
            f"poll={getattr(s, 'live_poll_sec', 8)}s · analyze={getattr(s, 'live_analyze_sec', 120)}s",
        )

        critical_fail = [c for c in checks if c["critical"] and not c["ok"]]
        ready = len(critical_fail) == 0
        return {
            "ready": ready,
            "mode": "paper" if not alpaca_keys else ("alpaca_paper" if s.alpaca_paper else "alpaca_live"),
            "paper_trading": bool(s.alpaca_paper) or not alpaca_keys,
            "disclaimer": (
                "Herramienta de apoyo a la decisión. No es asesoría financiera regulada. "
                "No garantiza rentabilidad. Opera primero en paper."
            ),
            "version": "0.4.0",
            "checks": checks,
            "last_audit": last_events[-3:] if last_events else [],
            "as_of": _now(),
        }
