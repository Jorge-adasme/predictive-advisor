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
    # Stop duro por activo: si cae X% desde entrada → vende esa posición
    max_position_loss_pct: float = Field(default=0.025, ge=0.01, le=0.15)
    # Al −X% diario: rotate = cierra perdedoras y sigue buscando; pause = bloquea compras
    kill_switch_mode: str = "rotate"  # rotate | pause
    # Al disparar kill-switch diario: vender perdedoras (True) o solo pausar compras
    halt_close_losers: bool = True
    # Si True, cierra TODAS las posiciones (incluye ganadoras) al −X% diario
    halt_flatten_all: bool = False
    # En modo rotate, reduce tamaño de nuevas entradas
    defense_risk_mult: float = Field(default=0.45, ge=0.15, le=1.0)
    # Edge neto mínimo (permite ganancias chicas tras costos)
    min_edge_net_pct: float = Field(default=0.0003, ge=0.0, le=0.05)
    allow_micro_edge: bool = True  # compra edges pequeños con tamaño reducido
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
    max_positions: int = Field(default=8, ge=1, le=16)
    max_per_sector: int = Field(default=3, ge=1, le=5)

    # Noticias mundiales
    news_enabled: bool = True
    news_cache_ttl_sec: int = Field(default=900, ge=60, le=7200)
    news_lookback_days: int = Field(default=14, ge=3, le=30)
    news_weight: float = Field(default=0.22, ge=0.0, le=0.5)
    news_semantic_weight: float = Field(default=0.55, ge=0.0, le=1.0)
    newsapi_key: str = ""  # opcional https://newsapi.org

    # Earnings blackout
    earnings_enabled: bool = True
    earnings_blackout_before: int = Field(default=2, ge=0, le=10)
    earnings_blackout_after: int = Field(default=1, ge=0, le=5)
    earnings_cache_ttl_sec: int = Field(default=43200, ge=3600, le=86400)

    # Alpaca default: commission-free equities + slippage model
    commission_rate: float = Field(default=0.0, ge=0.0, le=0.05)
    vat_rate: float = Field(default=0.0, ge=0.0, le=0.4)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=100.0)

    lookback_days: int = Field(default=420, ge=60, le=2000)
    horizon_days: int = Field(default=10, ge=1, le=60)
    top_n: int = Field(default=30, ge=1, le=80)
    # Cuántas ideas del universo completo mostrar (sigue escaneando TODOS los tickers)
    opportunity_limit: int = Field(default=60, ge=20, le=150)
    # Caché del último analyze para que la UI no quede vacía mientras rescanea
    analyze_cache_ttl_sec: int = Field(default=180, ge=30, le=1800)

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

    # IA de decisión (desactivada por ahora; se reactiva más adelante)
    ai_enabled: bool = False
    ai_provider: str = "local"  # local | openai | anthropic
    ai_api_key: str = ""
    ai_model: str = ""  # vacío = default del provider
    ai_base_url: str = "https://api.openai.com/v1"
    ai_gate_autopilot: bool = False  # solo aplica si ai_enabled=true

    # Tiempo real (UI)
    live_enabled: bool = True
    live_poll_sec: int = Field(default=8, ge=3, le=60)  # precios / portafolio
    live_analyze_sec: int = Field(default=120, ge=30, le=900)  # re-análisis cuant+IA

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
