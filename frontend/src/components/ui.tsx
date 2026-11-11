import { useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { Loader2, X } from "lucide-react";
import type { Bucket, Trend } from "../api/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  title,
  action,
  children,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cx("card", padded && "p-4 sm:p-5", className)}>
      {(title || action) && (
        <div className={cx("mb-4 flex items-center justify-between gap-3", !padded && "px-4 pt-4 sm:px-5 sm:pt-5")}>
          {title && <h2 className="text-sm font-semibold text-slate-300">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  valueClass = "",
  icon,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  valueClass?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
        {icon}
        {label}
      </div>
      <div className={cx("num mt-1 truncate text-lg font-semibold text-white sm:text-xl", valueClass)}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

type Tone = "slate" | "emerald" | "rose" | "amber" | "sky" | "violet" | "fuchsia";
const tones: Record<Tone, string> = {
  slate: "bg-slate-700/40 text-slate-300 ring-slate-600/40",
  emerald: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/25",
  rose: "bg-rose-500/10 text-rose-300 ring-rose-500/25",
  amber: "bg-amber-500/10 text-amber-300 ring-amber-500/25",
  sky: "bg-sky-500/10 text-sky-300 ring-sky-500/25",
  violet: "bg-violet-500/10 text-violet-300 ring-violet-500/25",
  fuchsia: "bg-fuchsia-500/10 text-fuchsia-300 ring-fuchsia-500/25",
};

export function Badge({ tone = "slate", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone], className)}>
      {children}
    </span>
  );
}

const trendTone: Record<Trend, Tone> = { up: "emerald", down: "rose", mixed: "amber", "n/a": "slate" };
export function TrendBadge({ trend }: { trend: Trend }) {
  return <Badge tone={trendTone[trend]}>{trend === "n/a" ? "no data" : trend}</Badge>;
}

export function BucketBadge({ bucket }: { bucket: Bucket }) {
  return <Badge tone={bucket === "core" ? "sky" : "fuchsia"}>{bucket}</Badge>;
}

export function SideBadge({ side }: { side: "buy" | "sell" }) {
  return (
    <span
      className={cx(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-bold uppercase tracking-wide",
        side === "buy" ? "bg-emerald-500 text-emerald-950" : "bg-rose-500 text-rose-950",
      )}
    >
      {side}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-slate-600">–</span>;
  const tone: Tone = score >= 7 ? "emerald" : score >= 5 ? "amber" : "rose";
  return <Badge tone={tone}>{score.toFixed(1)}</Badge>;
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-emerald-500 text-emerald-950 hover:bg-emerald-400 shadow-sm shadow-emerald-500/20",
  secondary: "bg-slate-800 text-slate-100 hover:bg-slate-700 ring-1 ring-inset ring-slate-700",
  ghost: "text-slate-300 hover:bg-slate-800 hover:text-white",
  danger: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30 hover:bg-rose-500/25",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variants[variant],
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children, className = "" }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block min-w-0", className)}>
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-snug text-slate-500">{hint}</span>}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx("input", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx("input pr-8", props.className)} />;
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 inline-flex h-5 w-9 shrink-0 rounded-full transition-colors", checked ? "bg-emerald-500" : "bg-slate-700")}
      >
        <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-4" : "translate-x-0.5")} />
      </button>
      <span>
        <span className="block text-sm text-slate-200">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
    </label>
  );
}

export function Tabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-lg bg-slate-900 p-0.5 ring-1 ring-inset ring-slate-800">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors sm:text-sm",
            value === o.value ? "bg-slate-700 text-white shadow" : "text-slate-400 hover:text-white",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      {icon && <div className="mb-3 rounded-full bg-slate-800/80 p-3 text-slate-400">{icon}</div>}
      <div className="text-sm font-medium text-slate-300">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">{message}</div>;
}

export function Callout({ tone = "amber", icon, children }: { tone?: "amber" | "sky" | "rose" | "emerald"; icon?: ReactNode; children: ReactNode }) {
  const cls = {
    amber: "border-amber-500/25 bg-amber-500/10 text-amber-200",
    sky: "border-sky-500/25 bg-sky-500/10 text-sky-200",
    rose: "border-rose-500/30 bg-rose-500/10 text-rose-200",
    emerald: "border-emerald-500/25 bg-emerald-500/10 text-emerald-200",
  }[tone];
  return (
    <div className={cx("flex gap-2.5 rounded-lg border p-3 text-sm", cls)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 className={cx("h-5 w-5 animate-spin text-slate-500", className)} />;
}

export function Loading() {
  return (
    <div className="flex justify-center py-16">
      <Spinner />
    </div>
  );
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative max-h-[92vh] w-full overflow-y-auto rounded-t-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl sm:max-w-lg sm:rounded-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Meter({ value, max, danger }: { value: number; max: number; danger?: boolean }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
      <div
        className={cx("h-full rounded-full transition-all", danger ? "bg-rose-500" : pct > 66 ? "bg-amber-400" : "bg-emerald-400")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function KV({ k, v, vClass = "" }: { k: ReactNode; v: ReactNode; vClass?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <span className="text-slate-400">{k}</span>
      <span className={cx("num text-right font-medium text-slate-100", vClass)}>{v}</span>
    </div>
  );
}
