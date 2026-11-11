"""Synthetic market data for strategy and trading tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from boursy.data.provider import BAR_COLUMNS
from boursy.db.models import DailyBar, Stock


def weekdays_until(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def uptrend_with_pullback(end: date, n: int = 300) -> pd.DataFrame:
    """Steady uptrend, a 6-session pullback, then a strong bounce on high volume on `end`.

    The last session is a buy setup (trend + pullback + volume) for the default strategy.
    """
    days = weekdays_until(end, n)
    close = [50 + 0.3 * i + 0.4 * np.sin(i / 3) for i in range(n)]
    for k, dv in zip(range(n - 7, n - 1), [-0.9, -1.1, -0.8, -1.0, -0.6, -0.3], strict=True):
        close[k] = close[k - 1] + dv
    close[-1] = close[-2] + 2.2
    c = np.array(close)
    return pd.DataFrame(
        {
            "open": c - 0.2,
            "high": c + 0.5,
            "low": c - 0.6,
            "close": c,
            "adj_close": c,
            "volume": [10_000] * (n - 1) + [30_000],
        },
        index=pd.Index(days, name="date"),
    )[BAR_COLUMNS]


def store_bars(session: Session, stock: Stock, df: pd.DataFrame) -> None:
    for d, r in df.iterrows():
        session.merge(
            DailyBar(
                stock_id=stock.id,
                date=d,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                adj_close=float(r["adj_close"]),
                volume=int(r["volume"]),
            )
        )
    session.commit()


def add_bar(
    session: Session, stock: Stock, day: date, o: float, h: float, low: float, c: float, v: int = 10_000
):
    session.merge(
        DailyBar(stock_id=stock.id, date=day, open=o, high=h, low=low, close=c, adj_close=c, volume=v)
    )
    session.commit()
