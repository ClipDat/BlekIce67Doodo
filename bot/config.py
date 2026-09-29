"""
Central configuration for the bot. Everything is driven by environment
variables so the same code runs locally (.env file) and on Railway
(Railway project variables) without any changes.
"""
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()  # no-op on Railway (no .env file there), loads .env locally


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _resolve_mode():
    """Returns (real_money, conflict). REAL_MONEY=true switches to live trading.
    The old PAPER_TRADING variable still works, but if the two disagree we play safe."""
    rm = os.getenv("REAL_MONEY", "").strip().lower()
    pt = os.getenv("PAPER_TRADING", "").strip().lower()
    from_rm = True if rm in _TRUE else False if rm in _FALSE else None
    from_pt = False if pt in _TRUE else True if pt in _FALSE else None   # PAPER_TRADING=true -> not real
    if from_rm is not None and from_pt is not None and from_rm != from_pt:
        return False, True
    if from_rm is not None:
        return from_rm, False
    if from_pt is not None:
        return from_pt, False
    return False, False


_REAL_MONEY, _MODE_CONFLICT = _resolve_mode()


@dataclass
class Settings:
    # --- Bitunix credentials -------------------------------------------------
    api_key: str = field(default_factory=lambda: os.getenv("BITUNIX_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BITUNIX_API_SECRET", ""))
    base_url: str = field(default_factory=lambda: _env_str("BITUNIX_BASE_URL", "https://fapi.bitunix.com"))

    # --- Market ---------------------------------------------------------------
    symbol: str = field(default_factory=lambda: _env_str("SYMBOL", "SOLUSDT"))
    margin_coin: str = field(default_factory=lambda: _env_str("MARGIN_COIN", "USDT"))

    # --- Money management (per the strategy spec) ------------------------------
    margin_fraction: float = field(default_factory=lambda: _env_float("MARGIN_FRACTION", 0.5))   # 50% of balance
    tp_pct: float = field(default_factory=lambda: _env_float("TP_PCT", 0.01))                     # +1%
    sl_pct: float = field(default_factory=lambda: _env_float("SL_PCT", 0.005))                    # -0.5%
    leverage_ladder: List[int] = field(default_factory=lambda: [
        int(x) for x in _env_str("LEVERAGE_LADDER", "2,4,8,16,32,64").split(",") if x.strip()
    ])

    # --- Entry signal (EMA crossover on last price sampled once per interval) --
    poll_interval_seconds: float = field(default_factory=lambda: _env_float("POLL_INTERVAL_SECONDS", 2.0))
    signal_interval_seconds: float = field(default_factory=lambda: _env_float("SIGNAL_INTERVAL_SECONDS", 60.0))
    ema_fast: int = field(default_factory=lambda: _env_int("EMA_FAST", 9))
    ema_slow: int = field(default_factory=lambda: _env_int("EMA_SLOW", 21))

    # --- Strategy selection -------------------------------------------------------
    # "ema" = EMA crossover (always has a direction, trades constantly)
    # "smc" = market structure + Fair Value Gaps + Order Blocks (waits for a setup)
    strategy: str = field(default_factory=lambda: _env_str("STRATEGY", "ema").strip().lower())
    smc_timeframe: str = field(default_factory=lambda: _env_str("SMC_TIMEFRAME", "5m"))
    smc_candles: int = field(default_factory=lambda: min(_env_int("SMC_CANDLES", 200), 200))
    smc_swing: int = field(default_factory=lambda: _env_int("SMC_SWING", 3))
    smc_min_zone_pct: float = field(default_factory=lambda: _env_float("SMC_MIN_ZONE_PCT", 0.0005))
    smc_zone_max_age: int = field(default_factory=lambda: _env_int("SMC_ZONE_MAX_AGE", 80))
    smc_first_touch_only: bool = field(default_factory=lambda: _env_bool("SMC_FIRST_TOUCH_ONLY", True))
    smc_min_score: int = field(default_factory=lambda: _env_int("SMC_MIN_SCORE", 1))
    smc_entry_tolerance: float = field(default_factory=lambda: _env_float("SMC_ENTRY_TOLERANCE", 0.0003))
    smc_refresh_seconds: float = field(default_factory=lambda: _env_float("SMC_REFRESH_SECONDS", 15.0))

    # --- Operational ------------------------------------------------------------
    position_poll_seconds: float = field(default_factory=lambda: _env_float("POSITION_POLL_SECONDS", 3.0))
    post_trade_pause_seconds: float = field(default_factory=lambda: _env_float("POST_TRADE_PAUSE_SECONDS", 5.0))
    balance_log_seconds: float = field(default_factory=lambda: _env_float("BALANCE_LOG_SECONDS", 300.0))
    # REAL_MONEY=false (default) -> paper trading: virtual money, real live prices, no API keys.
    # REAL_MONEY=true            -> REAL orders on Bitunix with real money.
    paper_trading: bool = field(default_factory=lambda: not _REAL_MONEY)
    mode_conflict: bool = field(default_factory=lambda: _MODE_CONFLICT)
    paper_balance: float = field(default_factory=lambda: _env_float("PAPER_BALANCE", 100.0))
    paper_fee_rate: float = field(default_factory=lambda: _env_float("PAPER_FEE_RATE", 0.0006))   # per side, taker
    paper_slippage: float = field(default_factory=lambda: _env_float("PAPER_SLIPPAGE", 0.0002))   # per fill
    state_file: str = field(default_factory=lambda: _env_str("STATE_FILE", "bot_state.json"))
    paper_trades_csv: str = field(default_factory=lambda: _env_str("PAPER_TRADES_CSV", "paper_trades.csv"))
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO"))

    # --- Safety rails (highly recommended, all optional / can be disabled) -----
    # Stop opening new trades once equity drops below this fraction of the
    # balance the bot started the session with. 0 disables the check.
    max_drawdown_fraction: float = field(default_factory=lambda: _env_float("MAX_DRAWDOWN_FRACTION", 0.5))
    # Minimum liquidation-distance safety multiple vs. the stop-loss distance.
    # e.g. 2.0 means: refuse to open if a SL-sized adverse move would already
    # put the position within 1/2.0 of the estimated liquidation distance.
    min_liquidation_buffer_multiple: float = field(
        default_factory=lambda: _env_float("MIN_LIQUIDATION_BUFFER_MULTIPLE", 2.0)
    )


settings = Settings()
