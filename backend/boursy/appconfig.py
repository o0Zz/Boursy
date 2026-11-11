"""Settings edited in the dashboard: strategy, risk rules, fee model, AI, notifications, portfolios.

Stored as one JSON document in the `app_config` table. Missing keys take the defaults below, so a new
parameter needs no data migration. Secrets (API keys, SMTP password) stay in environment variables.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from boursy.db.models import AppConfig as AppConfigRow


class StrategyParams(BaseModel):
    """Defaults from the 2022-2026 backtest (see SPEC section 6): the first draft (2 ATR stop, 2.5 ATR
    trailing, 2-session trend break, 60-session time stop) was stopped out by normal noise."""

    # Buy
    rsi_pullback: float = Field(45, ge=10, le=70, description="RSI level the pullback must go below")
    pullback_lookback: int = Field(5, ge=1, le=20, description="Sessions to look back for the pullback")
    volume_mult: float = Field(1.0, ge=0, le=5, description="Signal-day volume vs 20-day average")
    ai_min_score: float = Field(6, ge=0, le=10)
    ai_max_age_days: int = Field(7, ge=1, le=60)
    event_block_days: int = Field(5, ge=0, le=30, description="No buy before a binary event (trading days)")
    core_allow_earnings: bool = Field(True, description="Core stocks may be bought before regular earnings")
    buy_limit_offset: float = Field(0.005, ge=0, le=0.05, description="Buy limit = close x (1 + offset)")
    # Sell
    stop_atr_mult: float = Field(3.0, ge=0.5, le=6)
    stop_cap_core: float = Field(0.10, ge=0.02, le=0.5, description="Max initial stop distance, core")
    stop_cap_growth: float = Field(0.15, ge=0.02, le=0.5, description="Max initial stop distance, growth")
    trail_trigger_r: float = Field(
        1.5, ge=0, le=10, description="Gain (in initial risk units) to start trailing"
    )
    trail_atr_mult: float = Field(3.5, ge=0.5, le=8)
    trend_break_days: int = Field(10, ge=1, le=30, description="Closes below SMA50 in a row")
    exhaustion_rsi: float = Field(75, ge=55, le=95)
    event_protect_days: int = Field(
        2, ge=0, le=10, description="Reduce growth positions before binary events"
    )
    time_stop_days: int = Field(120, ge=5, le=500)
    time_stop_min_gain: float = Field(0.03, ge=-0.5, le=1)
    sell_limit_offset: float = Field(0.01, ge=0, le=0.05, description="Sell limit = close x (1 - offset)")


class RiskParams(BaseModel):
    small_capital: float = Field(1000, ge=0, description="Below this value the small-account limits apply")
    max_positions_small: int = Field(2, ge=1, le=20)
    max_positions: int = Field(6, ge=1, le=30)
    max_weight_core: float = Field(0.25, gt=0, le=1)
    max_weight_growth: float = Field(0.12, gt=0, le=1)
    max_weight_core_small: float = Field(1.0, gt=0, le=1)
    max_weight_growth_small: float = Field(0.5, gt=0, le=1)
    max_risk_per_trade: float = Field(0.02, gt=0, le=0.2)
    min_cash_buffer: float = Field(0.05, ge=0, le=0.5)
    kill_switch_drawdown: float = Field(0.20, gt=0, le=0.9)
    max_buys_per_day: int = Field(3, ge=0, le=20)
    max_fee_pct: float = Field(0.015, gt=0, le=0.2, description="Max round-trip fees / order value")
    reentry_cooldown_days: int = Field(10, ge=0, le=100)


class FeeTier(BaseModel):
    up_to: float = Field(gt=0, description="Order value (EUR) up to which the fixed fee applies")
    fee: float = Field(ge=0)


class FeeModel(BaseModel):
    preset: str = "boursobank_decouverte"
    tiers: list[FeeTier] = Field(default_factory=lambda: [FeeTier(up_to=500, fee=1.99)])
    pct_above: float = Field(0.006, ge=0, le=0.05, description="Percentage above the last tier")
    min_fee: float = Field(0, ge=0)
    cap_pct: float | None = Field(0.005, ge=0, le=0.05, description="PEA legal cap per order (0.5 %)")

    def fee(self, value: float) -> float:
        """Fee in EUR for one order of `value` EUR."""
        if value <= 0:
            return 0.0
        fee = None
        for tier in sorted(self.tiers, key=lambda t: t.up_to):
            if value <= tier.up_to:
                fee = tier.fee
                break
        if fee is None:
            fee = value * self.pct_above
        fee = max(fee, self.min_fee)
        if self.cap_pct is not None:
            fee = min(fee, value * self.cap_pct)
        return round(fee, 2)


FEE_PRESETS: dict[str, FeeModel] = {
    "boursobank_decouverte": FeeModel(
        preset="boursobank_decouverte", tiers=[FeeTier(up_to=500, fee=1.99)], pct_above=0.006
    ),
    "bourse_direct": FeeModel(
        preset="bourse_direct",
        tiers=[
            FeeTier(up_to=500, fee=0.99),
            FeeTier(up_to=1000, fee=1.90),
            FeeTier(up_to=2000, fee=2.90),
            FeeTier(up_to=4400, fee=3.80),
        ],
        pct_above=0.0009,
    ),
    "trade_republic": FeeModel(preset="trade_republic", tiers=[FeeTier(up_to=1e12, fee=1.0)], pct_above=0),
}

Backend = Literal["none", "api", "subscription"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]


class AITask(BaseModel):
    model: str = "claude-opus-5-5"
    effort: Effort = "medium"


class AIParams(BaseModel):
    backend: Backend = "none"
    screening: AITask = Field(default_factory=lambda: AITask(effort="high"))
    signal_review: AITask = Field(default_factory=lambda: AITask(effort="medium"))
    news_check: AITask = Field(default_factory=lambda: AITask(effort="medium"))
    monthly_budget_usd: float = Field(15, ge=0, le=1000, description="API backend only")
    daily_call_cap: int = Field(40, ge=0, le=500, description="Subscription backend only")
    web_search_max_uses: int = Field(5, ge=0, le=20)
    fallback_to_api: bool = Field(False, description="Subscription failures retry on the API backend")
    screening_max_stocks: int = Field(40, ge=1, le=200)


class NotifyParams(BaseModel):
    push: bool = True
    email: bool = True
    paper_proposals: bool = Field(True, description="Also notify proposals of the paper portfolio")
    large_move_core: float = Field(0.05, gt=0, le=1)
    large_move_growth: float = Field(0.08, gt=0, le=1)


class PortfolioParams(BaseModel):
    paper_enabled: bool = True
    paper_capital: float = Field(200, gt=0)
    live_enabled: bool = False
    live_capital: float = Field(200, gt=0)


class AppSettings(BaseModel):
    strategy: StrategyParams = Field(default_factory=StrategyParams)
    risk: RiskParams = Field(default_factory=RiskParams)
    fees: FeeModel = Field(default_factory=lambda: FEE_PRESETS["boursobank_decouverte"].model_copy())
    ai: AIParams = Field(default_factory=AIParams)
    notify: NotifyParams = Field(default_factory=NotifyParams)
    portfolios: PortfolioParams = Field(default_factory=PortfolioParams)


def load_app_settings(session: Session) -> AppSettings:
    row = session.get(AppConfigRow, 1)
    return AppSettings.model_validate(row.data if row else {})


def save_app_settings(session: Session, cfg: AppSettings) -> AppSettings:
    row = session.get(AppConfigRow, 1)
    data = cfg.model_dump(mode="json")
    if row is None:
        session.add(AppConfigRow(id=1, data=data))
    else:
        row.data = data
    session.commit()
    return cfg
