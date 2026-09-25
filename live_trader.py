import os
import json
import time
import uuid
import math
import hashlib
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://fapi.bitunix.com"
SYMBOL = "SOLUSDT"
MARGIN_COIN = "USDT"

STATE_FILE = Path(
    os.getenv("TRADER_STATE_FILE", "live_trader_state.json")
)

MARGIN_FRACTION = 0.50
LEVERAGE_LEVELS = [2, 4, 8, 16, 32]
TAKE_PROFIT_PERCENT = 0.005   # 0.5%
STOP_LOSS_PERCENT = 0.0025   # 0.25%
MAX_TRADE_SECONDS = 300


def leverage_after_loss(leverage):
    leverage = int(leverage)
    if leverage not in LEVERAGE_LEVELS:
        raise ValueError(f"Unknown leverage: {leverage}x")
    index = LEVERAGE_LEVELS.index(leverage)
    return LEVERAGE_LEVELS[(index + 1) % len(LEVERAGE_LEVELS)]


def leverage_after_normal_close(leverage, pnl):
    if pnl > 0:
        return 2
    if pnl < 0:
        return leverage_after_loss(leverage)
    return int(leverage)


def leverage_after_timeout(leverage, pnl):
    if pnl < 0:
        return leverage_after_loss(leverage)
    return int(leverage)


class BitunixClient:
    def __init__(self):
        self.api_key = os.getenv("BITUNIX_API_KEY")
        self.secret_key = os.getenv("BITUNIX_SECRET_KEY")

        if not self.api_key:
            raise Exception("BITUNIX_API_KEY missing")
        if not self.secret_key:
            raise Exception("BITUNIX_SECRET_KEY missing")

    def _sha256(self, value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _signature(self, nonce, timestamp, params=None, body=""):
        params = params or {}
        query_string = ""

        for key in sorted(params.keys()):
            value = params[key]
            if value is not None:
                query_string += str(key) + str(value)

        first = nonce + timestamp + self.api_key + query_string + body
        digest = self._sha256(first)
        return self._sha256(digest + self.secret_key)

    def _headers(self, params=None, body=""):
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time() * 1000))
        signature = self._signature(
            nonce,
            timestamp,
            params=params,
            body=body,
        )

        return {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": signature,
            "language": "en-US",
            "Content-Type": "application/json",
        }

    def private_get(self, path, params=None):
        params = params or {}
        response = requests.get(
            BASE_URL + path,
            params=params,
            headers=self._headers(params=params),
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

        if str(result.get("code")) != "0":
            raise Exception(f"Bitunix GET error: {result}")

        return result.get("data")

    def private_post(self, path, payload):
        body = json.dumps(payload, separators=(",", ":"))
        response = requests.post(
            BASE_URL + path,
            data=body,
            headers=self._headers(body=body),
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

        if str(result.get("code")) != "0":
            raise Exception(f"Bitunix POST error: {result}")

        return result.get("data")

    def get_account(self):
        data = self.private_get(
            "/api/v1/futures/account",
            {"marginCoin": MARGIN_COIN},
        )

        if isinstance(data, list):
            if not data:
                raise Exception("USDT account not returned")
            return data[0]
        return data

    def get_balance(self):
        return float(self.get_account()["available"])

    def get_positions(self):
        data = self.private_get(
            "/api/v1/futures/position/get_pending_positions",
            {"symbol": SYMBOL},
        )

        if isinstance(data, dict):
            return data.get("positionList", [])
        return data or []

    def get_history_position(self, position_id):
        data = self.private_get(
            "/api/v1/futures/position/get_history_positions",
            {
                "symbol": SYMBOL,
                "positionId": str(position_id),
                "limit": 10,
            },
        )

        if not data:
            return None

        if isinstance(data, dict):
            positions = data.get("positionList", [])
        elif isinstance(data, list):
            positions = data
        else:
            return None

        for position in positions:
            if str(position.get("positionId")) == str(position_id):
                return position
        return None

    def get_pair_info(self):
        response = requests.get(
            BASE_URL + "/api/v1/futures/market/trading_pairs",
            params={"symbols": SYMBOL},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

        if str(result.get("code")) != "0":
            raise Exception(f"Pair API error: {result}")

        data = result.get("data", [])
        if not data:
            raise Exception("SOLUSDT pair info missing")
        return data[0]

    def set_leverage(self, leverage):
        leverage = int(leverage)
        if leverage not in LEVERAGE_LEVELS:
            raise Exception(f"Invalid strategy leverage: {leverage}x")

        return self.private_post(
            "/api/v1/futures/account/change_leverage",
            {
                "marginCoin": MARGIN_COIN,
                "symbol": SYMBOL,
                "leverage": leverage,
            },
        )

    def open_market_order(self, side, qty):
        account = self.get_account()
        position_mode = account.get("positionMode", "ONE_WAY")

        payload = {
            "symbol": SYMBOL,
            "qty": str(qty),
            "side": "BUY" if side == "LONG" else "SELL",
            "orderType": "MARKET",
            "clientId": "solbot_" + uuid.uuid4().hex[:20],
        }

        if position_mode == "HEDGE":
            payload["tradeSide"] = "OPEN"

        return self.private_post(
            "/api/v1/futures/trade/place_order",
            payload,
        )

    def place_tp_sl(self, position_id, tp_price, sl_price):
        return self.private_post(
            "/api/v1/futures/tpsl/position/place_order",
            {
                "symbol": SYMBOL,
                "positionId": str(position_id),
                "tpPrice": str(tp_price),
                "tpStopType": "LAST_PRICE",
                "slPrice": str(sl_price),
                "slStopType": "LAST_PRICE",
            },
        )

    def flash_close(self, position_id):
        return self.private_post(
            "/api/v1/futures/trade/flash_close_position",
            {"positionId": str(position_id)},
        )


class LiveTrader:
    def __init__(self, client):
        self.client = client

        # This is the leverage the NEXT trade must use.
        self.next_leverage = 2

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        self.active_position_id = None
        self.active_leverage = None
        self.balance_before = None
        self.pending_exit_reason = None

        self.load_state()

    def current_leverage(self):
        return int(self.next_leverage)

    def save_state(self):
        state = {
            "next_leverage": self.next_leverage,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "active_position_id": self.active_position_id,
            "active_leverage": self.active_leverage,
            "balance_before": self.balance_before,
            "pending_exit_reason": self.pending_exit_reason,
        }

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")

        with open(temp_file, "w") as file:
            json.dump(state, file, indent=4)

        os.replace(temp_file, STATE_FILE)

    def load_state(self):
        if not STATE_FILE.exists():
            self.save_state()
            return

        try:
            with open(STATE_FILE, "r") as file:
                state = json.load(file)
        except Exception as error:
            raise Exception(
                f"State file exists but could not be read: {STATE_FILE}: {error}"
            )

        self.next_leverage = int(state.get("next_leverage", 2))
        if self.next_leverage not in LEVERAGE_LEVELS:
            self.next_leverage = 2

        self.total_trades = int(state.get("total_trades", 0))
        self.wins = int(state.get("wins", 0))
        self.losses = int(state.get("losses", 0))
        self.active_position_id = state.get("active_position_id")
        self.active_leverage = state.get("active_leverage")
        self.balance_before = state.get("balance_before")
        self.pending_exit_reason = state.get("pending_exit_reason")

        if self.active_leverage is not None:
            self.active_leverage = int(self.active_leverage)

    def floor_precision(self, value, precision):
        factor = 10 ** precision
        return math.floor(value * factor) / factor

    def wait_for_position(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            positions = self.client.get_positions()
            if positions:
                return positions[0]
            time.sleep(0.25)
        return None

    def wait_until_closed(self, position_id, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            positions = self.client.get_positions()
            exists = any(
                str(position.get("positionId")) == str(position_id)
                for position in positions
            )
            if not exists:
                return True
            time.sleep(0.25)
        return False

    def recover_open_position(self, position):
        position_id = str(position["positionId"])
        leverage = int(float(position.get("leverage", 0)))

        if leverage not in LEVERAGE_LEVELS:
            raise Exception(
                f"Open SOL position uses unexpected leverage {leverage}x. "
                "Bot will not adopt it."
            )

        self.active_position_id = position_id
        self.active_leverage = leverage
        self.next_leverage = leverage
        self.balance_before = None
        self.pending_exit_reason = None
        self.save_state()

        print("\n♻️ RECOVERED OPEN POSITION FROM BITUNIX")
        print(f"Position ID:       {position_id}")
        print(f"Recovered leverage:{leverage}x")

    def open_from_signal(self, signal):
        positions = self.client.get_positions()
        if positions:
            print("\n⚠️ SOL position already exists. Not opening another.")
            return False

        balance = self.client.get_balance()
        if balance <= 0:
            raise Exception("No available USDT")

        leverage = self.current_leverage()
        pair = self.client.get_pair_info()

        exchange_max_leverage = int(pair["maxLeverage"])
        exchange_min_leverage = int(pair["minLeverage"])

        if leverage > exchange_max_leverage:
            raise Exception(
                f"Bitunix max leverage is {exchange_max_leverage}x; "
                f"strategy requested {leverage}x"
            )
        if leverage < exchange_min_leverage:
            raise Exception(
                f"Bitunix min leverage is {exchange_min_leverage}x; "
                f"strategy requested {leverage}x"
            )

        target_margin = balance * MARGIN_FRACTION
        position_notional = target_margin * leverage

        base_precision = int(pair["basePrecision"])
        quote_precision = int(pair["quotePrecision"])
        min_qty = float(pair["minTradeVolume"])
        max_qty = float(pair["maxMarketOrderVolume"])

        entry_reference = float(signal["price"])
        qty = position_notional / entry_reference
        qty = min(qty, max_qty)
        qty = self.floor_precision(qty, base_precision)

        if qty < min_qty:
            minimum_margin_needed = min_qty * entry_reference / leverage
            if minimum_margin_needed > balance:
                print("\n⚠️ Balance too small for Bitunix minimum order.")
                return False

            print(f"\n⚠️ Using Bitunix minimum quantity: {min_qty} SOL")
            qty = min_qty

        qty_string = f"{qty:.{base_precision}f}"
        actual_notional = qty * entry_reference
        actual_margin = actual_notional / leverage

        self.client.set_leverage(leverage)

        print("\n" + "=" * 60)
        print("🔥 LIVE ORDER")
        print("=" * 60)
        print(f"Direction:         {signal['action']}")
        print(f"Balance:           ${balance:.4f}")
        print(f"Target margin:     ${target_margin:.4f}")
        print(f"Actual margin:     ${actual_margin:.4f}")
        print(f"Strategy leverage: {leverage}x")
        print(f"Position value:    ${actual_notional:.2f}")
        print(f"SOL quantity:      {qty_string}")

        self.balance_before = balance
        self.active_leverage = leverage
        self.pending_exit_reason = None
        self.save_state()

        order = self.client.open_market_order(signal["action"], qty_string)
        print(f"Order ID:          {order.get('orderId')}")

        position = self.wait_for_position()
        if not position:
            self.balance_before = None
            self.active_leverage = None
            self.save_state()
            raise Exception("Order sent but position did not appear")

        position_id = str(position["positionId"])
        real_entry = float(position["avgOpenPrice"])
        real_leverage = int(float(position.get("leverage", leverage)))

        if real_leverage != leverage:
            print("\n🚨 LEVERAGE MISMATCH")
            print(f"Requested: {leverage}x")
            print(f"Bitunix:   {real_leverage}x")
            self.client.flash_close(position_id)
            self.wait_until_closed(position_id)
            self.balance_before = None
            self.active_leverage = None
            self.save_state()
            return False

        if signal["action"] == "LONG":
            real_tp = real_entry * (1 + TAKE_PROFIT_PERCENT)
            real_sl = real_entry * (1 - STOP_LOSS_PERCENT)
        else:
            real_tp = real_entry * (1 - TAKE_PROFIT_PERCENT)
            real_sl = real_entry * (1 + STOP_LOSS_PERCENT)

        real_tp = round(real_tp, quote_precision)
        real_sl = round(real_sl, quote_precision)

        liq_price = 0.0
        try:
            liq_price = float(position.get("liqPrice", 0) or 0)
        except Exception:
            liq_price = 0.0

        unsafe_liquidation = False
        if liq_price > 0:
            if signal["action"] == "LONG" and liq_price >= real_sl:
                unsafe_liquidation = True
            elif signal["action"] == "SHORT" and liq_price <= real_sl:
                unsafe_liquidation = True

        if unsafe_liquidation:
            print("\n🚨 Liquidation price is inside the stop-loss range.")
            print(f"Entry: ${real_entry:.4f}")
            print(f"SL:    ${real_sl:.4f}")
            print(f"Liq:   ${liq_price:.4f}")
            self.client.flash_close(position_id)
            self.wait_until_closed(position_id)
            self.balance_before = None
            self.active_leverage = None
            self.save_state()
            return False

        self.active_position_id = position_id
        self.active_leverage = real_leverage
        self.next_leverage = real_leverage
        self.save_state()

        try:
            self.client.place_tp_sl(position_id, real_tp, real_sl)
        except Exception as error:
            print("\n🚨 TP/SL FAILED")
            print(error)
            print("Closing position immediately.")
            self.pending_exit_reason = "ERROR_CLOSE"
            self.save_state()
            self.client.flash_close(position_id)
            self.wait_until_closed(position_id)
            self.finalize_trade(exit_reason="ERROR_CLOSE")
            return False

        print(f"Entry:             ${real_entry:.4f}")
        print(f"TP +0.5%:          ${real_tp}")
        print(f"SL -0.25%:         ${real_sl}")
        print(f"Real leverage:     {real_leverage}x")
        print(f"Position ID:       {position_id}")
        return True

    def finalize_trade(self, exit_reason=None):
        position_id = self.active_position_id
        if not position_id:
            return

        closed_leverage = self.active_leverage
        if closed_leverage is None:
            closed_leverage = self.current_leverage()
        closed_leverage = int(closed_leverage)

        if closed_leverage not in LEVERAGE_LEVELS:
            raise Exception(f"Invalid closed leverage: {closed_leverage}x")

        if exit_reason is None:
            exit_reason = self.pending_exit_reason or "TP_SL"

        history = None
        for _ in range(20):
            history = self.client.get_history_position(position_id)
            if history:
                break
            time.sleep(0.5)

        new_balance = self.client.get_balance()

        if history:
            trade_pnl = float(history.get("realizedPNL", 0) or 0)
        elif self.balance_before is not None:
            trade_pnl = new_balance - float(self.balance_before)
        else:
            raise Exception(
                "Position closed but PnL could not be determined. "
                "Refusing to change leverage state."
            )

        self.total_trades += 1

        if exit_reason == "TIMEOUT":
            if trade_pnl < 0:
                result = "TIMEOUT LOSS"
                self.losses += 1
            elif trade_pnl > 0:
                result = "TIMEOUT PROFIT"
                self.wins += 1
            else:
                result = "TIMEOUT BREAKEVEN"

            self.next_leverage = leverage_after_timeout(
                closed_leverage,
                trade_pnl,
            )

        elif exit_reason == "ERROR_CLOSE":
            result = "ERROR CLOSE"
            # Technical close does not alter the progression.
            self.next_leverage = closed_leverage

        else:
            if trade_pnl < 0:
                result = "LOSS"
                self.losses += 1
            elif trade_pnl > 0:
                result = "WIN"
                self.wins += 1
            else:
                result = "BREAKEVEN"

            self.next_leverage = leverage_after_normal_close(
                closed_leverage,
                trade_pnl,
            )

        self.active_position_id = None
        self.active_leverage = None
        self.balance_before = None
        self.pending_exit_reason = None
        self.save_state()

        print("\n" + "=" * 60)
        print("🏁 LIVE TRADE FINISHED")
        print("=" * 60)
        print(f"Exit reason:      {exit_reason}")
        print(f"Closed leverage:  {closed_leverage}x")
        print(f"Result:           {result}")
        print(f"Trade PnL:        ${trade_pnl:.6f}")
        print(f"NEW BALANCE:      ${new_balance:.4f}")
        print(f"Wins / Losses:    {self.wins} / {self.losses}")
        print(f"NEXT LEVERAGE:    {self.next_leverage}x")

    def sync(self):
        positions = self.client.get_positions()

        if len(positions) > 1:
            raise Exception(
                "More than one SOL position exists. Bot refuses to guess which one to manage."
            )

        if positions:
            position = positions[0]

            if not self.active_position_id:
                self.recover_open_position(position)

            elif str(position.get("positionId")) != str(self.active_position_id):
                raise Exception(
                    "Bitunix open position does not match saved bot position."
                )

            real_leverage = int(float(position.get("leverage", 0)))
            if real_leverage not in LEVERAGE_LEVELS:
                raise Exception(
                    f"Unexpected live leverage {real_leverage}x. Bot will not manage it."
                )

            if self.active_leverage != real_leverage:
                print(
                    f"\n⚠️ State leverage {self.active_leverage}x differs from "
                    f"Bitunix {real_leverage}x. Using Bitunix value."
                )
                self.active_leverage = real_leverage
                self.next_leverage = real_leverage
                self.save_state()

            opened_at = int(position["ctime"]) / 1000
            age = time.time() - opened_at
            unrealized = float(position.get("unrealizedPNL", 0) or 0)

            print(
                f"\rLIVE {position.get('side')} | "
                f"Lev {real_leverage}x | "
                f"PnL ${unrealized:.4f} | "
                f"Age {int(age)}s / {MAX_TRADE_SECONDS}s",
                end="",
                flush=True,
            )

            if age >= MAX_TRADE_SECONDS:
                print("\n\n⏱️ 5 MINUTES REACHED")
                print("Closing position...")

                self.pending_exit_reason = "TIMEOUT"
                self.save_state()

                self.client.flash_close(self.active_position_id)
                closed = self.wait_until_closed(self.active_position_id)

                if not closed:
                    raise Exception("Position did not close")

                self.finalize_trade(exit_reason="TIMEOUT")
                return False

            return True

        if self.active_position_id:
            print("\nPosition closed on Bitunix.")
            self.finalize_trade(
                exit_reason=self.pending_exit_reason or "TP_SL"
            )

        return False
