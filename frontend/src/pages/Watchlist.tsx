import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, patch } from "../api/client";
import type { Bucket, Stock } from "../api/types";
import { BucketBadge, Card, ErrorBox, TrendBadge } from "../components/ui";
import { changeClass, fmtNum, fmtPct, fmtPrice } from "../lib/format";

type Filter = "all" | Bucket | "inactive";

export default function Watchlist() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api<Stock[]>("/stocks") });

  const toggle = useMutation({
    mutationFn: (s: Stock) => patch<Stock>(`/stocks/${s.symbol}`, { active: !s.active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stocks"] }),
  });

  const rows = useMemo(() => {
    const all = stocks.data ?? [];
    if (filter === "inactive") return all.filter((s) => !s.active);
    const active = all.filter((s) => s.active);
    return filter === "all" ? active : active.filter((s) => s.bucket === filter);
  }, [stocks.data, filter]);

  if (stocks.error) return <ErrorBox error={stocks.error} />;

  return (
    <Card>
      <div className="mb-4 flex flex-wrap gap-2">
        {(["all", "core", "growth", "inactive"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded px-3 py-1 text-sm ${filter === f ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}
          >
            {f}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2">Stock</th>
              <th>Bucket</th>
              <th className="text-right">Last</th>
              <th className="text-right">1 day</th>
              <th className="pl-4">Trend</th>
              <th className="text-right">RSI</th>
              <th className="text-right">ATR %</th>
              <th className="text-right">Data</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((s) => {
              const snap = s.snapshot;
              return (
                <tr key={s.symbol} onClick={() => navigate(`/stocks/${s.symbol}`)} className="cursor-pointer hover:bg-slate-800/40">
                  <td className="py-2">
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-slate-500">
                      {s.symbol} · {s.country}
                      {s.last_error && <span className="ml-2 text-rose-400" title={s.last_error}>data error</span>}
                    </div>
                  </td>
                  <td><BucketBadge bucket={s.bucket} /></td>
                  <td className="num text-right">{fmtPrice(snap?.close, s.currency)}</td>
                  <td className={`num text-right ${changeClass(snap?.change_1d_pct)}`}>{fmtPct(snap?.change_1d_pct)}</td>
                  <td className="pl-4"><TrendBadge trend={s.trend} /></td>
                  <td className={`num text-right ${rsiClass(snap?.rsi14)}`}>{fmtNum(snap?.rsi14, 0)}</td>
                  <td className="num text-right">{fmtNum(snap?.atr_pct, 1)}</td>
                  <td className="num text-right text-xs text-slate-500">{snap?.date ?? "–"}</td>
                  <td className="text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle.mutate(s);
                      }}
                      className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-white"
                    >
                      {s.active ? "Pause" : "Track"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {stocks.isPending && <p className="py-4 text-sm text-slate-500">Loading…</p>}
      </div>
    </Card>
  );
}

function rsiClass(v: number | null | undefined) {
  if (v == null) return "";
  if (v >= 70) return "text-rose-300";
  if (v <= 30) return "text-emerald-300";
  return "";
}
