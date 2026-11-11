import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, CalendarClock, CheckCircle2, Info, ShieldCheck, XCircle } from "lucide-react";
import { post } from "../api/client";
import type { Proposal } from "../api/types";
import { fmtDate, fmtEur, fmtPrice, todayIso } from "../lib/format";
import { Badge, BucketBadge, Button, Callout, cx, ErrorBox, Field, Input, Modal, SideBadge } from "./ui";

const statusTone = {
  pending: "amber",
  executed: "emerald",
  rejected: "slate",
  expired: "slate",
  cancelled: "slate",
} as const;

const aiTone = { confirmed: "emerald", vetoed: "rose", unavailable: "amber", not_used: "slate" } as const;
const aiLabel = { confirmed: "AI confirmed", vetoed: "AI veto", unavailable: "AI unavailable", not_used: "No AI" };

export function useInvalidateTrading() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["proposals", "portfolios", "portfolio", "trades", "equity", "stocks"]) qc.invalidateQueries({ queryKey: [key] });
  };
}

export default function ProposalCard({ p, compact = false, highlight = false }: { p: Proposal; compact?: boolean; highlight?: boolean }) {
  const [fill, setFill] = useState(false);
  const [reject, setReject] = useState(false);
  const live = p.mode === "live";
  const pending = p.status === "pending";

  return (
    <article
      id={`proposal-${p.id}`}
      className={cx(
        "card overflow-hidden",
        highlight && "ring-2 ring-emerald-500/60",
        pending && p.side === "buy" && "border-l-2 border-l-emerald-500",
        pending && p.side === "sell" && "border-l-2 border-l-rose-500",
      )}
    >
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <SideBadge side={p.side} />
            <div className="min-w-0">
              <Link to={`/stocks/${p.symbol}`} className="block truncate font-semibold text-white hover:text-emerald-300">
                {p.name}
              </Link>
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                {p.symbol} <BucketBadge bucket={p.bucket} /> <span>· {p.rule_label}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {p.mode === "paper" && <Badge tone="amber">paper</Badge>}
            {p.side === "buy" && <Badge tone={aiTone[p.ai_status]}><Bot className="h-3 w-3" />{aiLabel[p.ai_status]}</Badge>}
            <Badge tone={statusTone[p.status]}>{p.status}</Badge>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          <Mini label="Quantity" value={`${p.qty}`} />
          <Mini label="Limit price" value={fmtPrice(p.limit_price, p.currency)} strong />
          {p.stop_price != null ? <Mini label="Stop" value={fmtPrice(p.stop_price, p.currency)} /> : <Mini label="Order value" value={fmtEur(p.order_value_eur)} />}
          <Mini label={p.risk_eur != null ? "Risk" : "Est. fees"} value={p.risk_eur != null ? fmtEur(p.risk_eur) : fmtEur(p.expected_fees)} />
        </div>

        {!compact && (
          <>
            <ul className="mt-4 space-y-1.5 text-sm text-slate-300">
              {p.reasons.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-500" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
              <span>Order {fmtEur(p.order_value_eur)}</span>
              <span>Fees ≈ {fmtEur(p.expected_fees)}</span>
              <span className="flex items-center gap-1">
                <CalendarClock className="h-3.5 w-3.5" /> {fmtDate(p.created_on)} → valid until {fmtDate(p.valid_until)}
              </span>
            </div>
            {p.note && pending && live && (
              <div className="mt-3">
                <Callout tone="sky" icon={<Info className="h-4 w-4" />}>
                  {p.note}
                </Callout>
              </div>
            )}
            {p.note && !pending && <p className="mt-3 text-xs text-slate-500">{p.note}</p>}
          </>
        )}

        {pending && live && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => setFill(true)}>
              <CheckCircle2 className="h-4 w-4" /> I placed it — record fill
            </Button>
            <Button variant="ghost" onClick={() => setReject(true)}>
              <XCircle className="h-4 w-4" /> Reject
            </Button>
          </div>
        )}
        {pending && !live && (
          <p className="mt-4 flex items-center gap-1.5 text-xs text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5" /> Paper mode: filled automatically at the next session if the price reaches the limit.
          </p>
        )}
      </div>
      <FillModal p={p} open={fill} onClose={() => setFill(false)} />
      <RejectModal p={p} open={reject} onClose={() => setReject(false)} />
    </article>
  );
}

function Mini({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cx("num mt-0.5 text-sm", strong ? "font-semibold text-white" : "text-slate-200")}>{value}</div>
    </div>
  );
}

function FillModal({ p, open, onClose }: { p: Proposal; open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateTrading();
  const [qty, setQty] = useState(String(p.qty));
  const [price, setPrice] = useState(String(p.limit_price));
  const [fees, setFees] = useState(String(p.expected_fees));
  const [day, setDay] = useState(todayIso());
  const [stop, setStop] = useState(p.stop_price != null ? String(p.stop_price) : "");
  const m = useMutation({
    mutationFn: () =>
      post(`/proposals/${p.id}/fill`, {
        qty: Number(qty),
        price: Number(price),
        fees: Number(fees),
        date: day,
        ...(p.side === "buy" && stop ? { stop: Number(stop) } : {}),
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <Modal open={open} onClose={onClose} title={`Record fill: ${p.side.toUpperCase()} ${p.symbol}`}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-400">Enter what your broker actually executed. A partial fill is fine.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity filled">
            <Input type="number" min={1} max={p.side === "sell" ? p.qty : undefined} value={qty} onChange={(e) => setQty(e.target.value)} required />
          </Field>
          <Field label={`Price (${p.currency})`}>
            <Input type="number" step="any" min={0} value={price} onChange={(e) => setPrice(e.target.value)} required />
          </Field>
          <Field label="Fees (€)" hint="From the broker's order notice">
            <Input type="number" step="any" min={0} value={fees} onChange={(e) => setFees(e.target.value)} required />
          </Field>
          <Field label="Date">
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} required />
          </Field>
          {p.side === "buy" && (
            <Field label={`Stop placed at broker (${p.currency})`} className="col-span-2" hint="Boursy tracks this stop and raises it as the trailing stop moves.">
              <Input type="number" step="any" min={0} value={stop} onChange={(e) => setStop(e.target.value)} />
            </Field>
          )}
        </div>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={m.isPending}>
            Save fill
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RejectModal({ p, open, onClose }: { p: Proposal; open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateTrading();
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => post(`/proposals/${p.id}/reject`, { reason: reason || null }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  return (
    <Modal open={open} onClose={onClose} title={`Reject ${p.side} ${p.symbol}?`}>
      <div className="space-y-4">
        <Field label="Reason (optional)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. spread too wide, news pending" />
        </Field>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" loading={m.isPending} onClick={() => m.mutate()}>
            Reject proposal
          </Button>
        </div>
      </div>
    </Modal>
  );
}
