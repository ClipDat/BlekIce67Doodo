"""
Paper-trading broker: virtual balance, REAL live prices.

Simulates exactly what the live bot would do on Bitunix:
- isolated margin, position size = margin * leverage
- TP/SL triggered by the real price stream
- taker fees on both sides and a small slippage per fill
- estimated liquidation (position margin is lost if price reaches it)

Deliberately conservative choices:
- Stop-loss fills at the price actually observed (so a gap through the SL is
  a worse loss than -0.5%), take-profit fills exactly at the TP price.
- Slippage always works against you.

NOT simulated: funding fees, order-book depth/partial fills, exchange
downtime, and price moves between two polls (it samples every few seconds).
So treat results as a realistic-but-still-slightly-optimistic estimate.
"""
from __future__ import annotations

import csv
import os
import time
from typing import Any, Dict, Optional

from .risk_manager import estimate_liquidation_distance_fraction


class PaperBroker:
    def __init__(self, initial_balance: float, fee_rate: float, slippage: float,
                 csv_path: str, saved: Optional[Dict[str, Any]] = None):
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.csv_path = csv_path

        saved = saved or {}
        self.initial_balance: float = saved.get("initial_balance", initial_balance)
        self.balance: float = saved.get("balance", initial_balance)
        self.position: Optional[Dict[str, Any]] = saved.get("position")
        self.stats: Dict[str, Any] = saved.get("stats") or {
            "trades": 0, "wins": 0, "losses": 0, "liquidations": 0,
            "peak_balance": initial_balance, "max_drawdown": 0.0,
            "max_leverage_used": 0, "max_loss_streak": 0, "loss_streak": 0,
            "total_fees": 0.0,
        }

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {"initial_balance": self.initial_balance, "balance": self.balance,
                "position": self.position, "stats": self.stats}

    # ------------------------------------------------------------------ #
    def open(self, direction: str, price: float, qty: float, leverage: int,
             margin: float, tp_pct: float, sl_pct: float, mmr: float = 0.005) -> Dict[str, Any]:
        sign = 1 if direction == "LONG" else -1
        entry = price * (1 + sign * self.slippage)          # slippage hurts you
        liq_dist = estimate_liquidation_distance_fraction(leverage, mmr)
        self.position = {
            "direction": direction, "sign": sign, "entry": entry, "qty": qty,
            "leverage": leverage, "margin": margin,
            "tp": entry * (1 + sign * tp_pct),
            "sl": entry * (1 - sign * sl_pct),
            "liq": entry * (1 - sign * liq_dist),
            "opened_at": time.time(),
        }
        self.stats["max_leverage_used"] = max(self.stats["max_leverage_used"], leverage)
        return self.position

    # ------------------------------------------------------------------ #
    def on_price(self, price: float) -> Optional[Dict[str, Any]]:
        """Feed a live price. Returns a result dict when the position closes."""
        pos = self.position
        if pos is None:
            return None
        s = pos["sign"]

        reason = None
        exit_price = price
        if (price - pos["liq"]) * s <= 0:
            reason, exit_price = "LIQUIDATED", pos["liq"]
        elif (price - pos["sl"]) * s <= 0:
            reason, exit_price = "SL", price                  # actual observed price (gap-aware)
        elif (price - pos["tp"]) * s >= 0:
            reason, exit_price = "TP", pos["tp"]
        if reason is None:
            return None

        if reason != "LIQUIDATED":
            exit_price = exit_price * (1 - s * self.slippage)  # slippage hurts you
        gross = (exit_price - pos["entry"]) * pos["qty"] * s
        fees = self.fee_rate * pos["qty"] * (pos["entry"] + exit_price)
        net = gross - fees
        if reason == "LIQUIDATED":
            net = -pos["margin"]
            fees = self.fee_rate * pos["qty"] * pos["entry"]
        net = max(net, -self.balance)                          # can't lose more than you have

        self.balance += net
        st = self.stats
        st["trades"] += 1
        st["total_fees"] += fees
        if net > 0:
            st["wins"] += 1
            st["loss_streak"] = 0
        else:
            st["losses"] += 1
            st["loss_streak"] += 1
            st["max_loss_streak"] = max(st["max_loss_streak"], st["loss_streak"])
        if reason == "LIQUIDATED":
            st["liquidations"] += 1
        st["peak_balance"] = max(st["peak_balance"], self.balance)
        if st["peak_balance"] > 0:
            st["max_drawdown"] = max(st["max_drawdown"],
                                     1 - self.balance / st["peak_balance"])

        result = {"reason": reason, "net": net, "fees": fees, "exit": exit_price,
                  "entry": pos["entry"], "direction": pos["direction"],
                  "leverage": pos["leverage"], "qty": pos["qty"], "margin": pos["margin"],
                  "balance": self.balance}
        self._append_csv(result)
        self.position = None
        return result

    # ------------------------------------------------------------------ #
    def _append_csv(self, r: Dict[str, Any]) -> None:
        new_file = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time_utc", "direction", "leverage", "entry", "exit", "qty",
                            "margin", "result", "net_pnl", "fees", "balance_after"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), r["direction"],
                        r["leverage"], f'{r["entry"]:.4f}', f'{r["exit"]:.4f}', r["qty"],
                        f'{r["margin"]:.4f}', r["reason"], f'{r["net"]:.4f}',
                        f'{r["fees"]:.4f}', f'{r["balance"]:.4f}'])

    def summary(self) -> str:
        st = self.stats
        wr = (st["wins"] / st["trades"] * 100) if st["trades"] else 0.0
        pnl_pct = (self.balance / self.initial_balance - 1) * 100
        return (f"PAPER | balance=${self.balance:.2f} ({pnl_pct:+.1f}%) | trades={st['trades']} "
                f"win-rate={wr:.0f}% | max-loss-streak={st['max_loss_streak']} | "
                f"max-leverage={st['max_leverage_used']}x | liquidations={st['liquidations']} | "
                f"max-drawdown={st['max_drawdown'] * 100:.0f}% | fees=${st['total_fees']:.2f}")
