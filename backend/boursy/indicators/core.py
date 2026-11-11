"""Technical indicators on daily bars, implemented with pandas/numpy.

Conventions follow the classic definitions (StockCharts / Wilder):
- EMA is seeded with the SMA of its first `n` values, then smoothed with alpha = 2 / (n + 1).
- RSI and ATR use Wilder smoothing: seeded with an SMA, then alpha = 1 / n.
Values are NaN until enough history exists.
"""

import math

import numpy as np
import pandas as pd


def _seeded_smoothing(series: pd.Series, n: int, alpha: float) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if len(valid) == 0:
        return pd.Series(out, index=series.index)
    start = valid[0]
    seed_idx = start + n - 1
    if seed_idx >= len(values):
        return pd.Series(out, index=series.index)
    out[seed_idx] = values[start : seed_idx + 1].mean()
    for i in range(seed_idx + 1, len(values)):
        x = values[i]
        out[i] = out[i - 1] if np.isnan(x) else out[i - 1] + alpha * (x - out[i - 1])
    return pd.Series(out, index=series.index)


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return _seeded_smoothing(series, n, 2.0 / (n + 1))


def wilder(series: pd.Series, n: int) -> pd.Series:
    return _seeded_smoothing(series, n, 1.0 / n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    avg_gain = wilder(delta.clip(lower=0), n)
    avg_loss = wilder((-delta).clip(lower=0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0, np.where(avg_gain == 0, 50.0, 100.0))
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return wilder(true_range(high, low, close), n)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * std, "bb_lower": mid - k * std})


def adjusted(bars: pd.DataFrame) -> pd.DataFrame:
    """OHLC adjusted for dividends and splits using the adj_close / close ratio."""
    factor = (bars["adj_close"] / bars["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    out = bars.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = bars[col] * factor
    return out


INDICATOR_COLUMNS = [
    "ema20",
    "sma50",
    "sma200",
    "rsi14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr14",
    "bb_mid",
    "bb_upper",
    "bb_lower",
    "vol_avg20",
]


def compute_all(bars: pd.DataFrame) -> pd.DataFrame:
    """Adjusted OHLCV plus all indicators. Input: bars from `load_bars`."""
    df = adjusted(bars)
    c = df["close"]
    df["ema20"] = ema(c, 20)
    df["sma50"] = sma(c, 50)
    df["sma200"] = sma(c, 200)
    df["rsi14"] = rsi(c, 14)
    df = df.join(macd(c))
    df["atr14"] = atr(df["high"], df["low"], c, 14)
    df = df.join(bollinger(c))
    df["vol_avg20"] = sma(df["volume"].astype(float), 20)
    return df


def _f(value: object) -> float | None:
    if value is None:
        return None
    v = float(value)
    return None if math.isnan(v) else v


def snapshot(ind: pd.DataFrame, raw: pd.DataFrame) -> dict:
    """Latest values and simple trend states. `ind` from compute_all, `raw` the unadjusted bars."""
    if raw.empty:
        return {}
    last = ind.iloc[-1]
    raw_close = raw["close"]
    prev_close = float(raw_close.iloc[-2]) if len(raw_close) > 1 else None
    close = float(raw_close.iloc[-1])
    sma50, sma200 = _f(last["sma50"]), _f(last["sma200"])
    adj_close = float(last["close"])
    return {
        "date": raw.index[-1].isoformat(),
        "close": close,
        "change_1d_pct": (close / prev_close - 1) * 100 if prev_close else None,
        "ema20": _f(last["ema20"]),
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": _f(last["rsi14"]),
        "macd": _f(last["macd"]),
        "macd_signal": _f(last["macd_signal"]),
        "macd_hist": _f(last["macd_hist"]),
        "atr14": _f(last["atr14"]),
        "atr_pct": (_f(last["atr14"]) / adj_close * 100) if _f(last["atr14"]) else None,
        "volume": int(raw["volume"].iloc[-1]),
        "vol_avg20": _f(last["vol_avg20"]),
        "above_sma200": (adj_close > sma200) if sma200 else None,
        "sma50_above_sma200": (sma50 > sma200) if (sma50 and sma200) else None,
    }


def trend_label(snap: dict) -> str:
    above, golden = snap.get("above_sma200"), snap.get("sma50_above_sma200")
    if above is None or golden is None:
        return "n/a"
    if above and golden:
        return "up"
    if not above and not golden:
        return "down"
    return "mixed"
