import os
import json
import time
import uuid
import math
import hashlib
import requests

from pathlib import Path
from datetime import date
from dotenv import load_dotenv


load_dotenv()


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://fapi.bitunix.com"

SYMBOL = "SOLUSDT"
MARGIN_COIN = "USDT"

STATE_FILE = Path(
    os.getenv(
        "TRADER_STATE_FILE",
        "live_trader_state.json"
    )
)


# ============================================================
# RISK LIMITS
# ============================================================

# Absolute leverage ceiling.
MAX_EXCHANGE_LEVERAGE = 10

# First trade risks 0.5% of CURRENT available balance.
BASE_RISK_PERCENT = 0.005

# Loss progression:
#
# loss streak 0 -> 1x -> 0.5%
# loss streak 1 -> 2x -> 1.0%
# loss streak 2 -> 4x -> 2.0%
# loss streak 3 -> 8x -> 4.0%
# loss streak 4 -> STOP
MARTINGALE_MULTIPLIERS = [
    1,
    2,
    4,
    8,
]

MAX_LOSS_STREAK = 4

# Stop new trading after losing 10%
# from the day's starting available balance.
DAILY_DRAWDOWN_LIMIT = 0.10

# Maximum lifetime of one position.
MAX_TRADE_SECONDS = 300

# Small margin buffer when deciding required leverage.
LEVERAGE_HEADROOM = 1.15


# ============================================================
# BITUNIX CLIENT
# ============================================================

class BitunixClient:

    def __init__(self):

        self.api_key = os.getenv(
            "BITUNIX_API_KEY"
        )

        self.secret_key = os.getenv(
            "BITUNIX_SECRET_KEY"
        )

        if not self.api_key:
            raise Exception(
                "BITUNIX_API_KEY missing"
            )

        if not self.secret_key:
            raise Exception(
                "BITUNIX_SECRET_KEY missing"
            )


    # --------------------------------------------------------
    # SIGNATURE
    # --------------------------------------------------------

    def _sha256(self, value):

        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()


    def _signature(
        self,
        nonce,
        timestamp,
        params=None,
        body=""
    ):

        params = params or {}

        query_string = ""

        for key in sorted(params.keys()):

            value = params[key]

            if value is not None:

                query_string += (
                    str(key)
                    + str(value)
                )

        first = (
            nonce
            + timestamp
            + self.api_key
            + query_string
            + body
        )

        digest = self._sha256(
            first
        )

        return self._sha256(
            digest
            + self.secret_key
        )


    def _headers(
        self,
        params=None,
        body=""
    ):

        nonce = uuid.uuid4().hex

        timestamp = str(
            int(time.time() * 1000)
        )

        signature = self._signature(
            nonce,
            timestamp,
            params=params,
            body=body
        )

        return {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": signature,
            "language": "en-US",
            "Content-Type": "application/json",
        }


    # --------------------------------------------------------
    # PRIVATE GET
    # --------------------------------------------------------

    def private_get(
        self,
        path,
        params=None
    ):

        params = params or {}

        response = requests.get(
            BASE_URL + path,
            params=params,
            headers=self._headers(
                params=params
            ),
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if str(result.get("code")) != "0":

            raise Exception(
                f"Bitunix GET error: {result}"
            )

        return result.get("data")


    # --------------------------------------------------------
    # PRIVATE POST
    # --------------------------------------------------------

    def private_post(
        self,
        path,
        payload
    ):

        body = json.dumps(
            payload,
            separators=(",", ":")
        )

        response = requests.post(
            BASE_URL + path,
            data=body,
            headers=self._headers(
                body=body
            ),
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if str(result.get("code")) != "0":

            raise Exception(
                f"Bitunix POST error: {result}"
            )

        return result.get("data")


    # ========================================================
    # ACCOUNT
    # ========================================================

    def get_account(self):

        data = self.private_get(
            "/api/v1/futures/account",
            {
                "marginCoin": MARGIN_COIN
            }
        )

        if isinstance(data, list):

            if not data:
                raise Exception(
                    "USDT account not returned"
                )

            return data[0]

        return data


    def get_balance(self):

        account = self.get_account()

        return float(
            account["available"]
        )


    # ========================================================
    # POSITIONS
    # ========================================================

    def get_positions(self):

        data = self.private_get(
            "/api/v1/futures/position/get_pending_positions",
            {
                "symbol": SYMBOL
            }
        )

        # Depending on API shape.
        if isinstance(data, dict):

            return data.get(
                "positionList",
                []
            )

        return data or []


    def get_history_position(
        self,
        position_id
    ):

        data = self.private_get(
            "/api/v1/futures/position/get_history_positions",
            {
                "symbol": SYMBOL,
                "positionId": str(position_id),
                "limit": 10
            }
        )

        if not data:
            return None

        if isinstance(data, dict):

            positions = data.get(
                "positionList",
                []
            )

        elif isinstance(data, list):

            positions = data

        else:

            return None

        for position in positions:

            if str(
                position.get("positionId")
            ) == str(position_id):

                return position

        return None


    # ========================================================
    # PAIR INFO
    # ========================================================

    def get_pair_info(self):

        response = requests.get(
            BASE_URL
            + "/api/v1/futures/market/trading_pairs",
            params={
                "symbols": SYMBOL
            },
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if str(result.get("code")) != "0":

            raise Exception(
                f"Pair API error: {result}"
            )

        data = result.get(
            "data",
            []
        )

        if not data:

            raise Exception(
                "SOLUSDT pair info missing"
            )

        return data[0]


    # ========================================================
    # LEVERAGE
    # ========================================================

    def set_leverage(
        self,
        leverage
    ):

        leverage = int(
            leverage
        )

        # Second independent safety wall.
        if leverage > MAX_EXCHANGE_LEVERAGE:

            raise Exception(
                f"SAFETY BLOCK: tried to set "
                f"{leverage}x leverage"
            )

        return self.private_post(
            "/api/v1/futures/account/change_leverage",
            {
                "marginCoin": MARGIN_COIN,
                "symbol": SYMBOL,
                "leverage": leverage
            }
        )


    # ========================================================
    # OPEN MARKET ORDER
    # ========================================================

    def open_market_order(
        self,
        side,
        qty
    ):

        account = self.get_account()

        position_mode = account.get(
            "positionMode",
            "ONE_WAY"
        )

        payload = {
            "symbol": SYMBOL,

            "qty": str(qty),

            "side": (
                "BUY"
                if side == "LONG"
                else "SELL"
            ),

            "orderType": "MARKET",

            "clientId": (
                "solbot_"
                + uuid.uuid4().hex[:20]
            )
        }

        if position_mode == "HEDGE":

            payload["tradeSide"] = "OPEN"

        return self.private_post(
            "/api/v1/futures/trade/place_order",
            payload
        )


    # ========================================================
    # POSITION TP / SL
    # ========================================================

    def place_tp_sl(
        self,
        position_id,
        tp_price,
        sl_price
    ):

        return self.private_post(
            "/api/v1/futures/tpsl/position/place_order",
            {
                "symbol": SYMBOL,

                "positionId":
                    str(position_id),

                "tpPrice":
                    str(tp_price),

                "tpStopType":
                    "LAST_PRICE",

                "slPrice":
                    str(sl_price),

                "slStopType":
                    "LAST_PRICE"
            }
        )


    # ========================================================
    # CLOSE POSITION
    # ========================================================

    def flash_close(
        self,
        position_id
    ):

        return self.private_post(
            "/api/v1/futures/trade/flash_close_position",
            {
                "positionId":
                    str(position_id)
            }
        )


# ============================================================
# LIVE TRADER
# ============================================================

class LiveTrader:

    def __init__(
        self,
        client
    ):

        self.client = client

        self.loss_streak = 0

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        self.active_position_id = None
        self.balance_before = None

        self.trading_halted = False
        self.halt_reason = None

        self.day_start_date = str(
            date.today()
        )

        self.day_start_balance = None

        self.load_state()


    # ========================================================
    # STATE
    # ========================================================

    def save_state(self):

        state = {
            "loss_streak":
                self.loss_streak,

            "total_trades":
                self.total_trades,

            "wins":
                self.wins,

            "losses":
                self.losses,

            "active_position_id":
                self.active_position_id,

            "balance_before":
                self.balance_before,

            "trading_halted":
                self.trading_halted,

            "halt_reason":
                self.halt_reason,

            "day_start_date":
                self.day_start_date,

            "day_start_balance":
                self.day_start_balance,
        }

        STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            STATE_FILE,
            "w"
        ) as file:

            json.dump(
                state,
                file,
                indent=4
            )


    def load_state(self):

        if not STATE_FILE.exists():

            self.save_state()
            return

        with open(
            STATE_FILE,
            "r"
        ) as file:

            state = json.load(
                file
            )

        self.loss_streak = int(
            state.get(
                "loss_streak",
                0
            )
        )

        self.total_trades = int(
            state.get(
                "total_trades",
                0
            )
        )

        self.wins = int(
            state.get(
                "wins",
                0
            )
        )

        self.losses = int(
            state.get(
                "losses",
                0
            )
        )

        self.active_position_id = (
            state.get(
                "active_position_id"
            )
        )

        self.balance_before = (
            state.get(
                "balance_before"
            )
        )

        self.trading_halted = bool(
            state.get(
                "trading_halted",
                False
            )
        )

        self.halt_reason = (
            state.get(
                "halt_reason"
            )
        )

        self.day_start_date = (
            state.get(
                "day_start_date",
                str(date.today())
            )
        )

        self.day_start_balance = (
            state.get(
                "day_start_balance"
            )
        )


    # ========================================================
    # MARTINGALE
    # ========================================================

    def multiplier(self):

        if self.loss_streak >= MAX_LOSS_STREAK:
            return None

        return MARTINGALE_MULTIPLIERS[
            self.loss_streak
        ]


    def target_risk_percent(self):

        multiplier = self.multiplier()

        if multiplier is None:
            return 0

        return (
            BASE_RISK_PERCENT
            * multiplier
        )


    # ========================================================
    # HALT
    # ========================================================

    def halt_trading(
        self,
        reason
    ):

        self.trading_halted = True
        self.halt_reason = reason

        self.save_state()

        print("\n" + "!" * 60)
        print("🛑 TRADING HALTED")
        print("!" * 60)

        print(
            f"Reason: {reason}"
        )


    # ========================================================
    # DAILY LIMIT
    # ========================================================

    def check_daily_limits(self):

        current_balance = (
            self.client.get_balance()
        )

        today = str(
            date.today()
        )

        # New calendar day.
        if self.day_start_date != today:

            self.day_start_date = today
            self.day_start_balance = (
                current_balance
            )

            # Only clear a daily halt automatically.
            if self.halt_reason == "DAILY_DRAWDOWN":

                self.trading_halted = False
                self.halt_reason = None

            self.save_state()

        if self.day_start_balance is None:

            self.day_start_balance = (
                current_balance
            )

            self.save_state()

        if self.day_start_balance <= 0:

            self.halt_trading(
                "INVALID_START_BALANCE"
            )

            return False

        drawdown = (
            self.day_start_balance
            - current_balance
        ) / self.day_start_balance

        if (
            drawdown
            >= DAILY_DRAWDOWN_LIMIT
        ):

            self.trading_halted = True
            self.halt_reason = (
                "DAILY_DRAWDOWN"
            )

            self.save_state()

            print("\n🛑 DAILY DRAWDOWN LIMIT")

            print(
                f"Day start: "
                f"${self.day_start_balance:.4f}"
            )

            print(
                f"Current:   "
                f"${current_balance:.4f}"
            )

            print(
                f"Drawdown:  "
                f"{drawdown * 100:.2f}%"
            )

            return False

        return True


    # ========================================================
    # HELPERS
    # ========================================================

    def floor_precision(
        self,
        value,
        precision
    ):

        factor = (
            10 ** precision
        )

        return (
            math.floor(
                value * factor
            )
            / factor
        )


    def wait_for_position(
        self,
        timeout=10
    ):

        end = (
            time.time()
            + timeout
        )

        while time.time() < end:

            positions = (
                self.client.get_positions()
            )

            if positions:

                return positions[0]

            time.sleep(
                0.25
            )

        return None


    def wait_until_closed(
        self,
        position_id,
        timeout=10
    ):

        end = (
            time.time()
            + timeout
        )

        while time.time() < end:

            positions = (
                self.client.get_positions()
            )

            exists = any(
                str(
                    position.get(
                        "positionId"
                    )
                )
                == str(position_id)

                for position in positions
            )

            if not exists:

                return True

            time.sleep(
                0.25
            )

        return False


    # ========================================================
    # OPEN POSITION
    # ========================================================

    def open_from_signal(
        self,
        signal
    ):

        # ----------------------------------------------------
        # BOT HALT
        # ----------------------------------------------------

        if self.trading_halted:

            print(
                f"\n🛑 Bot halted: "
                f"{self.halt_reason}"
            )

            return False

        # ----------------------------------------------------
        # MARTINGALE LIMIT
        # ----------------------------------------------------

        if self.loss_streak >= MAX_LOSS_STREAK:

            self.halt_trading(
                "MAX_LOSS_STREAK"
            )

            return False

        # ----------------------------------------------------
        # DAILY LIMIT
        # ----------------------------------------------------

        if not self.check_daily_limits():

            return False

        # ----------------------------------------------------
        # ONLY ONE SOL POSITION
        # ----------------------------------------------------

        positions = (
            self.client.get_positions()
        )

        if positions:

            raise Exception(
                "SOL position already exists. "
                "Refusing another entry."
            )

        # ----------------------------------------------------
        # FRESH REAL BALANCE
        # ----------------------------------------------------

        balance = (
            self.client.get_balance()
        )

        if balance <= 0:

            self.halt_trading(
                "NO_AVAILABLE_BALANCE"
            )

            return False

        print(
            f"\nREAL AVAILABLE BALANCE: "
            f"${balance:.4f}"
        )

        # ----------------------------------------------------
        # RISK LEVEL
        # ----------------------------------------------------

        multiplier = (
            self.multiplier()
        )

        if multiplier is None:

            self.halt_trading(
                "MAX_LOSS_STREAK"
            )

            return False

        risk_percent = (
            self.target_risk_percent()
        )

        risk_dollars = (
            balance
            * risk_percent
        )

        # ----------------------------------------------------
        # STOP DISTANCE
        # ----------------------------------------------------

        entry_reference = float(
            signal["price"]
        )

        stop_reference = float(
            signal["stop_loss"]
        )

        stop_distance = abs(
            entry_reference
            - stop_reference
        )

        stop_distance_percent = (
            stop_distance
            / entry_reference
        )

        if stop_distance_percent <= 0:

            print(
                "\n⚠️ SKIP: invalid stop"
            )

            return False

        # ----------------------------------------------------
        # POSITION SIZE
        # ----------------------------------------------------

        desired_notional = (
            risk_dollars
            / stop_distance_percent
        )

        required_leverage = (
            desired_notional
            / balance
        )

        buffered_leverage = (
            required_leverage
            * LEVERAGE_HEADROOM
        )

        # ----------------------------------------------------
        # HARD 10X CAP
        # ----------------------------------------------------

        if (
            buffered_leverage
            > MAX_EXCHANGE_LEVERAGE
        ):

            print("\n⚠️ TRADE SKIPPED")

            print(
                f"Required: "
                f"{buffered_leverage:.2f}x"
            )

            print(
                f"Maximum:  "
                f"{MAX_EXCHANGE_LEVERAGE}x"
            )

            return False

        # ----------------------------------------------------
        # EXCHANGE PAIR LIMITS
        # ----------------------------------------------------

        pair = (
            self.client.get_pair_info()
        )

        exchange_max_leverage = int(
            pair["maxLeverage"]
        )

        exchange_min_leverage = int(
            pair["minLeverage"]
        )

        max_allowed = min(
            MAX_EXCHANGE_LEVERAGE,
            exchange_max_leverage
        )

        leverage = math.ceil(
            buffered_leverage
        )

        leverage = max(
            leverage,
            exchange_min_leverage
        )

        if leverage > max_allowed:

            print(
                "\n⚠️ TRADE SKIPPED: "
                "leverage limit"
            )

            return False

        # ----------------------------------------------------
        # QUANTITY
        # ----------------------------------------------------

        base_precision = int(
            pair["basePrecision"]
        )

        quote_precision = int(
            pair["quotePrecision"]
        )

        min_qty = float(
            pair["minTradeVolume"]
        )

        max_qty = float(
            pair["maxMarketOrderVolume"]
        )

        qty = (
            desired_notional
            / entry_reference
        )

        qty = min(
            qty,
            max_qty
        )

        qty = self.floor_precision(
            qty,
            base_precision
        )

        if qty < min_qty:

            print(
                "\n⚠️ TRADE SKIPPED: "
                "quantity below minimum"
            )

            return False

        qty_string = (
            f"{qty:.{base_precision}f}"
        )

        # ----------------------------------------------------
        # VERIFY REAL CALCULATED RISK
        # ----------------------------------------------------

        actual_notional = (
            qty
            * entry_reference
        )

        actual_risk_dollars = (
            actual_notional
            * stop_distance_percent
        )

        actual_risk_percent = (
            actual_risk_dollars
            / balance
        )

        if (
            actual_risk_percent
            > risk_percent * 1.05
        ):

            print(
                "\n⚠️ TRADE SKIPPED: "
                "risk calculation exceeded target"
            )

            return False

        # ----------------------------------------------------
        # SET LEVERAGE
        # ----------------------------------------------------

        self.client.set_leverage(
            leverage
        )

        # ----------------------------------------------------
        # PRINT BEFORE REAL ORDER
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("🔥 LIVE ORDER")
        print("=" * 60)

        print(
            f"Direction:         "
            f"{signal['action']}"
        )

        print(
            f"Signal:            "
            f"{signal['signal_strength']}"
        )

        print(
            f"Loss streak:       "
            f"{self.loss_streak}"
        )

        print(
            f"Martingale:        "
            f"{multiplier}x"
        )

        print(
            f"Balance:           "
            f"${balance:.4f}"
        )

        print(
            f"Target risk:       "
            f"{risk_percent * 100:.2f}%"
        )

        print(
            f"Actual risk:       "
            f"{actual_risk_percent * 100:.2f}%"
        )

        print(
            f"Position:          "
            f"${actual_notional:.2f}"
        )

        print(
            f"Exchange leverage: "
            f"{leverage}x"
        )

        print(
            f"SOL quantity:      "
            f"{qty_string}"
        )

        # Absolute assertion.
        if leverage > MAX_EXCHANGE_LEVERAGE:

            raise Exception(
                "CRITICAL: leverage above 10x"
            )

        # ----------------------------------------------------
        # SAVE BALANCE BEFORE TRADE
        # ----------------------------------------------------

        self.balance_before = balance

        self.save_state()

        # ----------------------------------------------------
        # SEND REAL MARKET ORDER
        # ----------------------------------------------------

        order = (
            self.client.open_market_order(
                signal["action"],
                qty_string
            )
        )

        print(
            f"Order ID:          "
            f"{order.get('orderId')}"
        )

        # ----------------------------------------------------
        # GET ACTUAL EXCHANGE POSITION
        # ----------------------------------------------------

        position = (
            self.wait_for_position()
        )

        if not position:

            self.balance_before = None
            self.save_state()

            raise Exception(
                "Order sent but no position appeared"
            )

        position_id = str(
            position["positionId"]
        )

        real_entry = float(
            position["avgOpenPrice"]
        )

        real_leverage = float(
            position.get(
                "leverage",
                leverage
            )
        )

        # ----------------------------------------------------
        # THIRD LEVERAGE SAFETY CHECK
        # ----------------------------------------------------

        if (
            real_leverage
            > MAX_EXCHANGE_LEVERAGE
        ):

            print(
                "\n🚨 BITUNIX REPORTS "
                f"{real_leverage}x"
            )

            print(
                "Closing immediately."
            )

            self.client.flash_close(
                position_id
            )

            self.wait_until_closed(
                position_id
            )

            self.balance_before = None
            self.save_state()

            return False

        # ----------------------------------------------------
        # RECALCULATE SL / TP USING REAL FILL
        # ----------------------------------------------------

        sl_distance = abs(
            float(signal["price"])
            - float(signal["stop_loss"])
        )

        tp_distance = abs(
            float(signal["take_profit"])
            - float(signal["price"])
        )

        if signal["action"] == "LONG":

            real_sl = (
                real_entry
                - sl_distance
            )

            real_tp = (
                real_entry
                + tp_distance
            )

        else:

            real_sl = (
                real_entry
                + sl_distance
            )

            real_tp = (
                real_entry
                - tp_distance
            )

        real_sl = round(
            real_sl,
            quote_precision
        )

        real_tp = round(
            real_tp,
            quote_precision
        )

        # ----------------------------------------------------
        # LIQUIDATION CHECK
        # ----------------------------------------------------

        liq_raw = position.get(
            "liqPrice"
        )

        liq_price = 0.0

        if liq_raw not in (
            None,
            "",
            "0"
        ):

            try:

                liq_price = float(
                    liq_raw
                )

            except Exception:

                liq_price = 0.0

        unsafe = False

        if liq_price > 0:

            if signal["action"] == "LONG":

                # Liquidation must be below SL.
                if liq_price >= real_sl:

                    unsafe = True

            else:

                # Liquidation must be above SL.
                if liq_price <= real_sl:

                    unsafe = True

        if unsafe:

            print(
                "\n🚨 LIQUIDATION TOO CLOSE"
            )

            print(
                f"Entry: ${real_entry:.4f}"
            )

            print(
                f"SL:    ${real_sl:.4f}"
            )

            print(
                f"Liq:   ${liq_price:.4f}"
            )

            self.client.flash_close(
                position_id
            )

            self.wait_until_closed(
                position_id
            )

            self.balance_before = None
            self.save_state()

            return False

        # ----------------------------------------------------
        # SAVE REAL POSITION ID
        # ----------------------------------------------------

        self.active_position_id = (
            position_id
        )

        self.save_state()

        # ----------------------------------------------------
        # PLACE REAL TP / SL
        # ----------------------------------------------------

        try:

            self.client.place_tp_sl(
                position_id,
                real_tp,
                real_sl
            )

        except Exception as error:

            print(
                "\n🚨 TP/SL FAILED"
            )

            print(
                error
            )

            print(
                "Closing position immediately."
            )

            self.client.flash_close(
                position_id
            )

            self.wait_until_closed(
                position_id
            )

            self.finalize_trade()

            return False

        print(
            f"Real entry:        "
            f"${real_entry:.4f}"
        )

        print(
            f"STOP on Bitunix:   "
            f"${real_sl}"
        )

        print(
            f"TARGET on Bitunix: "
            f"${real_tp}"
        )

        print(
            f"Real leverage:     "
            f"{real_leverage:.0f}x"
        )

        if liq_price > 0:

            print(
                f"Liquidation:       "
                f"${liq_price:.4f}"
            )

        print(
            f"Position ID:       "
            f"{position_id}"
        )

        return True


    # ========================================================
    # FINALIZE TRADE
    # ========================================================

    def finalize_trade(self):

        position_id = (
            self.active_position_id
        )

        if not position_id:

            return

        history = None

        # Position history can lag slightly.
        for _ in range(12):

            history = (
                self.client.get_history_position(
                    position_id
                )
            )

            if history:
                break

            time.sleep(
                0.5
            )

        new_balance = (
            self.client.get_balance()
        )

        # Most robust fallback for our purposes:
        # compare real available balance before/after.
        if self.balance_before is not None:

            net_pnl = (
                new_balance
                - float(
                    self.balance_before
                )
            )

        elif history:

            net_pnl = float(
                history.get(
                    "realizedPNL",
                    0
                )
            )

        else:

            net_pnl = 0.0

        self.total_trades += 1

        if net_pnl > 0:

            result = "WIN"

            self.wins += 1

            # WIN resets progression.
            self.loss_streak = 0

        elif net_pnl < 0:

            result = "LOSS"

            self.losses += 1

            self.loss_streak += 1

        else:

            result = "BREAKEVEN"

        self.active_position_id = None
        self.balance_before = None

        # ----------------------------------------------------
        # FOUR LOSSES -> HALT
        # ----------------------------------------------------

        if (
            self.loss_streak
            >= MAX_LOSS_STREAK
        ):

            self.trading_halted = True
            self.halt_reason = (
                "MAX_LOSS_STREAK"
            )

        self.save_state()

        print("\n" + "=" * 60)
        print("🏁 LIVE TRADE FINISHED")
        print("=" * 60)

        print(
            f"Result:            "
            f"{result}"
        )

        print(
            f"Net PnL:           "
            f"${net_pnl:.4f}"
        )

        print(
            f"NEW BALANCE:       "
            f"${new_balance:.4f}"
        )

        print(
            f"Trades:            "
            f"{self.total_trades}"
        )

        print(
            f"Wins / Losses:     "
            f"{self.wins} / {self.losses}"
        )

        print(
            f"Loss streak:       "
            f"{self.loss_streak}"
        )

        if self.trading_halted:

            print(
                "\n🛑 NEW TRADES HALTED"
            )

            print(
                f"Reason: "
                f"{self.halt_reason}"
            )

        else:

            print(
                f"NEXT MARTINGALE:   "
                f"{self.multiplier()}x"
            )


    # ========================================================
    # SYNC REAL BITUNIX STATE
    # ========================================================

    def sync(self):

        positions = (
            self.client.get_positions()
        )

        # ----------------------------------------------------
        # REAL POSITION EXISTS
        # ----------------------------------------------------

        if positions:

            if not self.active_position_id:

                raise Exception(
                    "A SOL position exists on "
                    "Bitunix but the bot does not "
                    "recognize it."
                )

            matching = None

            for position in positions:

                if str(
                    position.get(
                        "positionId"
                    )
                ) == str(
                    self.active_position_id
                ):

                    matching = position
                    break

            if matching is None:

                raise Exception(
                    "Bitunix SOL position does not "
                    "match saved bot position."
                )

            # ------------------------------------------------
            # KEEP CHECKING LEVERAGE
            # ------------------------------------------------

            real_leverage = float(
                matching.get(
                    "leverage",
                    0
                )
            )

            if (
                real_leverage
                > MAX_EXCHANGE_LEVERAGE
            ):

                print(
                    "\n🚨 LEVERAGE ABOVE 10x"
                )

                print(
                    "Closing immediately."
                )

                self.client.flash_close(
                    self.active_position_id
                )

                closed = (
                    self.wait_until_closed(
                        self.active_position_id
                    )
                )

                if closed:

                    self.finalize_trade()

                return False

            # ------------------------------------------------
            # POSITION AGE
            # ------------------------------------------------

            opened_at = (
                int(
                    matching["ctime"]
                )
                / 1000
            )

            age = (
                time.time()
                - opened_at
            )

            unrealized = float(
                matching.get(
                    "unrealizedPNL",
                    0
                )
            )

            print(
                f"\rLIVE "
                f"{matching.get('side')} | "
                f"Lev {real_leverage:.0f}x | "
                f"PnL ${unrealized:.4f} | "
                f"Age {int(age)}s / "
                f"{MAX_TRADE_SECONDS}s",
                end="",
                flush=True
            )

            # ------------------------------------------------
            # FIVE-MINUTE TIME EXIT
            # ------------------------------------------------

            if age >= MAX_TRADE_SECONDS:

                print(
                    "\n\n⏱️ 5 MINUTES REACHED"
                )

                print(
                    "Closing position..."
                )

                self.client.flash_close(
                    self.active_position_id
                )

                closed = (
                    self.wait_until_closed(
                        self.active_position_id
                    )
                )

                if not closed:

                    raise Exception(
                        "Close request sent but "
                        "position still exists."
                    )

                self.finalize_trade()

                return False

            return True

        # ----------------------------------------------------
        # NO REAL POSITION
        # ----------------------------------------------------

        if self.active_position_id:

            # TP, SL or manual close happened.
            print(
                "\nPosition closed on Bitunix."
            )

            self.finalize_trade()

        return False