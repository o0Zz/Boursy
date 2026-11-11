import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Briefcase, Pencil, Plus, ShieldCheck, Wallet } from "lucide-react";
import { api, patch, post } from "../api/client";
import type { CashMovement, PositionView, Stock } from "../api/types";
import { useInvalidateTrading } from "../components/ProposalCard";
import {
  Badge,
  BucketBadge,
  Button,
  Callout,
  Card,
  cx,
  Empty,
  ErrorBox,
  Field,
  Input,
  KV,
  Loading,
  Modal,
  PageHeader,
  Select,
} from "../components/ui";
import { changeClass, daysUntil, fmtDate, fmtEur, fmtPct, fmtPrice, todayIso } from "../lib/format";
import { useMode } from "../lib/mode";

export default function Positions() {
  const { mode, current, loading } = useMode();
  const [trade, setTrade] = useState(false);
  const [cash, setCash] = useState(false);
  const movements = useQuery({ queryKey: ["cash", mode], queryFn: () => api<CashMovement[]>(`/portfolios/${mode}/cash`), enabled: !!current });

  if (loading) return <Loading />;
  if (!current) return <ErrorBox error="No portfolio enabled" />;
  const live = mode === "live";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Positions"
        subtitle={`${current.positions.length} open · ${fmtEur(current.positions_value)} invested · ${fmtEur(current.cash)} cash`}
        action={
          <div className="flex gap-2">
            <Button onClick={() => setCash(true)}>
              <Wallet className="h-4 w-4" /> Cash
            </Button>
            <Button variant="primary" onClick={() => setTrade(true)}>
              <Plus className="h-4 w-4" /> Manual trade
            </Button>
          </div>
        }
      />
      {live && current.positions.length > 0 && (
        <Callout tone="sky" icon={<ShieldCheck className="h-4 w-4" />}>
          Keep a stop order at your broker for every position. Boursy checks stops only at 12:30 and after the close; the broker stop is the real protection.
          When the trailing stop moves up, move the broker stop too.
        </Callout>
      )}

      {current.positions.length === 0 ? (
        <Card>
          <Empty icon={<Briefcase className="h-6 w-6" />} title="No open position">
            {live ? "Record a fill from a proposal, or a trade you made yourself with “Manual trade”." : "Positions open when paper proposals fill."}
          </Empty>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {current.positions.map((p) => (
            <PositionCard key={p.id} p={p} mode={mode} />
          ))}
        </div>
      )}

      <Card title="Cash movements" padded={false}>
        <div className="overflow-x-auto pb-2">
          <table className="table-base">
            <thead>
              <tr>
                <th>Date</th>
                <th>Note</th>
                <th className="!text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {(movements.data ?? []).map((m) => (
                <tr key={m.id}>
                  <td className="num whitespace-nowrap text-slate-400">{fmtDate(m.date)}</td>
                  <td className="text-slate-300">{m.note ?? "–"}</td>
                  <td className={cx("num text-right font-medium", changeClass(m.amount))}>{fmtEur(m.amount, 2, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <ManualTradeModal open={trade} onClose={() => setTrade(false)} mode={mode} positions={current.positions} />
      <CashModal open={cash} onClose={() => setCash(false)} mode={mode} />
    </div>
  );
}

function PositionCard({ p, mode }: { p: PositionView; mode: string }) {
  const [edit, setEdit] = useState(false);
  const eventSoon = p.next_event && daysUntil(p.next_event.date) <= 10;
  return (
    <div className="card p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/stocks/${p.symbol}`} className="block truncate font-semibold text-white hover:text-emerald-300">
            {p.name}
          </Link>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
            {p.symbol} <BucketBadge bucket={p.bucket} /> {p.trailing && <Badge tone="emerald">trailing</Badge>} {p.half_sold && <Badge>half sold</Badge>}
          </div>
        </div>
        <div className="text-right">
          <div className={cx("num text-lg font-semibold", changeClass(p.pnl_eur))}>{fmtEur(p.pnl_eur, 2, true)}</div>
          <div className={cx("num text-xs", changeClass(p.pnl_pct))}>{fmtPct(p.pnl_pct)}</div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-x-6">
        <KV k="Quantity" v={p.qty} />
        <KV k="Value" v={fmtEur(p.value_eur)} />
        <KV k="Average price" v={fmtPrice(p.avg_price, p.currency)} />
        <KV k="Last close" v={fmtPrice(p.price, p.currency)} />
        <KV
          k={
            <span className="flex items-center gap-1">
              Stop
              <button onClick={() => setEdit(true)} className="rounded p-0.5 text-slate-500 hover:text-white" title="Edit stop">
                <Pencil className="h-3 w-3" />
              </button>
            </span>
          }
          v={fmtPrice(p.stop, p.currency)}
          vClass="text-amber-300"
        />
        <KV k="Distance to stop" v={fmtPct(p.stop_distance_pct, false, 1)} />
        <KV k="Opened" v={fmtDate(p.opened_on)} />
        <KV k="Sessions held" v={p.days_held} />
      </div>
      {p.next_event && (
        <div className={cx("mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs", eventSoon ? "bg-amber-500/10 text-amber-200" : "bg-slate-800/60 text-slate-400")}>
          {eventSoon && <AlertTriangle className="h-3.5 w-3.5" />}
          {fmtDate(p.next_event.date)} · {p.next_event.title}
          {p.next_event.binary && <Badge tone="amber">binary</Badge>}
        </div>
      )}
      <StopModal p={p} mode={mode} open={edit} onClose={() => setEdit(false)} />
    </div>
  );
}

function StopModal({ p, mode, open, onClose }: { p: PositionView; mode: string; open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateTrading();
  const [stop, setStop] = useState(String(p.stop));
  const m = useMutation({
    mutationFn: () => patch(`/portfolios/${mode}/positions/${p.id}`, { stop: Number(stop) }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  return (
    <Modal open={open} onClose={onClose} title={`Stop for ${p.symbol}`}>
      <div className="space-y-4">
        <Field label={`Stop price (${p.currency})`} hint={`Initial stop ${fmtPrice(p.initial_stop)} · last close ${fmtPrice(p.price)}`}>
          <Input type="number" step="any" value={stop} onChange={(e) => setStop(e.target.value)} />
        </Field>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}

function ManualTradeModal({ open, onClose, mode, positions }: { open: boolean; onClose: () => void; mode: string; positions: PositionView[] }) {
  const invalidate = useInvalidateTrading();
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api<Stock[]>("/stocks"), enabled: open });
  const [form, setForm] = useState({ symbol: "", side: "buy", qty: "", price: "", fees: "0", date: todayIso(), stop: "", note: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () =>
      post(`/portfolios/${mode}/trades`, {
        symbol: form.symbol,
        side: form.side,
        qty: Number(form.qty),
        price: Number(form.price),
        fees: Number(form.fees),
        date: form.date,
        stop: form.stop ? Number(form.stop) : null,
        note: form.note || null,
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  const choices = form.side === "sell" ? positions.map((p) => ({ symbol: p.symbol, name: p.name })) : (stocks.data ?? []);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <Modal open={open} onClose={onClose} title="Record a manual trade">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-400">For trades Boursy did not propose, so the portfolio matches your broker.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Side">
            <Select value={form.side} onChange={set("side")}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </Select>
          </Field>
          <Field label="Stock">
            <Select value={form.symbol} onChange={set("symbol")} required>
              <option value="">Choose…</option>
              {choices.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.name} ({s.symbol})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Quantity">
            <Input type="number" min={1} value={form.qty} onChange={set("qty")} required />
          </Field>
          <Field label="Price (stock currency)">
            <Input type="number" step="any" min={0} value={form.price} onChange={set("price")} required />
          </Field>
          <Field label="Fees (€)">
            <Input type="number" step="any" min={0} value={form.fees} onChange={set("fees")} required />
          </Field>
          <Field label="Date">
            <Input type="date" value={form.date} onChange={set("date")} required />
          </Field>
          {form.side === "buy" && (
            <Field label="Stop (optional)" hint="Default: entry − 3 × ATR, capped" className="col-span-2">
              <Input type="number" step="any" min={0} value={form.stop} onChange={set("stop")} />
            </Field>
          )}
          <Field label="Note" className="col-span-2">
            <Input value={form.note} onChange={set("note")} />
          </Field>
        </div>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={m.isPending}>Save trade</Button>
        </div>
      </form>
    </Modal>
  );
}

function CashModal({ open, onClose, mode }: { open: boolean; onClose: () => void; mode: string }) {
  const invalidate = useInvalidateTrading();
  const [amount, setAmount] = useState("");
  const [kind, setKind] = useState("deposit");
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: () =>
      post(`/portfolios/${mode}/cash`, { amount: (kind === "deposit" ? 1 : -1) * Number(amount), note: note || (kind === "deposit" ? "Deposit" : "Withdrawal") }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  return (
    <Modal open={open} onClose={onClose} title="Cash movement">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="deposit">Deposit</option>
              <option value="withdrawal">Withdrawal</option>
            </Select>
          </Field>
          <Field label="Amount (€)">
            <Input type="number" step="any" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Note" className="col-span-2">
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
        {m.error && <ErrorBox error={m.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!amount} loading={m.isPending} onClick={() => m.mutate()}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}
