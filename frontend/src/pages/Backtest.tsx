import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Info, Play, Trash2 } from "lucide-react";
import { api, post } from "../api/client";
import type { BacktestRun, SettingsResponse } from "../api/types";
import EquityChart from "../components/EquityChart";
import { Badge, Button, Callout, Card, cx, Empty, ErrorBox, Field, Input, Loading, PageHeader, Select, Spinner, Stat } from "../components/ui";
import { changeClass, fmtDate, fmtDateTime, fmtEur, fmtPct, fmtShortDate } from "../lib/format";

const PARAMS: { key: string; label: string; step: number }[] = [
  { key: "stop_atr_mult", label: "Stop (× ATR)", step: 0.5 },
  { key: "trail_atr_mult", label: "Trailing (× ATR)", step: 0.5 },
  { key: "trail_trigger_r", label: "Trail after (× risk)", step: 0.5 },
  { key: "trend_break_days", label: "Trend break (sessions)", step: 1 },
  { key: "rsi_pullback", label: "Pullback RSI below", step: 1 },
  { key: "time_stop_days", label: "Time stop (sessions)", step: 10 },
];

export default function Backtest() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const runs = useQuery({
    queryKey: ["backtests"],
    queryFn: () => api<BacktestRun[]>("/backtests"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running") ? 1500 : false),
  });
  const [selected, setSelected] = useState<number | null>(null);
  const [capital, setCapital] = useState("10000");
  const [preset, setPreset] = useState("");
  const [strategy, setStrategy] = useState<Record<string, string>>({});
  const [killOff, setKillOff] = useState(false);

  useEffect(() => {
    if (settings.data && !preset) {
      setPreset(settings.data.settings.fees.preset);
      setStrategy(Object.fromEntries(PARAMS.map((p) => [p.key, String(settings.data!.settings.strategy[p.key])])));
    }
  }, [settings.data, preset]);
  useEffect(() => {
    if (selected == null && runs.data?.length) setSelected(runs.data[0].id);
  }, [runs.data, selected]);

  const run = useMutation({
    mutationFn: () =>
      post<{ id: number }>("/backtests", {
        capital: Number(capital),
        strategy: Object.fromEntries(Object.entries(strategy).map(([k, v]) => [k, Number(v)])),
        risk: killOff ? { kill_switch_drawdown: 0.9 } : {},
        fees: settings.data?.fee_presets[preset] ?? {},
      }),
    onSuccess: (r) => {
      setSelected(r.id);
      qc.invalidateQueries({ queryKey: ["backtests"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/backtests/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setSelected(null);
      qc.invalidateQueries({ queryKey: ["backtests"] });
    },
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Backtest" subtitle="Replays strategy v1 day by day over the stored history, with the same fills, fees and risk rules as paper trading." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="New run">
          {settings.isPending ? (
            <Loading />
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Capital (€)">
                  <Input type="number" min={100} value={capital} onChange={(e) => setCapital(e.target.value)} />
                </Field>
                <Field label="Fees">
                  <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    {Object.keys(settings.data?.fee_presets ?? {}).map((k) => (
                      <option key={k} value={k}>{k.replace(/_/g, " ")}</option>
                    ))}
                  </Select>
                </Field>
                {PARAMS.map((p) => (
                  <Field key={p.key} label={p.label}>
                    <Input type="number" step={p.step} value={strategy[p.key] ?? ""} onChange={(e) => setStrategy({ ...strategy, [p.key]: e.target.value })} />
                  </Field>
                ))}
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={killOff} onChange={(e) => setKillOff(e.target.checked)} className="accent-emerald-500" />
                Ignore the kill switch (see the raw strategy)
              </label>
              {run.error && <ErrorBox error={run.error} />}
              <Button variant="primary" className="w-full" onClick={() => run.mutate()} loading={run.isPending}>
                <Play className="h-4 w-4" /> Run backtest
              </Button>
              <p className="text-xs text-slate-500">Other settings (risk rules, sizing) come from Settings.</p>
            </div>
          )}
        </Card>

        <Card title="Runs" padded={false} className="lg:col-span-2">
          {(runs.data ?? []).length === 0 ? (
            <Empty icon={<FlaskConical className="h-6 w-6" />} title="No run yet" />
          ) : (
            <div className="max-h-[420px] overflow-y-auto pb-2">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th className="!text-right">Return</th>
                    <th className="!text-right">Max DD</th>
                    <th className="!text-right">Trades</th>
                    <th className="!text-right">vs B&H</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {runs.data!.map((r) => (
                    <tr key={r.id} onClick={() => setSelected(r.id)} className={cx("cursor-pointer hover:bg-slate-800/40", selected === r.id && "bg-slate-800/60")}>
                      <td>
                        <div className="text-sm text-white">#{r.id} · {fmtEur(r.params.capital ?? 0, 0)}</div>
                        <div className="text-xs text-slate-500">{fmtDateTime(r.created_at)}</div>
                      </td>
                      {r.status === "ok" && r.summary ? (
                        <>
                          <td className={cx("num text-right", changeClass(r.summary.total_return_pct))}>{fmtPct(r.summary.total_return_pct, true, 1)}</td>
                          <td className="num text-right text-rose-300">{fmtPct(r.summary.max_drawdown_pct, false, 1)}</td>
                          <td className="num text-right">{r.summary.trades}</td>
                          <td className="num text-right text-slate-400">{fmtPct(r.summary.benchmark_return_pct, true, 0)}</td>
                        </>
                      ) : (
                        <td colSpan={4} className="text-right text-xs">
                          {r.status === "running" ? <Spinner className="ml-auto h-4 w-4" /> : <span className="text-rose-300">{r.error}</span>}
                        </td>
                      )}
                      <td className="text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            del.mutate(r.id);
                          }}
                          className="rounded p-1 text-slate-600 hover:text-rose-300"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      {selected != null && <Report id={selected} />}
    </div>
  );
}

function Report({ id }: { id: number }) {
  const q = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api<BacktestRun>(`/backtests/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
  const series = useMemo(() => {
    const eq = q.data?.report?.equity ?? [];
    return [
      { label: "Strategy", color: "#34d399", data: eq.map((e) => ({ time: e.time, value: e.value })), area: true },
      { label: "Buy & hold (equal weight)", color: "#94a3b8", dashed: true, data: eq.filter((e) => e.benchmark != null).map((e) => ({ time: e.time, value: e.benchmark as number })) },
    ];
  }, [q.data]);

  if (q.isPending) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data!;
  if (r.status === "running") return <Card><div className="flex items-center gap-3 text-sm text-slate-400"><Spinner /> Running…</div></Card>;
  if (r.status === "error" || !r.summary || !r.report) return <ErrorBox error={r.error ?? "Backtest failed"} />;
  const s = r.summary;
  const trades = r.report.trades;

  return (
    <div className="space-y-5">
      <Card title={`Run #${r.id} · ${fmtDate(s.start)} → ${fmtDate(s.end)} (${s.years} years)`}>
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4 lg:grid-cols-6">
          <Stat label="Final value" value={fmtEur(s.final_value, 0)} sub={`from ${fmtEur(s.capital, 0)}`} />
          <Stat label="Total return" value={fmtPct(s.total_return_pct, true, 1)} valueClass={changeClass(s.total_return_pct)} sub={`CAGR ${fmtPct(s.cagr_pct, true, 1)}`} />
          <Stat label="Max drawdown" value={fmtPct(s.max_drawdown_pct, false, 1)} valueClass="text-rose-300" sub={`B&H ${fmtPct(s.benchmark_max_drawdown_pct, false, 1)}`} />
          <Stat label="Buy & hold" value={fmtPct(s.benchmark_return_pct, true, 1)} valueClass={changeClass(s.benchmark_return_pct)} />
          <Stat label="Trades" value={s.trades} sub={`win ${s.win_rate_pct ?? "–"} % · PF ${s.profit_factor ?? "–"}`} />
          <Stat label="Fees" value={fmtEur(s.fees_paid, 0)} sub={`exposure ${s.exposure_pct} %`} />
        </div>
        <div className="mt-6">
          <EquityChart series={series} height={320} />
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <KStat k="Average win" v={fmtPct(s.avg_win_pct)} cls="text-emerald-300" />
          <KStat k="Average loss" v={fmtPct(s.avg_loss_pct)} cls="text-rose-300" />
        </div>
        {s.kill_switch_on && (
          <div className="mt-4">
            <Callout tone="rose">Kill switch triggered on {fmtDate(s.kill_switch_on)}: no new buys after that date. Tick “Ignore the kill switch” to see the raw strategy.</Callout>
          </div>
        )}
        <div className="mt-4">
          <Callout tone="sky" icon={<Info className="h-4 w-4" />}>
            <ul className="list-inside list-disc space-y-0.5">
              {r.report.notes.filter((n) => !n.startsWith("Kill switch")).map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </Callout>
        </div>
      </Card>

      <Card title={`Trades (${trades.length})`} padded={false}>
        <div className="max-h-[480px] overflow-auto pb-2">
          <table className="table-base min-w-[760px]">
            <thead className="sticky top-0 bg-slate-900">
              <tr>
                <th>Stock</th>
                <th>Entry</th>
                <th>Exit</th>
                <th className="!text-right">Days</th>
                <th>Rules</th>
                <th className="!text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {[...trades].reverse().map((t, i) => (
                <tr key={i}>
                  <td>
                    <div className="text-white">{t.name}</div>
                    <div className="text-xs text-slate-500">{t.symbol}</div>
                  </td>
                  <td className="num text-xs text-slate-400">{fmtShortDate(t.entry_date)} @ {t.entry.toFixed(2)}</td>
                  <td className="num text-xs text-slate-400">{t.exit_date ? `${fmtShortDate(t.exit_date)} @ ${t.exit.toFixed(2)}` : "open"}</td>
                  <td className="num text-right text-slate-400">{t.days}</td>
                  <td className="text-xs">
                    <Badge>{t.entry_rule}</Badge> → <Badge tone={t.exit_rule === "stop_loss" ? "rose" : t.exit_rule === "open" ? "sky" : "slate"}>{t.exit_rule}</Badge>
                  </td>
                  <td className={cx("num text-right font-medium", changeClass(t.pnl_eur))}>
                    {fmtEur(t.pnl_eur, 0, true)}
                    <div className="text-xs">{fmtPct(t.pnl_pct, true, 1)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function KStat({ k, v, cls }: { k: string; v: string; cls: string }) {
  return (
    <div className="flex justify-between rounded-lg bg-slate-950/50 px-3 py-2 text-sm ring-1 ring-inset ring-slate-800">
      <span className="text-slate-400">{k}</span>
      <span className={cx("num font-medium", cls)}>{v}</span>
    </div>
  );
}
