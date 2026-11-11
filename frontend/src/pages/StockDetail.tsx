import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BarsResponse, Stock } from "../api/types";
import PriceChart from "../components/PriceChart";
import { BucketBadge, Card, ErrorBox, Stat, TrendBadge } from "../components/ui";
import { changeClass, fmtNum, fmtPct, fmtPrice } from "../lib/format";

const RANGES = [
  { label: "6M", days: 126 },
  { label: "1Y", days: 252 },
  { label: "2Y", days: 504 },
  { label: "5Y", days: 1260 },
];

export default function StockDetail() {
  const { symbol = "" } = useParams();
  const [days, setDays] = useState(252);
  const stock = useQuery({ queryKey: ["stock", symbol], queryFn: () => api<Stock>(`/stocks/${symbol}`) });
  const bars = useQuery({
    queryKey: ["bars", symbol, days],
    queryFn: () => api<BarsResponse>(`/stocks/${symbol}/bars?days=${days}`),
    placeholderData: (prev) => prev,
  });

  if (stock.error) return <ErrorBox error={stock.error} />;
  const s = stock.data;
  const snap = s?.snapshot;

  return (
    <div className="space-y-4">
      <Link to="/watchlist" className="text-sm text-slate-500 hover:text-slate-300">← Watchlist</Link>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="text-2xl font-semibold">{s?.name ?? symbol}</h1>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            {symbol} · {s?.exchange} · {s?.currency}
            {s && <BucketBadge bucket={s.bucket} />}
            {s && <TrendBadge trend={s.trend} />}
            {s?.pea_eligible && <span className="rounded bg-slate-700/50 px-2 py-0.5 text-xs text-slate-300">PEA</span>}
          </div>
        </div>
        {snap && (
          <div className="flex items-baseline gap-3">
            <span className="num text-3xl font-semibold">{fmtPrice(snap.close, s?.currency)}</span>
            <span className={`num ${changeClass(snap.change_1d_pct)}`}>{fmtPct(snap.change_1d_pct)}</span>
            <span className="text-xs text-slate-500">{snap.date}</span>
          </div>
        )}
      </div>

      {s?.last_error && <ErrorBox error={`Last data refresh failed: ${s.last_error}`} />}

      <Card>
        <div className="mb-3 flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.label}
              onClick={() => setDays(r.days)}
              className={`rounded px-3 py-1 text-sm ${days === r.days ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}
            >
              {r.label}
            </button>
          ))}
        </div>
        {bars.error ? (
          <ErrorBox error={bars.error} />
        ) : bars.data && bars.data.bars.length > 0 ? (
          <PriceChart bars={bars.data.bars} />
        ) : (
          <p className="py-10 text-center text-sm text-slate-500">{bars.isPending ? "Loading…" : "No data yet."}</p>
        )}
        <p className="mt-2 text-xs text-slate-600">Prices adjusted for dividends and splits. Data delayed ~15 min.</p>
      </Card>

      {snap && (
        <Card title="Indicators">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="RSI 14" value={fmtNum(snap.rsi14, 1)} />
            <Stat label="MACD histogram" value={fmtNum(snap.macd_hist, 3)} valueClass={changeClass(snap.macd_hist)} />
            <Stat label="ATR 14" value={fmtNum(snap.atr14)} sub={`${fmtNum(snap.atr_pct, 1)} % of price`} />
            <Stat label="Volume vs 20d avg" value={snap.vol_avg20 ? `${fmtNum(snap.volume / snap.vol_avg20, 2)}×` : "–"} />
            <Stat label="EMA 20" value={fmtNum(snap.ema20)} />
            <Stat label="SMA 50" value={fmtNum(snap.sma50)} />
            <Stat label="SMA 200" value={fmtNum(snap.sma200)} sub={snap.above_sma200 == null ? undefined : snap.above_sma200 ? "price above" : "price below"} />
            <Stat label="SMA 50 vs 200" value={snap.sma50_above_sma200 == null ? "–" : snap.sma50_above_sma200 ? "above" : "below"} />
          </div>
        </Card>
      )}
    </div>
  );
}
