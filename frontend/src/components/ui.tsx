import type { ReactNode } from "react";
import type { Bucket, Trend } from "../api/types";

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-slate-800 bg-slate-900/60 p-4 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-400">{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, valueClass = "" }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`num text-xl font-semibold ${valueClass}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

const trendStyle: Record<Trend, string> = {
  up: "bg-emerald-500/15 text-emerald-300",
  down: "bg-rose-500/15 text-rose-300",
  mixed: "bg-amber-500/15 text-amber-300",
  "n/a": "bg-slate-700/40 text-slate-400",
};

export function TrendBadge({ trend }: { trend: Trend }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${trendStyle[trend]}`}>{trend}</span>;
}

export function BucketBadge({ bucket }: { bucket: Bucket }) {
  const cls = bucket === "core" ? "bg-sky-500/15 text-sky-300" : "bg-fuchsia-500/15 text-fuchsia-300";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{bucket}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return <div className="rounded border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">{message}</div>;
}
