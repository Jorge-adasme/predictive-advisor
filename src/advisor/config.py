from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_prefix="ADVISOR_",
        extra="ignore",
    )

    env: str = "dev"
    base_currency: str = "USD"
    broker: str = "alpaca"  # alpaca | local_paper | btg_stub

    risk_per_trade: float = Field(default=0.0075, ge=0.001, le=0.05)
    max_position_pct: float = Field(default=0.12, ge=0.01, le=0.5)
    max_daily_loss_pct: float = Field(default=0.02, ge=0.005, le=0.1)
    min_edge_net_pct: float = Field(default=0.002, ge=0.0, le=0.05)
    # Stop inicial mínimo / ATR
    min_stop_pct: float = Field(default=0.015, ge=0.005, le=0.08)
    atr_stop_mult: float = Field(default=2.0, ge=1.0, le=4.0)
    # Trailing: break-even a +1R, lock +1R al llegar a +2R
    breakeven_at_r: float = Field(default=1.0, ge=0.5, le=3.0)
    trail_at_r: float = Field(default=2.0, ge=1.0, le=5.0)
    trail_atr_mult: float = Field(default=2.0, ge=1.0, le=4.0)
    # Gestión avanzada de posición
    partial_tp_at_r: float = Field(default=1.5, ge=1.0, le=3.0)
    partial_tp_fraction: float = Field(default=0.5, ge=0.25, le=0.75)
    time_stop_frac: float = Field(default=0.7, ge=0.4, le=1.0)
    time_stop_min_r: float = Field(default=0.3, ge=0.0, le=1.0)
    max_positions: int = Field(default=4, ge=1, le=10)
    max_per_sector: int = Field(default=1, ge=1, le=3)

    # Alpaca default: commission-free equities + slippage model
    commission_rate: float = Field(default=0.0, ge=0.0, le=0.05)
    vat_rate: float = Field(default=0.0, ge=0.0, le=0.4)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=100.0)

    lookback_days: int = Field(default=420, ge=60, le=2000)
    horizon_days: int = Field(default=10, ge=1, le=60)
    top_n: int = Field(default=8, ge=1, le=30)

    data_dir: Path = ROOT_DIR / "data"
    universe_path: Path = ROOT_DIR / "configs" / "universe_alpaca_us.json"

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    # Live BTG (oficial). Por defecto OFF.
    btg_live_enabled: bool = False
    btg_account_id: str = ""
    btg_live_token: str = ""

    @property
    def round_trip_cost_pct(self) -> float:
        """Costo estimado ida y vuelta: comisión(+IVA) por lado + slippage."""
        commission_with_vat = self.commission_rate * (1 + self.vat_rate)
        slippage = self.slippage_bps / 10_000.0
        return 2 * (commission_with_vat + slippage)


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
