import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Download } from "lucide-react";
import { api } from "../api/client";
import type { Trade } from "../api/types";
import { Badge, Card, cx, Empty, ErrorBox, Loading, PageHeader, SideBadge, Stat } from "../components/ui";
import { changeClass, fmtDate, fmtEur, fmtPrice } from "../lib/format";
import { useMode } from "../lib/mode";

export default function Journal() {
  const { mode } = useMode();
  const q = useQuery({ queryKey: ["trades", mode], queryFn: () => api<Trade[]>(`/portfolios/${mode}/trades`) });
  const stats = useMemo(() => {
    const t = q.data ?? [];
    const sells = t.filter((x) => x.realized_pnl_eur != null);
    const wins = sells.filter((x) => (x.realized_pnl_eur ?? 0) > 0);
    return {
      count: t.length,
      realized: sells.reduce((n, x) => n + (x.realized_pnl_eur ?? 0), 0),
      fees: t.reduce((n, x) => n + x.fees, 0),
      winRate: sells.length ? Math.round((wins.length / sells.length) * 100) : null,
    };
  }, [q.data]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Journal"
        subtitle="Every fill, with fees and realized P&L."
        action={
          <a href={`/api/portfolios/${mode}/trades.csv`} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3.5 py-2 text-sm font-medium text-slate-100 ring-1 ring-inset ring-slate-700 hover:bg-slate-700">
            <Download className="h-4 w-4" /> CSV
          </a>
        }
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card><Stat label="Fills" value={stats.count} /></Card>
        <Card><Stat label="Realized P&L" value={fmtEur(stats.realized, 2, true)} valueClass={changeClass(stats.realized)} /></Card>
        <Card><Stat label="Fees" value={fmtEur(stats.fees)} /></Card>
        <Card><Stat label="Winning sells" value={stats.winRate == null ? "–" : `${stats.winRate} %`} /></Card>
      </div>
      {q.error && <ErrorBox error={q.error} />}
      <Card padded={false}>
        {q.isPending ? (
          <Loading />
        ) : (q.data ?? []).length === 0 ? (
          <Empty icon={<BookOpen className="h-6 w-6" />} title="No trade yet" />
        ) : (
          <div className="overflow-x-auto pb-2">
            <table className="table-base min-w-[760px]">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Side</th>
                  <th>Stock</th>
                  <th className="!text-right">Qty</th>
                  <th className="!text-right">Price</th>
                  <th className="!text-right">Value</th>
                  <th className="!text-right">Fees</th>
                  <th className="!text-right">Realized</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {q.data!.map((t) => (
                  <tr key={t.id}>
                    <td className="num whitespace-nowrap text-slate-400">{fmtDate(t.date)}</td>
                    <td><SideBadge side={t.side} /></td>
                    <td>
                      <Link to={`/stocks/${t.symbol}`} className="text-white hover:text-emerald-300">{t.name}</Link>
                      <div className="text-xs text-slate-500">{t.symbol}</div>
                    </td>
                    <td className="num text-right">{t.qty}</td>
                    <td className="num text-right">{fmtPrice(t.price, t.currency)}</td>
                    <td className="num text-right">{fmtEur(t.value_eur)}</td>
                    <td className="num text-right text-slate-400">{fmtEur(t.fees)}</td>
                    <td className={cx("num text-right font-medium", changeClass(t.realized_pnl_eur))}>
                      {t.realized_pnl_eur == null ? "–" : fmtEur(t.realized_pnl_eur, 2, true)}
                    </td>
                    <td>
                      <Badge tone={t.source === "confirmed" ? "emerald" : t.source === "manual" ? "sky" : "amber"}>{t.source}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
