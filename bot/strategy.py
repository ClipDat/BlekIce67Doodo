"""
Entry signal: a simple EMA(fast) / EMA(slow) crossover computed from the
stream of last-traded prices the bot polls from Bitunix's ticker endpoint.

Why this instead of random or always-one-direction:
- Random 50/50 throws away any edge and just adds variance.
- A short trend filter (fast EMA above/below slow EMA) at least aligns each
  entry with the prevailing very-short-term direction, which is a standard,
  simple starting point for a momentum/trend-following entry.

This is intentionally simple. It is NOT a guarantee of a profitable edge —
see the README's risk section. You can swap this module out for a different
signal later without touching the rest of the bot.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional


class EmaCrossSignal:
    def __init__(self, fast_period: int, slow_period: int):
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._fast_ema: Optional[float] = None
        self._slow_ema: Optional[float] = None
        self._prices: Deque[float] = deque(maxlen=slow_period * 3)

    @staticmethod
    def _ema_step(prev: Optional[float], price: float, period: int) -> float:
        k = 2.0 / (period + 1.0)
        if prev is None:
            return price
        return price * k + prev * (1.0 - k)

    def update(self, price: float) -> None:
        self._prices.append(price)
        self._fast_ema = self._ema_step(self._fast_ema, price, self.fast_period)
        self._slow_ema = self._ema_step(self._slow_ema, price, self.slow_period)

    @property
    def ready(self) -> bool:
        return len(self._prices) >= self.slow_period

    def direction(self) -> Optional[str]:
        """Returns 'LONG', 'SHORT', or None if not enough data yet / flat."""
        if not self.ready or self._fast_ema is None or self._slow_ema is None:
            return None
        if self._fast_ema > self._slow_ema:
            return "LONG"
        if self._fast_ema < self._slow_ema:
            return "SHORT"
        return None
