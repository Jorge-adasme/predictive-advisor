from __future__ import annotations

import json
from pathlib import Path

from advisor.models import SymbolInfo


def load_universe(path: Path) -> tuple[str, list[SymbolInfo]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = [SymbolInfo(**item) for item in payload["symbols"]]
    return payload["benchmark"], symbols
