"""
Mechanical detectors for Smart-Money-Concepts style indicators.

These are ONE precise, rule-based interpretation of concepts that traders
often draw by eye. Different people draw them differently, so treat the
definitions below as the contract of this bot (and tweak them if you disagree).

Only CLOSED candles are analysed, and nothing looks into the future: every
level is only used after the candles needed to confirm it have closed.

Definitions
-----------
Swing high / low   A candle whose high (low) is higher (lower) than the `swing_n`
                   candles on its left and not lower (higher) than the `swing_n`
                   candles on its right. Known only `swing_n` candles later.
BOS                Break Of Structure: a candle CLOSES beyond the latest unbroken
                   swing high (bullish) / swing low (bearish) in the direction of
                   the current trend. Each swing can be broken only once.
CHoCH              Change Of Character: same as BOS but against the previous
                   trend (first break of the opposite side). Flips the trend.
Liquidity sweep    A candle WICKS beyond the latest unbroken swing level but
                   CLOSES back inside it (stop-hunt / rejection).
FVG                Fair Value Gap: 3 candles where candle 1 and candle 3 do not
                   overlap. Bullish: low[3] > high[1] -> zone [high[1], low[3]].
                   Bearish: high[3] < low[1] -> zone [high[3], low[1]].
Order Block        On a bullish break, the candle with the LOWEST low between the
                   broken swing high and the breaking candle (bearish break:
                   highest high). Zone = that candle's full high-low range.
Touched            A later closed candle already traded into the zone.
Invalid            A later candle CLOSED through the far side of the zone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}


@dataclass
class Candle:
    t: int      # open time, ms
    o: float
    h: float
    l: float
    c: float


@dataclass
class Zone:
    kind: str          # "FVG" or "OB"
    side: str          # "bull" or "bear"
    low: float
    high: float
    created: int       # index of the candle on which the zone became known
    touched: bool = False
    invalid: bool = False


@dataclass
class Event:
    kind: str          # "BOS", "CHoCH" or "SWEEP"
    side: str          # "bull" / "bear"  (SWEEP of lows = "bull", sweep of highs = "bear")
    index: int
    level: float


@dataclass
class Analysis:
    trend: Optional[str]
    events: List[Event]
    zones: List[Zone]
    n: int


def parse_klines(raw: list, interval: str, now_ms: int) -> List[Candle]:
    """Bitunix kline rows -> ascending list of CLOSED candles."""
    step = INTERVAL_MS[interval]
    by_time: Dict[int, Candle] = {}
    for k in raw:
        t = int(float(k["time"]))
        if t < 10 ** 12:          # seconds -> ms, just in case
            t *= 1000
        by_time[t] = Candle(t, float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"]))
    candles = [by_time[t] for t in sorted(by_time)]
    if candles and candles[-1].t + step > now_ms:   # still forming -> drop
        candles.pop()
    return candles


def analyze(c: List[Candle], swing_n: int = 3, min_zone_pct: float = 0.0005) -> Analysis:
    n = len(c)
    if n < 2 * swing_n + 3:
        return Analysis(None, [], [], n)

    # ---- swing points -------------------------------------------------------
    is_sh = [False] * n
    is_sl = [False] * n
    for i in range(swing_n, n - swing_n):
        left_h = max(c[j].h for j in range(i - swing_n, i))
        right_h = max(c[j].h for j in range(i + 1, i + swing_n + 1))
        if c[i].h > left_h and c[i].h >= right_h:
            is_sh[i] = True
        left_l = min(c[j].l for j in range(i - swing_n, i))
        right_l = min(c[j].l for j in range(i + 1, i + swing_n + 1))
        if c[i].l < left_l and c[i].l <= right_l:
            is_sl[i] = True

    # ---- structure (BOS / CHoCH), sweeps, order blocks ------------------------
    trend: Optional[str] = None
    events: List[Event] = []
    zones: List[Zone] = []
    sh = None   # (index, level) latest unbroken swing high
    sl = None   # latest unbroken swing low

    for k in range(n):
        s = k - swing_n                      # this swing becomes known only now
        if s >= swing_n:
            if is_sh[s]:
                sh = (s, c[s].h)
            if is_sl[s]:
                sl = (s, c[s].l)
        cd = c[k]

        if sh is not None:
            if cd.c > sh[1]:
                events.append(Event("CHoCH" if trend == "bear" else "BOS", "bull", k, sh[1]))
                trend = "bull"
                if k - sh[0] > 1:
                    m = min(range(sh[0] + 1, k), key=lambda j: c[j].l)
                    if (c[m].h - c[m].l) / c[m].c >= min_zone_pct:
                        zones.append(Zone("OB", "bull", c[m].l, c[m].h, k))
                sh = None
            elif cd.h > sh[1]:
                events.append(Event("SWEEP", "bear", k, sh[1]))

        if sl is not None:
            if cd.c < sl[1]:
                events.append(Event("CHoCH" if trend == "bull" else "BOS", "bear", k, sl[1]))
                trend = "bear"
                if k - sl[0] > 1:
                    m = max(range(sl[0] + 1, k), key=lambda j: c[j].h)
                    if (c[m].h - c[m].l) / c[m].c >= min_zone_pct:
                        zones.append(Zone("OB", "bear", c[m].l, c[m].h, k))
                sl = None
            elif cd.l < sl[1]:
                events.append(Event("SWEEP", "bull", k, sl[1]))

    # ---- fair value gaps --------------------------------------------------------
    for i in range(2, n):
        if c[i].l > c[i - 2].h:
            if (c[i].l - c[i - 2].h) / c[i].c >= min_zone_pct:
                zones.append(Zone("FVG", "bull", c[i - 2].h, c[i].l, i))
        elif c[i].h < c[i - 2].l:
            if (c[i - 2].l - c[i].h) / c[i].c >= min_zone_pct:
                zones.append(Zone("FVG", "bear", c[i].h, c[i - 2].l, i))

    # ---- zone state: touched / invalid ------------------------------------------
    for z in zones:
        for j in range(z.created + 1, n):
            cd = c[j]
            if z.side == "bull":
                if cd.c < z.low:
                    z.invalid = True
                    break
                if cd.l <= z.high:
                    z.touched = True
            else:
                if cd.c > z.high:
                    z.invalid = True
                    break
                if cd.h >= z.low:
                    z.touched = True

    zones.sort(key=lambda z: z.created)
    return Analysis(trend, events, zones, n)
