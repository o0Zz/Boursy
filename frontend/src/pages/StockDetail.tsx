import { useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, CalendarPlus, Sparkles, Trash2 } from "lucide-react";
import { api, post } from "../api/client";
import type { AIReview, AIStatus, BarsResponse, Stock, StockEvent, StockTrade } from "../api/types";
import PriceChart, { type PriceLine } from "../components/PriceChart";
import { Badge, BucketBadge, Button, Card, cx, Empty, ErrorBox, Field, Input, Loading, Modal, ScoreBadge, Select, Stat, Tabs, TrendBadge } from "../components/ui";
import { changeClass, fmtDate, fmtDateTime, fmtNum, fmtPct, fmtPrice } from "../lib/format";
import { useMode } from "../lib/mode";

const RANGES = [
  { label: "6M", days: 126 },
  { label: "1Y", days: 252 },
  { label: "2Y", days: 504 },
  { label: "5Y", days: 1260 },
] as const;

export default function StockDetail() {
  const { symbol = "" } = useParams();
  const { current } = useMode();
  const [days, setDays] = useState("252");
  const stock = useQuery({ queryKey: ["stock", symbol], queryFn: () => api<Stock>(`/stocks/${symbol}`) });
  const bars = useQuery({
    queryKey: ["bars", symbol, days],
    queryFn: () => api<BarsResponse>(`/stocks/${symbol}/bars?days=${days}`),
    placeholderData: (prev) => prev,
  });
  const trades = useQuery({ queryKey: ["stock-trades", symbol], queryFn: () => api<StockTrade[]>(`/stocks/${symbol}/trades`) });

  const position = current?.positions.find((p) => p.symbol === symbol.toUpperCase());
  const lines = useMemo<PriceLine[]>(
    () => (position ? [{ price: position.stop, label: "stop", color: "#fbbf24" }, { price: position.avg_price, label: "entry", color: "#94a3b8" }] : []),
    [position],
  );

  if (stock.error) return <ErrorBox error={stock.error} />;
  const s = stock.data;
  const snap = s?.snapshot;

  return (
    <div className="space-y-5">
      <Link to="/watchlist" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300">
        <ArrowLeft className="h-4 w-4" /> Watchlist
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">{s?.name ?? symbol}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-slate-500">
            {symbol} · {s?.exchange} · {s?.currency}
            {s && <BucketBadge bucket={s.bucket} />}
            {s && <TrendBadge trend={s.trend} />}
            {s?.pea_eligible && <Badge>PEA</Badge>}
            {s?.ai && (
              <span className="flex items-center gap-1">
                AI <ScoreBadge score={s.ai.score} />
              </span>
            )}
          </div>
        </div>
        {snap && (
          <div className="text-right">
            <div className="num text-3xl font-semibold text-white">{fmtPrice(snap.close, s?.currency)}</div>
            <div className="flex items-center justify-end gap-2 text-sm">
              <span className={cx("num font-medium", changeClass(snap.change_1d_pct))}>{fmtPct(snap.change_1d_pct)}</span>
              <span className="text-xs text-slate-500">{fmtDate(snap.date)}</span>
            </div>
          </div>
        )}
      </div>

      {s?.last_error && <ErrorBox error={`Last data refresh failed: ${s.last_error}`} />}
      {s?.notes && <p className="text-sm text-slate-400">{s.notes}</p>}

      <Card
        title="Chart"
        action={
          <Tabs
            value={days}
            onChange={setDays}
            options={RANGES.map((r) => ({ value: String(r.days), label: r.label }))}
          />
        }
      >
        {bars.error ? (
          <ErrorBox error={bars.error} />
        ) : bars.data && bars.data.bars.length > 0 ? (
          <PriceChart bars={bars.data.bars} trades={trades.data ?? []} lines={lines} />
        ) : bars.isPending ? (
          <Loading />
        ) : (
          <Empty title="No data yet" />
        )}
        <p className="mt-2 text-xs text-slate-600">Prices adjusted for dividends and splits. Data delayed ~15 min. Arrows mark fills.</p>
      </Card>

      {snap && (
        <Card title="Indicators">
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="RSI 14" value={fmtNum(snap.rsi14, 1)} sub={snap.rsi14 == null ? undefined : snap.rsi14 >= 70 ? "overbought" : snap.rsi14 <= 30 ? "oversold" : "neutral"} />
            <Stat label="MACD histogram" value={fmtNum(snap.macd_hist, 3)} valueClass={changeClass(snap.macd_hist)} />
            <Stat label="ATR 14" value={fmtNum(snap.atr14)} sub={`${fmtNum(snap.atr_pct, 1)} % of price`} />
            <Stat label="Volume vs 20d" value={snap.vol_avg20 ? `${fmtNum(snap.volume / snap.vol_avg20, 2)}×` : "–"} />
            <Stat label="EMA 20" value={fmtNum(snap.ema20)} />
            <Stat label="SMA 50" value={fmtNum(snap.sma50)} />
            <Stat label="SMA 200" value={fmtNum(snap.sma200)} sub={snap.above_sma200 == null ? undefined : snap.above_sma200 ? "price above" : "price below"} />
            <Stat label="SMA 50 vs 200" value={snap.sma50_above_sma200 == null ? "–" : snap.sma50_above_sma200 ? "above" : "below"} />
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <AIPanel symbol={symbol} />
        </div>
        <div className="lg:col-span-2">
          <EventsPanel symbol={symbol} />
        </div>
      </div>
    </div>
  );
}

const taskLabel = { screening: "Screening", signal_review: "Signal review", news_check: "News check" };

function AIPanel({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const reviews = useQuery({
    queryKey: ["reviews", symbol],
    queryFn: () => api<AIReview[]>(`/ai/reviews?symbol=${symbol}&limit=20`),
    refetchInterval: (q) => (q.state.dataUpdatedAt && Date.now() - q.state.dataUpdatedAt < 120_000 ? 10_000 : false),
  });
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/ai/status") });
  const run = useMutation({
    mutationFn: () => post(`/ai/screen/${symbol}`),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["reviews", symbol] }), 3000),
  });
  const ok = (reviews.data ?? []).filter((r) => r.ok);
  const latest = ok[0];

  return (
    <Card
      title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" /> AI research</span>}
      action={
        <Button size="sm" onClick={() => run.mutate()} loading={run.isPending} disabled={!status.data?.available} title={status.data?.reason ?? ""}>
          <Sparkles className="h-3.5 w-3.5" /> Review now
        </Button>
      }
    >
      {run.isSuccess && <p className="mb-3 text-xs text-emerald-300">Review started: it takes one to three minutes with web search.</p>}
      {run.error && <div className="mb-3"><ErrorBox error={run.error} /></div>}
      {!latest ? (
        <Empty icon={<Bot className="h-6 w-6" />} title="No AI review yet">
          {status.data?.available ? "Run a review now, or wait for the Saturday screening." : `AI is not available: ${status.data?.reason ?? ""}`}
        </Empty>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl bg-slate-950/50 p-4 ring-1 ring-inset ring-slate-800">
            <div className="flex flex-wrap items-center gap-2">
              <ScoreBadge score={latest.score} />
              <span className="text-sm font-medium text-white">{taskLabel[latest.task]}</span>
              {latest.verdict && <Badge tone={latest.verdict === "veto" || latest.verdict === "thesis_break" ? "rose" : latest.verdict === "warning" ? "amber" : "emerald"}>{latest.verdict}</Badge>}
              <span className="ml-auto text-xs text-slate-500">{fmtDateTime(latest.created_at)}</span>
            </div>
            <p className="mt-2 text-sm text-slate-200">{latest.summary}</p>
            {typeof latest.output?.thesis === "string" && <p className="mt-2 text-sm text-slate-400">{latest.output.thesis}</p>}
            {Array.isArray(latest.output?.risks) && (latest.output!.risks as string[]).length > 0 && (
              <div className="mt-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Risks</div>
                <ul className="mt-1 list-inside list-disc space-y-0.5 text-sm text-slate-400">
                  {(latest.output!.risks as string[]).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
            {Array.isArray(latest.output?.items) && (latest.output!.items as string[]).length > 0 && (
              <ul className="mt-3 list-inside list-disc space-y-0.5 text-sm text-slate-400">
                {(latest.output!.items as string[]).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
            <div className="mt-3 text-[11px] text-slate-500">
              {latest.model} · {latest.backend} · {latest.web_searches} searches · {latest.cost_is_estimate ? "≈" : ""}${latest.cost_usd.toFixed(3)}
            </div>
          </div>
          {(reviews.data ?? []).slice(1).map((r) => (
            <div key={r.id} className="flex items-start gap-3 border-t border-slate-800/70 pt-3 text-sm">
              {r.ok ? <ScoreBadge score={r.score} /> : <Badge tone="rose">error</Badge>}
              <div className="min-w-0 flex-1">
                <div className="text-xs text-slate-500">{taskLabel[r.task]} · {fmtDateTime(r.created_at)}</div>
                <div className="text-slate-300">{r.ok ? r.summary : r.error}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function EventsPanel({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const events = useQuery({ queryKey: ["events", symbol], queryFn: () => api<StockEvent[]>(`/stocks/${symbol}/events`) });
  const del = useMutation({
    mutationFn: (id: number) => api(`/events/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["events", symbol] }),
  });
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = (events.data ?? []).filter((e) => e.date >= today).reverse();
  const past = (events.data ?? []).filter((e) => e.date < today).slice(0, 5);

  return (
    <Card
      title="Events"
      action={
        <Button size="sm" onClick={() => setOpen(true)}>
          <CalendarPlus className="h-3.5 w-3.5" /> Add
        </Button>
      }
    >
      {upcoming.length === 0 && past.length === 0 ? (
        <Empty title="No known event">Binary events (trial readouts, FDA/EMA decisions) block buys and trigger protective sells.</Empty>
      ) : (
        <ul className="space-y-2">
          {[...upcoming, ...past].map((e) => (
            <li key={e.id} className={cx("flex items-start gap-3 rounded-lg px-2 py-1.5", e.date < today && "opacity-50")}>
              <div className="w-14 shrink-0 text-center">
                <div className="num text-sm font-semibold text-white">{new Date(`${e.date}T12:00:00`).getDate()}</div>
                <div className="text-[10px] uppercase text-slate-500">{new Date(`${e.date}T12:00:00`).toLocaleDateString("fr-FR", { month: "short", year: "2-digit" })}</div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-200">{e.title}</div>
                <div className="mt-0.5 flex gap-1">
                  <Badge>{e.kind}</Badge>
                  {e.binary && <Badge tone="amber">binary</Badge>}
                  <Badge tone={e.source === "ai" ? "violet" : "slate"}>{e.source}</Badge>
                </div>
              </div>
              <button onClick={() => del.mutate(e.id)} className="rounded p-1 text-slate-600 hover:text-rose-300" title="Delete">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <EventModal symbol={symbol} open={open} onClose={() => setOpen(false)} />
    </Card>
  );
}

function EventModal({ symbol, open, onClose }: { symbol: string; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ date: "", kind: "trial", title: "", binary: true });
  const m = useMutation({
    mutationFn: () => post(`/stocks/${symbol}/events`, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events", symbol] });
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <Modal open={open} onClose={onClose} title="Add an event">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date">
            <Input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
          </Field>
          <Field label="Kind">
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="trial">Trial readout</option>
              <option value="regulatory">Regulator decision</option>
              <option value="earnings">Earnings</option>
              <option value="agm">Shareholder meeting</option>
              <option value="other">Other</option>
            </Select>
          </Field>
          <Field label="Title" className="col-span-2">
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
          </Field>
          <label className="col-span-2 flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.binary} onChange={(e) => setForm({ ...form, binary: e.target.checked })} className="accent-emerald-500" />
            Binary: the outcome can move the stock a lot in one day
          </label>
        </div>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={m.isPending}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}
