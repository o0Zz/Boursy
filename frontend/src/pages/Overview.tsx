import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Bot, Inbox, ShieldAlert, TrendingUp, Wallet } from "lucide-react";
import { api } from "../api/client";
import type { AIStatus, EquityPoint, Proposal, Stock, SystemStatus } from "../api/types";
import EquityChart from "../components/EquityChart";
import ProposalCard from "../components/ProposalCard";
import { Badge, Card, Callout, cx, Empty, ErrorBox, Loading, Meter, Stat, TrendBadge } from "../components/ui";
import { changeClass, fmtDateTime, fmtEur, fmtPct, fmtPrice } from "../lib/format";
import { useMode } from "../lib/mode";

export default function Overview() {
  const { mode, current, loading } = useMode();
  const equity = useQuery({ queryKey: ["equity", mode], queryFn: () => api<EquityPoint[]>(`/portfolios/${mode}/equity`), enabled: !!current });
  const proposals = useQuery({
    queryKey: ["proposals", mode, "pending"],
    queryFn: () => api<Proposal[]>(`/proposals?mode=${mode}&status=pending`),
    enabled: !!current,
  });
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api<Stock[]>("/stocks") });
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<SystemStatus>("/system/status") });
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/ai/status") });

  const movers = useMemo(() => {
    const withData = (stocks.data ?? []).filter((s) => s.active && s.snapshot?.change_1d_pct != null);
    return [...withData].sort((a, b) => Math.abs(b.snapshot!.change_1d_pct!) - Math.abs(a.snapshot!.change_1d_pct!)).slice(0, 6);
  }, [stocks.data]);
  const trendCount = (t: string) => (stocks.data ?? []).filter((s) => s.active && s.trend === t).length;

  if (loading) return <Loading />;
  if (!current)
    return (
      <Card>
        <Empty icon={<Wallet className="h-6 w-6" />} title="No portfolio enabled">
          Enable the paper or the live portfolio in <Link className="text-emerald-400" to="/settings">Settings</Link>.
        </Empty>
      </Card>
    );

  const p = current;
  const ddUsed = Math.abs(p.drawdown_pct);
  const ddMax = Math.abs(p.kill_switch_drawdown_pct);
  const curve = (equity.data ?? []).map((e) => ({ time: e.time, value: e.value }));

  return (
    <div className="space-y-5">
      {p.kill_switch && (
        <Callout tone="rose" icon={<ShieldAlert className="h-4 w-4" />}>
          <b>Kill switch active.</b> The portfolio fell {ddMax}% below its peak: no new buys until you reset it in{" "}
          <Link to="/settings" className="underline">Settings</Link>.
        </Callout>
      )}

      {/* Hero */}
      <section className="card relative overflow-hidden p-5 sm:p-6">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <div>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              {p.name}
              <Badge tone={p.mode === "live" ? "emerald" : "amber"}>{p.mode === "live" ? "real money" : "simulation"}</Badge>
            </div>
            <div className="num mt-2 text-4xl font-semibold tracking-tight text-white sm:text-5xl">{fmtEur(p.value)}</div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Delta label="Today" eur={p.pnl_day} pct={p.pnl_day_pct} />
              <Delta label="Total" eur={p.pnl_total} pct={p.pnl_total_pct} />
            </div>
            <div className="mt-6 grid grid-cols-2 gap-4">
              <Stat label="Cash" value={fmtEur(p.cash)} sub={`${p.value ? Math.round((p.cash / p.value) * 100) : 0}% of value`} />
              <Stat label="Invested" value={fmtEur(p.invested)} sub={`since ${p.started_on}`} />
              <Stat label="Realized P&L" value={fmtEur(p.realized_pnl, 2, true)} valueClass={changeClass(p.realized_pnl)} />
              <Stat label="Fees paid" value={fmtEur(p.fees_paid)} />
            </div>
            <div className="mt-6">
              <div className="mb-1.5 flex justify-between text-xs">
                <span className="text-slate-400">Drawdown from peak {fmtEur(p.peak_value, 0)}</span>
                <span className={cx("num font-medium", p.kill_switch ? "text-rose-400" : "text-slate-300")}>
                  {fmtPct(p.drawdown_pct)} / −{ddMax}%
                </span>
              </div>
              <Meter value={ddUsed} max={ddMax} danger={p.kill_switch || ddUsed / ddMax > 0.8} />
              <div className="mt-1 text-[11px] text-slate-500">Kill switch at {fmtEur(p.kill_switch_level)}</div>
            </div>
          </div>
          <div className="min-w-0">
            {curve.length > 1 ? (
              <EquityChart series={[{ label: "Value", color: "#34d399", data: curve, area: true }]} height={280} />
            ) : (
              <Empty icon={<TrendingUp className="h-6 w-6" />} title="Equity curve starts after the first post-close run">
                One point per trading day, recorded at 17:45.
              </Empty>
            )}
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Proposals */}
        <div className="space-y-3 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300">Pending proposals</h2>
            <Link to="/proposals" className="text-xs text-emerald-400 hover:text-emerald-300">All proposals →</Link>
          </div>
          {proposals.error && <ErrorBox error={proposals.error} />}
          {(proposals.data ?? []).length === 0 ? (
            <Card>
              <Empty icon={<Inbox className="h-6 w-6" />} title="Nothing to do">
                New buy and sell proposals appear here after the market close (17:45, Paris time).
              </Empty>
            </Card>
          ) : (
            proposals.data!.map((pr) => <ProposalCard key={pr.id} p={pr} />)
          )}

          <Card title="Open positions" action={<Link to="/positions" className="text-xs text-emerald-400">Details →</Link>} padded={false}>
            {p.positions.length === 0 ? (
              <Empty title="No open position" />
            ) : (
              <div className="overflow-x-auto pb-2">
                <table className="table-base min-w-[520px]">
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th className="!text-right">Value</th>
                      <th className="!text-right">P&L</th>
                      <th className="!text-right">To stop</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.positions.map((pos) => (
                      <tr key={pos.id}>
                        <td>
                          <Link to={`/stocks/${pos.symbol}`} className="font-medium text-white hover:text-emerald-300">{pos.name}</Link>
                          <div className="text-xs text-slate-500">{pos.qty} × {fmtPrice(pos.price, pos.currency)}</div>
                        </td>
                        <td className="num text-right">{fmtEur(pos.value_eur)}</td>
                        <td className={cx("num text-right", changeClass(pos.pnl_eur))}>
                          {fmtEur(pos.pnl_eur, 2, true)}
                          <div className="text-xs">{fmtPct(pos.pnl_pct)}</div>
                        </td>
                        <td className="num text-right text-slate-300">{fmtPct(pos.stop_distance_pct, false, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        {/* Market side */}
        <div className="space-y-5">
          <Card title="Market">
            <div className="grid grid-cols-3 gap-2 text-center">
              <TrendBox n={trendCount("up")} label="uptrend" cls="text-emerald-400" />
              <TrendBox n={trendCount("mixed")} label="mixed" cls="text-amber-300" />
              <TrendBox n={trendCount("down")} label="down" cls="text-rose-400" />
            </div>
            <div className="mt-4 space-y-2">
              {movers.map((s) => (
                <Link key={s.symbol} to={`/stocks/${s.symbol}`} className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-slate-800/60">
                  <div className="min-w-0">
                    <div className="truncate text-sm text-slate-200">{s.name}</div>
                    <div className="flex items-center gap-1.5 text-xs text-slate-500">{s.symbol} <TrendBadge trend={s.trend} /></div>
                  </div>
                  <span className={cx("num flex items-center text-sm font-medium", changeClass(s.snapshot!.change_1d_pct))}>
                    {s.snapshot!.change_1d_pct! >= 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
                    {fmtPct(s.snapshot!.change_1d_pct)}
                  </span>
                </Link>
              ))}
            </div>
            <div className="mt-3 text-[11px] text-slate-500">Last session {status.data?.last_bar_date ?? "–"} · data delayed</div>
          </Card>

          <Card title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" /> AI analyst</span>}>
            {ai.data && (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Backend</span>
                  <Badge tone={ai.data.available ? "emerald" : "slate"}>{ai.data.backend}</Badge>
                </div>
                {!ai.data.available && <p className="text-xs text-slate-500">{ai.data.reason}</p>}
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">API cost this month</span>
                  <span className="num">{ai.data.month_cost_usd.toFixed(2)} / {ai.data.monthly_budget_usd} $</span>
                </div>
                <Meter value={ai.data.month_cost_usd} max={Math.max(ai.data.monthly_budget_usd, 0.01)} />
              </div>
            )}
          </Card>

          <Card title="Schedule">
            <ul className="space-y-2 text-sm">
              {(status.data?.scheduled_jobs ?? []).map((j) => (
                <li key={j.id} className="flex justify-between gap-3">
                  <span className="truncate text-slate-400">{j.name}</span>
                  <span className="num shrink-0 text-slate-300">{fmtDateTime(j.next_run)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Delta({ label, eur, pct }: { label: string; eur: number | null; pct: number | null }) {
  const up = (eur ?? 0) >= 0;
  return (
    <span
      className={cx(
        "num inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm font-medium ring-1 ring-inset",
        eur == null ? "bg-slate-800 text-slate-400 ring-slate-700" : up ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/25" : "bg-rose-500/10 text-rose-300 ring-rose-500/25",
      )}
    >
      <span className="text-xs font-normal opacity-70">{label}</span>
      {eur == null ? "–" : `${fmtEur(eur, 2, true)} (${fmtPct(pct)})`}
    </span>
  );
}

function TrendBox({ n, label, cls }: { n: number; label: string; cls: string }) {
  return (
    <div className="rounded-xl bg-slate-950/60 py-3 ring-1 ring-inset ring-slate-800">
      <div className={cx("num text-2xl font-semibold", cls)}>{n}</div>
      <div className="text-[11px] text-slate-500">{label}</div>
    </div>
  );
}
