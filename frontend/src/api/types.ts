export type Bucket = "core" | "growth";
export type Trend = "up" | "down" | "mixed" | "n/a";

export interface Snapshot {
  date: string;
  close: number;
  change_1d_pct: number | null;
  ema20: number | null;
  sma50: number | null;
  sma200: number | null;
  rsi14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  atr14: number | null;
  atr_pct: number | null;
  volume: number;
  vol_avg20: number | null;
  above_sma200: boolean | null;
  sma50_above_sma200: boolean | null;
}

export interface Stock {
  symbol: string;
  name: string;
  country: string;
  exchange: string;
  currency: string;
  bucket: Bucket;
  pea_eligible: boolean;
  active: boolean;
  notes: string | null;
  last_full_refresh: string | null;
  last_error: string | null;
  snapshot: Snapshot | null;
  trend: Trend;
}

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20: number | null;
  sma50: number | null;
  sma200: number | null;
  rsi14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  atr14: number | null;
  bb_mid: number | null;
  bb_upper: number | null;
  bb_lower: number | null;
  vol_avg20: number | null;
}

export interface BarsResponse {
  symbol: string;
  currency?: string;
  bars: Bar[];
}

export interface SystemStatus {
  version: string;
  stocks: number;
  active_stocks: number;
  bars: number;
  last_bar_date: string | null;
  stocks_with_errors: number;
  refresh_running: boolean;
  scheduler_running: boolean;
  scheduled_jobs: { id: string; name: string; next_run: string | null }[];
  data_provider: string;
}

export interface JobRun {
  id: number;
  job: string;
  status: "running" | "ok" | "error";
  message: string | null;
  started_at: string;
  finished_at: string | null;
}
