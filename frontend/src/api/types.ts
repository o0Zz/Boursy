export type Bucket = "core" | "growth";
export type Trend = "up" | "down" | "mixed" | "n/a";
export type Mode = "paper" | "live";

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

export interface EventLite {
  date: string;
  kind: string;
  title: string;
  binary: boolean;
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
  ai: { score: number; summary: string; task: string; date: string } | null;
  last_signal: { side: "buy" | "sell"; rule: string; date: string; status: string } | null;
  next_event: EventLite | null;
  held_in: Mode[];
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

export interface StockTrade {
  date: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  mode: Mode;
  realized_pnl_eur: number | null;
}

export interface SystemStatus {
  version: string;
  stocks: number;
  active_stocks: number;
  bars: number;
  last_bar_date: string | null;
  stocks_with_errors: number;
  refresh_running: boolean;
  trading_running: boolean;
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

export interface PositionView {
  id: number;
  symbol: string;
  name: string;
  bucket: Bucket;
  currency: string;
  qty: number;
  avg_price: number;
  price: number;
  price_date: string | null;
  value_eur: number;
  cost_eur: number;
  pnl_eur: number;
  pnl_pct: number;
  stop: number;
  initial_stop: number;
  trailing: boolean;
  stop_distance_pct: number | null;
  highest_close: number;
  opened_on: string;
  days_held: number;
  half_sold: boolean;
  realized_pnl_eur: number;
  next_event: EventLite | null;
  binary_event_days: number | null;
}

export interface PortfolioOverview {
  mode: Mode;
  name: string;
  started_on: string;
  value: number;
  cash: number;
  positions_value: number;
  invested: number;
  pnl_total: number;
  pnl_total_pct: number;
  pnl_day: number | null;
  pnl_day_pct: number | null;
  realized_pnl: number;
  fees_paid: number;
  peak_value: number;
  drawdown_pct: number;
  kill_switch_level: number;
  kill_switch_drawdown_pct: number;
  kill_switch: boolean;
  kill_switch_at: string | null;
  positions: PositionView[];
  pending_proposals: number;
}

export interface EquityPoint {
  time: string;
  value: number;
  cash: number;
  invested?: number;
  benchmark?: number | null;
}

export interface AIReview {
  id: number;
  task: "screening" | "signal_review" | "news_check";
  backend: string;
  model: string;
  ok: boolean;
  score: number | null;
  verdict: string | null;
  summary: string | null;
  output: Record<string, unknown> | null;
  error: string | null;
  cost_usd: number;
  cost_is_estimate: boolean;
  web_searches: number;
  created_at: string;
  symbol?: string | null;
}

export type ProposalStatus = "pending" | "executed" | "rejected" | "expired" | "cancelled";

export interface Proposal {
  id: number;
  mode: Mode;
  symbol: string;
  name: string;
  bucket: Bucket;
  currency: string;
  side: "buy" | "sell";
  qty: number;
  limit_price: number;
  stop_price: number | null;
  order_value_eur: number;
  created_on: string;
  valid_until: string;
  status: ProposalStatus;
  rule: string;
  rule_label: string;
  reasons: string[];
  ai_status: "confirmed" | "vetoed" | "unavailable" | "not_used";
  expected_fees: number;
  risk_eur: number | null;
  note: string | null;
  decided_at: string | null;
  position_id: number | null;
  snapshot?: Record<string, number | string | null>;
  ai_review?: AIReview | null;
  position?: { qty: number; avg_price: number; stop: number; status: string };
}

export interface Trade {
  id: number;
  date: string;
  symbol: string;
  name: string;
  currency: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  value_eur: number;
  fees: number;
  realized_pnl_eur: number | null;
  source: "simulated" | "confirmed" | "manual";
  proposal_id: number | null;
  note: string | null;
}

export interface CashMovement {
  id: number;
  date: string;
  amount: number;
  note: string | null;
}

export interface BacktestSummary {
  start: string;
  end: string;
  years: number;
  capital: number;
  final_value: number;
  total_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  trades: number;
  open_positions: number;
  win_rate_pct: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  profit_factor: number | null;
  fees_paid: number;
  exposure_pct: number;
  benchmark_return_pct: number | null;
  benchmark_max_drawdown_pct: number | null;
  kill_switch_on: string | null;
}

export interface BacktestTrade {
  symbol: string;
  name: string;
  bucket: Bucket;
  entry_date: string;
  exit_date: string | null;
  entry: number;
  exit: number;
  qty: number;
  pnl_eur: number;
  pnl_pct: number;
  days: number;
  entry_rule: string;
  exit_rule: string;
}

export interface BacktestRun {
  id: number;
  status: "running" | "ok" | "error";
  params: Record<string, unknown> & { capital?: number; label?: string };
  summary: BacktestSummary | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  report?: {
    equity: EquityPoint[];
    trades: BacktestTrade[];
    notes: string[];
    settings: { strategy: Record<string, number | boolean>; risk: Record<string, number>; fees: FeeModel };
    symbols: string[];
  } | null;
}

export interface FeeModel {
  preset: string;
  tiers: { up_to: number; fee: number }[];
  pct_above: number;
  min_fee: number;
  cap_pct: number | null;
}

export interface AITask {
  model: string;
  effort: "low" | "medium" | "high" | "xhigh" | "max";
}

export interface AppSettings {
  strategy: Record<string, number | boolean>;
  risk: Record<string, number>;
  fees: FeeModel;
  ai: {
    backend: "none" | "api" | "subscription";
    screening: AITask;
    signal_review: AITask;
    news_check: AITask;
    monthly_budget_usd: number;
    daily_call_cap: number;
    web_search_max_uses: number;
    fallback_to_api: boolean;
    screening_max_stocks: number;
  };
  notify: {
    push: boolean;
    email: boolean;
    paper_proposals: boolean;
    large_move_core: number;
    large_move_growth: number;
  };
  portfolios: { paper_enabled: boolean; paper_capital: number; live_enabled: boolean; live_capital: number };
}

export interface SettingsResponse {
  settings: AppSettings;
  defaults: AppSettings;
  fee_presets: Record<string, FeeModel>;
  models: string[];
  prices: Record<string, { input: number; output: number }>;
  env: {
    anthropic_api_key: boolean;
    claude_code_oauth_token: boolean;
    ntfy_topic: boolean;
    ntfy_url: string;
    smtp: boolean;
    public_url: string;
  };
}

export interface AIStatus {
  backend: string;
  available: boolean;
  reason: string | null;
  api_key_set: boolean;
  subscription_token_set: boolean;
  month_cost_usd: number;
  month_cost_subscription_estimate_usd: number;
  monthly_budget_usd: number;
  calls_today: number;
  daily_call_cap: number;
  costs: { month: string; backend: string; task: string; calls: number; cost_usd: number; web_searches: number }[];
}

export interface NotificationRow {
  id: number;
  kind: string;
  title: string;
  body: string;
  push: string;
  email: string;
  error: string | null;
  created_at: string;
}

export interface StockEvent {
  id: number;
  date: string;
  kind: string;
  title: string;
  binary: boolean;
  source: "manual" | "ai";
}
