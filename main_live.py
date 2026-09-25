import time

from strategy_engine import analyse_sol
from live_trader import BitunixClient, LiveTrader


CHECK_INTERVAL = 15


def print_signal(signal):
    print("\n" + "=" * 60)
    print("SOL LIVE STRATEGY")
    print("=" * 60)

    print(f"Live Price:   ${signal['price']:.4f}")
    print(f"Mark Price:   ${signal['mark_price']:.4f}")
    print(f"5m Close:     ${signal['candle_price']:.4f}")
    print(f"5m Candle:    {signal['last_candle_time']}")
    print(f"Direction:    {signal['action']}")
    print(f"Strength:     {signal['signal_strength']}")
    print(f"Score:        {signal['score']}")
    print(f"RSI:          {signal['rsi']:.2f}")
    print(f"ATR:          {signal['atr']:.4f}")
    print(f"Suggested SL: ${signal['stop_loss']:.4f}")
    print(f"Suggested TP: ${signal['take_profit']:.4f}")

    print("\nReasons:")

    for reason in signal["reasons"]:
        print(f" - {reason}")


def main():
    print("\n" + "=" * 60)
    print("🔥 BITUNIX SOL LIVE BOT")
    print("=" * 60)
    print("REAL MONEY: YES")
    print("Strategy: HIGH-FREQUENCY SOL")
    print("Leverage cycle: 2x -> 4x -> 8x -> 16x -> 32x")
    print("WIN -> 2x")
    print("32x LOSS -> 2x")
    print("Maximum trade duration: 5 minutes")
    print("Market check: every 15 seconds")
    print()

    client = BitunixClient()
    trader = LiveTrader(client)

    account = client.get_account()

    print(
        f"Starting available USDT: "
        f"${float(account['available']):.4f}"
    )

    print(
        f"Position mode: "
        f"{account.get('positionMode')}"
    )

    print(
        f"Starting leverage level: "
        f"{trader.current_leverage()}x"
    )

    while True:
        try:
            # First check whether an existing
            # real Bitunix position is still open.
            position_open = trader.sync()

            # If not, immediately look for another trade.
            if not position_open:
                signal = analyse_sol()

                print_signal(signal)

                if signal["action"] in ("LONG", "SHORT"):
                    opened = trader.open_from_signal(signal)

                    if not opened:
                        print("\nNo trade opened this cycle.")

                else:
                    print("\nNo actionable signal.")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nBot stopped manually.")
            print(
                "An existing Bitunix position, if any, "
                "remains managed by the exchange TP/SL."
            )
            break

        except Exception as error:
            print("\n\n⚠️ LIVE BOT ERROR:")
            print(error)
            print("Retrying in 15 seconds...")

            time.sleep(15)


if __name__ == "__main__":
    main()