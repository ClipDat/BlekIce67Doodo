import requests

BASE_URL = "https://fapi.bitunix.com"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT"
]


def percentage_change(old, new):
    old = float(old)
    new = float(new)

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100


def get_tickers():
    url = BASE_URL + "/api/v1/futures/market/tickers"

    params = {
        "symbols": ",".join(SYMBOLS)
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    return response.json()["data"]


def get_hourly_change(symbol):
    url = BASE_URL + "/api/v1/futures/market/kline"

    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 2
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    candles = response.json()["data"]

    if len(candles) < 2:
        return 0.0

    # Make sure candles are chronological
    candles = sorted(
        candles,
        key=lambda x: int(x["time"])
    )

    previous = candles[-2]
    current = candles[-1]

    return percentage_change(
        previous["close"],
        current["close"]
    )


def get_market_context():

    tickers = get_tickers()

    market = {}

    for ticker in tickers:

        symbol = ticker["symbol"]

        price = float(ticker["lastPrice"])
        open_24h = float(ticker["open"])

        change_24h = percentage_change(
            open_24h,
            price
        )

        change_1h = get_hourly_change(symbol)

        market[symbol] = {
            "price": price,
            "change_1h": round(change_1h, 3),
            "change_24h": round(change_24h, 3),
            "volume_24h": float(ticker["quoteVol"])
        }

    return market
