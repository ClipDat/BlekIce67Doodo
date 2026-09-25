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
# STRICT SYSTEM
# ============================================================

MARGIN_FRACTION = 0.50

LEVERAGE_LEVELS = [
    2,
    4,
    8,
    16,
    32,
]

TAKE_PROFIT_PERCENT = 0.005
STOP_LOSS_PERCENT = 0.0025

MAX_TRADE_SECONDS = 300


# ============================================================
# BITUNIX CLIENT
# ============================================================

class BitunixClient:

    def __init__(self):
        self.api_key = os.getenv("BITUNIX_API_KEY")
        self.secret_key = os.getenv("BITUNIX_SECRET_KEY")

        if not self.api_key:
            raise Exception("BITUNIX_API_KEY missing")

        if not self.secret_key:
            raise Exception("BITUNIX_SECRET_KEY missing")


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

        digest = self._sha256(first)

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

        data = result.get("data", [])

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
        leverage = int(leverage)

        if leverage not in LEVERAGE_LEVELS:
            raise Exception(
                f"Invalid leverage level: {leverage}x"
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
    # OPEN ORDER
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
    # TP / SL
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
    # CLOSE
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

        self.leverage_index = 0

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        self.active_position_id = None
        self.balance_before = None

        self.load_state()


    # ========================================================
    # LEVERAGE SYSTEM
    # ========================================================

    def current_leverage(self):
        return LEVERAGE_LEVELS[
            self.leverage_index
        ]


    def register_win(self):
        # ANY WIN -> 2x
        self.leverage_index = 0


    def register_loss(self):
        # 2 -> 4 -> 8 -> 16 -> 32 -> 2

        if self.leverage_index >= (
            len(LEVERAGE_LEVELS) - 1
        ):
            self.leverage_index = 0

        else:
            self.leverage_index += 1


    # ========================================================
    # STATE
    # ========================================================

    def save_state(self):
        state = {
            "leverage_index":
                self.leverage_index,

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

        try:
            with open(
                STATE_FILE,
                "r"
            ) as file:
                state = json.load(file)

        except Exception:
            print(
                "⚠️ Could not read state. "
                "Starting at 2x."
            )

            self.leverage_index = 0
            self.save_state()

            return

        self.leverage_index = int(
            state.get(
                "leverage_index",
                0
            )
        )

        if (
            self.leverage_index < 0
            or self.leverage_index
            >= len(LEVERAGE_LEVELS)
        ):
            self.leverage_index = 0

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
        end = time.time() + timeout

        while time.time() < end:
            positions = (
                self.client.get_positions()
            )

            if positions:
                return positions[0]

            time.sleep(0.25)

        return None


    def wait_until_closed(
        self,
        position_id,
        timeout=10
    ):
        end = time.time() + timeout

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

            time.sleep(0.25)

        return False


    # ========================================================
    # OPEN POSITION
    # ========================================================

    def open_from_signal(
        self,
        signal
    ):
        positions = (
            self.client.get_positions()
        )

        if positions:
            print(
                "\n⚠️ SOL position already exists."
            )

            return False


        # ----------------------------------------------------
        # REAL CURRENT BALANCE
        # ----------------------------------------------------

        balance = (
            self.client.get_balance()
        )

        if balance <= 0:
            raise Exception(
                "No available USDT"
            )


        # ----------------------------------------------------
        # CURRENT LEVERAGE
        # ----------------------------------------------------

        leverage = (
            self.current_leverage()
        )


        # ----------------------------------------------------
        # PAIR LIMITS
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

        if leverage > exchange_max_leverage:
            raise Exception(
                f"Bitunix maximum leverage is "
                f"{exchange_max_leverage}x, "
                f"but strategy requested "
                f"{leverage}x."
            )

        if leverage < exchange_min_leverage:
            raise Exception(
                f"Bitunix minimum leverage is "
                f"{exchange_min_leverage}x."
            )


        # ----------------------------------------------------
        # 50% MARGIN
        # ----------------------------------------------------

        margin = (
            balance
            * MARGIN_FRACTION
        )

        position_notional = (
            margin
            * leverage
        )


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

        entry_reference = float(
            signal["price"]
        )

        qty = (
            position_notional
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


        # ----------------------------------------------------
        # BITUNIX MINIMUM ORDER
        # ----------------------------------------------------

        if qty < min_qty:
            minimum_margin_needed = (
                min_qty
                * entry_reference
                / leverage
            )

            if minimum_margin_needed > balance:
                print(
                    "\n⚠️ Balance too small "
                    "for Bitunix minimum order."
                )

                return False

            print(
                "\n⚠️ Using Bitunix minimum "
                f"quantity: {min_qty} SOL"
            )

            qty = min_qty


        qty_string = (
            f"{qty:.{base_precision}f}"
        )


        actual_notional = (
            qty
            * entry_reference
        )


        # ----------------------------------------------------
        # SET EXACT LEVERAGE
        # ----------------------------------------------------

        self.client.set_leverage(
            leverage
        )


        # ----------------------------------------------------
        # PRINT
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("🔥 LIVE ORDER")
        print("=" * 60)

        print(
            f"Direction:         "
            f"{signal['action']}"
        )

        print(
            f"Balance:           "
            f"${balance:.4f}"
        )

        print(
            f"Margin fraction:   "
            f"50%"
        )

        print(
            f"Strategy leverage: "
            f"{leverage}x"
        )

        print(
            f"Position value:    "
            f"${actual_notional:.2f}"
        )

        print(
            f"SOL quantity:      "
            f"{qty_string}"
        )


        self.balance_before = balance
        self.save_state()


        # ----------------------------------------------------
        # OPEN REAL POSITION
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
        # GET REAL POSITION
        # ----------------------------------------------------

        position = (
            self.wait_for_position()
        )

        if not position:
            self.balance_before = None
            self.save_state()

            raise Exception(
                "Order sent but position "
                "did not appear."
            )


        position_id = str(
            position["positionId"]
        )

        real_entry = float(
            position["avgOpenPrice"]
        )

        real_leverage = int(
            float(
                position.get(
                    "leverage",
                    leverage
                )
            )
        )


        # ----------------------------------------------------
        # LEVERAGE MUST MATCH EXACTLY
        # ----------------------------------------------------

        if real_leverage != leverage:
            print(
                "\n🚨 LEVERAGE MISMATCH"
            )

            print(
                f"Requested: {leverage}x"
            )

            print(
                f"Bitunix:   {real_leverage}x"
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
        # FIXED 3% TP / 1.5% SL
        # ----------------------------------------------------

        if signal["action"] == "LONG":

            real_tp = (
                real_entry
                * (
                    1
                    + TAKE_PROFIT_PERCENT
                )
            )

            real_sl = (
                real_entry
                * (
                    1
                    - STOP_LOSS_PERCENT
                )
            )

        else:

            real_tp = (
                real_entry
                * (
                    1
                    - TAKE_PROFIT_PERCENT
                )
            )

            real_sl = (
                real_entry
                * (
                    1
                    + STOP_LOSS_PERCENT
                )
            )


        real_tp = round(
            real_tp,
            quote_precision
        )

        real_sl = round(
            real_sl,
            quote_precision
        )


        # ----------------------------------------------------
        # LIQUIDATION CHECK
        # ----------------------------------------------------

        liq_price = 0.0

        try:
            liq_price = float(
                position.get(
                    "liqPrice",
                    0
                )
                or 0
            )

        except Exception:
            liq_price = 0.0


        unsafe_liquidation = False

        if liq_price > 0:

            if signal["action"] == "LONG":
                if liq_price >= real_sl:
                    unsafe_liquidation = True

            else:
                if liq_price <= real_sl:
                    unsafe_liquidation = True


        if unsafe_liquidation:
            print(
                "\n🚨 Liquidation price is "
                "inside the stop-loss range."
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
        # SAVE POSITION
        # ----------------------------------------------------

        self.active_position_id = (
            position_id
        )

        self.save_state()


        # ----------------------------------------------------
        # PLACE TP / SL ON BITUNIX
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

            print(error)

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
            f"Entry:             "
            f"${real_entry:.4f}"
        )

        print(
            f"TP +3%:            "
            f"${real_tp}"
        )

        print(
            f"SL -1.5%:          "
            f"${real_sl}"
        )

        print(
            f"Real leverage:     "
            f"{real_leverage}x"
        )

        print(
            f"Position ID:       "
            f"{position_id}"
        )

        return True


    # ========================================================
    # FINISH TRADE
    # ========================================================

    def finalize_trade(self, exit_reason="TP_SL"):
        position_id = (
            self.active_position_id
        )

        if not position_id:
            return


        history = None

        for _ in range(12):
            history = (
                self.client.get_history_position(
                    position_id
                )
            )

            if history:
                break

            time.sleep(0.5)


        new_balance = (
            self.client.get_balance()
        )


        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        if history:
            trade_pnl = float(
                history.get(
                    "realizedPNL",
                    0
                )
                or 0
            )

        elif self.balance_before is not None:
            trade_pnl = (
                new_balance
                - float(
                    self.balance_before
                )
            )

        else:
            trade_pnl = 0.0


        self.total_trades += 1


        # ----------------------------------------------------
        # STRICT LEVERAGE RULE
        # ----------------------------------------------------

        # ========================================================
# LEVERAGE RULES
# ========================================================

        if exit_reason == "TIMEOUT":

            # ---------------------------------------------
            # 5 MINUTE FORCED CLOSE
            # ---------------------------------------------

            if trade_pnl > 0:

                result = "TIMEOUT PROFIT"

                self.wins += 1

                # IMPORTANT:
                # Small timeout profit does NOT reset leverage.
                # Stay on current level.

            elif trade_pnl < 0:

                result = "TIMEOUT LOSS"

                self.losses += 1

                # Timeout loss -> next leverage.
                self.register_loss()

            else:

                result = "TIMEOUT BREAKEVEN"

                # Stay on same leverage.


        else:

            # ---------------------------------------------
            # NORMAL TP / SL CLOSE
            # ---------------------------------------------

            if trade_pnl > 0:

                result = "WIN"

                self.wins += 1

                # Proper winning trade -> reset to 2x.
                self.register_win()

            elif trade_pnl < 0:

                result = "LOSS"

                self.losses += 1

                # Proper loss -> next leverage.
                self.register_loss()

            else:

                result = "BREAKEVEN"
            # Keep current leverage.


        self.active_position_id = None
        self.balance_before = None

        self.save_state()


        print("\n" + "=" * 60)
        print("🏁 LIVE TRADE FINISHED")
        print("=" * 60)

        print(
            f"Result:          "
            f"{result}"
        )

        print(
            f"Trade PnL:       "
            f"${trade_pnl:.4f}"
        )

        print(
            f"NEW BALANCE:     "
            f"${new_balance:.4f}"
        )

        print(
            f"Wins / Losses:   "
            f"{self.wins} / {self.losses}"
        )

        print(
            f"NEXT LEVERAGE:   "
            f"{self.current_leverage()}x"
        )


    # ========================================================
    # SYNC
    # ========================================================

    def sync(self):
        positions = (
            self.client.get_positions()
        )


        if positions:

            if not self.active_position_id:
                raise Exception(
                    "SOL position exists on Bitunix "
                    "but bot has no saved position ID."
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
                    "Bitunix position does not "
                    "match saved bot position."
                )


            real_leverage = int(
                float(
                    matching.get(
                        "leverage",
                        0
                    )
                )
            )


            # Only our five levels are valid.
            if real_leverage not in LEVERAGE_LEVELS:

                print(
                    "\n🚨 INVALID LEVERAGE DETECTED"
                )

                print(
                    f"Bitunix reports "
                    f"{real_leverage}x"
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
                    self.finalize_trade(
                    exit_reason="TIMEOUT"
                )

                return False


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
                or 0
            )


            print(
                f"\rLIVE "
                f"{matching.get('side')} | "
                f"Lev {real_leverage}x | "
                f"PnL ${unrealized:.4f} | "
                f"Age {int(age)}s / "
                f"{MAX_TRADE_SECONDS}s",
                end="",
                flush=True
            )


            # ------------------------------------------------
            # 5 MINUTE EXIT
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
                        "Position did not close."
                    )

                self.finalize_trade()

                return False


            return True


        # ----------------------------------------------------
        # NO POSITION -> TP / SL / MANUAL CLOSE
        # ----------------------------------------------------

        if self.active_position_id:

            print(
                "\nPosition closed on Bitunix."
            )

            self.finalize_trade()


        return False