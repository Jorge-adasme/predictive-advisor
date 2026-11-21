from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from advisor.models import JournalEntry, Recommendation


class JournalStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _read(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def record_decision(
        self,
        recommendation: Recommendation,
        decision: str,
        outcome_note: str = "",
    ) -> JournalEntry:
        entry = JournalEntry(
            ts=datetime.now(timezone.utc),
            ticker=recommendation.prediction.ticker,
            decision=decision,
            recommendation=recommendation.model_dump(mode="json"),
            outcome_note=outcome_note,
        )
        rows = self._read()
        rows.append(entry.model_dump(mode="json"))
        self._write(rows)
        return entry

    def list_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._read()
        return rows[-limit:]
