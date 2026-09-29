"""
Minimal REST client for the Bitunix Futures API.

Implements exactly the endpoints this bot needs, following the official
docs at https://www.bitunix.com/api-docs/futures/ :

- Sign:                  common/sign.html
- Get single account:    account/get_single_account.html
- Change leverage:       account/change_leverage.html
- Change margin mode:    account/change_margin_mode.html
- Get tickers:           market/get_tickers.html
- Get trading pairs:     market/get_trading_pairs.html
- Place order:           trade/place_order.html
- Get pending positions: position/get_pending_positions.html
- Get history positions: position/get_history_positions.html
- Flash close position:  trade/flash_close_position.html
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Dict, Optional

import requests


class BitunixAPIError(RuntimeError):
    def __init__(self, code: Any, msg: str, payload: Optional[dict] = None):
        super().__init__(f"Bitunix API error {code}: {msg}")
        self.code = code
        self.msg = msg
        self.payload = payload


class BitunixClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str, timeout: float = 10.0):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    # Signing                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sha256_hex(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _sorted_query_string(params: Dict[str, Any]) -> str:
        """queryParams sorted ascending by key, concatenated as key+value, no separators."""
        if not params:
            return ""
        parts = []
        for k in sorted(params.keys()):
            parts.append(f"{k}{params[k]}")
        return "".join(parts)

    @staticmethod
    def _compact_json(body: Optional[dict]) -> str:
        if not body:
            return ""
        # compact separators -> no spaces, matches what must be sent on the wire
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False)

    def _sign(self, nonce: str, timestamp: str, query_string: str, body_str: str) -> str:
        digest_input = nonce + timestamp + self.api_key + query_string + body_str
        digest = self._sha256_hex(digest_input)
        sign_input = digest + self.api_secret
        return self._sha256_hex(sign_input)

    def _headers(self, query_params: Optional[dict], body: Optional[dict]) -> Dict[str, str]:
        nonce = secrets.token_hex(16)  # 32 hex chars
        timestamp = str(int(time.time() * 1000))
        query_string = self._sorted_query_string(query_params or {})
        body_str = self._compact_json(body)
        sign = self._sign(nonce, timestamp, query_string, body_str)
        return {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": sign,
            "language": "en-US",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Low level request                                                   #
    # ------------------------------------------------------------------ #
    def _send(self, method: str, path: str, query: Optional[dict], body: Optional[dict],
              signed: bool) -> Any:
        """One HTTP call. GET requests are retried on network hiccups / 429 / 5xx.
        POST requests (orders) are NEVER retried, to avoid duplicate orders."""
        url = f"{self.base_url}{path}"
        body_str = self._compact_json(body) if body else None
        attempts = 4 if method == "GET" else 1

        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                headers = self._headers(query, body) if signed else None  # fresh nonce each try
                resp = self.session.request(method, url, params=query,
                                            data=body_str,  # EXACT string that was signed
                                            headers=headers, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.exceptions.ConnectionError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json()
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError):
                if last:
                    raise
                self.session.close()
                self.session = requests.Session()  # drop a possibly dead connection
                time.sleep(2 ** attempt)           # 1s, 2s, 4s

        if payload.get("code") not in (0, "0"):
            raise BitunixAPIError(payload.get("code"), payload.get("msg", "unknown error"), payload)
        return payload.get("data")

    def _request(self, method: str, path: str, query: Optional[dict] = None,
                 body: Optional[dict] = None) -> Any:
        return self._send(method, path, query, body, signed=True)

    def _public_get(self, path: str, query: Optional[dict] = None) -> Any:
        """Unsigned GET for public market data (works without API keys)."""
        return self._send("GET", path, query, None, signed=False)

    # ------------------------------------------------------------------ #
    # Account                                                             #
    # ------------------------------------------------------------------ #
    def get_single_account(self, margin_coin: str) -> dict:
        data = self._request("GET", "/api/v1/futures/account", query={"marginCoin": margin_coin})
        # API returns either a dict or a one-element list depending on version; normalize.
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def change_leverage(self, symbol: str, leverage: int, margin_coin: str) -> Any:
        return self._request(
            "POST",
            "/api/v1/futures/account/change_leverage",
            body={"symbol": symbol, "leverage": int(leverage), "marginCoin": margin_coin},
        )

    def change_margin_mode(self, symbol: str, margin_mode: str, margin_coin: str) -> Any:
        """margin_mode: 'ISOLATION' or 'CROSS'. Only works with no open position/orders."""
        return self._request(
            "POST",
            "/api/v1/futures/account/change_margin_mode",
            body={"marginMode": margin_mode, "symbol": symbol, "marginCoin": margin_coin},
        )

    # ------------------------------------------------------------------ #
    # Market data                                                         #
    # ------------------------------------------------------------------ #
    def get_ticker(self, symbol: str) -> dict:
        data = self._public_get("/api/v1/futures/market/tickers", {"symbols": symbol})
        if not data:
            raise BitunixAPIError("empty", f"No ticker data for {symbol}")
        return data[0]

    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        """Candles (public). interval like 1m 5m 15m 1h. Max 200 per request."""
        data = self._public_get("/api/v1/futures/market/kline",
                                {"symbol": symbol, "interval": interval, "limit": limit})
        return data or []

    def get_trading_pair(self, symbol: str) -> dict:
        data = self._public_get("/api/v1/futures/market/trading_pairs", {"symbols": symbol})
        if not data:
            raise BitunixAPIError("empty", f"No trading pair info for {symbol}")
        return data[0]

    # ------------------------------------------------------------------ #
    # Trading                                                             #
    # ------------------------------------------------------------------ #
    def place_order(self, symbol: str, side: str, qty: str, order_type: str = "MARKET",
                     trade_side: str = "OPEN", price: Optional[str] = None,
                     tp_price: Optional[str] = None, sl_price: Optional[str] = None,
                     position_id: Optional[str] = None, client_id: Optional[str] = None) -> dict:
        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,              # BUY or SELL
            "tradeSide": trade_side,   # OPEN or CLOSE
            "qty": qty,
            "orderType": order_type,   # MARKET or LIMIT
        }
        if order_type == "LIMIT":
            body["effect"] = "GTC"
            if price is not None:
                body["price"] = price
        if position_id is not None:
            body["positionId"] = position_id
        if client_id is not None:
            body["clientId"] = client_id
        if tp_price is not None:
            body["tpPrice"] = tp_price
            body["tpStopType"] = "MARK_PRICE"
            body["tpOrderType"] = "MARKET"
        if sl_price is not None:
            body["slPrice"] = sl_price
            body["slStopType"] = "MARK_PRICE"
            body["slOrderType"] = "MARKET"
        return self._request("POST", "/api/v1/futures/trade/place_order", body=body)

    def get_pending_positions(self, symbol: str) -> list:
        data = self._request("GET", "/api/v1/futures/position/get_pending_positions",
                              query={"symbol": symbol})
        return data or []

    def get_history_positions(self, symbol: str, limit: int = 5) -> list:
        data = self._request("GET", "/api/v1/futures/position/get_history_positions",
                              query={"symbol": symbol, "limit": limit})
        if isinstance(data, dict):
            return data.get("positionList", [])
        return data or []

    def flash_close_position(self, position_id: str) -> Any:
        """Emergency market-close of a position, used only for manual/kill-switch use."""
        return self._request("POST", "/api/v1/futures/trade/flash_close_position",
                              body={"positionId": position_id})
