"""
Entry signal built on the detectors in indicators.py.

Idea (classic "retest" setup):
  1. Market structure gives the bias: last break bullish (BOS/CHoCH) -> only LONGS,
     last break bearish -> only SHORTS.
  2. Wait until the live price pulls back INTO a fresh, unmitigated zone of the
     same direction (bullish FVG / bullish Order Block for longs, and vice versa).
  3. Score: +1 per zone the price is inside (FVG + OB overlapping = 2),
     +1 if there was a matching liquidity sweep in the last 10 candles.
     A trade needs at least one zone AND score >= SMC_MIN_SCORE.

Unlike the EMA strategy this is NOT always in the market: most of the time
direction() returns None and the bot simply waits.
"""
from __future__ import annotations

from typing import List, Optional

from .indicators import Analysis, Candle, Zone, analyze


class SmcSignal:
    def __init__(self, swing_n: int, min_zone_pct: float, zone_max_age: int,
                 first_touch_only: bool, min_score: int, tolerance: float):
        self.swing_n = swing_n
        self.min_zone_pct = min_zone_pct
        self.zone_max_age = zone_max_age
        self.first_touch_only = first_touch_only
        self.min_score = min_score
        self.tolerance = tolerance
        self.analysis: Optional[Analysis] = None
        self.reason = ""

    def update(self, candles: List[Candle]) -> None:
        self.analysis = analyze(candles, self.swing_n, self.min_zone_pct)

    # ------------------------------------------------------------------ #
    def _usable(self, z: Zone, side: str) -> bool:
        a = self.analysis
        if z.side != side or z.invalid:
            return False
        if a.n - z.created > self.zone_max_age:
            return False
        if self.first_touch_only and z.touched:
            return False
        return True

    def direction(self, price: float) -> Optional[str]:
        a = self.analysis
        self.reason = ""
        if a is None or a.trend is None:
            return None
        side = a.trend
        hits = [z for z in a.zones if self._usable(z, side)
                and z.low * (1 - self.tolerance) <= price <= z.high * (1 + self.tolerance)]
        if not hits:
            return None

        sweep = any(e.kind == "SWEEP" and e.side == side and e.index >= a.n - 10 for e in a.events)
        score = len(hits) + (1 if sweep else 0)
        if score < self.min_score:
            return None

        last_break = next((e for e in reversed(a.events) if e.kind in ("BOS", "CHoCH")), None)
        parts = [f"{z.kind} {z.low:.4f}-{z.high:.4f}" for z in hits]
        if sweep:
            parts.append("liquidity sweep")
        self.reason = (f"{side} trend ({last_break.kind if last_break else '?'}) | "
                       f"price {price:.4f} in " + " + ".join(parts) + f" | score {score}")
        return "LONG" if side == "bull" else "SHORT"

    def describe(self, price: float) -> str:
        a = self.analysis
        if a is None:
            return "SMC: no candle data yet"
        if a.trend is None:
            return f"SMC: no market structure yet ({a.n} candles)"
        zones = [z for z in a.zones if self._usable(z, a.trend)]
        text = f"SMC: trend={a.trend} | {len(zones)} usable {a.trend} zone(s) | price={price:.4f}"
        if zones:
            def dist(z: Zone) -> float:
                return 0.0 if z.low <= price <= z.high else min(abs(price - z.low), abs(price - z.high)) / price
            z = min(zones, key=dist)
            text += f" | nearest {z.kind} {z.low:.4f}-{z.high:.4f} ({dist(z) * 100:.2f}% away)"
        return text
