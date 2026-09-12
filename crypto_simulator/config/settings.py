"""Configuration loading for the Crypto Market Simulator.

Settings are loaded once from a YAML file (``default.yaml`` unless
overridden) and can be selectively overridden by environment variables
prefixed with ``CRYPTOSIM_``. Every other module receives settings via
dependency injection (a ``Settings`` instance passed in) rather than
reading files or environment variables itself — this file is the single
place configuration is resolved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default.yaml"

# Maps CRYPTOSIM_<ENV_VAR> to a dotted path within the loaded YAML config.
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "CRYPTOSIM_DB_PATH": ("database", "path"),
    "CRYPTOSIM_STARTING_BALANCE": ("simulation", "starting_balance"),
    "CRYPTOSIM_LOG_LEVEL": ("logging", "level"),
    "CRYPTOSIM_RANDOM_SEED": ("simulation", "random_seed"),
    "CRYPTOSIM_PRICING_MODE": ("coin", "pricing_mode"),
}


@dataclass(frozen=True)
class SimulationSettings:
    starting_balance: float
    base_currency: str
    tick_interval_seconds: float
    random_seed: int


@dataclass(frozen=True)
class MarketSettings:
    assets: list[str]
    initial_prices: dict[str, float]
    volatility: float


@dataclass(frozen=True)
class WhaleSettings:
    id: str
    holdings: float
    activity_probability: float = 0.1
    max_trade_fraction: float = 0.05
    impact_coefficient: float = 2.0


@dataclass(frozen=True)
class TraderSettings:
    """One rule-based trader; ``strategy`` is a key of ``TRADER_STRATEGIES``
    and ``params`` holds that strategy's specific parameters."""

    id: str
    strategy: str
    starting_cash: float = 0.0
    starting_coins: float = 0.0
    trade_probability: float = 0.5
    max_trade_size: float = 1_000.0
    risk_tolerance: float = 0.5
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AMMSettings:
    """Constant-product pool used when ``coin.pricing_mode`` is ``amm``.

    ``pool_coin_reserve`` coins (plus ``pool_coin_reserve × starting_price``
    cash) are deposited by the market reserve; ``None`` deposits as much as
    the reserve can pair at the starting price.
    """

    pool_coin_reserve: float | None = None
    fee_rate: float = 0.003


@dataclass(frozen=True)
class CoinSettings:
    """Config for the minimum-viable single-coin economy simulation.

    Separate from ``MarketSettings`` above, which configures the
    multi-asset trading engine/dashboard.
    """

    symbol: str
    name: str
    initial_supply: float
    starting_price: float
    volatility: float
    base_volume_pct: float
    whales: list[WhaleSettings] = field(default_factory=list)
    traders: list[TraderSettings] = field(default_factory=list)
    # None = reserve holds cash equal to its coins' value at the starting price.
    market_reserve_cash: float | None = None
    trader_impact_coefficient: float = 2.0
    # "random_walk" (default) or "amm" — see core.coin_simulator.PricingMode.
    pricing_mode: str = "random_walk"
    amm: AMMSettings = field(default_factory=AMMSettings)


@dataclass(frozen=True)
class DatabaseSettings:
    path: str
    echo: bool


@dataclass(frozen=True)
class UISettings:
    page_title: str
    page_icon: str
    layout: str


@dataclass(frozen=True)
class LoggingSettings:
    level: str
    format: str


@dataclass(frozen=True)
class Settings:
    """Root settings object composed of one dataclass per config section."""

    simulation: SimulationSettings
    market: MarketSettings
    coin: CoinSettings
    database: DatabaseSettings
    ui: UISettings
    logging: LoggingSettings
    config_path: Path = field(repr=False, default=DEFAULT_CONFIG_PATH)


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Mutate ``raw`` in place with any matching ``CRYPTOSIM_*`` env vars."""
    for env_var, path in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value is None:
            continue
        target = raw
        for key in path[:-1]:
            target = target.setdefault(key, {})
        # Best-effort type coercion based on the existing default's type.
        current = target.get(path[-1])
        if isinstance(current, bool):
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int) and not isinstance(current, bool):
            value = int(value)
        elif isinstance(current, float):
            value = float(value)
        target[path[-1]] = value
    return raw


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load raw configuration as a dict, applying environment overrides."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return _apply_env_overrides(raw)


def build_settings(raw: dict[str, Any], config_path: Path) -> Settings:
    """Convert a raw config dict into a typed, immutable ``Settings`` object."""
    coin_raw = dict(raw["coin"])
    whales_raw = coin_raw.pop("whales", None) or []
    traders_raw = coin_raw.pop("traders", None) or []
    amm_raw = coin_raw.pop("amm", None) or {}
    coin_settings = CoinSettings(
        **coin_raw,
        whales=[WhaleSettings(**whale) for whale in whales_raw],
        traders=[TraderSettings(**trader) for trader in traders_raw],
        amm=AMMSettings(**amm_raw),
    )
    return Settings(
        simulation=SimulationSettings(**raw["simulation"]),
        market=MarketSettings(**raw["market"]),
        coin=coin_settings,
        database=DatabaseSettings(**raw["database"]),
        ui=UISettings(**raw["ui"]),
        logging=LoggingSettings(**raw["logging"]),
        config_path=config_path,
    )


@lru_cache(maxsize=None)
def get_settings(path: str | Path | None = None) -> Settings:
    """Return a cached, typed ``Settings`` instance.

    Cached per distinct ``path`` argument so tests can load alternate
    config files without clobbering the default singleton.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = load_config(config_path)
    return build_settings(raw, config_path)


def clear_settings_cache() -> None:
    """Clear the cached settings — primarily useful in tests."""
    get_settings.cache_clear()
