import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { api, patch, post } from "../api/client";
import type { Bucket, Stock } from "../api/types";
import { Badge, BucketBadge, Button, Card, cx, ErrorBox, Field, Input, Loading, Modal, PageHeader, ScoreBadge, Select, Tabs, TrendBadge } from "../components/ui";
import { changeClass, fmtNum, fmtPct, fmtPrice, fmtShortDate } from "../lib/format";

type Filter = "all" | Bucket | "uptrend" | "inactive";
type Sort = "name" | "change" | "score" | "rsi";

export default function Watchlist() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("name");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api<Stock[]>("/stocks") });

  const toggle = useMutation({
    mutationFn: (s: Stock) => patch<Stock>(`/stocks/${s.symbol}`, { active: !s.active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stocks"] }),
  });

  const rows = useMemo(() => {
    let all = stocks.data ?? [];
    if (filter === "inactive") all = all.filter((s) => !s.active);
    else {
      all = all.filter((s) => s.active);
      if (filter === "core" || filter === "growth") all = all.filter((s) => s.bucket === filter);
      if (filter === "uptrend") all = all.filter((s) => s.trend === "up");
    }
    const q = query.trim().toLowerCase();
    if (q) all = all.filter((s) => s.name.toLowerCase().includes(q) || s.symbol.toLowerCase().includes(q));
    const key: Record<Sort, (s: Stock) => number | string> = {
      name: (s) => s.name.toLowerCase(),
      change: (s) => -(s.snapshot?.change_1d_pct ?? -999),
      score: (s) => -(s.ai?.score ?? -1),
      rsi: (s) => s.snapshot?.rsi14 ?? 999,
    };
    return [...all].sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : key[sort](a) > key[sort](b) ? 1 : 0));
  }, [stocks.data, filter, sort, query]);

  if (stocks.error) return <ErrorBox error={stocks.error} />;

  return (
    <div>
      <PageHeader
        title="Watchlist"
        subtitle="PEA-eligible European healthcare stocks. Click a row for the chart and the AI research."
        action={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Add stock
          </Button>
        }
      />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 p-4">
          <Tabs
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "uptrend", label: "Uptrend" },
              { value: "core", label: "Core" },
              { value: "growth", label: "Growth" },
              { value: "inactive", label: "Paused" },
            ]}
          />
          <div className="relative min-w-[160px] flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
            <Input placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-8" />
          </div>
          <Select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="!w-auto">
            <option value="name">Sort: name</option>
            <option value="change">Sort: 1-day change</option>
            <option value="score">Sort: AI score</option>
            <option value="rsi">Sort: RSI (low first)</option>
          </Select>
        </div>
        {stocks.isPending ? (
          <Loading />
        ) : (
          <div className="overflow-x-auto pb-2">
            <table className="table-base min-w-[880px]">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th className="!text-right">Last</th>
                  <th className="!text-right">1 day</th>
                  <th>Trend</th>
                  <th className="!text-right">RSI</th>
                  <th className="!text-right">ATR %</th>
                  <th>AI</th>
                  <th>Last signal</th>
                  <th>Next event</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const snap = s.snapshot;
                  return (
                    <tr key={s.symbol} onClick={() => navigate(`/stocks/${s.symbol}`)} className="cursor-pointer transition-colors hover:bg-slate-800/40">
                      <td>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-white">{s.name}</span>
                          {s.held_in.map((m) => (
                            <Badge key={m} tone={m === "live" ? "emerald" : "amber"}>held{m === "paper" ? " (paper)" : ""}</Badge>
                          ))}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                          {s.symbol} · {s.country} <BucketBadge bucket={s.bucket} />
                          {s.last_error && <span className="text-rose-400" title={s.last_error}>data error</span>}
                        </div>
                      </td>
                      <td className="num text-right">{fmtPrice(snap?.close, s.currency)}</td>
                      <td className={cx("num text-right", changeClass(snap?.change_1d_pct))}>{fmtPct(snap?.change_1d_pct)}</td>
                      <td><TrendBadge trend={s.trend} /></td>
                      <td className={cx("num text-right", rsiClass(snap?.rsi14))}>{fmtNum(snap?.rsi14, 0)}</td>
                      <td className="num text-right text-slate-400">{fmtNum(snap?.atr_pct, 1)}</td>
                      <td title={s.ai?.summary}><ScoreBadge score={s.ai?.score} /></td>
                      <td>
                        {s.last_signal ? (
                          <span className={cx("text-xs", s.last_signal.side === "buy" ? "text-emerald-300" : "text-rose-300")}>
                            {s.last_signal.side} · {fmtShortDate(s.last_signal.date)}
                          </span>
                        ) : (
                          <span className="text-slate-600">–</span>
                        )}
                      </td>
                      <td className="max-w-[180px] truncate text-xs text-slate-400" title={s.next_event?.title}>
                        {s.next_event ? `${fmtShortDate(s.next_event.date)} · ${s.next_event.title}` : "–"}
                      </td>
                      <td className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggle.mutate(s);
                          }}
                        >
                          {s.active ? "Pause" : "Track"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <AddStockModal open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function rsiClass(v: number | null | undefined) {
  if (v == null) return "";
  if (v >= 70) return "text-rose-300";
  if (v <= 30) return "text-emerald-300";
  return "";
}

function AddStockModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ symbol: "", name: "", country: "FR", bucket: "growth" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const m = useMutation({
    mutationFn: async () => {
      await post("/stocks", { ...form, symbol: form.symbol.toUpperCase(), country: form.country.toUpperCase() });
      await post("/system/refresh", { symbols: [form.symbol.toUpperCase()] });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stocks"] });
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <Modal open={open} onClose={onClose} title="Add a stock">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Yahoo symbol" hint="With the exchange suffix: .PA .AS .BR .DE .MI .MC .CO .ST .HE .LS">
            <Input value={form.symbol} onChange={set("symbol")} placeholder="ALCLS.PA" required />
          </Field>
          <Field label="Name">
            <Input value={form.name} onChange={set("name")} required />
          </Field>
          <Field label="Country (ISO)" hint="EU/EEA headquarters only (PEA)">
            <Input value={form.country} onChange={set("country")} maxLength={2} required />
          </Field>
          <Field label="Bucket">
            <Select value={form.bucket} onChange={set("bucket")}>
              <option value="core">Core (large cap)</option>
              <option value="growth">Growth (small/mid, biotech)</option>
            </Select>
          </Field>
        </div>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={m.isPending}>Add and download history</Button>
        </div>
      </form>
    </Modal>
  );
}
