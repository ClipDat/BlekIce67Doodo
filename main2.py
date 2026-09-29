import os
import time
import secrets
import hashlib
import requests

from dotenv import load_dotenv
from news_feed import get_new_articles
from paper_trader import PaperTrader
from signal_engine import analyze_news
from market_data import get_market_context
from ntfy_listener import listen_for_news

# --------------------------------------------------
# LOAD API KEYS
# --------------------------------------------------

load_dotenv()

API_KEY = os.getenv("BITUNIX_API_KEY")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY")

BASE_URL = "https://fapi.bitunix.com"


# --------------------------------------------------
# BITUNIX AUTHENTICATION
# --------------------------------------------------

def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def create_signature(params):

    nonce = secrets.token_hex(16)

    timestamp = str(
        int(time.time() * 1000)
    )

    query_string = ""

    for key in sorted(params):
        query_string += key + str(params[key])

    body = ""

    first_hash = sha256(
        nonce
        + timestamp
        + API_KEY
        + query_string
        + body
    )

    signature = sha256(
        first_hash + SECRET_KEY
    )

    return nonce, timestamp, signature


# --------------------------------------------------
# GET BITUNIX ACCOUNT
# --------------------------------------------------

def get_account():

    params = {
        "marginCoin": "USDT"
    }

    nonce, timestamp, signature = create_signature(
        params
    )

    headers = {
        "api-key": API_KEY,
        "nonce": nonce,
        "timestamp": timestamp,
        "sign": signature,
        "Content-Type": "application/json",
        "language": "en-US"
    }

    url = BASE_URL + "/api/v1/futures/account"

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    return response.json()


# --------------------------------------------------
# START BOT
# --------------------------------------------------

print("\n--- BITUNIX NEWS BOT ---")


# --------------------------------------------------
# ACCOUNT INFORMATION
# --------------------------------------------------

try:

    account_data = get_account()

    account = account_data["data"]

    if isinstance(account, list):
        account = account[0]

    print(
        f"Available USDT: "
        f"{float(account['available']):.4f}"
    )

    cross_pnl = float(
        account.get(
            "crossUnrealizedPNL",
            0
        )
    )

    isolation_pnl = float(
        account.get(
            "isolationUnrealizedPNL",
            0
        )
    )

    total_pnl = (
        cross_pnl
        + isolation_pnl
    )

    print(
        f"Unrealized PNL: "
        f"{total_pnl:.4f} USDT"
    )

except Exception as error:

    print(
        "Could not load Bitunix account:"
    )

    print(error)


# --------------------------------------------------
# GET LIVE MARKET DATA
# --------------------------------------------------

print("\n--- MARKET ---")

try:

    market = get_market_context()

except Exception as error:

    print(
        "Could not load market data:"
    )

    print(error)

    exit()


for symbol, data in market.items():

    print(
        f"{symbol}: "
        f"${data['price']:.2f} | "
        f"1H {data['change_1h']:+.2f}% | "
        f"24H {data['change_24h']:+.2f}%"
    )


# --------------------------------------------------
# CREATE PAPER TRADER
# --------------------------------------------------

trader = PaperTrader(
    starting_balance=1000
)

print(
    f"Paper balance: ${trader.balance:.2f}"
)

if trader.position is not None:

    symbol = trader.position["symbol"]

    current_price = market[
        symbol
    ]["price"]

    trader.check_position(
        current_price
    )

# --------------------------------------------------
# AUTOMATIC NEWS LOOP
# --------------------------------------------------

print("\n--- AUTOMATIC NEWS MODE ---")

print("Watching for new headlines...")
print("Press Ctrl+C to stop.\n")


while True:

    try:

        # ------------------------------------------
        # REFRESH MARKET DATA
        # ------------------------------------------

        market = get_market_context()


        # ------------------------------------------
        # CHECK OPEN PAPER POSITION
        # ------------------------------------------

        if trader.position is not None:

            symbol = trader.position["symbol"]

            current_price = market[
                symbol
            ]["price"]

            trader.check_position(
                current_price
            )


        # ------------------------------------------
        # FETCH NEW NEWS
        # ------------------------------------------

        articles = get_new_articles()


        if len(articles) > 0:

            print(
                f"\nFound "
                f"{len(articles)} new article(s)"
            )


        # ------------------------------------------
        # ANALYZE EVERY NEW ARTICLE
        # ------------------------------------------

        for article in articles:

            print(
                "\n================================"
            )

            print(
                f"SOURCE: "
                f"{article['source']}"
            )

            print(
                f"NEWS: "
                f"{article['title']}"
            )

            headline = (
                article["title"]
                + " | Source: "
                + article["source"]
            )


            # --------------------------------------
            # AI ANALYSIS
            # --------------------------------------

            signal = analyze_news(
                headline,
                market
            )


            print("\n--- AI SIGNAL ---")

            print(
                f"Symbol: "
                f"{signal['symbol']}"
            )

            print(
                f"Action: "
                f"{signal['action']}"
            )

            print(
                f"Confidence: "
                f"{signal['confidence']}%"
            )

            print(
                f"Duration: "
                f"{signal['duration']}"
            )

            print(
                f"Reason: "
                f"{signal['reason']}"
            )


            # --------------------------------------
            # PAPER TRADE RULE
            # --------------------------------------

            if (
                signal["action"]
                != "IGNORE"

                and signal["confidence"]
                >= 70

                and trader.position
                is None
            ):

                symbol = signal[
                    "symbol"
                ]

                trade_price = market[
                    symbol
                ]["price"]

                print(
                    "\n--- PAPER TRADE ---"
                )

                trader.open_position(
                    symbol=symbol,
                    side=signal["action"],
                    price=trade_price,
                    amount=100,
                    stop_loss_pct=2,
                    take_profit_pct=4
                )

            elif (
                signal["action"]
                != "IGNORE"
                and signal["confidence"]
                < 70
            ):

                print(
                    "\nSignal rejected: "
                    "confidence below 70%."
                )

            elif trader.position is not None:

                print(
                    "\nSignal rejected: "
                    "position already open."
                )


        # ------------------------------------------
        # WAIT
        # ------------------------------------------

        time.sleep(60)


    except KeyboardInterrupt:

        print(
            "\nBot stopped."
        )

        break


    except Exception as error:

        print(
            "\nBot error:"
        )

        print(error)

        print(
            "Retrying in 60 seconds..."
        )

        time.sleep(60)

