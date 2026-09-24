import os
import json
import time
import uuid
import math
import hashlib
import requests

from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


BASE_URL = "https://fapi.bitunix.com"

SYMBOL = "SOLUSDT"
MARGIN_COIN = "USDT"

STATE_FILE = Path(
    os.getenv(
        "TRADER_STATE_FILE",
        "live_trader_state.json"
    )
)


# =====================================================
# BITUNIX API CLIENT
# =====================================================

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
                "BITUNIX_API_KEY missing from .env"
            )

        if not self.secret_key:
            raise Exception(
                "BITUNIX_SECRET_KEY missing from .env"
            )


    # -------------------------------------------------
    # SIGNATURE
    # -------------------------------------------------

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

        # Bitunix wants:
        #
        # key1value1key2value2
        #
        # sorted by key

        query_string = ""

        for key in sorted(params.keys()):

            if params[key] is not None:

                query_string += (
                    str(key)
                    + str(params[key])
                )

        digest_input = (
            nonce
            + timestamp
            + self.api_key
            + query_string
            + body
        )

        digest = self._sha256(
            digest_input
        )

        signature = self._sha256(
            digest
            + self.secret_key
        )

        return signature


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
            params,
            body
        )

        return {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": signature,
            "language": "en-US",
            "Content-Type": "application/json",
        }


    # -------------------------------------------------
    # PRIVATE GET
    # -------------------------------------------------

    def private_get(
        self,
        path,
        params=None
    ):

        params = params or {}

        headers = self._headers(
            params=params
        )

        response = requests.get(
            BASE_URL + path,
            params=params,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if str(result.get("code")) != "0":

            raise Exception(
                f"Bitunix GET error: {result}"
            )

        return result.get("data")


    # -------------------------------------------------
    # PRIVATE POST
    # -------------------------------------------------

    def private_post(
        self,
        path,
        payload
    ):

        body = json.dumps(
            payload,
            separators=(",", ":")
        )

        headers = self._headers(
            body=body
        )

        response = requests.post(
            BASE_URL + path,
            data=body,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if str(result.get("code")) != "0":

            raise Exception(
                f"Bitunix POST error: {result}"
            )

        return result.get("data")


    # =================================================
    # ACCOUNT
    # =================================================

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
                    "No USDT account returned"
                )

            return data[0]

        return data


    def get_balance(self):

        account = self.get_account()

        return float(
            account["available"]
        )


    # =================================================
    # POSITION
    # =================================================

    def get_positions(self):

        data = self.private_get(
            "/api/v1/futures/position/get_pending_positions",
            {
                "symbol": SYMBOL
            }
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
                "positionId": position_id,
                "limit": 10
            }
        )

        if not data:
            return None

        positions = data.get(
            "positionList",
            []
        )

        for position in positions:

            if str(
                position.get("positionId")
            ) == str(position_id):

                return position

        return None


    # =================================================
    # PAIR INFORMATION
    # =================================================

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

        data = result["data"]

        if not data:
            raise Exception(
                "SOLUSDT pair not found"
            )

        return data[0]


    # =================================================
    # LEVERAGE
    # =================================================

    def set_leverage(
        self,
        leverage
    ):

        return self.private_post(
            "/api/v1/futures/account/change_leverage",
            {
                "marginCoin": MARGIN_COIN,
                "symbol": SYMBOL,
                "leverage": int(leverage)
            }
        )


    # =================================================
    # OPEN ORDER
    # =================================================

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
            "qty": qty,
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

        # tradeSide is only required
        # in hedge mode.

        if position_mode == "HEDGE":

            payload[
                "tradeSide"
            ] = "OPEN"

        return self.private_post(
            "/api/v1/futures/trade/place_order",
            payload
        )


    # =================================================
    # TP / SL
    # =================================================

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


    # =================================================
    # CLOSE POSITION
    # =================================================

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


# =====================================================
# LIVE TRADER
# =====================================================

class LiveTrader:

    def __init__(self, client):

        self.client = client

        # ---------------------------------------------
        # MARTINGALE
        # ---------------------------------------------

        self.base_risk_percent = 0.01

        self.multipliers = [
            1,
            2,
            4,
            8,
            16,
            32,
            64,
        ]

        self.loss_streak = 0

        # ---------------------------------------------
        # STATS
        # ---------------------------------------------

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        # ---------------------------------------------
        # POSITION
        # ---------------------------------------------

        self.active_position_id = None
        self.balance_before = None

        # Maximum trade = 5 minutes
        self.max_trade_seconds = 300

        # Additional margin headroom.
        #
        # Example:
        # calculated effective leverage = 10x
        # exchange leverage ≈ 13x

        self.leverage_headroom = 1.25

        self.load_state()


    # =================================================
    # STATE
    # =================================================

    def save_state(self):

        data = {
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
        }

        with open(
            STATE_FILE,
            "w"
        ) as file:

            json.dump(
                data,
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

            data = json.load(file)

        self.loss_streak = data.get(
            "loss_streak",
            0
        )

        self.total_trades = data.get(
            "total_trades",
            0
        )

        self.wins = data.get(
            "wins",
            0
        )

        self.losses = data.get(
            "losses",
            0
        )

        self.active_position_id = data.get(
            "active_position_id"
        )

        self.balance_before = data.get(
            "balance_before"
        )


    # =================================================
    # MARTINGALE
    # =================================================

    def multiplier(self):

        index = min(
            self.loss_streak,
            len(self.multipliers) - 1
        )

        return self.multipliers[index]


    def target_risk_percent(self):

        return (
            self.base_risk_percent
            * self.multiplier()
        )


    # =================================================
    # HELPERS
    # =================================================

    def floor_precision(
        self,
        value,
        precision
    ):

        factor = 10 ** precision

        return (
            math.floor(
                value * factor
            )
            / factor
        )


    def wait_for_position(
        self,
        timeout=8
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

            time.sleep(0.25)

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
                str(p["positionId"])
                == str(position_id)

                for p in positions
            )

            if not exists:
                return True

            time.sleep(0.25)

        return False


    # =================================================
    # OPEN POSITION
    # =================================================

    def open_from_signal(
        self,
        signal
    ):

        # ---------------------------------------------
        # SAFETY:
        # Never create another SOL position
        # if one already exists.
        # ---------------------------------------------

        positions = (
            self.client.get_positions()
        )

        if positions:

            raise Exception(
                "SOL position already exists. "
                "Refusing to open another."
            )

        # ---------------------------------------------
        # FRESH REAL BALANCE
        # ---------------------------------------------

        balance = (
            self.client.get_balance()
        )

        print(
            f"\nREAL AVAILABLE BALANCE: "
            f"${balance:.4f}"
        )

        if balance <= 0:

            raise Exception(
                "No available USDT"
            )

        # ---------------------------------------------
        # MARTINGALE RISK
        # ---------------------------------------------

        multiplier = (
            self.multiplier()
        )

        target_risk_percent = (
            self.target_risk_percent()
        )

        target_risk_dollars = (
            balance
            * target_risk_percent
        )

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

            raise Exception(
                "Invalid stop distance"
            )

        # Desired notional position based on
        # how much money should be lost at SL.

        desired_notional = (
            target_risk_dollars
            / stop_distance_percent
        )

        # ---------------------------------------------
        # EXCHANGE LIMITS
        # ---------------------------------------------

        pair = (
            self.client.get_pair_info()
        )

        max_leverage = int(
            pair["maxLeverage"]
        )

        min_leverage = int(
            pair["minLeverage"]
        )

        base_precision = int(
            pair["basePrecision"]
        )

        min_qty = float(
            pair["minTradeVolume"]
        )

        max_market_qty = float(
            pair["maxMarketOrderVolume"]
        )

        # Leave leverage headroom.
        #
        # If desired trade requires more leverage
        # than Bitunix supports, position gets capped.

        maximum_notional = (
            balance
            * max_leverage
            / self.leverage_headroom
        )

        actual_notional = min(
            desired_notional,
            maximum_notional
        )

        if actual_notional < desired_notional:

            print(
                "\n⚠️ MARTINGALE POSITION CAPPED"
            )

            print(
                "Requested risk cannot be achieved "
                "with available margin / max leverage."
            )

        # ---------------------------------------------
        # REQUIRED LEVERAGE
        # ---------------------------------------------

        effective_leverage = (
            actual_notional
            / balance
        )

        leverage = math.ceil(
            effective_leverage
            * self.leverage_headroom
        )

        leverage = max(
            leverage,
            min_leverage
        )

        leverage = min(
            leverage,
            max_leverage
        )

        # ---------------------------------------------
        # QUANTITY
        # ---------------------------------------------

        qty = (
            actual_notional
            / entry_reference
        )

        qty = min(
            qty,
            max_market_qty
        )

        qty = self.floor_precision(
            qty,
            base_precision
        )

        if qty < min_qty:

            raise Exception(
                f"Calculated qty {qty} "
                f"is below minimum {min_qty}"
            )

        qty_string = (
            f"{qty:.{base_precision}f}"
        )

        # Actual approximate risk after caps

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

        # ---------------------------------------------
        # SET LEVERAGE
        # ---------------------------------------------

        self.client.set_leverage(
            leverage
        )

        print("\n" + "=" * 60)
        print("🔥 LIVE ORDER")
        print("=" * 60)

        print(
            f"Direction:        "
            f"{signal['action']}"
        )

        print(
            f"Signal:           "
            f"{signal['signal_strength']}"
        )

        print(
            f"Martingale:       "
            f"{multiplier}x"
        )

        print(
            f"Loss streak:      "
            f"{self.loss_streak}"
        )

        print(
            f"Balance:          "
            f"${balance:.4f}"
        )

        print(
            f"Target risk:      "
            f"{target_risk_percent * 100:.2f}%"
        )

        print(
            f"Actual risk:      "
            f"{actual_risk_percent * 100:.2f}%"
        )

        print(
            f"Position:         "
            f"${actual_notional:.2f}"
        )

        print(
            f"Exchange leverage:"
            f" {leverage}x"
        )

        print(
            f"SOL quantity:     "
            f"{qty_string}"
        )

        # ---------------------------------------------
        # REMEMBER BALANCE BEFORE TRADE
        # ---------------------------------------------

        self.balance_before = balance

        # ---------------------------------------------
        # MARKET ORDER
        # ---------------------------------------------

        order = (
            self.client.open_market_order(
                signal["action"],
                qty_string
            )
        )

        print(
            f"Order ID:         "
            f"{order.get('orderId')}"
        )

        # ---------------------------------------------
        # WAIT FOR ACTUAL POSITION
        # ---------------------------------------------

        position = (
            self.wait_for_position()
        )

        if not position:

            self.balance_before = None
            self.save_state()

            raise Exception(
                "Market order sent but no "
                "SOL position appeared."
            )

        position_id = str(
            position["positionId"]
        )

        real_entry = float(
            position["avgOpenPrice"]
        )

        # ---------------------------------------------
        # RECALCULATE TP/SL FROM REAL FILL
        # ---------------------------------------------

        sl_distance = abs(
            signal["price"]
            - signal["stop_loss"]
        )

        tp_distance = abs(
            signal["take_profit"]
            - signal["price"]
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

        quote_precision = int(
            pair["quotePrecision"]
        )

        real_sl = round(
            real_sl,
            quote_precision
        )

        real_tp = round(
            real_tp,
            quote_precision
        )

        # Save position BEFORE TP/SL request
        # so a restart knows it belongs to us.

        self.active_position_id = (
            position_id
        )

        self.save_state()

        # ---------------------------------------------
        # EXCHANGE-SIDE TP + SL
        # ---------------------------------------------

        try:

            self.client.place_tp_sl(
                position_id,
                real_tp,
                real_sl
            )

        except Exception:

            # Never intentionally leave the live
            # trade without exchange protection.

            print(
                "\nTP/SL FAILED."
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

            raise

        print(
            f"Real entry:       "
            f"${real_entry:.4f}"
        )

        print(
            f"STOP on Bitunix:  "
            f"${real_sl}"
        )

        print(
            f"TARGET on Bitunix:"
            f" ${real_tp}"
        )

        print(
            f"Position ID:      "
            f"{position_id}"
        )


    # =================================================
    # FINALIZE CLOSED TRADE
    # =================================================

    def finalize_trade(self):

        position_id = (
            self.active_position_id
        )

        if not position_id:
            return

        history = None

        # History API can lag slightly.

        for _ in range(10):

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

        # ---------------------------------------------
        # NET PNL
        # ---------------------------------------------

        if history:

            realized = float(
                history.get(
                    "realizedPNL",
                    0
                )
            )

            fee = float(
                history.get(
                    "fee",
                    0
                )
            )

            funding = float(
                history.get(
                    "funding",
                    0
                )
            )

            net_pnl = (
                realized
                - abs(fee)
                + funding
            )

        elif self.balance_before is not None:

            # Fallback if history hasn't appeared.

            net_pnl = (
                new_balance
                - self.balance_before
            )

        else:

            net_pnl = 0

        self.total_trades += 1

        # ---------------------------------------------
        # MARTINGALE RESULT
        # ---------------------------------------------

        if net_pnl > 0:

            result = "WIN"

            self.wins += 1

            # WIN -> back to 1x
            self.loss_streak = 0

        elif net_pnl < 0:

            result = "LOSS"

            self.losses += 1

            # LOSS -> double next trade
            self.loss_streak += 1

        else:

            result = "BREAKEVEN"

        print("\n" + "=" * 60)
        print("🏁 LIVE TRADE FINISHED")
        print("=" * 60)

        print(
            f"Result:           "
            f"{result}"
        )

        print(
            f"Net PnL:          "
            f"${net_pnl:.4f}"
        )

        print(
            f"NEW BALANCE:      "
            f"${new_balance:.4f}"
        )

        print(
            f"Trades:           "
            f"{self.total_trades}"
        )

        print(
            f"Wins / Losses:    "
            f"{self.wins} / {self.losses}"
        )

        print(
            f"Loss streak:      "
            f"{self.loss_streak}"
        )

        print(
            f"NEXT MARTINGALE:  "
            f"{self.multiplier()}x"
        )

        self.active_position_id = None
        self.balance_before = None

        self.save_state()


    # =================================================
    # SYNC WITH REAL BITUNIX
    # =================================================

    def sync(self):

        positions = (
            self.client.get_positions()
        )

        # ---------------------------------------------
        # POSITION EXISTS
        # ---------------------------------------------

        if positions:

            # We don't want to hijack
            # a manual SOL position.

            if not self.active_position_id:

                raise Exception(
                    "There is an existing SOLUSDT "
                    "position on Bitunix that this "
                    "bot did not open. Bot stopped."
                )

            matching = None

            for position in positions:

                if str(
                    position["positionId"]
                ) == str(
                    self.active_position_id
                ):

                    matching = position
                    break

            if matching is None:

                raise Exception(
                    "Bitunix has a SOL position, "
                    "but its ID doesn't match "
                    "the bot state."
                )

            # -----------------------------------------
            # FIVE MINUTE LIMIT
            # -----------------------------------------

            opened_at = (
                int(matching["ctime"])
                / 1000
            )

            age = (
                time.time()
                - opened_at
            )

            print(
                f"\rLIVE {matching['side']} | "
                f"PnL: ${float(matching['unrealizedPNL']):.4f} | "
                f"Age: {int(age)}s / 300s",
                end="",
                flush=True
            )

            if age >= self.max_trade_seconds:

                print(
                    "\n\n⏱️ 5 MINUTES REACHED"
                )

                print(
                    "Closing real position..."
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

        # ---------------------------------------------
        # NO POSITION
        # ---------------------------------------------

        if self.active_position_id:

            # Position was most likely closed
            # by TP or SL.

            print(
                "\nPosition disappeared from "
                "open positions."
            )

            self.finalize_trade()

        return False