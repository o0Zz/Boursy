import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Database, Play, RefreshCw } from "lucide-react";
import { api, post } from "../api/client";
import type { AIStatus, JobRun, NotificationRow, SystemStatus } from "../api/types";
import { Badge, Button, Card, cx, ErrorBox, PageHeader, Stat } from "../components/ui";
import { fmtDateTime } from "../lib/format";

const statusTone = { ok: "emerald", error: "rose", running: "amber" } as const;
const JOBS = [
  { id: "post_close", label: "Post-close run", hint: "Download, signals, proposals" },
  { id: "trading", label: "Signals only", hint: "No download" },
  { id: "midday", label: "Midday monitor", hint: "Stops and large moves" },
  { id: "pre_open", label: "News check", hint: "AI, open positions" },
  { id: "weekly", label: "Weekly", hint: "AI screening, summary" },
];

export default function System() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => api<SystemStatus>("/system/status"),
    refetchInterval: (q) => (q.state.data?.refresh_running || q.state.data?.trading_running ? 2000 : 30_000),
  });
  const busy = !!(status.data?.refresh_running || status.data?.trading_running);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api<JobRun[]>("/system/jobs?limit=40"), refetchInterval: busy ? 2000 : 30_000 });
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/ai/status") });
  const notes = useQuery({ queryKey: ["notifications"], queryFn: () => api<NotificationRow[]>("/notifications?limit=30") });

  const refresh = useMutation({
    mutationFn: () => post("/system/refresh", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
  const runJob = useMutation({
    mutationFn: (job: string) => post(`/system/run/${job}`),
    onSuccess: () => {
      setTimeout(() => {
        for (const k of ["status", "jobs", "portfolios", "proposals", "notifications"]) qc.invalidateQueries({ queryKey: [k] });
      }, 1500);
    },
  });

  const s = status.data;
  return (
    <div className="space-y-5">
      <PageHeader title="System" subtitle={s ? `Version ${s.version} · data from ${s.data_provider}` : undefined} />
      {status.error && <ErrorBox error={status.error} />}
      <Card>
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat icon={<Database className="h-3.5 w-3.5" />} label="Stocks" value={s ? `${s.active_stocks} / ${s.stocks}` : "–"} sub={`${s?.stocks_with_errors ?? 0} with errors`} />
          <Stat label="Daily bars" value={s?.bars.toLocaleString("fr-FR") ?? "–"} />
          <Stat label="Last session" value={s?.last_bar_date ?? "–"} />
          <Stat label="Scheduler" value={s ? (s.scheduler_running ? "running" : "stopped") : "–"} valueClass={s?.scheduler_running ? "text-emerald-400" : "text-rose-400"} />
        </div>
        <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-800 pt-4">
          <Button variant="primary" onClick={() => refresh.mutate()} loading={refresh.isPending} disabled={busy}>
            <RefreshCw className={cx("h-4 w-4", s?.refresh_running && "animate-spin")} /> {s?.refresh_running ? "Refreshing…" : "Refresh data"}
          </Button>
          {JOBS.map((j) => (
            <Button key={j.id} onClick={() => runJob.mutate(j.id)} disabled={busy} title={j.hint}>
              <Play className="h-3.5 w-3.5" /> {j.label}
            </Button>
          ))}
        </div>
        {(refresh.error || runJob.error) && <div className="mt-3"><ErrorBox error={refresh.error ?? runJob.error} /></div>}
        {runJob.isSuccess && <p className="mt-2 text-xs text-emerald-300">Started {runJob.variables}. Results appear in the job runs below.</p>}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Scheduled jobs">
          <ul className="space-y-2 text-sm">
            {(s?.scheduled_jobs ?? []).map((j) => (
              <li key={j.id} className="flex justify-between gap-4">
                <span className="text-slate-300">{j.name}</span>
                <span className="num text-slate-400">{fmtDateTime(j.next_run)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="AI usage">
          {ai.data && (
            <>
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                <Badge tone={ai.data.available ? "emerald" : "slate"}>backend {ai.data.backend}</Badge>
                <Badge>{ai.data.calls_today} calls today</Badge>
                <Badge>{ai.data.month_cost_usd.toFixed(2)} $ API this month</Badge>
              </div>
              {ai.data.costs.length === 0 ? (
                <p className="text-sm text-slate-500">No AI call yet.</p>
              ) : (
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th>Task</th>
                      <th className="!text-right">Calls</th>
                      <th className="!text-right">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ai.data.costs.map((c, i) => (
                      <tr key={i}>
                        <td className="num text-slate-400">{c.month}</td>
                        <td>{c.task} <span className="text-xs text-slate-500">({c.backend})</span></td>
                        <td className="num text-right">{c.calls}</td>
                        <td className="num text-right">{c.backend === "subscription" ? "≈" : ""}{c.cost_usd.toFixed(3)} $</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Card>
      </div>

      <Card title="Job runs" padded={false}>
        <div className="overflow-x-auto pb-2">
          <table className="table-base min-w-[640px]">
            <thead>
              <tr>
                <th>Job</th>
                <th>Status</th>
                <th>Started</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {(jobs.data ?? []).map((j) => (
                <tr key={j.id} className="align-top">
                  <td className="whitespace-nowrap font-medium text-slate-200">{j.job}</td>
                  <td><Badge tone={statusTone[j.status]}>{j.status}</Badge></td>
                  <td className="num whitespace-nowrap text-slate-400">{fmtDateTime(j.started_at)}</td>
                  <td className="max-w-xl break-words text-xs text-slate-400">{j.message ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={<span className="flex items-center gap-2"><Bell className="h-4 w-4" /> Notifications</span>} padded={false}>
        <div className="overflow-x-auto pb-2">
          <table className="table-base min-w-[640px]">
            <thead>
              <tr>
                <th>When</th>
                <th>Title</th>
                <th>Push</th>
                <th>Email</th>
              </tr>
            </thead>
            <tbody>
              {(notes.data ?? []).map((n) => (
                <tr key={n.id} title={n.body}>
                  <td className="num whitespace-nowrap text-slate-400">{fmtDateTime(n.created_at)}</td>
                  <td className="text-slate-200">{n.title}{n.error && <div className="text-xs text-rose-300">{n.error}</div>}</td>
                  <td><Badge tone={n.push === "sent" ? "emerald" : n.push === "failed" ? "rose" : "slate"}>{n.push}</Badge></td>
                  <td><Badge tone={n.email === "sent" ? "emerald" : n.email === "failed" ? "rose" : "slate"}>{n.email}</Badge></td>
                </tr>
              ))}
              {(notes.data ?? []).length === 0 && (
                <tr><td colSpan={4} className="py-6 text-center text-sm text-slate-500">No notification sent yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
