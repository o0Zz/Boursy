const fr = (digits: number) => ({ minimumFractionDigits: digits, maximumFractionDigits: digits });

export function fmtPrice(value: number | null | undefined, currency?: string): string {
  if (value == null) return "–";
  const digits = Math.abs(value) >= 1000 ? 0 : 2;
  const text = value.toLocaleString("fr-FR", fr(digits));
  return currency ? `${text} ${currency === "EUR" ? "€" : currency}` : text;
}

export function fmtEur(value: number | null | undefined, digits = 2, signed = false): string {
  if (value == null) return "–";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("fr-FR", fr(digits))} €`;
}

export function fmtPct(value: number | null | undefined, signed = true, digits = 2): string {
  if (value == null) return "–";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)} %`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null) return "–";
  return value.toLocaleString("fr-FR", fr(digits));
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtShortDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

export function daysUntil(iso: string): number {
  const d = new Date(`${iso}T12:00:00`).getTime();
  return Math.round((d - Date.now()) / 86_400_000);
}

export function changeClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-400" : "text-rose-400";
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
