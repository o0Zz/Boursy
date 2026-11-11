export function fmtPrice(value: number | null | undefined, currency?: string): string {
  if (value == null) return "–";
  const digits = Math.abs(value) >= 1000 ? 0 : 2;
  const text = value.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return currency ? `${text} ${currency === "EUR" ? "€" : currency}` : text;
}

export function fmtPct(value: number | null | undefined, signed = true): string {
  if (value == null) return "–";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} %`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null) return "–";
  return value.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export function changeClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-400" : "text-rose-400";
}
