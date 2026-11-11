"""Yahoo Finance provider (free, unofficial, ~15 min delayed)."""

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from boursy.data.provider import BAR_COLUMNS, DataError

log = logging.getLogger(__name__)


class YahooProvider:
    name = "yahoo"

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            raw = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                interval="1d",
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
        except Exception as exc:  # yfinance raises many different exception types
            raise DataError(f"{symbol}: {exc}") from exc

        if raw is None or raw.empty:
            raise DataError(f"{symbol}: no data returned")

        df = raw.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]
        df = df[BAR_COLUMNS].dropna(subset=["open", "high", "low", "close"])
        # Index is tz-aware in the exchange timezone; .date gives the local trading date.
        df.index = pd.Index(df.index.date, name="date")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df["adj_close"] = df["adj_close"].fillna(df["close"])
        df["volume"] = df["volume"].fillna(0).astype("int64")
        return df
