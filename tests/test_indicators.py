"""Run:  python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.indicators import Candle, analyze, parse_klines   # noqa: E402
from bot.smc_strategy import SmcSignal                      # noqa: E402


def from_closes(closes, start=100.0, wick=0.1):
    out, prev = [], start
    for i, cl in enumerate(closes):
        out.append(Candle(i * 300_000, prev, max(prev, cl) + wick, min(prev, cl) - wick, cl))
        prev = cl
    return out


class TestFvg(unittest.TestCase):
    def test_bullish_fvg(self):
        c = [Candle(0, 10, 11, 9, 10.5), Candle(1, 10.5, 13, 10.4, 12.9), Candle(2, 12.9, 14, 11.5, 13.8)]
        # pad so analyze() has enough candles
        pad = [Candle(-i, 10, 11.5, 8.5, 10) for i in range(10, 0, -1)]
        a = analyze(pad + c, swing_n=2, min_zone_pct=0.001)
        fvg = [z for z in a.zones if z.kind == "FVG" and z.side == "bull"]
        self.assertEqual(len(fvg), 1)
        self.assertAlmostEqual(fvg[0].low, 11.0)
        self.assertAlmostEqual(fvg[0].high, 11.5)

    def test_bearish_fvg(self):
        c = [Candle(0, 10, 11, 9, 9.5), Candle(1, 9.5, 9.6, 7, 7.1), Candle(2, 7.1, 8.5, 6, 6.2)]
        pad = [Candle(-i, 10, 11.5, 8.5, 10) for i in range(10, 0, -1)]
        a = analyze(pad + c, swing_n=2, min_zone_pct=0.001)
        fvg = [z for z in a.zones if z.kind == "FVG" and z.side == "bear"]
        self.assertEqual(len(fvg), 1)
        self.assertAlmostEqual(fvg[0].low, 8.5)
        self.assertAlmostEqual(fvg[0].high, 9.0)

    def test_fvg_invalidated_by_close_through(self):
        c = [Candle(0, 10, 11, 9, 10.5), Candle(1, 10.5, 13, 10.4, 12.9), Candle(2, 12.9, 14, 11.5, 13.8),
             Candle(3, 13.8, 13.9, 10.0, 10.2)]          # closes below 11 -> invalid
        pad = [Candle(-i, 10, 11.5, 8.5, 10) for i in range(10, 0, -1)]
        a = analyze(pad + c, swing_n=2, min_zone_pct=0.001)
        z = [z for z in a.zones if z.kind == "FVG" and z.side == "bull" and abs(z.low - 11.0) < 1e-9][0]
        self.assertTrue(z.invalid)


class TestStructure(unittest.TestCase):
    PATH = [100, 101, 102, 103, 102, 101, 100.5, 101.5, 102.5, 104]

    def test_bos_and_order_block(self):
        a = analyze(from_closes(self.PATH), swing_n=2, min_zone_pct=0.0001)
        self.assertEqual(a.trend, "bull")
        self.assertEqual(a.events[-1].kind, "BOS")
        ob = [z for z in a.zones if z.kind == "OB"]
        self.assertEqual(len(ob), 1)
        self.assertAlmostEqual(ob[0].low, 100.4)     # candle with the lowest low in the pullback
        self.assertAlmostEqual(ob[0].high, 101.1)

    def test_choch_flips_trend(self):
        path = self.PATH + [103.5, 103, 102.5, 103.2, 102.0, 100.0, 99.0]
        a = analyze(from_closes(path), swing_n=2, min_zone_pct=0.0001)
        kinds = [e.kind for e in a.events if e.kind != "SWEEP"]
        self.assertEqual(kinds[0], "BOS")
        self.assertIn("CHoCH", kinds)
        self.assertEqual(a.trend, "bear")


class TestSignal(unittest.TestCase):
    def make(self, tail):
        c = from_closes(self.PATH_PLUS(tail))
        s = SmcSignal(swing_n=2, min_zone_pct=0.0001, zone_max_age=80,
                      first_touch_only=True, min_score=1, tolerance=0.0)
        s.update(c)
        return s

    @staticmethod
    def PATH_PLUS(tail):
        return TestStructure.PATH + tail

    def test_long_when_price_retraces_into_fresh_bullish_ob(self):
        s = self.make([104.5, 105.0, 105.5])       # runs away, OB untouched
        self.assertIsNone(s.direction(106.0))       # far from the zone -> wait
        self.assertEqual(s.direction(100.8), "LONG")
        self.assertIn("OB", s.reason)

    def test_no_signal_after_zone_was_touched(self):
        s = self.make([104.5, 105.0, 101.0, 105.5])  # candle dips into OB first
        self.assertIsNone(s.direction(100.8))

    def test_no_counter_trend_trade(self):
        s = self.make([104.5, 105.0, 105.5])
        self.assertNotEqual(s.direction(100.8), "SHORT")


class TestParse(unittest.TestCase):
    def test_drops_unclosed_candle_and_sorts(self):
        base = 1_790_000_000_000
        raw = [{"time": base + 600_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
               {"time": base + 300_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
               {"time": base, "open": "1", "high": "2", "low": "0.5", "close": "1.5"}]
        # candle at base+600000 closes at base+900000 -> still forming when now = base+650000
        c = parse_klines(raw, "5m", now_ms=base + 650_000)
        self.assertEqual([x.t for x in c], [base, base + 300_000])


if __name__ == "__main__":
    unittest.main()
