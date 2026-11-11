import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Bot, CheckCircle2, Coins, RotateCcw, Save, ShieldAlert, SlidersHorizontal, Wallet, XCircle } from "lucide-react";
import { api, post } from "../api/client";
import type { AIStatus, AppSettings, SettingsResponse } from "../api/types";
import { Badge, Button, Callout, Card, cx, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select, Toggle } from "../components/ui";
import { useMode } from "../lib/mode";

type Kind = "pct" | "num" | "int" | "bool";
interface Spec {
  key: string;
  label: string;
  kind: Kind;
  hint?: string;
}

const STRATEGY: { title: string; fields: Spec[] }[] = [
  {
    title: "Buy signal",
    fields: [
      { key: "rsi_pullback", label: "Pullback: RSI went below", kind: "num" },
      { key: "pullback_lookback", label: "Pullback lookback (sessions)", kind: "int" },
      { key: "volume_mult", label: "Volume ≥ × 20-day average", kind: "num" },
      { key: "ai_min_score", label: "Minimum AI score", kind: "num" },
      { key: "event_block_days", label: "No buy before binary event (sessions)", kind: "int" },
      { key: "core_allow_earnings", label: "Core stocks may be bought before earnings", kind: "bool" },
      { key: "buy_limit_offset", label: "Buy limit above close", kind: "pct" },
    ],
  },
  {
    title: "Exits",
    fields: [
      { key: "stop_atr_mult", label: "Initial stop (× ATR)", kind: "num" },
      { key: "stop_cap_core", label: "Max stop distance, core", kind: "pct" },
      { key: "stop_cap_growth", label: "Max stop distance, growth", kind: "pct" },
      { key: "trail_trigger_r", label: "Start trailing after (× initial risk)", kind: "num" },
      { key: "trail_atr_mult", label: "Trailing stop (× ATR)", kind: "num" },
      { key: "trend_break_days", label: "Trend break: closes below SMA50", kind: "int" },
      { key: "exhaustion_rsi", label: "Exhaustion RSI (sell half)", kind: "num" },
      { key: "event_protect_days", label: "Reduce growth before event (sessions)", kind: "int" },
      { key: "time_stop_days", label: "Time stop (sessions)", kind: "int" },
      { key: "time_stop_min_gain", label: "Time stop: minimum gain", kind: "pct" },
      { key: "sell_limit_offset", label: "Sell limit below close", kind: "pct" },
    ],
  },
];

const RISK: Spec[] = [
  { key: "max_risk_per_trade", label: "Max risk per trade", kind: "pct", hint: "(entry − stop) × quantity, share of capital" },
  { key: "kill_switch_drawdown", label: "Kill switch drawdown", kind: "pct" },
  { key: "max_positions", label: "Max positions", kind: "int" },
  { key: "max_positions_small", label: "Max positions (small account)", kind: "int" },
  { key: "small_capital", label: "Small account below (€)", kind: "num" },
  { key: "max_weight_core", label: "Max weight, core", kind: "pct" },
  { key: "max_weight_growth", label: "Max weight, growth", kind: "pct" },
  { key: "max_weight_core_small", label: "Max weight, core (small)", kind: "pct" },
  { key: "max_weight_growth_small", label: "Max weight, growth (small)", kind: "pct" },
  { key: "min_cash_buffer", label: "Cash buffer", kind: "pct" },
  { key: "max_buys_per_day", label: "Max buy proposals per day", kind: "int" },
  { key: "max_fee_pct", label: "Max round-trip fees", kind: "pct" },
  { key: "reentry_cooldown_days", label: "Re-entry cooldown after stop (sessions)", kind: "int" },
];

export default function Settings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/settings") });
  const [draft, setDraft] = useState<AppSettings | null>(null);
  useEffect(() => {
    if (q.data && !draft) setDraft(structuredClone(q.data.settings));
  }, [q.data, draft]);

  const save = useMutation({
    mutationFn: () => api<SettingsResponse>("/settings", { method: "PUT", body: JSON.stringify(draft) }),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      setDraft(structuredClone(data.settings));
      for (const k of ["portfolios", "ai-status"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });

  if (q.error) return <ErrorBox error={q.error} />;
  if (!draft || !q.data) return <Loading />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(q.data.settings);
  const env = q.data.env;
  const setSection = <K extends keyof AppSettings>(k: K, v: AppSettings[K]) => setDraft({ ...draft, [k]: v });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Settings"
        subtitle="Strategy, risk, fees, AI and notifications. Secrets stay in the server's .env file."
        action={
          <div className="flex gap-2">
            {dirty && <Button variant="ghost" onClick={() => setDraft(structuredClone(q.data.settings))}>Discard</Button>}
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
              <Save className="h-4 w-4" /> Save
            </Button>
          </div>
        }
      />
      {save.error && <ErrorBox error={save.error} />}
      {save.isSuccess && !dirty && <Callout tone="emerald" icon={<CheckCircle2 className="h-4 w-4" />}>Saved.</Callout>}

      <Section icon={<Wallet className="h-4 w-4" />} title="Portfolios">
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-3 rounded-xl bg-slate-950/40 p-4 ring-1 ring-inset ring-slate-800">
            <Toggle label="Paper portfolio (simulation)" hint="Proposals fill automatically on the next session." checked={draft.portfolios.paper_enabled} onChange={(v) => setSection("portfolios", { ...draft.portfolios, paper_enabled: v })} />
            <Field label="Starting capital (€)" hint="Used when the portfolio is created or reset.">
              <Input type="number" value={draft.portfolios.paper_capital} onChange={(e) => setSection("portfolios", { ...draft.portfolios, paper_capital: Number(e.target.value) })} />
            </Field>
          </div>
          <div className="space-y-3 rounded-xl bg-slate-950/40 p-4 ring-1 ring-inset ring-slate-800">
            <Toggle label="Live PEA portfolio (semi-automatic)" hint="You place the orders at your broker and record the fills." checked={draft.portfolios.live_enabled} onChange={(v) => setSection("portfolios", { ...draft.portfolios, live_enabled: v })} />
            <Field label="Starting capital (€)">
              <Input type="number" value={draft.portfolios.live_capital} onChange={(e) => setSection("portfolios", { ...draft.portfolios, live_capital: Number(e.target.value) })} />
            </Field>
          </div>
        </div>
        <DangerZone />
      </Section>

      <Section icon={<SlidersHorizontal className="h-4 w-4" />} title="Strategy v1">
        {STRATEGY.map((group) => (
          <div key={group.title} className="mb-5 last:mb-0">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">{group.title}</h3>
            <Fields specs={group.fields} values={draft.strategy} defaults={q.data.defaults.strategy} onChange={(v) => setSection("strategy", v)} />
          </div>
        ))}
      </Section>

      <Section icon={<ShieldAlert className="h-4 w-4" />} title="Risk rules" subtitle="Enforced by code. The AI cannot override them.">
        <Fields specs={RISK} values={draft.risk} defaults={q.data.defaults.risk} onChange={(v) => setSection("risk", v as AppSettings["risk"])} />
      </Section>

      <Section icon={<Coins className="h-4 w-4" />} title="Fees" subtitle="Per order, capped at 0.5 % on a PEA.">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Broker preset">
            <Select value={draft.fees.preset} onChange={(e) => setSection("fees", structuredClone(q.data.fee_presets[e.target.value] ?? draft.fees))}>
              {Object.keys(q.data.fee_presets).map((k) => (
                <option key={k} value={k}>{k.replace(/_/g, " ")}</option>
              ))}
            </Select>
          </Field>
          <Field label="Above the last tier">
            <PctInput value={draft.fees.pct_above} onChange={(v) => setSection("fees", { ...draft.fees, pct_above: v })} />
          </Field>
          <Field label="Cap per order">
            <PctInput value={draft.fees.cap_pct ?? 0} onChange={(v) => setSection("fees", { ...draft.fees, cap_pct: v })} />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
          {draft.fees.tiers.map((t, i) => (
            <Badge key={i}>≤ {t.up_to >= 1e9 ? "any" : `${t.up_to} €`}: {t.fee} €</Badge>
          ))}
        </div>
        <FeeExamples fees={draft.fees} />
      </Section>

      <AISection draft={draft} setDraft={setDraft} data={q.data} />

      <Section icon={<BellRing className="h-4 w-4" />} title="Notifications">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-3">
            <Toggle label="Push (ntfy)" hint={env.ntfy_topic ? `Server ${env.ntfy_url}` : "Set BOURSY_NTFY_TOPIC in .env"} checked={draft.notify.push} onChange={(v) => setSection("notify", { ...draft.notify, push: v })} />
            <Toggle label="Email" hint={env.smtp ? "SMTP configured" : "Set BOURSY_SMTP_* and BOURSY_MAIL_TO in .env"} checked={draft.notify.email} onChange={(v) => setSection("notify", { ...draft.notify, email: v })} />
            <Toggle label="Notify paper proposals too" checked={draft.notify.paper_proposals} onChange={(v) => setSection("notify", { ...draft.notify, paper_proposals: v })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Large move alert, core">
              <PctInput value={draft.notify.large_move_core} onChange={(v) => setSection("notify", { ...draft.notify, large_move_core: v })} />
            </Field>
            <Field label="Large move alert, growth">
              <PctInput value={draft.notify.large_move_growth} onChange={(v) => setSection("notify", { ...draft.notify, large_move_growth: v })} />
            </Field>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <EnvBadge ok={env.ntfy_topic} label="ntfy topic" />
          <EnvBadge ok={env.smtp} label="SMTP" />
          <EnvBadge ok={!!env.public_url} label="public URL" />
          <TestNotification />
        </div>
      </Section>
    </div>
  );
}

function Section({ icon, title, subtitle, children }: { icon: ReactNode; title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Card>
      <div className="mb-4">
        <h2 className="flex items-center gap-2 text-base font-semibold text-white">
          <span className="text-emerald-400">{icon}</span>
          {title}
        </h2>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {children}
    </Card>
  );
}

function PctInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="relative">
      <Input type="number" step="any" value={Number((value * 100).toFixed(4))} onChange={(e) => onChange(Number(e.target.value) / 100)} className="pr-8" />
      <span className="pointer-events-none absolute right-3 top-2 text-sm text-slate-500">%</span>
    </div>
  );
}

function Fields({
  specs,
  values,
  defaults,
  onChange,
}: {
  specs: Spec[];
  values: Record<string, number | boolean>;
  defaults: Record<string, number | boolean>;
  onChange: (v: Record<string, number | boolean>) => void;
}) {
  const set = (k: string, v: number | boolean) => onChange({ ...values, [k]: v });
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {specs.map((s) => {
        const changed = values[s.key] !== defaults[s.key];
        const hint = s.hint ?? (changed ? `Default ${s.kind === "pct" ? `${Number(defaults[s.key]) * 100} %` : String(defaults[s.key])}` : undefined);
        if (s.kind === "bool")
          return (
            <div key={s.key} className="flex items-end pb-2">
              <Toggle label={s.label} checked={Boolean(values[s.key])} onChange={(v) => set(s.key, v)} />
            </div>
          );
        return (
          <Field key={s.key} label={<span className={cx(changed && "text-amber-300")}>{s.label}</span>} hint={hint}>
            {s.kind === "pct" ? (
              <PctInput value={Number(values[s.key])} onChange={(v) => set(s.key, v)} />
            ) : (
              <Input type="number" step={s.kind === "int" ? 1 : "any"} value={String(values[s.key])} onChange={(e) => set(s.key, Number(e.target.value))} />
            )}
          </Field>
        );
      })}
    </div>
  );
}

function FeeExamples({ fees }: { fees: AppSettings["fees"] }) {
  const fee = (v: number) => {
    let f: number | null = null;
    for (const t of [...fees.tiers].sort((a, b) => a.up_to - b.up_to)) if (v <= t.up_to) { f = t.fee; break; }
    if (f == null) f = v * fees.pct_above;
    f = Math.max(f, fees.min_fee);
    if (fees.cap_pct != null) f = Math.min(f, v * fees.cap_pct);
    return f;
  };
  return (
    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
      {[200, 500, 1000, 2000, 5000].map((v) => (
        <div key={v} className="rounded-lg bg-slate-950/50 px-3 py-2 text-center ring-1 ring-inset ring-slate-800">
          <div className="text-[11px] text-slate-500">{v} € order</div>
          <div className="num text-sm font-medium text-white">{fee(v).toFixed(2)} €</div>
          <div className="num text-[11px] text-slate-500">{((fee(v) / v) * 100).toFixed(2)} %</div>
        </div>
      ))}
    </div>
  );
}

function AISection({ draft, setDraft, data }: { draft: AppSettings; setDraft: (s: AppSettings) => void; data: SettingsResponse }) {
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/ai/status") });
  const ai = draft.ai;
  const set = (v: Partial<AppSettings["ai"]>) => setDraft({ ...draft, ai: { ...ai, ...v } });
  const tasks = [
    { key: "screening", label: "Weekly screening" },
    { key: "signal_review", label: "Signal review" },
    { key: "news_check", label: "Pre-open news check" },
  ] as const;
  return (
    <Section icon={<Bot className="h-4 w-4" />} title="AI analyst" subtitle="Claude reviews news and events. It never places orders; risk rules have the last word.">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Backend">
          <Select value={ai.backend} onChange={(e) => set({ backend: e.target.value as AppSettings["ai"]["backend"] })}>
            <option value="none">Off (technical signals only)</option>
            <option value="api">Anthropic API (pay per use)</option>
            <option value="subscription">Claude subscription (Claude Code)</option>
          </Select>
        </Field>
        <Field label="Monthly budget, API (USD)">
          <Input type="number" step="any" value={ai.monthly_budget_usd} onChange={(e) => set({ monthly_budget_usd: Number(e.target.value) })} />
        </Field>
        <Field label="Daily calls, subscription">
          <Input type="number" value={ai.daily_call_cap} onChange={(e) => set({ daily_call_cap: Number(e.target.value) })} />
        </Field>
        <Field label="Web searches per call">
          <Input type="number" value={ai.web_search_max_uses} onChange={(e) => set({ web_search_max_uses: Number(e.target.value) })} />
        </Field>
        <Field label="Stocks screened per week">
          <Input type="number" value={ai.screening_max_stocks} onChange={(e) => set({ screening_max_stocks: Number(e.target.value) })} />
        </Field>
        <div className="flex items-end pb-2">
          <Toggle label="Fall back to the API" hint="When the subscription fails" checked={ai.fallback_to_api} onChange={(v) => set({ fallback_to_api: v })} />
        </div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        {tasks.map((t) => (
          <div key={t.key} className="space-y-2 rounded-xl bg-slate-950/40 p-3 ring-1 ring-inset ring-slate-800">
            <div className="text-sm font-medium text-slate-200">{t.label}</div>
            <Select value={ai[t.key].model} onChange={(e) => set({ [t.key]: { ...ai[t.key], model: e.target.value } })}>
              {data.models.map((m) => (
                <option key={m} value={m}>{m} ({data.prices[m]?.input}/{data.prices[m]?.output} $)</option>
              ))}
            </Select>
            <Select value={ai[t.key].effort} onChange={(e) => set({ [t.key]: { ...ai[t.key], effort: e.target.value as "medium" } })}>
              {["low", "medium", "high", "xhigh", "max"].map((x) => (
                <option key={x} value={x}>effort {x}</option>
              ))}
            </Select>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <EnvBadge ok={data.env.anthropic_api_key} label="ANTHROPIC_API_KEY" />
        <EnvBadge ok={data.env.claude_code_oauth_token} label="CLAUDE_CODE_OAUTH_TOKEN" />
        {status.data && (
          <span className={cx("text-xs", status.data.available ? "text-emerald-300" : "text-slate-500")}>
            {status.data.available ? "AI available" : status.data.reason}
          </span>
        )}
      </div>
      {ai.backend === "subscription" && !data.env.claude_code_oauth_token && (
        <div className="mt-3">
          <Callout tone="sky">
            On your PC, run <code className="rounded bg-slate-800 px-1">claude setup-token</code>, then put the token in the server's{" "}
            <code className="rounded bg-slate-800 px-1">.env</code> as <code className="rounded bg-slate-800 px-1">CLAUDE_CODE_OAUTH_TOKEN</code> and restart the container.
            Personal use only.
          </Callout>
        </div>
      )}
    </Section>
  );
}

function EnvBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <Badge tone={ok ? "emerald" : "slate"}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />} {label}
    </Badge>
  );
}

function TestNotification() {
  const m = useMutation({ mutationFn: () => post<{ push: string; email: string; error: string | null }>("/settings/test-notification") });
  return (
    <span className="flex items-center gap-2">
      <Button size="sm" onClick={() => m.mutate()} loading={m.isPending}>
        <BellRing className="h-3.5 w-3.5" /> Send test
      </Button>
      {m.data && (
        <span className="text-xs text-slate-400">
          push {m.data.push} · email {m.data.email}
          {m.data.error && <span className="text-rose-300"> · {m.data.error}</span>}
        </span>
      )}
    </span>
  );
}

function DangerZone() {
  const qc = useQueryClient();
  const { portfolios } = useMode();
  const [reset, setReset] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const kill = useMutation({
    mutationFn: (mode: string) => post(`/portfolios/${mode}/kill-switch/reset`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });
  const doReset = useMutation({
    mutationFn: () => post(`/portfolios/${reset}/reset`, { confirm }),
    onSuccess: () => {
      for (const k of ["portfolios", "proposals", "trades", "equity"]) qc.invalidateQueries({ queryKey: [k] });
      setReset(null);
      setConfirm("");
    },
  });
  return (
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-800 pt-4">
      {portfolios.map((p) => (
        <span key={p.mode} className="flex gap-2">
          {p.kill_switch && (
            <Button variant="danger" size="sm" onClick={() => kill.mutate(p.mode)} loading={kill.isPending}>
              <ShieldAlert className="h-3.5 w-3.5" /> Reset kill switch ({p.mode})
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => setReset(p.mode)}>
            <RotateCcw className="h-3.5 w-3.5" /> Restart {p.mode} portfolio
          </Button>
        </span>
      ))}
      <Modal open={reset != null} onClose={() => setReset(null)} title={`Restart the ${reset} portfolio?`}>
        <div className="space-y-4">
          <Callout tone="rose">This deletes every position, trade, proposal and equity point of the {reset} portfolio and starts again with its starting capital. It cannot be undone.</Callout>
          <Field label={`Type "${reset}" to confirm`}>
            <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </Field>
          {doReset.error && <ErrorBox error={doReset.error} />}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setReset(null)}>Cancel</Button>
            <Button variant="danger" disabled={confirm !== reset} loading={doReset.isPending} onClick={() => doReset.mutate()}>Restart</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
