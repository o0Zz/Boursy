"""Strategy v1 (trend-following swing): buy setups and indicator-based sell conditions.

Everything here is vectorized over a frame from `indicators.compute_all`, so the backtest evaluates
the whole history at once and live trading reads the last row. Prices are the adjusted ones.
"""

import math

import numpy as np
import pandas as pd

from boursy.appconfig import StrategyParams

SIGNAL_COLUMNS = ["trend_ok", "pullback", "momentum", "volume_ok", "buy_setup", "trend_break", "exhaustion"]


def add_signals(ind: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    df = ind.copy()
    close, rsi = df["close"], df["rsi14"]
    macd, sig = df["macd"], df["macd_signal"]

    df["trend_ok"] = (close > df["sma200"]) & (df["sma50"] > df["sma200"])

    # Pullback: RSI went below the threshold in the previous N sessions, is rising again, and the
    # close is back above EMA 20.
    recent_min = rsi.shift(1).rolling(p.pullback_lookback, min_periods=1).min()
    df["pullback"] = (recent_min < p.rsi_pullback) & (rsi > rsi.shift(1)) & (close > df["ema20"])

    # Momentum: MACD crosses above its signal line while above zero.
    cross_up = (macd > sig) & (macd.shift(1) <= sig.shift(1))
    df["momentum"] = cross_up & (macd > 0)

    df["volume_ok"] = df["volume"] >= p.volume_mult * df["vol_avg20"]
    df["buy_setup"] = df["trend_ok"] & (df["pullback"] | df["momentum"]) & df["volume_ok"]

    below = (close < df["sma50"]).astype(float)
    df["trend_break"] = below.rolling(p.trend_break_days, min_periods=p.trend_break_days).sum() >= (
        p.trend_break_days
    )

    # Exhaustion: RSI above the threshold in the last 3 sessions and MACD crossing below its signal.
    cross_down = (macd < sig) & (macd.shift(1) >= sig.shift(1))
    df["exhaustion"] = (rsi.rolling(3, min_periods=1).max() > p.exhaustion_rsi) & cross_down

    for col in SIGNAL_COLUMNS:
        df[col] = df[col].fillna(False).astype(bool)
    return df


def entry_rule(row: pd.Series) -> str:
    return "pullback" if row["pullback"] else "momentum"


def buy_reasons(row: pd.Series, p: StrategyParams) -> list[str]:
    reasons = [
        f"Uptrend: close {row['close']:.2f} > SMA200 {row['sma200']:.2f}, SMA50 {row['sma50']:.2f} > SMA200"
    ]
    if row["pullback"]:
        reasons.append(
            f"Pullback: RSI went below {p.rsi_pullback:g} and is rising ({row['rsi14']:.0f}), "
            f"close back above EMA20 {row['ema20']:.2f}"
        )
    if row["momentum"]:
        reasons.append(f"Momentum: MACD crossed above its signal line while positive ({row['macd']:.3f})")
    if row["vol_avg20"] and not math.isnan(row["vol_avg20"]):
        reasons.append(f"Volume {row['volume'] / row['vol_avg20']:.1f}x the 20-day average")
    return reasons


def strength(row: pd.Series) -> float:
    """Ranking key between buy candidates: distance above SMA200 (stronger trend first)."""
    return float(row["close"] / row["sma200"]) if row["sma200"] else 0.0


def row_snapshot(row: pd.Series) -> dict:
    keys = [
        "close",
        "ema20",
        "sma50",
        "sma200",
        "rsi14",
        "macd",
        "macd_signal",
        "atr14",
        "volume",
        "vol_avg20",
    ]
    out = {}
    for k in keys:
        v = row.get(k)
        out[k] = None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)
    return out
