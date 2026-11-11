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

    def fx_rate(self, currency: str) -> float:
        """EUR per unit of `currency` (Yahoo quotes EURDKK=X as DKK per EUR)."""
        try:
            hist = yf.Ticker(f"EUR{currency}=X").history(period="5d", interval="1d", raise_errors=True)
        except Exception as exc:
            raise DataError(f"EUR{currency}: {exc}") from exc
        if hist is None or hist.empty:
            raise DataError(f"EUR{currency}: no data")
        return 1.0 / float(hist["Close"].dropna().iloc[-1])

    def quote(self, symbol: str) -> dict:
        """Latest price (delayed ~15 min) and previous close."""
        try:
            info = yf.Ticker(symbol).fast_info
            return {"last": float(info["last_price"]), "previous_close": float(info["previous_close"])}
        except Exception as exc:
            raise DataError(f"{symbol}: {exc}") from exc
