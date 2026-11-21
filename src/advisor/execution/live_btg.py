from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from advisor.config import Settings


@dataclass
class LiveGate:
    enabled: bool
    reason: str
    next_steps: list[str]


class BTGLiveExecutor:
    """Ejecutor live BTG Chile.

    Bloqueado hasta que exista credencial/API oficial (DMA/partner).
    No usa scrapers ni APIs no oficiales del Home Broker.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def gate(self) -> LiveGate:
        token = getattr(self.settings, "btg_live_token", "") or ""
        account = getattr(self.settings, "btg_account_id", "") or ""
        enabled_flag = bool(getattr(self.settings, "btg_live_enabled", False))

        if not enabled_flag:
            return LiveGate(
                enabled=False,
                reason="BTG live deshabilitado. Falta autorización/API oficial.",
                next_steps=[
                    "Abrir/fondear cuenta en BTG Inversiones Digitales",
                    "Solicitar a BTG acceso DMA/API de ruteo de órdenes",
                    "Recibir credenciales sandbox + producción",
                    "Configurar ADVISOR_BTG_LIVE_ENABLED=true y token/cuenta",
                    "Activar live con capital pequeño y kill-switch",
                ],
            )

        if not token or not account:
            return LiveGate(
                enabled=False,
                reason="Faltan ADVISOR_BTG_LIVE_TOKEN / ADVISOR_BTG_ACCOUNT_ID",
                next_steps=[
                    "Pedir a BTG las credenciales de ejecución",
                    "Cargarlas en variables de entorno",
                    "Probar primero en sandbox",
                ],
            )

        return LiveGate(
            enabled=True,
            reason="Credenciales presentes (adapter listo para integración real).",
            next_steps=["Implementar endpoint oficial entregado por BTG"],
        )

    def place_order(self, plan: dict[str, Any]) -> dict[str, Any]:
        status = self.gate()
        if not status.enabled:
            return {
                "ok": False,
                "mode": "live_btg",
                "blocked": True,
                "reason": status.reason,
                "next_steps": status.next_steps,
                "order_draft": plan,
            }

        # Placeholder: aquí irá el cliente oficial FIX/REST que entregue BTG.
        return {
            "ok": False,
            "mode": "live_btg",
            "blocked": True,
            "reason": (
                "Credenciales marcadas, pero el conector oficial BTG Chile "
                "aún no fue entregado/implementado."
            ),
            "next_steps": status.next_steps,
            "order_draft": plan,
        }
