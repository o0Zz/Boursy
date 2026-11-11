import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type LineData,
  type Time,
} from "lightweight-charts";
import type { Bar, StockTrade } from "../api/types";

const COLORS = {
  text: "#94a3b8",
  grid: "#1e293b",
  up: "#34d399",
  down: "#fb7185",
  ema20: "#fbbf24",
  sma50: "#38bdf8",
  sma200: "#c084fc",
  rsi: "#e2e8f0",
  macd: "#38bdf8",
  signal: "#fbbf24",
};

type NumKey = { [K in keyof Bar]: Bar[K] extends number | null ? K : never }[keyof Bar];

function line(bars: Bar[], key: NumKey): LineData<Time>[] {
  return bars.filter((b) => b[key] != null).map((b) => ({ time: b.time as Time, value: b[key] as number }));
}

export interface PriceLine {
  price: number;
  label: string;
  color: string;
}

export default function PriceChart({ bars, trades = [], lines = [] }: { bars: Bar[]; trades?: StockTrade[]; lines?: PriceLine[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: COLORS.text,
        attributionLogo: false,
        panes: { separatorColor: COLORS.grid },
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: COLORS.grid },
      timeScale: { borderColor: COLORS.grid },
      crosshair: { mode: 0 },
    });

    // Pane 0: price, moving averages, volume overlay
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      borderVisible: false,
    });
    candles.setData(bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));

    // Fills (adjusted prices on the chart are close to the raw fill prices for recent trades).
    const first = bars[0].time;
    const markers = trades
      .filter((t) => t.date >= first)
      .map((t) => ({
        time: t.date as Time,
        position: t.side === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
        color: t.side === "buy" ? COLORS.up : COLORS.down,
        shape: t.side === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
        text: `${t.side === "buy" ? "B" : "S"} ${t.qty}${t.mode === "paper" ? " (paper)" : ""}`,
      }));
    if (markers.length) createSeriesMarkers(candles, markers);
    for (const l of lines) {
      candles.createPriceLine({ price: l.price, color: l.color, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: l.label });
    }

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false });
    volume.setData(
      bars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(52,211,153,0.25)" : "rgba(251,113,133,0.25)",
      })),
    );
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    for (const [key, color] of [
      ["ema20", COLORS.ema20],
      ["sma50", COLORS.sma50],
      ["sma200", COLORS.sma200],
    ] as const) {
      chart
        .addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(line(bars, key));
    }

    // Pane 1: RSI
    const rsi = chart.addSeries(LineSeries, { color: COLORS.rsi, lineWidth: 1, priceLineVisible: false }, 1);
    rsi.setData(line(bars, "rsi14"));
    for (const level of [30, 70]) {
      rsi.createPriceLine({ price: level, color: "#475569", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    }

    // Pane 2: MACD
    const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 2);
    hist.setData(
      bars
        .filter((b) => b.macd_hist != null)
        .map((b) => ({
          time: b.time as Time,
          value: b.macd_hist as number,
          color: (b.macd_hist as number) >= 0 ? "rgba(52,211,153,0.5)" : "rgba(251,113,133,0.5)",
        })),
    );
    chart.addSeries(LineSeries, { color: COLORS.macd, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 2).setData(line(bars, "macd"));
    chart
      .addSeries(LineSeries, { color: COLORS.signal, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 2)
      .setData(line(bars, "macd_signal"));

    const panes = chart.panes();
    panes[0]?.setStretchFactor(3);
    panes[1]?.setStretchFactor(1);
    panes[2]?.setStretchFactor(1);
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [bars, trades, lines]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-slate-400">
        <Legend color={COLORS.ema20} label="EMA 20" />
        <Legend color={COLORS.sma50} label="SMA 50" />
        <Legend color={COLORS.sma200} label="SMA 200" />
        <span className="text-slate-600">|</span>
        <span>RSI 14 (30/70)</span>
        <span>MACD 12/26/9</span>
      </div>
      <div ref={ref} className="h-[520px] w-full sm:h-[620px]" />
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block h-0.5 w-4" style={{ background: color }} />
      {label}
    </span>
  );
}
