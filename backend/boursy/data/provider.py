"""Market data provider interface."""

from datetime import date
from typing import Protocol

import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


class DataError(Exception):
    """Raised when a provider cannot return usable data for a symbol."""


class MarketDataProvider(Protocol):
    name: str

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Daily bars from start to end (both inclusive).

        Returns a DataFrame indexed by `datetime.date` (ascending) with columns BAR_COLUMNS.
        Prices are raw (not adjusted); `adj_close` is the dividend/split-adjusted close.
        """
        ...
