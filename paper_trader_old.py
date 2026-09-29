import json
import os


class PaperTrader:

    def __init__(
        self,
        starting_balance=1000,
        filename="paper_account.json"
    ):
        self.filename = filename
        self.starting_balance = starting_balance

        self.balance = starting_balance
        self.position = None

        self.load()


    def load(self):

        if not os.path.exists(self.filename):
            self.save()
            return

        with open(self.filename, "r") as file:
            data = json.load(file)

        self.balance = data["balance"]
        self.position = data["position"]


    def save(self):

        data = {
            "balance": self.balance,
            "position": self.position
        }

        with open(self.filename, "w") as file:
            json.dump(
                data,
                file,
                indent=4
            )


    def open_position(
        self,
        symbol,
        side,
        price,
        amount,
        stop_loss_pct=2,
        take_profit_pct=4
    ):

        if self.position is not None:
            print("Position already open.")
            return

        self.position = {
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "amount": amount,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct
        }

        self.save()

        print(
            f"PAPER {side} {symbol}"
        )

        print(
            f"Entry: ${price:.2f}"
        )

        print(
            f"Position size: ${amount:.2f}"
        )

        print(
            f"Stop loss: {stop_loss_pct}%"
        )

        print(
            f"Take profit: {take_profit_pct}%"
        )


    def close_position(
        self,
        current_price,
        reason="manual"
    ):

        if self.position is None:
            return

        entry = self.position["entry_price"]
        amount = self.position["amount"]
        side = self.position["side"]

        change = (
            current_price - entry
        ) / entry

        if side == "SHORT":
            change *= -1

        profit = amount * change

        self.balance += profit

        print("\n--- POSITION CLOSED ---")

        print(f"Reason: {reason}")
        print(f"Side: {side}")
        print(f"Entry: ${entry:.2f}")
        print(f"Exit:  ${current_price:.2f}")
        print(f"P/L: ${profit:+.2f}")
        print(f"Balance: ${self.balance:.2f}")

        self.position = None

        self.save()


    def check_position(
        self,
        current_price
    ):

        if self.position is None:
            return

        entry = self.position["entry_price"]
        side = self.position["side"]

        change = (
            current_price - entry
        ) / entry * 100

        if side == "SHORT":
            change *= -1

        print("\n--- OPEN PAPER POSITION ---")

        print(
            f"{self.position['symbol']} "
            f"{side}"
        )

        print(
            f"Entry: ${entry:.2f}"
        )

        print(
            f"Current: ${current_price:.2f}"
        )

        print(
            f"Change: {change:+.2f}%"
        )

        if change <= -self.position["stop_loss_pct"]:

            self.close_position(
                current_price,
                "STOP LOSS"
            )

        elif change >= self.position["take_profit_pct"]:

            self.close_position(
                current_price,
                "TAKE PROFIT"
            )