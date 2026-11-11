"""Database tables."""

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from boursy.db.session import Base
from boursy.timeutil import utcnow


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(2))
    exchange: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    bucket: Mapped[str] = mapped_column(String(16))  # "core" | "growth"
    pea_eligible: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    last_full_refresh: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DailyBar(Base):
    __tablename__ = "daily_bars"

    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | error
    message: Mapped[str | None] = mapped_column(Text, default=None)


class AppConfig(Base):
    """Strategy, risk, fee, AI and notification settings edited in the dashboard (one row, JSON)."""

    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Portfolio(Base):
    """One portfolio per mode: "paper" (simulated fills) and "live" (real PEA, semi-automatic)."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), unique=True)  # paper | live
    name: Mapped[str] = mapped_column(String(64))
    cash: Mapped[float] = mapped_column(Float)  # EUR
    peak_value: Mapped[float] = mapped_column(Float)
    kill_switch: Mapped[bool] = mapped_column(default=False)
    kill_switch_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    started_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    qty: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)  # local currency, fees excluded
    cost_eur: Mapped[float] = mapped_column(Float)  # EUR paid for the shares still held, fees included
    opened_on: Mapped[date] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date, default=None)
    initial_stop: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    highest_close: Mapped[float] = mapped_column(Float)
    half_sold: Mapped[bool] = mapped_column(default=False)
    realized_pnl_eur: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str | None] = mapped_column(String(32), default=None)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), default=None)
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    qty: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float, default=None)
    created_on: Mapped[date] = mapped_column(Date, index=True)
    valid_until: Mapped[date] = mapped_column(Date)
    # pending | executed | rejected | expired | cancelled
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    rule: Mapped[str] = mapped_column(
        String(32)
    )  # main rule: pullback, momentum, stop_loss, trend_break, ...
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # confirmed | vetoed | unavailable | not_used
    ai_status: Mapped[str] = mapped_column(String(16), default="not_used")
    ai_review_id: Mapped[int | None] = mapped_column(ForeignKey("ai_reviews.id"), default=None)
    expected_fees: Mapped[float] = mapped_column(Float, default=0.0)
    risk_eur: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Trade(Base):
    """An executed fill (simulated in paper mode, confirmed by the user in live mode)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), default=None)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"), default=None)
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)  # local currency
    fees: Mapped[float] = mapped_column(Float)  # EUR
    fx_rate: Mapped[float] = mapped_column(Float, default=1.0)  # EUR per unit of local currency
    executed_on: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(16))  # simulated | confirmed | manual
    realized_pnl_eur: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CashMovement(Base):
    """Deposits and withdrawals on a portfolio (not trades). The first one is the starting capital."""

    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)  # EUR, negative for a withdrawal
    on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    invested: Mapped[float] = mapped_column(Float)  # net deposits up to this date


class StockEvent(Base):
    """Dated company event: earnings, trial readout, regulator decision, shareholder meeting."""

    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # earnings | trial | regulatory | agm | other
    title: Mapped[str] = mapped_column(String(256))
    binary: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(8), default="manual")  # manual | ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIReview(Base):
    __tablename__ = "ai_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(16), index=True)  # screening | signal_review | news_check
    backend: Mapped[str] = mapped_column(String(16))  # api | subscription
    model: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(default=True)
    score: Mapped[float | None] = mapped_column(Float, default=None)
    verdict: Mapped[str | None] = mapped_column(String(16), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    output: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_is_estimate: Mapped[bool] = mapped_column(default=False)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | error
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict | None] = mapped_column(JSON, default=None)
    report: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    push_status: Mapped[str] = mapped_column(String(16), default="skipped")  # sent | failed | skipped
    email_status: Mapped[str] = mapped_column(String(16), default="skipped")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class FxRate(Base):
    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    eur_per_unit: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
