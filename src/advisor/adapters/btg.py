from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BTGConnectionStatus:
    market_data: str
    portfolio: str
    orders: str
    notes: list[str]


class BTGChileAdapter:
    """Stub de integración BTG Chile.

    En Chile no hay API retail pública simple. Este adapter deja el contrato
    listo para partner oficial / SFA / ejecución asistida.
    """

    def status(self) -> BTGConnectionStatus:
        return BTGConnectionStatus(
            market_data="not_connected",
            portfolio="manual_or_sfa_pending",
            orders="draft_only",
            notes=[
                "Usar Yahoo/BCS data providers mientras se negocia acceso BTG.",
                "Portfolio: CSV/manual o Finanzas Abiertas cuando esté disponible.",
                "Orders: generar draft + aprobación humana (semi-auto).",
            ],
        )

    def create_order_draft(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "draft",
            "broker": "BTG_CHILE",
            "requires_approval": True,
            "payload": plan,
            "message": "Orden preparada. Ejecutar manualmente en BTG o vía partner API.",
        }
