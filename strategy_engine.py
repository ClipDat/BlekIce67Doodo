import requests
from datetime import datetime

BASE_URL = "https://fapi.bitunix.com"
SYMBOL = "SOLUSDT"

# Compatibility values only. live_trader.py uses fixed TP/SL.
SL_ATR_MULTIPLIER = 0.65
TP_ATR_MULTIPLIER = 0.90


def get_live_price():
    response = requests.get(
        f"{BASE_URL}/api/v1/futures/market/tickers",
        params={"symbols": SYMBOL},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()

    if str(result.get("code")) != "0":
        raise Exception(f"Ticker API error: {result}")

    data = result.get("data") or []
    if not data:
        raise Exception("No ticker data returned")

    ticker = data[0]
    return {
        "last_price": float(ticker["lastPrice"]),
        "mark_price": float(ticker["markPrice"]),
    }


def get_klines(interval, limit=200):
    response = requests.get(
        f"{BASE_URL}/api/v1/futures/market/kline",
        params={
            "symbol": SYMBOL,
            "interval": interval,
            "limit": limit,
            "type": "LAST_PRICE",
        },
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()

    if str(result.get("code")) != "0":
        raise Exception(f"Kline API error: {result}")

    candles = []
    for candle in result.get("data", []):
        candles.append(
            {
                "time": int(candle["time"]),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle["baseVol"]),
            }
        )

    candles.sort(key=lambda x: x["time"])
    return candles


def ema(values, period):
    multiplier = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = value * multiplier + current * (1 - multiplier)
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
    ticker = get_live_price()
    live_price = ticker["last_price"]
    mark_price = ticker["mark_price"]

    candles_1h = get_klines("1h", 200)
    candles_15m = get_klines("15m", 200)
    candles_5m = get_klines("5m", 100)

    if len(candles_1h) < 200 or len(candles_15m) < 50 or len(candles_5m) < 20:
        raise Exception("Not enough candle data")

    close_1h = [c["close"] for c in candles_1h]
    close_15m = [c["close"] for c in candles_15m]
    close_5m = [c["close"] for c in candles_5m]

    candle_price = close_5m[-1]
    previous_close = close_5m[-2]
    three_candles_ago = close_5m[-4]

    ema20_1h = ema(close_1h, 20)
    ema50_1h = ema(close_1h, 50)
    ema200_1h = ema(close_1h, 200)

    ema20_15m = ema(close_15m, 20)
    ema50_15m = ema(close_15m, 50)
    ema20_5m = ema(close_5m, 20)

    current_rsi = rsi(close_5m)
    current_atr = atr(candles_5m)

    # Symmetric score. Short-term signals have more influence than the 1h trend.
    score = 0
    reasons = []

    if live_price > ema200_1h:
        score += 1
        reasons.append("1H macro bullish +1")
    else:
        score -= 1
        reasons.append("1H macro bearish -1")

    if ema20_1h > ema50_1h:
        score += 1
        reasons.append("1H EMA trend bullish +1")
    else:
        score -= 1
        reasons.append("1H EMA trend bearish -1")

    if ema20_15m > ema50_15m:
        score += 2
        reasons.append("15m trend bullish +2")
    else:
        score -= 2
        reasons.append("15m trend bearish -2")

    if live_price > ema20_5m:
        score += 2
        reasons.append("5m price above EMA20 +2")
    else:
        score -= 2
        reasons.append("5m price below EMA20 -2")

    if candle_price > three_candles_ago:
        score += 2
        reasons.append("recent 5m momentum bullish +2")
    elif candle_price < three_candles_ago:
        score -= 2
        reasons.append("recent 5m momentum bearish -2")
    else:
        reasons.append("recent 5m momentum flat")

    if candle_price > previous_close:
        score += 1
        reasons.append("latest 5m momentum up +1")
    elif candle_price < previous_close:
        score -= 1
        reasons.append("latest 5m momentum down -1")
    else:
        reasons.append("latest 5m momentum flat")

    # Do not keep rewarding an already overbought market with more LONG score.
    if current_rsi >= 70:
        score -= 1
        reasons.append(f"RSI overbought {current_rsi:.1f} -1")
    elif current_rsi >= 55:
        score += 1
        reasons.append(f"RSI bullish {current_rsi:.1f} +1")
    elif current_rsi <= 30:
        score += 1
        reasons.append(f"RSI oversold {current_rsi:.1f} +1")
    elif current_rsi <= 45:
        score -= 1
        reasons.append(f"RSI bearish {current_rsi:.1f} -1")
    else:
        reasons.append(f"RSI neutral {current_rsi:.1f}")

    if score >= 5:
        action = "LONG"
        signal_strength = "STRONG"
    elif score >= 1:
        action = "LONG"
        signal_strength = "WEAK"
    elif score <= -5:
        action = "SHORT"
        signal_strength = "STRONG"
    elif score <= -1:
        action = "SHORT"
        signal_strength = "WEAK"
    else:
        # High-frequency version always chooses a direction.
        if candle_price < three_candles_ago:
            action = "SHORT"
        elif candle_price > three_candles_ago:
            action = "LONG"
        elif live_price < ema20_5m:
            action = "SHORT"
        else:
            action = "LONG"
        signal_strength = "VERY WEAK"

    # Compatibility fields only; live_trader.py ignores these for real TP/SL.
    if action == "LONG":
        stop_loss = live_price - SL_ATR_MULTIPLIER * current_atr
        take_profit = live_price + TP_ATR_MULTIPLIER * current_atr
    else:
        stop_loss = live_price + SL_ATR_MULTIPLIER * current_atr
        take_profit = live_price - TP_ATR_MULTIPLIER * current_atr

    timestamp = candles_5m[-1]["time"]
    last_candle_time = datetime.fromtimestamp(timestamp / 1000).strftime("%H:%M:%S")

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
