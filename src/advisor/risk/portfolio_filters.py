from __future__ import annotations

from typing import Iterable


def sector_capacity_ok(
    candidate_sector: str,
    open_sectors: Iterable[str],
    max_per_sector: int = 1,
) -> bool:
    """Evita saturar un sector (proxy de correlación)."""
    sector = (candidate_sector or "Unknown").strip() or "Unknown"
    count = sum(1 for s in open_sectors if (s or "Unknown") == sector)
    return count < max_per_sector


def select_diversified(
    candidates: list[tuple[dict, dict]],
    *,
    open_sectors: list[str] | None = None,
    max_positions: int,
    max_per_sector: int = 1,
) -> list[tuple[dict, dict]]:
    """candidates = [(prediction_dict, plan_dict), ...] ya rankeados."""
    open_secs = list(open_sectors or [])
    chosen: list[tuple[dict, dict]] = []
    for pred, plan in candidates:
        if len(chosen) >= max_positions:
            break
        sector = pred.get("sector") or "Unknown"
        trial_secs = open_secs + [p.get("sector") or "Unknown" for p, _ in chosen]
        if not sector_capacity_ok(sector, trial_secs, max_per_sector=max_per_sector):
            continue
        chosen.append((pred, plan))
    return chosen
