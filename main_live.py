import time

from strategy_engine import analyse_sol

from live_trader import (
    BitunixClient,
    LiveTrader
)


CHECK_INTERVAL = 5


def print_signal(signal):

    print("\n" + "=" * 60)
    print("SOL LIVE STRATEGY")
    print("=" * 60)

    print(
        f"Price:       "
        f"${signal['price']:.4f}"
    )

    print(
        f"Direction:   "
        f"{signal['action']}"
    )

    print(
        f"Strength:    "
        f"{signal['signal_strength']}"
    )

    print(
        f"Score:       "
        f"{signal['score']}"
    )

    print(
        f"RSI:         "
        f"{signal['rsi']:.2f}"
    )

    print(
        f"ATR:         "
        f"{signal['atr']:.4f}"
    )

    print(
        f"Suggested SL:"
        f" ${signal['stop_loss']:.4f}"
    )

    print(
        f"Suggested TP:"
        f" ${signal['take_profit']:.4f}"
    )


def main():

    print("\n" + "=" * 60)
    print("🔥 BITUNIX SOL LIVE BOT")
    print("=" * 60)

    print("REAL MONEY: YES")
    print("Pair: SOLUSDT")
    print("Maximum position time: 5 minutes")
    print("Martingale: 1x → 2x → 4x → 8x → 16x → 32x → 64x")
    print()

    client = BitunixClient()

    trader = LiveTrader(
        client
    )

    account = (
        client.get_account()
    )

    print(
        f"Starting available USDT: "
        f"${float(account['available']):.4f}"
    )

    print(
        f"Position mode: "
        f"{account['positionMode']}"
    )

    while True:

        try:

            # =========================================
            # FIRST:
            # synchronize with REAL Bitunix positions
            # =========================================

            position_open = (
                trader.sync()
            )

            # =========================================
            # IF NO POSITION:
            # generate next trade immediately
            # =========================================

            if not position_open:

                signal = (
                    analyse_sol()
                )

                print_signal(
                    signal
                )

                trader.open_from_signal(
                    signal
                )

            time.sleep(
                CHECK_INTERVAL
            )

        except KeyboardInterrupt:

            print(
                "\n\nBot stopped."
            )

            print(
                "IMPORTANT: an open position "
                "remains protected by Bitunix "
                "TP/SL even though Python stopped."
            )

            break

        except Exception as error:

            print(
                "\n\nLIVE BOT ERROR:"
            )

            print(
                error
            )

            # Don't spam API / orders after error
            time.sleep(10)


if __name__ == "__main__":
    main()