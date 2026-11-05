# Hour Window Order Block

`Hour_Window_Order_Block.pine` is a TradingView Pine Script v6 overlay. Each
hour it can draw one CISD order block on the chart's own candles. On a
1-minute chart the candle is a 1-minute candle. On a 5-minute chart it is a
5-minute candle.

The clock is `America/New_York`. TradingView follows US daylight-saving changes.
The hours on the chart match this clock when the chart timezone is New York.

## Inputs

**Window / to** are minutes inside each hour. The start minute is inclusive and
the end minute is exclusive. `0` to `15` is 9:00 inclusive until 9:15 exclusive
when the hour is 9. A candle that opens at 9:14 is inside. A candle that opens
at 9:15 is outside. Set the end to `60` to use the full hour.

**Bullish Order Block** and **Bearish Order Block** set each zone color,
including transparency. The border is drawn solid so the zone stays visible.

**Show Order Blocks** draws the order blocks. Turn it off to leave only
breaker blocks on the chart. A hidden order block is still tracked, so a
close through it can still produce a breaker.

**Show buy/sell signals** draws a `BUY` label under a bullish order block or
breaker, and a `SELL` label over a bearish one. The label uses the same color
as that zone. Turn the input off to leave the boxes and remove the labels.
Hiding an order block hides its label too. A breaker stays on the chart with
its label. The next hour removes the label with the zone.

## What gets marked

The zone is the candle that reclaims the hour open, from that candle's body
through the wick that took the open. The wick on the other side stays outside
the box.

A bullish order block:

1. Inside the window, price trades under the hour open.
2. A candle closes back above that open. On a single candle, the lower wick
   takes the open and the close finishes above it. The 10:00 candle on a
   5-minute chart is this candle when it opens the hour.
3. The box runs from that candle's body top (the close) down through its low.

A candle that trades under the hour open and closes below it is not a bearish
order block. It is the bullish sweep. The bullish order block is the candle
that later closes back above that open, in the same hour.

A bearish order block starts only when a candle trades above the hour open and
does not trade under it. A later candle that closes back below that open is
the zone. The box runs from that candle's body bottom up through its high.

A bearish candle that only trades under the open can be reclaimed by a later
candle in the same hour. The box is that later candle, with the same wick rule.
The next hour cancels a sweep that never gets that close. The first confirmed
reclaim of the hour is the one that is drawn.

The rectangle extends to the right. A wick back into the zone leaves it in
place. The candle that closes through an order block becomes the breaker: the
box moves onto that candle, switches to the opposite color, and is labeled
`BRK`. The candle that closes through the breaker becomes the new order block,
labeled `OB`, built from that candle. The candle after either close is not
used.

When the next New York hour opens, the zone is removed. The chart keeps only
the order block or breaker of the hour in progress. In Bar Replay that is the
hour at the replay position. The color is the bullish or bearish input, so a
bullish zone is blue with the default colors.

## Live and history

The reclaim is read from a confirmed candle (`barstate.isconfirmed`). Historical
bars, Bar Replay, and a live close use that same close. The hour open is the
open of the first chart candle of the hour and stays fixed for the rest of the
hour.

Use an intraday timeframe. The script stops on a daily, weekly, or monthly
chart.

This is a chart indicator. Bar Replay and chart history are the backtest view.
TradingView-hosted compilation and visual inspection are still required because
this workspace does not include TradingView's Pine compiler or chart renderer.
