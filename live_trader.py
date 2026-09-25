import os
import json
import time
import uuid
import math
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests
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
# HARD SAFETY LIMITS
# =====================================================

RISK_VERSION = 2

BASE_RISK_PERCENT = 0.005       # 0.5%

MARTINGALE_LEVELS = [
    1,
    2,
    4,
    8,
]

MAX_LOSS_STREAK = 4

MAX_EXCHANGE_LEVERAGE = 10

MAX_DAILY_LOSS_PERCENT = 0.10   # 10%

MAX_TRADE_SECONDS = 300

LEVERAGE_HEADROOM = 1.15

# Liquidation must be at least twice as far
# from entry as our stop-loss.
LIQUIDATION_SAFETY_MULTIPLIER = 2.0


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
                "BITUNIX_API_KEY missing"
            )

        if not self.secret_key:
            raise Exception(
                "BITUNIX_SECRET_KEY missing"
            )


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

            if params[key] is not None:

                query_string += (
                    str(key)
                    + str(params[key])
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

        sign = self._signature(
            nonce,
            timestamp,
            params,
            body
        )

        return {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": sign,
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
            headers=self._headers(params=params),
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
            headers=self._headers(body=body),
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
    # POSITIONS
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

        if isinstance(data, dict):

            positions = data.get(
                "positionList",
                []
            )

        else:

            positions = data

        for position in positions:

            if str(
                position.get("positionId")
            ) == str(position_id):

                return position

        return None


    # =================================================
    # PAIR INFO
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

        leverage = int(leverage)

        # HARD BLOCK
        if leverage > MAX_EXCHANGE_LEVERAGE:

            raise Exception(
                f"SAFETY BLOCK: attempted "
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


    # =================================================
    # MARKET ORDER
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

            "clientId":
                "solsafe_"
                + uuid.uuid4().hex[:20]
        }

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
    # CLOSE
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

    def __init__(
        self,
        client
    )
