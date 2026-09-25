import requests
from datetime import datetime


BASE_URL = "https://fapi.bitunix.com"
SYMBOL = "SOLUSDT"


# These are kept for compatibility.
# live_trader.py currently uses its own fixed TP/SL.
SL_ATR_MULTIPLIER = 0.65
TP_ATR_MULTIPLIER = 0.90


# ============================================================
# MARKET DATA
# ============================================================

def get_live_price():
    url = (
        f"{BASE_URL}"
        "/api/v1/futures/market/tickers"
    )

    params = {
        "symbols": SYMBOL
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    result = response.json()

    if str(result.get("code")) != "0":
        raise Exception(
            f"Ticker API error: {result}"
        )

    data = result["data"]

    if not data:
        raise Exception(
            "No ticker data returned"
        )

    ticker = data[0]

    return {
        "last_price":
            float(ticker["lastPrice"]),

        "mark_price":
            float(ticker["markPrice"]),
    }


def get_klines(
    interval,
    limit=200
):
    url = (
        f"{BASE_URL}"
        "/api/v1/futures/market/kline"
    )

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "limit": limit,
        "type": "LAST_PRICE",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    result = response.json()

    if str(result.get("code")) != "0":
        raise Exception(
            f"Kline API error: {result}"
        )

    candles = []

    for candle in result["data"]:
        candles.append({
            "time":
                int(candle["time"]),

            "open":
                float(candle["open"]),

            "high":
                float(candle["high"]),

            "low":
                float(candle["low"]),

            "close":
                float(candle["close"]),

            "volume":
                float(candle["baseVol"]),
        })

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# INDICATORS
# ============================================================

def ema(
    values,
    period
):
    multiplier = (
        2
        / (period + 1)
    )

    current = values[0]

    for value in values[1:]:
        current = (
            value * multiplier
            + current
            * (1 - multiplier)
        )

    return current


def rsi(
    values,
    period=14
):
    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):
        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[-period:])
        / period
    )

    avg_loss = (
        sum(losses[-period:])
        / period
    )

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


def atr(
    candles,
    period=14
):
    ranges = []

    for i in range(
        1,
        len(candles)
    ):
        high = (
            candles[i]["high"]
        )

        low = (
            candles[i]["low"]
        )

        previous_close = (
            candles[i - 1][
                "close"
            ]
        )

        true_range = max(
            high - low,

            abs(
                high
                - previous_close
            ),

            abs(
                low
                - previous_close
            ),
        )

        ranges.append(
            true_range
        )

    return (
        sum(
            ranges[-period:]
        )
        / period
    )


# ============================================================
# SOL STRATEGY
# ============================================================

def analyse_sol():

    # --------------------------------------------------------
    # LIVE PRICE
    # --------------------------------------------------------

    ticker = (
        get_live_price()
    )

    live_price = (
        ticker["last_price"]
    )

    mark_price = (
        ticker["mark_price"]
    )


    # --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candles_1h = get_klines(
        "1h",
        200
    )

    candles_15m = get_klines(
        "15m",
        200
    )

    candles_5m = get_klines(
        "5m",
        100
    )


    close_1h = [
        candle["close"]
        for candle
        in candles_1h
    ]

    close_15m = [
        candle["close"]
        for candle
        in candles_15m
    ]

    close_5m = [
        candle["close"]
        for candle
        in candles_5m
    ]


    candle_price = (
        close_5m[-1]
    )

    previous_close = (
        close_5m[-2]
    )

    three_candles_ago = (
        close_5m[-4]
    )


    # --------------------------------------------------------
    # INDICATORS
    # --------------------------------------------------------

    ema20_1h = ema(
        close_1h,
        20
    )

    ema50_1h = ema(
        close_1h,
        50
    )

    ema200_1h = ema(
        close_1h,
        200
    )


    ema20_15m = ema(
        close_15m,
        20
    )

    ema50_15m = ema(
        close_15m,
        50
    )


    ema20_5m = ema(
        close_5m,
        20
    )


    current_rsi = rsi(
        close_5m
    )

    current_atr = atr(
        candles_5m
    )


    # ========================================================
    # SCORE
    #
    # LONG  = positive
    # SHORT = negative
    #
    # Long-term trend gets SMALLER weight.
    # Short-term movement gets BIGGER weight.
    # ========================================================

    score = 0
    reasons = []


    # --------------------------------------------------------
    # 1H MACRO PRICE
    #
    # Only +/-1 now.
    # --------------------------------------------------------

    if live_price > ema200_1h:

        score += 1

        reasons.append(
            "1H macro bullish +1"
        )

    else:

        score -= 1

        reasons.append(
            "1H macro bearish -1"
        )


    # --------------------------------------------------------
    # 1H EMA TREND
    #
    # Only +/-1.
    # --------------------------------------------------------

    if ema20_1h > ema50_1h:

        score += 1

        reasons.append(
            "1H EMA trend bullish +1"
        )

    else:

        score -= 1

        reasons.append(
            "1H EMA trend bearish -1"
        )


    # --------------------------------------------------------
    # 15M TREND
    #
    # More important: +/-2
    # --------------------------------------------------------

    if ema20_15m > ema50_15m:

        score += 2

        reasons.append(
            "15m trend bullish +2"
        )

    else:

        score -= 2

        reasons.append(
            "15m trend bearish -2"
        )


    # --------------------------------------------------------
    # 5M LOCAL TREND
    #
    # Live price used here so this can react
    # between completed 5m candles.
    # --------------------------------------------------------

    if live_price > ema20_5m:

        score += 2

        reasons.append(
            "5m price above EMA20 +2"
        )

    else:

        score -= 2

        reasons.append(
            "5m price below EMA20 -2"
        )


    # --------------------------------------------------------
    # RECENT 3-CANDLE MOMENTUM
    #
    # Important for flipping direction.
    # --------------------------------------------------------

    if candle_price > three_candles_ago:

        score += 2

        reasons.append(
            "recent 5m momentum bullish +2"
        )

    elif candle_price < three_candles_ago:

        score -= 2

        reasons.append(
            "recent 5m momentum bearish -2"
        )

    else:

        reasons.append(
            "recent 5m momentum flat"
        )


    # --------------------------------------------------------
    # LAST 5M MOMENTUM
    # --------------------------------------------------------

    if candle_price > previous_close:

        score += 1

        reasons.append(
            "latest 5m momentum up +1"
        )

    elif candle_price < previous_close:

        score -= 1

        reasons.append(
            "latest 5m momentum down -1"
        )

    else:

        reasons.append(
            "latest 5m momentum flat"
        )


    # --------------------------------------------------------
    # RSI
    #
    # IMPORTANT:
    #
    # RSI 75 is NOT automatically bullish anymore.
    #
    # Extreme RSI acts against chasing.
    # --------------------------------------------------------

    if current_rsi >= 70:

        score -= 1

        reasons.append(
            f"RSI overbought "
            f"{current_rsi:.1f} -1"
        )


    elif current_rsi >= 55:

        score += 1

        reasons.append(
            f"RSI bullish "
            f"{current_rsi:.1f} +1"
        )


    elif current_rsi <= 30:

        score += 1

        reasons.append(
            f"RSI oversold "
            f"{current_rsi:.1f} +1"
        )


    elif current_rsi <= 45:

        score -= 1

        reasons.append(
            f"RSI bearish "
            f"{current_rsi:.1f} -1"
        )


    else:

        reasons.append(
            f"RSI neutral "
            f"{current_rsi:.1f}"
        )


    # ========================================================
    # DECISION
    # ========================================================

    if score >= 5:

        action = "LONG"

        signal_strength = (
            "STRONG"
        )


    elif score >= 1:

        action = "LONG"

        signal_strength = (
            "WEAK"
        )


    elif score <= -5:

        action = "SHORT"

        signal_strength = (
            "STRONG"
        )


    elif score <= -1:

        action = "SHORT"

        signal_strength = (
            "WEAK"
        )


    else:

        # Score = 0.
        #
        # Still always choose a direction,
        # because this is the high-frequency
        # version of the bot.
        #
        # Use recent movement as the tie-breaker.

        if (
            candle_price
            < three_candles_ago
        ):

            action = "SHORT"

        elif (
            candle_price
            > three_candles_ago
        ):

            action = "LONG"

        else:

            if live_price < ema20_5m:

                action = "SHORT"

            else:

                action = "LONG"


        signal_strength = (
            "VERY WEAK"
        )


    # ========================================================
    # ATR VALUES
    #
    # Kept in return object for compatibility.
    # live_trader.py currently uses fixed:
    #
    # TP = 0.5%
    # SL = 0.25%
    # ========================================================

    if action == "LONG":

        stop_loss = (
            live_price
            - (
                SL_ATR_MULTIPLIER
                * current_atr
            )
        )

        take_profit = (
            live_price
            + (
                TP_ATR_MULTIPLIER
                * current_atr
            )
        )


    else:

        stop_loss = (
            live_price
            + (
                SL_ATR_MULTIPLIER
                * current_atr
            )
        )

        take_profit = (
            live_price
            - (
                TP_ATR_MULTIPLIER
                * current_atr
            )
        )


    # --------------------------------------------------------
    # CANDLE TIME
    # --------------------------------------------------------

    timestamp = (
        candles_5m[-1]["time"]
    )

    last_candle_time = (
        datetime.fromtimestamp(
            timestamp / 1000
        )
        .strftime(
            "%H:%M:%S"
        )
    )


    # --------------------------------------------------------
    # RETURN
    # --------------------------------------------------------

    return {
        "symbol":
            SYMBOL,

        "action":
            action,

        "signal_strength":
            signal_strength,

        "score":
            score,

        "price":
            live_price,

        "mark_price":
            mark_price,

        "candle_price":
            candle_price,

        "rsi":
            current_rsi,

        "atr":
            current_atr,

        "stop_loss":
            stop_loss,

        "take_profit":
            take_profit,

        "last_candle_time":
            last_candle_time,

        "reasons":
            reasons,
    }