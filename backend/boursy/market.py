"""Market helpers shared by trading jobs: trading calendar, FX rates, latest prices, events."""

import logging
from datetime import date, timedelta
from functools import lru_cache

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.db.models import DailyBar, FxRate, StockEvent
from boursy.timeutil import utcnow

log = logging.getLogger(__name__)

# EUR per unit, used until a rate has been downloaded. DKK is pegged to the euro.
FALLBACK_FX = {"EUR": 1.0, "DKK": 1 / 7.46, "SEK": 1 / 11.2, "NOK": 1 / 11.5}
BINARY_KINDS = {"earnings", "trial", "regulatory"}


@lru_cache(maxsize=4)
def _calendar(mic: str):
    return xcals.get_calendar(mic)


def is_trading_day(day: date, mic: str = "XPAR") -> bool:
    cal = _calendar(mic)
    ts = pd.Timestamp(day)
    if ts < cal.first_session or ts > cal.last_session:
        return day.weekday() < 5
    return bool(cal.is_session(ts))


def next_trading_day(day: date, mic: str = "XPAR") -> date:
    d = day + timedelta(days=1)
    while not is_trading_day(d, mic):
        d += timedelta(days=1)
    return d


def trading_days_between(start: date, end: date) -> int:
    """Weekdays from start (excluded) to end (included); holidays are ignored (close enough)."""
    return int(np.busday_count(start + timedelta(days=1), end + timedelta(days=1))) if end > start else 0


def eur_per_unit(session: Session, currency: str) -> float:
    if currency == "EUR":
        return 1.0
    row = session.get(FxRate, currency)
    return row.eur_per_unit if row else FALLBACK_FX.get(currency, 1.0)


def refresh_fx(session: Session, provider, currencies: set[str]) -> list[str]:
    fetch = getattr(provider, "fx_rate", None)
    done = []
    for cur in sorted(currencies - {"EUR"}):
        if fetch is None:
            continue
        try:
            rate = float(fetch(cur))
        except Exception as exc:
            log.warning("FX rate for %s failed: %s", cur, exc)
            continue
        ref = FALLBACK_FX.get(cur)
        if rate <= 0 or (ref and not 0.5 * ref < rate < 2 * ref):
            log.warning("FX rate for %s rejected: %s", cur, rate)
            continue
        row = session.get(FxRate, cur)
        if row is None:
            session.add(FxRate(currency=cur, eur_per_unit=rate))
        else:
            row.eur_per_unit, row.updated_at = rate, utcnow()
        done.append(cur)
    session.commit()
    return done


def last_bar(session: Session, stock_id: int) -> DailyBar | None:
    return session.scalar(
        select(DailyBar).where(DailyBar.stock_id == stock_id).order_by(DailyBar.date.desc()).limit(1)
    )


def bar_on(session: Session, stock_id: int, day: date) -> DailyBar | None:
    return session.get(DailyBar, (stock_id, day))


def upcoming_events(session: Session, stock_id: int, today: date, days: int = 120) -> list[StockEvent]:
    return list(
        session.scalars(
            select(StockEvent)
            .where(
                StockEvent.stock_id == stock_id,
                StockEvent.date >= today,
                StockEvent.date <= today + timedelta(days=days),
            )
            .order_by(StockEvent.date)
        )
    )


def next_binary_event(
    session: Session, stock_id: int, today: date, ignore_earnings: bool = False
) -> tuple[StockEvent, int] | None:
    """The next binary event and the number of trading days until it."""
    for ev in upcoming_events(session, stock_id, today):
        if not (ev.binary or ev.kind in BINARY_KINDS):
            continue
        if ignore_earnings and ev.kind == "earnings":
            continue
        return ev, trading_days_between(today, ev.date)
    return None
