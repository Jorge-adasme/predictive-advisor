from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from advisor.config import Settings


class TrailStore:
    """Estado local de stops para brokers que no persisten trailing (Alpaca)."""

    def __init__(self, settings: Settings, path: Path | None = None):
        self.path = path or (settings.data_dir / "trail_stops.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def upsert(
        self,
        ticker: str,
        *,
        entry: float,
        stop: float,
        initial_stop: float,
        target: float,
        horizon_days: int = 10,
        sector: str = "Unknown",
    ) -> None:
        data = self._read()
        data[ticker] = {
            "entry": float(entry),
            "stop": float(stop),
            "initial_stop": float(initial_stop),
            "target": float(target),
            "trail_event": "",
            "partial_taken": False,
            "horizon_days": int(horizon_days),
            "sector": sector or "Unknown",
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(data)

    def get(self, ticker: str) -> dict[str, Any] | None:
        return self._read().get(ticker)

    def sector_of(self, ticker: str) -> str | None:
        row = self.get(ticker)
        return None if not row else row.get("sector")

    def update_stop(self, ticker: str, stop: float, event: str = "") -> None:
        data = self._read()
        row = data.get(ticker)
        if not row:
            return
        if float(stop) > float(row.get("stop") or 0):
            row["stop"] = float(stop)
            if event:
                row["trail_event"] = event
            self._write(data)

    def mark_partial(self, ticker: str) -> None:
        data = self._read()
        row = data.get(ticker)
        if not row:
            return
        row["partial_taken"] = True
        self._write(data)

    def remove(self, ticker: str) -> None:
        data = self._read()
        if ticker in data:
            del data[ticker]
            self._write(data)

    def all(self) -> dict[str, Any]:
        return self._read()
