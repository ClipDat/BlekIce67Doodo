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
    print("Reasons:")
    for reason in signal["reasons"]:
        print(f" - {reason}")


def main():
    print("\n" + "=" * 60)
    print("🔥 BITUNIX SOL LIVE BOT")
    print("=" * 60)
    print("REAL MONEY: YES")
    print("Strategy: HIGH-FREQUENCY SOL")
    print("TP: 0.5%")
    print("SL: 0.25%")
    print("Leverage: 2x -> 4x -> 8x -> 16x -> 32x")
    print("Normal WIN -> 2x")
    print("LOSS -> next leverage; 32x LOSS -> 2x")
    print("Timeout profit -> same leverage")
    print("Timeout loss -> next leverage")
    print("Margin target: 50% of current available balance")
    print("Maximum trade duration: 5 minutes")
    print("Market check: every 15 seconds")
    print()

    client = BitunixClient()
    trader = LiveTrader(client)

    account = client.get_account()
    print(f"State file: {str(__import__('live_trader').STATE_FILE)}")
    print(f"Starting available USDT: ${float(account['available']):.4f}")
    print(f"Position mode: {account.get('positionMode')}")
    print(f"NEXT leverage from state: {trader.current_leverage()}x")

    while True:
        try:
            position_open = trader.sync()

            if not position_open:
                signal = analyse_sol()
                print_signal(signal)

                if signal["action"] in ("LONG", "SHORT"):
                    trader.open_from_signal(signal)

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\nBot stopped manually.")
            break

        except Exception as error:
            print("\n⚠️ LIVE BOT ERROR:")
            print(error)
            print("Retrying in 15 seconds...")
            time.sleep(15)


if __name__ == "__main__":
    main()
