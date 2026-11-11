import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Stock, SystemStatus } from "../api/types";
import { Card, ErrorBox, Stat, TrendBadge } from "../components/ui";
import { changeClass, fmtDateTime, fmtPct, fmtPrice } from "../lib/format";

export default function Overview() {
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api<Stock[]>("/stocks") });
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<SystemStatus>("/system/status") });

  if (stocks.error) return <ErrorBox error={stocks.error} />;

  const withData = (stocks.data ?? []).filter((s) => s.active && s.snapshot);
  const movers = [...withData].sort(
    (a, b) => Math.abs(b.snapshot!.change_1d_pct ?? 0) - Math.abs(a.snapshot!.change_1d_pct ?? 0),
  );
  const count = (t: string) => withData.filter((s) => s.trend === t).length;
  const nextJob = status.data?.scheduled_jobs.find((j) => j.id === "post_close");

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card>
          <Stat label="Tracked stocks" value={status.data?.active_stocks ?? "–"} sub={`${withData.length} with data`} />
        </Card>
        <Card>
          <Stat label="Uptrend" value={count("up")} valueClass="text-emerald-400" sub={`${count("mixed")} mixed · ${count("down")} down`} />
        </Card>
        <Card>
          <Stat label="Last data" value={status.data?.last_bar_date ?? "–"} sub={`${status.data?.stocks_with_errors ?? 0} stocks with errors`} />
        </Card>
        <Card>
          <Stat label="Next refresh" value={nextJob?.next_run ? fmtDateTime(nextJob.next_run) : "–"} sub="post-close, trading days" />
        </Card>
      </div>

      <Card title="Portfolio">
        <p className="text-sm text-slate-400">
          Portfolio, signals and trade proposals arrive with the paper-trading milestone (M4). For now Boursy collects
          market data and computes indicators.
        </p>
      </Card>

      <Card title="Biggest moves (last session)">
        {stocks.isPending ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : movers.length === 0 ? (
          <p className="text-sm text-slate-500">No data yet. The first download starts automatically, or run it from System.</p>
        ) : (
          <ul className="divide-y divide-slate-800">
            {movers.slice(0, 8).map((s) => (
              <li key={s.symbol}>
                <Link to={`/stocks/${s.symbol}`} className="flex items-center gap-3 py-2 hover:bg-slate-800/40">
                  <span className="w-44 truncate font-medium">{s.name}</span>
                  <TrendBadge trend={s.trend} />
                  <span className="num ml-auto">{fmtPrice(s.snapshot!.close, s.currency)}</span>
                  <span className={`num w-20 text-right ${changeClass(s.snapshot!.change_1d_pct)}`}>
                    {fmtPct(s.snapshot!.change_1d_pct)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
