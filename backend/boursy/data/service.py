"""Download, store and load daily bars."""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from boursy.data.provider import BAR_COLUMNS, MarketDataProvider
from boursy.db.models import DailyBar, Stock
from boursy.timeutil import utcnow

log = logging.getLogger(__name__)

INCREMENTAL_OVERLAP_DAYS = 10


@dataclass
class RefreshSummary:
    ok: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    bars_written: int = 0

    def message(self) -> str:
        text = f"{len(self.ok)} ok, {len(self.errors)} errors, {self.bars_written} bars written"
        if self.errors:
            text += " | " + "; ".join(f"{k}: {v}" for k, v in self.errors.items())
        return text


def last_bar_date(session: Session, stock_id: int) -> date | None:
    return session.scalar(select(func.max(DailyBar.date)).where(DailyBar.stock_id == stock_id))


def refresh_stock(
    session: Session,
    stock: Stock,
    provider: MarketDataProvider,
    today: date,
    history_years: int = 5,
    full_refresh_days: int = 7,
    force_full: bool = False,
) -> int:
    """Download bars for one stock and upsert them. Returns the number of bars written.

    A full refresh (whole history) runs on first load and every `full_refresh_days`, because a dividend
    changes the adjusted close of the whole history. Otherwise only the last days are downloaded.
    """
    last = last_bar_date(session, stock.id)
    stale = stock.last_full_refresh is None or utcnow() - stock.last_full_refresh > timedelta(
        days=full_refresh_days
    )
    full = force_full or last is None or stale
    start = (
        today - timedelta(days=365 * history_years + 7)
        if full
        else last - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    )

    df = provider.daily_bars(stock.symbol, start, today)
    rows = [
        {
            "stock_id": stock.id,
            "date": d,
            **{c: (int(r[c]) if c == "volume" else float(r[c])) for c in BAR_COLUMNS},
        }
        for d, r in df.iterrows()
    ]

    if full:
        session.execute(delete(DailyBar).where(DailyBar.stock_id == stock.id))
    if rows:
        stmt = sqlite_insert(DailyBar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DailyBar.stock_id, DailyBar.date],
            set_={c: getattr(stmt.excluded, c) for c in BAR_COLUMNS},
        )
        session.execute(stmt)
    if full:
        stock.last_full_refresh = utcnow()
    stock.last_error = None
    session.commit()
    return len(rows)


def refresh_stocks(
    session: Session,
    stocks: list[Stock],
    provider: MarketDataProvider,
    today: date,
    history_years: int = 5,
    full_refresh_days: int = 7,
    pause_seconds: float = 0.5,
) -> RefreshSummary:
    summary = RefreshSummary()
    for i, stock in enumerate(stocks):
        if i and pause_seconds:
            time.sleep(pause_seconds)  # be gentle with the free data source
        try:
            summary.bars_written += refresh_stock(
                session, stock, provider, today, history_years, full_refresh_days
            )
            summary.ok.append(stock.symbol)
        except Exception as exc:
            session.rollback()
            msg = str(exc)[:300]
            log.warning("Refresh failed for %s: %s", stock.symbol, msg)
            stock.last_error = msg
            session.commit()
            summary.errors[stock.symbol] = msg
    return summary


def load_bars(session: Session, stock_id: int, limit: int | None = None) -> pd.DataFrame:
    """Bars for one stock, ascending by date, indexed by date. `limit` keeps the most recent rows."""
    q = select(DailyBar).where(DailyBar.stock_id == stock_id).order_by(DailyBar.date.desc())
    if limit:
        q = q.limit(limit)
    bars = session.scalars(q).all()
    df = pd.DataFrame(
        [{"date": b.date, **{c: getattr(b, c) for c in BAR_COLUMNS}} for b in reversed(bars)],
        columns=["date", *BAR_COLUMNS],
    )
    return df.set_index("date")
