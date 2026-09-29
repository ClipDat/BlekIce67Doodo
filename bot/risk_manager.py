"""
Implements exactly the money-management rule described by the user:

- Every trade risks a fixed fraction (default 50%) of current available
  balance as margin.
- Leverage starts at the first rung of the ladder (default 2x).
- On a LOSING trade: leverage moves to the next rung up (2->4->8->16->32->64).
  If it loses again at the last rung (64x), it wraps back to the first rung.
- On a WINNING trade, *regardless* of what leverage it just won at: leverage
  resets straight back to the first rung.
"""
from __future__ import annotations

from typing import List


class LeverageLadder:
    def __init__(self, ladder: List[int]):
        if not ladder:
            raise ValueError("ladder must not be empty")
        self.ladder = ladder
        self._index = 0

    @property
    def current(self) -> int:
        return self.ladder[self._index]

    @property
    def index(self) -> int:
        return self._index

    def set_index(self, index: int) -> None:
        if 0 <= index < len(self.ladder):
            self._index = index

    def on_win(self) -> int:
        self._index = 0
        return self.current

    def on_loss(self) -> int:
        if self._index < len(self.ladder) - 1:
            self._index += 1
        else:
            self._index = 0  # was at max rung and lost again -> back to the start
        return self.current

    def reset(self) -> int:
        self._index = 0
        return self.current


def estimate_liquidation_distance_fraction(leverage: int, maintenance_margin_rate: float = 0.005) -> float:
    """
    Rough estimate of the fractional adverse price move that would liquidate
    an isolated position at the given leverage, ignoring fees/funding:

        distance ~= 1/leverage - maintenance_margin_rate

    This is a simplification (Bitunix's real maintenance margin is tiered by
    notional, see get_position_tiers), but it's a fine conservative sanity
    check to make sure the stop-loss actually triggers before liquidation.
    """
    return max(0.0, (1.0 / leverage) - maintenance_margin_rate)


def sl_is_safe(sl_pct: float, leverage: int, min_buffer_multiple: float,
               maintenance_margin_rate: float = 0.005) -> bool:
    """True if the liquidation distance is comfortably farther away than the
    stop-loss distance, by at least `min_buffer_multiple`."""
    liq_distance = estimate_liquidation_distance_fraction(leverage, maintenance_margin_rate)
    if liq_distance <= 0:
        return False
    return liq_distance >= sl_pct * min_buffer_multiple
