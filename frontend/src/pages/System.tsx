import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "../api/client";
import type { JobRun, SystemStatus } from "../api/types";
import { Card, ErrorBox, Stat } from "../components/ui";
import { fmtDateTime } from "../lib/format";

const statusClass = { ok: "text-emerald-400", error: "text-rose-400", running: "text-amber-300" };

export default function System() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => api<SystemStatus>("/system/status"),
    refetchInterval: (q) => (q.state.data?.refresh_running ? 2000 : false),
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<JobRun[]>("/system/jobs?limit=30"),
    refetchInterval: status.data?.refresh_running ? 2000 : false,
  });

  const refresh = useMutation({
    mutationFn: () => post("/system/refresh", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["stocks"] });
    },
  });

  const s = status.data;
  return (
    <div className="space-y-4">
      {status.error && <ErrorBox error={status.error} />}
      <Card title="Status">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Stocks" value={s ? `${s.active_stocks} / ${s.stocks}` : "–"} sub="active / total" />
          <Stat label="Daily bars" value={s?.bars.toLocaleString("fr-FR") ?? "–"} sub={`provider: ${s?.data_provider ?? "–"}`} />
          <Stat label="Last bar" value={s?.last_bar_date ?? "–"} />
          <Stat label="Scheduler" value={s ? (s.scheduler_running ? "running" : "stopped") : "–"} valueClass={s?.scheduler_running ? "text-emerald-400" : "text-rose-400"} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || s?.refresh_running}
            className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {s?.refresh_running ? "Refreshing…" : "Refresh data now"}
          </button>
          {refresh.error && <span className="text-sm text-rose-400">{(refresh.error as Error).message}</span>}
        </div>
      </Card>

      <Card title="Scheduled jobs">
        <ul className="space-y-1 text-sm">
          {(s?.scheduled_jobs ?? []).map((j) => (
            <li key={j.id} className="flex justify-between gap-4">
              <span>{j.name}</span>
              <span className="num text-slate-400">{fmtDateTime(j.next_run)}</span>
            </li>
          ))}
          {s && s.scheduled_jobs.length === 0 && <li className="text-slate-500">No scheduled jobs.</li>}
        </ul>
      </Card>

      <Card title="Recent job runs">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px] text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Job</th>
                <th>Status</th>
                <th>Started</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(jobs.data ?? []).map((j) => (
                <tr key={j.id} className="align-top">
                  <td className="py-2 pr-3">{j.job}</td>
                  <td className={`pr-3 ${statusClass[j.status]}`}>{j.status}</td>
                  <td className="num whitespace-nowrap pr-3 text-slate-400">{fmtDateTime(j.started_at)}</td>
                  <td className="break-words text-slate-400">{j.message ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
