import requests
from datetime import datetime

BASE_URL = "https://fapi.bitunix.com"
SYMBOL = "SOLUSDT"


SL_ATR_MULTIPLIER = 0.65
TP_ATR_MULTIPLIER = 0.90

def get_live_price():
    url = f"{BASE_URL}/api/v1/futures/market/tickers"

    params = {
        "symbols": SYMBOL
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"Ticker API error: {result}")

    data = result["data"]

    if not data:
        raise Exception("No ticker data returned")

    ticker = data[0]

    return {
        "last_price": float(ticker["lastPrice"]),
        "mark_price": float(ticker["markPrice"]),
    }


def get_klines(interval, limit=200):
    url = f"{BASE_URL}/api/v1/futures/market/kline"

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "limit": limit,
        "type": "LAST_PRICE",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"Kline API error: {result}")

    candles = []

    for candle in result["data"]:
        candles.append({
            "time": int(candle["time"]),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["baseVol"]),
        })

    candles.sort(key=lambda x: x["time"])

    return candles


def ema(values, period):
    multiplier = 2 / (period + 1)

    current = values[0]

    for value in values[1:]:
        current = (
            value * multiplier
            + current * (1 - multiplier)
        )

    return current


def rsi(values, period=14):
    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    ranges = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        ranges.append(true_range)

    return sum(ranges[-period:]) / period


def analyse_sol():

    # ---------------------------------
    # LIVE PRICE
    # ---------------------------------

    ticker = get_live_price()

    live_price = ticker["last_price"]
    mark_price = ticker["mark_price"]

    # ---------------------------------
    # MARKET DATA
    # ---------------------------------

    candles_1h = get_klines("1h", 200)
    candles_15m = get_klines("15m", 200)
    candles_5m = get_klines("5m", 100)

    close_1h = [c["close"] for c in candles_1h]
    close_15m = [c["close"] for c in candles_15m]
    close_5m = [c["close"] for c in candles_5m]

    candle_price = close_5m[-1]

    # ---------------------------------
    # INDICATORS
    # ---------------------------------

    ema20_1h = ema(close_1h, 20)
    ema50_1h = ema(close_1h, 50)
    ema200_1h = ema(close_1h, 200)

    ema20_15m = ema(close_15m, 20)
    ema50_15m = ema(close_15m, 50)

    ema20_5m = ema(close_5m, 20)

    current_rsi = rsi(close_5m)
    current_atr = atr(candles_5m)

    # ---------------------------------
    # SCORE
    # ---------------------------------

    score = 0
    reasons = []

    # 1H large trend

    if candle_price > ema200_1h:
        score += 2
        reasons.append("price > 1H EMA200")
    else:
        score -= 2
        reasons.append("price < 1H EMA200")

    # 1H medium trend

    if ema20_1h > ema50_1h:
        score += 2
        reasons.append("1H EMA20 > EMA50")
    else:
        score -= 2
        reasons.append("1H EMA20 < EMA50")

    # 15m trend

    if ema20_15m > ema50_15m:
        score += 2
        reasons.append("15m trend bullish")
    else:
        score -= 2
        reasons.append("15m trend bearish")

    # 5m local trend

    if candle_price > ema20_5m:
        score += 1
        reasons.append("5m price > EMA20")
    else:
        score -= 1
        reasons.append("5m price < EMA20")

    # RSI direction

    if current_rsi > 55:
        score += 1
        reasons.append(f"RSI bullish {current_rsi:.1f}")

    elif current_rsi < 45:
        score -= 1
        reasons.append(f"RSI bearish {current_rsi:.1f}")

    else:
        reasons.append(f"RSI neutral {current_rsi:.1f}")

    # Recent 5m momentum

    previous_close = close_5m[-2]

    if candle_price > previous_close:
        score += 1
        reasons.append("5m momentum up")

    elif candle_price < previous_close:
        score -= 1
        reasons.append("5m momentum down")

    else:
        reasons.append("5m momentum flat")

    # ---------------------------------
    # DECISION
    # ---------------------------------

    if score >= 4:
        action = "LONG"
        signal_strength = "STRONG"

    elif score >= 1:
        action = "LONG"
        signal_strength = "WEAK"

    elif score <= -4:
        action = "SHORT"
        signal_strength = "STRONG"

    elif score <= -1:
        action = "SHORT"
        signal_strength = "WEAK"

    else:

        # Score exactly 0.
        # We still choose a direction.
        if candle_price >= previous_close:
            action = "LONG"
        else:
            action = "SHORT"

        signal_strength = "VERY WEAK"

    if action == "LONG":

        stop_loss = (
            live_price
            - SL_ATR_MULTIPLIER * current_atr
        )

        take_profit = (
            live_price
            + TP_ATR_MULTIPLIER * current_atr
        )

    else:

        stop_loss = (
            live_price
            + SL_ATR_MULTIPLIER * current_atr
        )

        take_profit = (
            live_price
            - TP_ATR_MULTIPLIER * current_atr
        )
    # ---------------------------------
    # CANDLE TIME
    # ---------------------------------

    timestamp = candles_5m[-1]["time"]

    last_candle_time = datetime.fromtimestamp(
        timestamp / 1000
    ).strftime("%H:%M:%S")

    return {
        "symbol": SYMBOL,

        "action": action,
        "signal_strength": signal_strength,
        "score": score,

        "price": live_price,
        "mark_price": mark_price,
        "candle_price": candle_price,

        "rsi": current_rsi,
        "atr": current_atr,

        "stop_loss": stop_loss,
        "take_profit": take_profit,

        "last_candle_time": last_candle_time,

        "reasons": reasons,
    }