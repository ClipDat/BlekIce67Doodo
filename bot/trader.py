from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .client import BitunixClient, BitunixAPIError
from .config import Settings
from .indicators import parse_klines
from .paper import PaperBroker
from .risk_manager import LeverageLadder, sl_is_safe
from .state import load_state, save_state
from .smc_strategy import SmcSignal
from .strategy import EmaCrossSignal


def _round_down(value: float, precision: int) -> str:
    if precision <= 0:
        return str(int(value))
    q = Decimal(1).scaleb(-precision)  # e.g. precision=3 -> 0.001
    d = Decimal(str(value)).quantize(q, rounding=ROUND_DOWN)
    return format(d, "f")


class Trader:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.cfg = settings
        self.log = logger
        self.client = BitunixClient(settings.api_key, settings.api_secret, settings.base_url)
        self.ladder = LeverageLadder(settings.leverage_ladder)
        self.signal = EmaCrossSignal(settings.ema_fast, settings.ema_slow)
        self._last_sample = 0.0
        self.smc: Optional[SmcSignal] = None
        if settings.strategy == "smc":
            self.smc = SmcSignal(settings.smc_swing, settings.smc_min_zone_pct,
                                 settings.smc_zone_max_age, settings.smc_first_touch_only,
                                 settings.smc_min_score, settings.smc_entry_tolerance)
        self._last_candle_fetch = 0.0
        self._last_status_log = 0.0
        self._entry_reason = ""

        # Persistent state: survives in-process restarts (and container restarts
        # if the state file lives on a persistent volume).
        mode = "paper" if settings.paper_trading else "live"
        self.state = load_state(settings.state_file)
        if self.state.get("mode") != mode:      # never mix paper and live state
            self.state = {"mode": mode}
        self.ladder.set_index(int(self.state.get("ladder_index", 0)))

        self.paper: Optional[PaperBroker] = None
        if settings.paper_trading:
            self.paper = PaperBroker(settings.paper_balance, settings.paper_fee_rate,
                                     settings.paper_slippage, settings.paper_trades_csv,
                                     saved=self.state.get("paper"))

        self._session_start_balance: Optional[float] = self.state.get("session_start_balance")
        self._symbol_info: Optional[dict] = None

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        self.state["mode"] = "paper" if self.paper else "live"
        self.state["ladder_index"] = self.ladder.index
        self.state["session_start_balance"] = self._session_start_balance
        if self.paper:
            self.state["paper"] = self.paper.to_dict()
        save_state(self.cfg.state_file, self.state)

    def _bootstrap(self) -> None:
        self._symbol_info = self.client.get_trading_pair(self.cfg.symbol)
        self.log.info("Trading pair info: %s", self._symbol_info)

        if self.paper:
            self._session_start_balance = self.paper.initial_balance
            self.log.info("PAPER TRADING (virtual money, real prices). Balance: $%.2f | ladder at %dx",
                          self.paper.balance, self.ladder.current)
        else:
            acct = self.client.get_single_account(self.cfg.margin_coin)
            available = float(acct.get("available", 0))
            if not self._session_start_balance:
                self._session_start_balance = available
            self.log.warning("LIVE TRADING with REAL money. Balance: %.4f %s | session start: %.4f | ladder at %dx",
                             available, self.cfg.margin_coin, self._session_start_balance,
                             self.ladder.current)
            try:
                self.client.change_margin_mode(self.cfg.symbol, "ISOLATION", self.cfg.margin_coin)
                self.log.info("Margin mode set to ISOLATION for %s", self.cfg.symbol)
            except BitunixAPIError as e:
                # Fails if there's already an open position/order, or it's already isolated.
                self.log.warning("Could not set margin mode (continuing): %s", e)
        self._save()

    # ------------------------------------------------------------------ #
    def _price(self) -> float:
        return float(self.client.get_ticker(self.cfg.symbol)["lastPrice"])

    def _current_balance(self) -> float:
        if self.paper:
            return self.paper.balance
        acct = self.client.get_single_account(self.cfg.margin_coin)
        return float(acct.get("available", 0))

    def _drawdown_breached(self, balance: float) -> bool:
        if self.cfg.max_drawdown_fraction <= 0 or not self._session_start_balance:
            return False
        floor = self._session_start_balance * (1.0 - self.cfg.max_drawdown_fraction)
        return balance <= floor

    # ------------------------------------------------------------------ #
    def _feed_signal(self, price: float) -> bool:
        """Sample the price for the EMA once per SIGNAL_INTERVAL_SECONDS."""
        now = time.time()
        if now - self._last_sample >= self.cfg.signal_interval_seconds:
            self.signal.update(price)
            self._last_sample = now
            return True
        return False

    def _refresh_candles(self) -> None:
        now = time.time()
        if now - self._last_candle_fetch < self.cfg.smc_refresh_seconds:
            return
        raw = self.client.get_klines(self.cfg.symbol, self.cfg.smc_timeframe, self.cfg.smc_candles)
        self.smc.update(parse_klines(raw, self.cfg.smc_timeframe, int(now * 1000)))
        self._last_candle_fetch = now

    def _signal_direction(self, price: float) -> Optional[str]:
        if self.smc is not None:
            self._refresh_candles()
            direction = self.smc.direction(price)
            self._entry_reason = self.smc.reason if direction else ""
            if direction is None and time.time() - self._last_status_log >= 60:
                self.log.info(self.smc.describe(price))
                self._last_status_log = time.time()
            return direction

        added = self._feed_signal(price)
        direction = self.signal.direction()
        if direction is None and added:
            self.log.info("Warming up EMA signal (%d/%d samples)...",
                          len(self.signal._prices), self.cfg.ema_slow)
        return direction

    def _wait_for_signal(self) -> str:
        while True:
            direction = self._signal_direction(self._price())
            if direction is not None:
                return direction
            time.sleep(self.cfg.poll_interval_seconds)

    # ------------------------------------------------------------------ #
    def _has_open_position(self) -> bool:
        if self.paper:
            return self.paper.position is not None
        return bool(self.client.get_pending_positions(self.cfg.symbol))

    def _stop_with_summary(self, reason: str) -> None:
        if self.paper:
            self.log.info(self.paper.summary())
        self._save()
        raise SystemExit(reason)

    def _open_trade(self, direction: str) -> Optional[dict]:
        leverage = self.ladder.current

        if not sl_is_safe(self.cfg.sl_pct, leverage, self.cfg.min_liquidation_buffer_multiple):
            self.log.error(
                "Refusing to open: SL distance (%.3f%%) too close to estimated liquidation "
                "distance at %dx leverage. Check MIN_LIQUIDATION_BUFFER_MULTIPLE / SL_PCT.",
                self.cfg.sl_pct * 100, leverage)
            return None

        balance = self._current_balance()
        if self._drawdown_breached(balance):
            self._stop_with_summary(
                f"Max drawdown reached (balance {balance:.4f} vs start "
                f"{self._session_start_balance:.4f}, limit {self.cfg.max_drawdown_fraction * 100:.0f}%). "
                "No new trades. Set MAX_DRAWDOWN_FRACTION=0 to disable or delete the state file to restart.")

        price = self._price()
        margin_usdt = balance * self.cfg.margin_fraction
        raw_qty = margin_usdt * leverage / price

        precision = int(self._symbol_info.get("basePrecision", 3))
        min_qty = float(self._symbol_info.get("minTradeVolume", 0))
        qty_str = _round_down(raw_qty, precision)

        if float(qty_str) < min_qty:
            if self.paper:
                self._stop_with_summary("Paper account too small to open the minimum position.")
            self.log.warning("Computed qty %s below exchange minimum %s - balance too small "
                             "for this leverage rung.", qty_str, min_qty)
            return None

        real_margin = float(qty_str) * price / leverage
        side = "BUY" if direction == "LONG" else "SELL"
        sign = 1 if direction == "LONG" else -1
        tp_price = price * (1 + sign * self.cfg.tp_pct)
        sl_price = price * (1 - sign * self.cfg.sl_pct)
        quote_precision = int(self._symbol_info.get("quotePrecision", 4))
        tp_str = _round_down(tp_price, quote_precision)
        sl_str = _round_down(sl_price, quote_precision)

        self.log.info("OPEN %s %s qty=%s @~%.4f leverage=%dx margin=%.4f tp=%s sl=%s",
                      direction, self.cfg.symbol, qty_str, price, leverage, real_margin, tp_str, sl_str)
        if self._entry_reason:
            self.log.info("Entry reason: %s", self._entry_reason)

        if self.paper:
            pos = self.paper.open(direction, price, float(qty_str), leverage, real_margin,
                                  self.cfg.tp_pct, self.cfg.sl_pct)
            self._save()
            return pos

        self.client.change_leverage(self.cfg.symbol, leverage, self.cfg.margin_coin)
        order = self.client.place_order(
            symbol=self.cfg.symbol, side=side, qty=qty_str, order_type="MARKET",
            trade_side="OPEN", tp_price=tp_str, sl_price=sl_str,
            client_id=uuid.uuid4().hex[:20])
        self.log.info("Order placed: %s", order)

        # Wait until the exchange actually shows the position (avoids reading stale data).
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.client.get_pending_positions(self.cfg.symbol):
                return order
            time.sleep(1.0)
        self.log.error("Order accepted but no open position appeared within 20s. "
                       "Check Bitunix manually. The bot will pick it up if it shows later.")
        return None

    # ------------------------------------------------------------------ #
    def _manage_paper(self) -> Optional[float]:
        last_heartbeat = 0.0
        while True:
            price = self._price()
            self._feed_signal(price)
            res = self.paper.on_price(price)
            if res is None and time.time() - last_heartbeat >= 60:
                p = self.paper.position
                self.log.info("Watching %s x%d: price=%.4f | SL=%.4f | TP=%.4f",
                              p["direction"], p["leverage"], price, p["sl"], p["tp"])
                last_heartbeat = time.time()
            if res:
                self.log.info("CLOSED %s x%d entry=%.4f exit=%.4f -> %s net=%+.4f | balance=$%.2f",
                              res["direction"], res["leverage"], res["entry"], res["exit"],
                              res["reason"], res["net"], res["balance"])
                self.log.info(self.paper.summary())
                return res["net"]
            time.sleep(self.cfg.poll_interval_seconds)

    def _manage_live(self) -> Optional[float]:
        pending = self.client.get_pending_positions(self.cfg.symbol)
        if not pending:
            return None
        pid = pending[0]["positionId"]
        last_unrealized = float(pending[0].get("unrealizedPNL", 0))

        last_heartbeat = 0.0
        while True:
            time.sleep(self.cfg.position_poll_seconds)
            pending = self.client.get_pending_positions(self.cfg.symbol)
            mine = [p for p in pending if p.get("positionId") == pid]
            if not mine:
                break
            last_unrealized = float(mine[0].get("unrealizedPNL", last_unrealized))
            price = self._price()
            self._feed_signal(price)
            if time.time() - last_heartbeat >= 60:
                self.log.info("Watching position %s: price=%.4f | unrealized PnL=%.4f",
                              pid, price, last_unrealized)
                last_heartbeat = time.time()

        for _ in range(8):  # history can lag a few seconds behind
            history = self.client.get_history_positions(self.cfg.symbol, limit=10)
            match = [h for h in history if h.get("positionId") == pid]
            if match:
                pnl = float(match[0].get("realizedPNL", 0))
                self.log.info("Position %s closed. realizedPNL=%.4f", pid, pnl)
                return pnl
            time.sleep(2.0)
        self.log.warning("No history entry for position %s; using last unrealized PnL (%.4f).",
                         pid, last_unrealized)
        return last_unrealized

    def _manage_open_position(self) -> None:
        pnl = self._manage_paper() if self.paper else self._manage_live()
        if pnl is None:
            return
        if pnl > 0:
            self.log.info("WIN -> leverage reset to %dx", self.ladder.on_win())
        else:
            self.log.info("LOSS -> leverage now %dx", self.ladder.on_loss())
        self._save()

    # ------------------------------------------------------------------ #
    def run_forever(self) -> None:
        self._bootstrap()
        while True:
            if self._has_open_position():
                self.log.info("Open position found - managing it before opening a new one.")
                self._manage_open_position()
                time.sleep(self.cfg.post_trade_pause_seconds)
                continue

            direction = self._wait_for_signal()
            if self._open_trade(direction) is None:
                time.sleep(max(self.cfg.poll_interval_seconds, 30.0))
                continue

            self._manage_open_position()
            time.sleep(self.cfg.post_trade_pause_seconds)
