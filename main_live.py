import time

from strategy_engine import analyse_sol
from live_trader import BitunixClient, LiveTrader


CHECK_INTERVAL = 15


def print_signal(signal):

    print("\n" + "=" * 60)
    print("SOL LIVE STRATEGY")
    print("=" * 60)

    print(
        f"Live Price:   "
        f"${signal['price']:.4f}"
    )

    print(
        f"Mark Price:   "
        f"${signal['mark_price']:.4f}"
    )

    print(
        f"5m Close:     "
        f"${signal['candle_price']:.4f}"
    )

    print(
        f"5m Candle:    "
        f"{signal['last_candle_time']}"
    )

    print(
        f"Direction:    "
        f"{signal['action']}"
    )

    print(
        f"Strength:     "
        f"{signal['signal_strength']}"
    )

    print(
        f"Score:        "
        f"{signal['score']}"
    )

    print(
        f"RSI:          "
        f"{signal['rsi']:.2f}"
    )

    print(
        f"ATR:          "
        f"{signal['atr']:.4f}"
    )

    print(
        f"Suggested SL: "
        f"${signal['stop_loss']:.4f}"
    )

    print(
        f"Suggested TP: "
        f"${signal['take_profit']:.4f}"
    )

    print("\nReasons:")

    for reason in signal["reasons"]:
        print(
            f" - {reason}"
        )


def main():

    print("\n" + "=" * 60)
    print("🔥 BITUNIX SOL LIVE BOT")
    print("=" * 60)

    print("REAL MONEY: YES")
    print("Strategy: HIGH-FREQUENCY SOL")
    print("Decision engine: strategy_engine.py")
    print("Maximum trade duration: 5 minutes")
    print("Market check: every 15 seconds")
    print()

    # ---------------------------------------------
    # BITUNIX
    # ---------------------------------------------

    client = BitunixClient()

    trader = LiveTrader(
        client
    )

    account = client.get_account()

    print(
        f"Starting available USDT: "
        f"${float(account['available']):.4f}"
    )

    print(
        f"Position mode: "
        f"{account['positionMode']}"
    )

    # ---------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------

    while True:

        try:

            # =====================================
            # FIRST:
            # CHECK REAL BITUNIX POSITION
            # =====================================

            position_open = (
                trader.sync()
            )

            # =====================================
            # BOT HALTED?
            # =====================================

            if trader.trading_halted:

                print(
                    "\n🛑 BOT ONLINE, "
                    "BUT NEW TRADES ARE HALTED"
                )

                print(
                    f"Reason: "
                    f"{trader.halt_reason}"
                )

                time.sleep(
                    60
                )

                continue

            # =====================================
            # NO POSITION:
            # FIND NEXT DIRECTION
            # =====================================

            if not position_open:

                signal = (
                    analyse_sol()
                )

                print_signal(
                    signal
                )

                # strategy_engine almost always
                # returns LONG or SHORT

                if signal["action"] in [
                    "LONG",
                    "SHORT"
                ]:

                    opened = (
                        trader.open_from_signal(
                            signal
                        )
                    )

                    if not opened:

                        print(
                            "\nNo trade opened "
                            "for this setup."
                        )

                else:

                    print(
                        "\nNo actionable signal."
                    )

            # =====================================
            # WAIT
            # =====================================

            time.sleep(
                CHECK_INTERVAL
            )

        except KeyboardInterrupt:

            print(
                "\n\nBot stopped manually."
            )

            print(
                "Any existing Bitunix position "
                "remains on the exchange."
            )

            break

        except Exception as error:

            print(
                "\n\nLIVE BOT ERROR:"
            )

            print(
                error
            )

            print(
                "Retrying in 15 seconds..."
            )

            time.sleep(
                15
            )


if __name__ == "__main__":
    main()