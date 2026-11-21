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
    base_currency: str = "CLP"

    risk_per_trade: float = Field(default=0.0075, ge=0.001, le=0.05)
    max_position_pct: float = Field(default=0.12, ge=0.01, le=0.5)
    max_daily_loss_pct: float = Field(default=0.02, ge=0.005, le=0.1)
    min_edge_net_pct: float = Field(default=0.004, ge=0.0, le=0.05)

    commission_rate: float = Field(default=0.004, ge=0.0, le=0.05)
    vat_rate: float = Field(default=0.19, ge=0.0, le=0.4)
    slippage_bps: float = Field(default=8.0, ge=0.0, le=100.0)

    lookback_days: int = Field(default=420, ge=60, le=2000)
    horizon_days: int = Field(default=10, ge=1, le=60)
    top_n: int = Field(default=8, ge=1, le=30)

    data_dir: Path = ROOT_DIR / "data"
    universe_path: Path = ROOT_DIR / "configs" / "universe_chile.json"

    @property
    def round_trip_cost_pct(self) -> float:
        """Costo estimado ida y vuelta: comisión+IVA por lado + slippage."""
        commission_with_vat = self.commission_rate * (1 + self.vat_rate)
        slippage = self.slippage_bps / 10_000.0
        return 2 * (commission_with_vat + slippage)


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
