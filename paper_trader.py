import json
import time
from pathlib import Path


STATE_FILE = Path(__file__).with_name("trader_state.json")


class PaperTrader:

    def __init__(self, balance=100.0):

        # Defaults - used only when there is no saved state
        self.balance = balance
        self.starting_balance = balance

        self.position = None

        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.breakevens = 0

        self.loss_streak = 0

        # Martingale progression
        self.martingale_multipliers = [
            1,
            2,
            4,
            8,
            16,
            32,
            64,
        ]

        # Base risk = 1%
        self.base_risk_percent = 0.01

        # Maximum trade duration = 5 minutes
        self.max_trade_seconds = 300

        # Load previous session
        self.load_state()


    # =====================================
    # SAVE / LOAD
    # =====================================

    def save_state(self):

        state = {
            "balance": self.balance,
            "starting_balance": self.starting_balance,

            "position": self.position,

            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "breakevens": self.breakevens,

            "loss_streak": self.loss_streak,
        }

        try:
            with open(STATE_FILE, "w") as file:
                json.dump(
                    state,
                    file,
                    indent=4
                )

        except Exception as error:
            print(
                "ERROR saving trader state:",
                error
            )


    def load_state(self):

        if not STATE_FILE.exists():

            print(
                "\nNo previous trader state found."
            )

            print(
                f"Starting fresh with "
                f"${self.balance:.2f}"
            )

            self.save_state()

            return

        try:

            with open(STATE_FILE, "r") as file:
                state = json.load(file)

            self.balance = state.get(
                "balance",
                self.balance
            )

            self.starting_balance = state.get(
                "starting_balance",
                self.starting_balance
            )

            self.position = state.get(
                "position"
            )

            self.total_trades = state.get(
                "total_trades",
                0
            )

            self.wins = state.get(
                "wins",
                0
            )

            self.losses = state.get(
                "losses",
                0
            )

            self.breakevens = state.get(
                "breakevens",
                0
            )

            self.loss_streak = state.get(
                "loss_streak",
                0
            )

            print("\n" + "=" * 55)
            print("💾 PREVIOUS SESSION LOADED")
            print("=" * 55)

            print(
                f"Balance:       "
                f"${self.balance:.2f}"
            )

            print(
                f"Trades:        "
                f"{self.total_trades}"
            )

            print(
                f"Wins:          "
                f"{self.wins}"
            )

            print(
                f"Losses:        "
                f"{self.losses}"
            )

            print(
                f"Loss streak:   "
                f"{self.loss_streak}"
            )

            print(
                f"Next level:    "
                f"{self.current_multiplier()}x"
            )

            if self.position:

                print("\nSaved open trade:")

                print(
                    f"Side:          "
                    f"{self.position['side']}"
                )

                print(
                    f"Entry:         "
                    f"${self.position['entry']:.4f}"
                )

                print(
                    f"Position size: "
                    f"${self.position['size']:.2f}"
                )

            else:

                print(
                    "\nSaved open trade: NONE"
                )

        except Exception as error:

            print(
                "\nERROR loading trader state:",
                error
            )

            print(
                "Starting with default values."
            )


    # =====================================
    # MARTINGALE
    # =====================================

    def current_multiplier(self):

        index = min(
            self.loss_streak,
            len(self.martingale_multipliers) - 1
        )

        return self.martingale_multipliers[
            index
        ]


    def current_risk_percent(self):

        return (
            self.base_risk_percent
            * self.current_multiplier()
        )


    # =====================================
    # POSITION SIZE
    # =====================================

    def calculate_position_size(
        self,
        entry,
        stop_loss
    ):

        risk_percent = (
            self.current_risk_percent()
        )

        risk_dollars = (
            self.balance
            * risk_percent
        )

        stop_distance_percent = (
            abs(entry - stop_loss)
            / entry
        )

        if stop_distance_percent <= 0:
            return 0

        position_size = (
            risk_dollars
            / stop_distance_percent
        )

        return position_size


    # =====================================
    # OPEN POSITION
    # =====================================

    def open_position(
        self,
        side,
        entry,
        stop_loss,
        take_profit,
        signal_strength="UNKNOWN"
    ):

        if self.position is not None:
            return

        multiplier = (
            self.current_multiplier()
        )

        risk_percent = (
            self.current_risk_percent()
        )

        risk_dollars = (
            self.balance
            * risk_percent
        )

        size = self.calculate_position_size(
            entry,
            stop_loss
        )

        self.position = {
            "side": side,

            "entry": entry,

            "stop_loss": stop_loss,

            "take_profit": take_profit,

            "size": size,

            "signal_strength":
                signal_strength,

            "risk_percent":
                risk_percent,

            "risk_dollars":
                risk_dollars,

            "martingale_multiplier":
                multiplier,

            # Real timestamp survives restart
            "opened_at": time.time(),
        }

        # SAVE immediately
        self.save_state()

        print("\n" + "=" * 55)
        print("🚀 PAPER TRADE OPENED")
        print("=" * 55)

        print(
            f"Side:             "
            f"{side}"
        )

        print(
            f"Strength:         "
            f"{signal_strength}"
        )

        print(
            f"Martingale:       "
            f"{multiplier}x"
        )

        print(
            f"Loss streak:      "
            f"{self.loss_streak}"
        )

        print(
            f"Entry:            "
            f"${entry:.4f}"
        )

        print(
            f"Stop:             "
            f"${stop_loss:.4f}"
        )

        print(
            f"Target:           "
            f"${take_profit:.4f}"
        )

        print(
            f"Account risk:     "
            f"{risk_percent * 100:.2f}%"
        )

        print(
            f"Risk dollars:     "
            f"${risk_dollars:.2f}"
        )

        print(
            f"Position size:    "
            f"${size:.2f}"
        )


    # =====================================
    # UPDATE POSITION
    # =====================================

    def update(self, price):

        if self.position is None:
            return

        position = self.position
        side = position["side"]

        # LONG

        if side == "LONG":

            if price <= position["stop_loss"]:

                self.close_position(
                    position["stop_loss"],
                    "STOP"
                )

                return

            if price >= position["take_profit"]:

                self.close_position(
                    position["take_profit"],
                    "TARGET"
                )

                return

        # SHORT

        elif side == "SHORT":

            if price >= position["stop_loss"]:

                self.close_position(
                    position["stop_loss"],
                    "STOP"
                )

                return

            if price <= position["take_profit"]:

                self.close_position(
                    position["take_profit"],
                    "TARGET"
                )

                return

        # ---------------------------------
        # MAXIMUM TRADE TIME
        # ---------------------------------

        elapsed = (
            time.time()
            - position["opened_at"]
        )

        if elapsed >= self.max_trade_seconds:

            self.close_position(
                price,
                "TIME"
            )


    # =====================================
    # CLOSE POSITION
    # =====================================

    def close_position(
        self,
        exit_price,
        reason
    ):

        if self.position is None:
            return

        position = self.position

        entry = position["entry"]
        size = position["size"]

        if position["side"] == "LONG":

            pnl_percent = (
                exit_price - entry
            ) / entry

        else:

            pnl_percent = (
                entry - exit_price
            ) / entry

        pnl = (
            size
            * pnl_percent
        )

        self.balance += pnl

        self.total_trades += 1

        # ---------------------------------
        # RESULT
        # ---------------------------------

        if pnl > 0:

            result = "WIN"

            self.wins += 1

            # Reset Martingale
            self.loss_streak = 0

        elif pnl < 0:

            result = "LOSS"

            self.losses += 1

            # Move to next Martingale level
            self.loss_streak += 1

        else:

            result = "BREAKEVEN"

            self.breakevens += 1

        print("\n" + "=" * 55)
        print("🏁 TRADE CLOSED")
        print("=" * 55)

        print(
            f"Reason:           "
            f"{reason}"
        )

        print(
            f"Result:           "
            f"{result}"
        )

        print(
            f"Exit:             "
            f"${exit_price:.4f}"
        )

        print(
            f"PnL:              "
            f"${pnl:.4f}"
        )

        print(
            f"Balance:          "
            f"${self.balance:.2f}"
        )

        print(
            f"Loss streak:      "
            f"{self.loss_streak}"
        )

        print(
            f"NEXT multiplier:  "
            f"{self.current_multiplier()}x"
        )

        print(
            f"NEXT risk:        "
            f"{self.current_risk_percent() * 100:.2f}%"
        )

        self.position = None

        # SAVE immediately after close
        self.save_state()


    # =====================================
    # UNREALIZED PNL
    # =====================================

    def unrealized_pnl(
        self,
        current_price
    ):

        if self.position is None:
            return 0

        position = self.position

        entry = position["entry"]
        size = position["size"]

        if position["side"] == "LONG":

            percentage = (
                current_price - entry
            ) / entry

        else:

            percentage = (
                entry - current_price
            ) / entry

        return (
            size
            * percentage
        )


    # =====================================
    # POSITION AGE
    # =====================================

    def position_age(self):

        if self.position is None:
            return 0

        return int(
            time.time()
            - self.position["opened_at"]
        )