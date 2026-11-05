from __future__ import annotations

import pathlib
import unittest
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE = ROOT / "Hour_Window_Order_Block.pine"

PHASE_LOOK = 0
PHASE_ARMED_BULL = 1
PHASE_ARMED_BEAR = 2
PHASE_DONE = 3


@dataclass(frozen=True)
class Bar:
    hour_key: int
    minute: int
    open: float
    high: float
    low: float
    close: float


def scan(bars: list[Bar], start: int, end: int) -> list[dict]:
    """Mirror the Pine reclaim state machine."""
    active_hour = None
    hour_open = None
    phase = PHASE_LOOK
    series_open = None
    zones = []

    for i, bar in enumerate(bars):
        new_hour = bar.hour_key != active_hour
        if new_hour:
            if active_hour is not None:
                zones.clear()
            active_hour = bar.hour_key
            hour_open = bar.open
            phase = PHASE_LOOK
        bullish = bar.close > bar.open
        in_window = start <= bar.minute < end
        took_sell = bar.low < hour_open
        took_buy = bar.high > hour_open

        flipped = False
        if zones and i > zones[0]["created"]:
            zone = zones[0]
            closed_through = (
                bar.close < zone["bottom"]
                if zone["direction"] == 1
                else bar.close > zone["top"]
            )
            if closed_through:
                flipped = True
                new_direction = -zone["direction"]
                top, bottom = _bounds(new_direction, bar)
                _place(
                    zones,
                    active_hour,
                    hour_open,
                    new_direction,
                    top,
                    bottom,
                    i,
                    bar.open,
                    not zone["breaker"],
                )
                phase = PHASE_DONE

        if not flipped:
            direction = 0
            cisd_open = None
            if phase == PHASE_ARMED_BULL and bar.close > series_open:
                direction = 1
                cisd_open = series_open
            elif phase == PHASE_ARMED_BEAR and bar.close < series_open:
                direction = -1
                cisd_open = series_open
            elif (
                phase == PHASE_LOOK
                and in_window
                and took_sell
                and bar.close > hour_open
                and bar.close > bar.open
            ):
                direction = 1
                cisd_open = bar.open
            elif phase == PHASE_LOOK and in_window and took_sell:
                phase = PHASE_ARMED_BULL
                series_open = bar.open
            elif (
                phase == PHASE_LOOK
                and in_window
                and bullish
                and took_buy
                and not took_sell
            ):
                phase = PHASE_ARMED_BEAR
                series_open = bar.open
            if direction != 0:
                top, bottom = _bounds(direction, bar)
                _place(
                    zones,
                    active_hour,
                    hour_open,
                    direction,
                    top,
                    bottom,
                    i,
                    cisd_open,
                    False,
                )
                phase = PHASE_DONE

    return zones


def _bounds(direction, bar):
    """Bullish keeps the lower wick. Bearish keeps the upper wick."""
    if direction == 1:
        return max(bar.open, bar.close), bar.low
    return bar.high, min(bar.open, bar.close)


def _zone(hour_key, hour_open, direction, top, bottom, created, cisd_open):
    return {
        "hour_key": hour_key,
        "hour_open": hour_open,
        "direction": direction,
        "top": top,
        "bottom": bottom,
        "created": created,
        "cisd_open": cisd_open,
        "breaker": False,
    }


def signal_for(zone):
    """Buy sits under a bullish zone. Sell sits over a bearish zone."""
    if zone["direction"] == 1:
        return "BUY", zone["bottom"]
    return "SELL", zone["top"]


def _place(zones, hour_key, hour_open, direction, top, bottom, created, cisd_open, breaker):
    zones.clear()
    zone = _zone(hour_key, hour_open, direction, top, bottom, created, cisd_open)
    zone["breaker"] = breaker
    zones.append(zone)


class DetectionTests(unittest.TestCase):
    def test_bullish_candle_keeps_the_lower_wick_and_drops_the_upper_wick(self):
        bars = [Bar(10, 0, 100.0, 101.2, 98.8, 100.8)]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(zone["direction"], 1)
        self.assertEqual(zone["top"], 100.8)
        self.assertEqual(zone["bottom"], 98.8)
        self.assertEqual(zone["created"], 0)
        self.assertNotEqual(zone["top"], 101.2)

    def test_a_sweep_under_the_open_is_not_a_bearish_order_block(self):
        bars = [Bar(10, 0, 100.0, 101.5, 99.2, 99.4)]
        self.assertEqual(scan(bars, 0, 15), [])

    def test_the_close_back_above_that_sweep_is_a_bullish_order_block(self):
        bars = [
            Bar(10, 0, 100.0, 101.5, 99.2, 99.4),
            Bar(10, 5, 99.6, 100.9, 99.3, 100.6),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(zone["direction"], 1)
        self.assertFalse(zone["breaker"])
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["top"], 100.6)
        self.assertEqual(zone["bottom"], 99.3)
        self.assertEqual(signal_for(zone), ("BUY", 99.3))

    def test_bearish_candle_keeps_the_upper_wick_and_drops_the_lower_wick(self):
        bars = [
            Bar(10, 0, 100.0, 101.5, 100.0, 100.8),
            Bar(10, 5, 100.6, 101.2, 99.2, 99.4),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(zone["direction"], -1)
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["top"], 101.2)
        self.assertEqual(zone["bottom"], 99.4)
        self.assertNotEqual(zone["bottom"], 99.2)

    def test_a_down_candle_without_an_upper_wick_waits_for_the_reclaim(self):
        bars = [
            Bar(10, 0, 100.0, 100.0, 98.5, 99.2),
            Bar(10, 5, 99.4, 101.0, 99.2, 100.6),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(zone["direction"], 1)
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["bottom"], 99.2)
        self.assertEqual(zone["top"], 100.6)
        self.assertEqual(zone["cisd_open"], 100.0)

    def test_reclaim_can_close_after_the_window_in_the_same_hour(self):
        bars = [
            Bar(10, 0, 100.0, 100.0, 98.5, 99.2),
            Bar(10, 20, 99.5, 100.8, 99.4, 100.4),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["direction"], 1)

    def test_the_next_hour_cancels_an_unclaimed_sweep(self):
        bars = [
            Bar(10, 0, 100.0, 100.0, 98.5, 99.2),
            Bar(11, 0, 101.0, 101.2, 100.8, 101.1),
        ]
        found = scan(bars, 0, 15)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["hour_key"], 11)
        self.assertEqual(found[0]["hour_open"], 101.0)

    def test_a_candle_outside_the_window_does_not_start_the_hour(self):
        bars = [Bar(10, 30, 100.0, 100.4, 98.8, 100.8)]
        self.assertEqual(scan(bars, 0, 15), [])

    def test_a_wick_into_the_zone_does_not_flip_it(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 100.6, 100.9, 98.4, 100.2),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertFalse(zone["breaker"])
        self.assertEqual(zone["direction"], 1)

    def test_a_close_through_a_bullish_order_block_flips_it_into_a_breaker(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 100.4, 100.5, 98.2, 98.5),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(zone["direction"], -1)
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["top"], 100.5)
        self.assertEqual(zone["bottom"], 98.5)

    def test_a_close_through_a_bearish_order_block_flips_it_into_a_breaker(self):
        bars = [
            Bar(10, 0, 100.0, 101.5, 100.0, 100.8),
            Bar(10, 5, 100.6, 101.2, 99.2, 99.4),
            Bar(10, 10, 101.0, 102.0, 100.8, 101.8),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(zone["direction"], 1)
        self.assertEqual(zone["created"], 2)
        self.assertEqual(zone["top"], 101.8)
        self.assertEqual(zone["bottom"], 100.8)

    def test_the_candle_after_the_break_does_not_replace_the_breaker(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 100.0, 100.2, 98.0, 98.4),
            Bar(10, 10, 99.5, 100.2, 97.5, 100.1),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["direction"], -1)
        self.assertEqual(zone["top"], 100.2)
        self.assertEqual(zone["bottom"], 98.4)

    def test_a_later_order_block_replaces_the_breaker(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 99.0, 99.2, 98.0, 98.4),
            Bar(10, 10, 99.0, 101.0, 97.5, 100.5),
        ]
        found = scan(bars, 0, 15)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["breaker"])
        self.assertEqual(found[0]["direction"], 1)
        self.assertEqual(found[0]["created"], 2)
        self.assertEqual(found[0]["top"], 100.5)
        self.assertEqual(found[0]["bottom"], 97.5)

    def test_a_close_through_the_breaker_becomes_the_last_order_block(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 99.0, 99.2, 98.0, 98.4),
            Bar(10, 10, 100.0, 101.0, 99.6, 100.9),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertFalse(zone["breaker"])
        self.assertEqual(zone["direction"], 1)
        self.assertEqual(zone["created"], 2)
        self.assertEqual(zone["top"], 100.9)
        self.assertEqual(zone["bottom"], 99.6)

    def test_a_later_candle_that_stays_inside_the_breaker_leaves_it(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 99.0, 99.2, 98.0, 98.4),
            Bar(10, 20, 99.1, 99.2, 98.6, 99.0),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(zone["direction"], -1)
        self.assertEqual(zone["created"], 1)
        self.assertEqual(zone["top"], 99.2)
        self.assertEqual(zone["bottom"], 98.4)

    def test_the_next_hour_removes_the_previous_order_block(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(11, 0, 102.0, 102.4, 101.6, 102.2),
        ]
        found = scan(bars, 0, 15)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["hour_key"], 11)

    def test_a_new_hour_with_no_reclaim_leaves_the_chart_empty(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(11, 30, 102.0, 102.4, 101.8, 102.2),
        ]
        self.assertEqual(scan(bars, 0, 15), [])

    def test_only_the_first_reclaim_of_the_hour_is_kept(self):
        bars = [
            Bar(10, 0, 100.0, 100.4, 98.8, 100.8),
            Bar(10, 5, 100.8, 102.0, 99.0, 101.4),
        ]
        self.assertEqual(len(scan(bars, 0, 15)), 1)

    def test_a_bullish_order_block_is_a_buy_under_the_zone(self):
        bars = [Bar(10, 0, 100.0, 101.2, 98.8, 100.8)]
        zone = scan(bars, 0, 15)[0]
        self.assertEqual(signal_for(zone), ("BUY", 98.8))

    def test_a_bearish_breaker_is_a_sell_over_the_zone(self):
        bars = [
            Bar(10, 0, 100.0, 101.2, 98.8, 100.8),
            Bar(10, 5, 100.4, 100.5, 98.2, 98.5),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(signal_for(zone), ("SELL", 100.5))

    def test_a_bullish_breaker_is_a_buy_under_the_zone(self):
        bars = [
            Bar(10, 0, 100.0, 101.5, 100.0, 100.8),
            Bar(10, 5, 100.6, 101.2, 99.2, 99.4),
            Bar(10, 10, 101.0, 102.0, 100.8, 101.8),
        ]
        zone = scan(bars, 0, 15)[0]
        self.assertTrue(zone["breaker"])
        self.assertEqual(signal_for(zone), ("BUY", 100.8))


class SourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PINE.read_text(encoding="utf-8")

    def test_is_v6_overlay_on_the_chart_timeframe(self):
        self.assertIn("//@version=6", self.source)
        self.assertIn('indicator("Hour Window Order Block"', self.source)
        self.assertIn("overlay = true", self.source)
        self.assertNotIn("request.security", self.source)
        self.assertNotIn("timeframe.period", self.source)

    def test_zone_keeps_the_liquidity_wick(self):
        self.assertIn("drawDirection == 1 ? math.max(open, close) : high", self.source)
        self.assertIn("drawDirection == 1 ? low : math.min(open, close)", self.source)
        self.assertIn("top = zoneTop", self.source)
        self.assertIn("bottom = zoneBottom", self.source)
        self.assertIn("left = bar_index", self.source)

    def test_the_first_hour_is_not_lost_to_na(self):
        self.assertIn("na(activeHourKey) or f_hourKey(time) != activeHourKey", self.source)

    def test_a_new_hour_deletes_the_previous_zones(self):
        self.assertIn("array.clear(zones)", self.source)
        self.assertLess(self.source.index("array.clear(zones)"), self.source.index("array.push(zones"))

    def test_bullish_reclaim_trades_under_the_open_and_closes_above(self):
        self.assertIn(
            "tookSellSide and close > hourOpen and close > open",
            self.source,
        )
        self.assertIn("and inWindow and tookSellSide\n", self.source)
        self.assertIn("bullishCandle and tookBuySide and not tookSellSide", self.source)
        self.assertNotIn("tookBuySide and close < hourOpen and close < open", self.source)

    def test_a_later_close_can_reclaim_the_first_candle_open(self):
        self.assertIn("phase == PHASE_ARMED_BULL and close > seriesOpen", self.source)
        self.assertIn("phase == PHASE_ARMED_BEAR and close < seriesOpen", self.source)
        look_at = self.source.index("phase := PHASE_LOOK")
        reclaim_at = self.source.index("phase == PHASE_ARMED_BULL and close > seriesOpen")
        self.assertLess(look_at, reclaim_at)

    def test_mitigation_is_a_close_through_the_body(self):
        self.assertIn("close < zone.bottom", self.source)
        self.assertIn("close > zone.top", self.source)
        self.assertIn("bar_index > zone.createdBar", self.source)
        self.assertNotIn("high >= zone.bottom", self.source)

    def test_order_blocks_can_be_hidden(self):
        self.assertIn('input.bool(true, "Show Order Blocks"', self.source)
        self.assertIn("showOrderBlocks or drawAsBreaker", self.source)
        self.assertIn("not na(zone.zone)", self.source)

    def test_buy_and_sell_signals_can_be_hidden(self):
        self.assertIn('input.bool(true, "Show buy/sell signals"', self.source)
        self.assertIn("if showSignals and (showOrderBlocks or drawAsBreaker)", self.source)
        self.assertIn("buySide ? zoneBottom : zoneTop", self.source)
        self.assertIn('buySide ? "BUY" : "SELL"', self.source)
        self.assertIn(
            "buySide ? label.style_label_up : label.style_label_down",
            self.source,
        )
        self.assertIn("label.delete(gone.signal)", self.source)
        self.assertIn("label.delete(previous.signal)", self.source)

    def test_a_close_through_flips_the_order_block_into_a_breaker(self):
        self.assertIn("drawAsBreaker := not zone.breaker", self.source)
        self.assertIn('drawAsBreaker ? "BRK" : "OB"', self.source)
        self.assertLess(
            self.source.index("drawAsBreaker := not zone.breaker"),
            self.source.index("tookSellSide and close > hourOpen and close > open"),
        )

    def test_window_is_half_open_in_new_york(self):
        self.assertIn('const string NY_TIMEZONE = "America/New_York"', self.source)
        self.assertIn("m >= windowStartMinute and m < windowEndMinute", self.source)
        self.assertIn('input.int(0, "Window"', self.source)
        self.assertIn('input.int(15, "to"', self.source)

    def test_detection_waits_for_a_confirmed_close(self):
        self.assertIn("if barstate.isconfirmed and not na(hourOpen)", self.source)
        self.assertNotIn("barstate.isrealtime", self.source)
        self.assertNotIn("timenow", self.source)
        self.assertNotIn("barstate.islast", self.source)


if __name__ == "__main__":
    unittest.main()
