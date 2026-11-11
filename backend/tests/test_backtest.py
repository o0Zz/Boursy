from datetime import date

import numpy as np
import pandas as pd
import pytest

from boursy.appconfig import AppSettings
from boursy.backtest.engine import Instrument, run_backtest
from boursy.indicators.core import compute_all
from tests.helpers import uptrend_with_pullback, weekdays_until


def wave(end: date, n: int = 600, drift: float = 0.0008, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = weekdays_until(end, n)
    ret = drift + 0.015 * rng.standard_normal(n)
    c = 50 * np.exp(np.cumsum(ret))
    o = c * (1 + 0.003 * rng.standard_normal(n))
    df = pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.01,
            "low": np.minimum(o, c) * 0.99,
            "close": c,
            "adj_close": c,
            "volume": rng.integers(5_000, 20_000, n),
        },
        index=pd.Index(days, name="date"),
    )
    return df


def instruments(end=date(2026, 11, 10)):
    return [
        Instrument("AAA.PA", "Alpha", "core", "EUR", compute_all(wave(end, seed=1))),
        Instrument("BBB.PA", "Beta", "growth", "EUR", compute_all(wave(end, seed=2, drift=0.001))),
        Instrument("CCC.CO", "Gamma", "core", "DKK", compute_all(wave(end, seed=3) * 7)),
    ]


def test_backtest_runs_and_accounts_for_every_euro():
    res = run_backtest(instruments(), AppSettings(), capital=10_000)
    s = res.summary
    assert s["trades"] > 0
    assert len(res.equity) > 300
    assert res.equity[0]["value"] == pytest.approx(10_000, rel=0.02)
    # Final value = capital + P&L of closed trades + unrealized P&L of open ones (P&L is net of fees).
    pnl = sum(t["pnl_eur"] for t in res.trades)
    assert s["final_value"] == pytest.approx(10_000 + pnl, abs=1.0)
    assert s["fees_paid"] > 0
    assert s["max_drawdown_pct"] <= 0
    assert all(p["benchmark"] is not None for p in res.equity)
    assert any("Survivorship" in n for n in res.notes)


def test_backtest_respects_position_limit_and_cash():
    res = run_backtest(instruments(), AppSettings(), capital=10_000)
    for point in res.equity:
        assert point["cash"] >= -0.01
    # Never more open positions than the limit at any time.
    events = []
    for t in res.trades:
        events.append((t["entry_date"], 1))
        if t["exit_date"]:
            events.append((t["exit_date"], -1))
    open_count, peak = 0, 0
    for _, delta in sorted(events, key=lambda e: (e[0], e[1])):
        open_count += delta
        peak = max(peak, open_count)
    assert peak <= AppSettings().risk.max_positions


def test_backtest_buys_the_pullback_next_day():
    end = date(2026, 11, 10)
    frame = uptrend_with_pullback(end)
    # One more session after the signal, opening below the limit: the buy fills at the open.
    nxt = date(2026, 11, 11)
    last = frame["close"].iloc[-1]
    frame.loc[nxt] = [last - 0.1, last + 0.5, last - 0.3, last + 0.2, last + 0.2, 12_000]
    # Earlier swings stop the position out on 2026-11-05: no re-entry cooldown for this test.
    cfg = AppSettings.model_validate({"risk": {"reentry_cooldown_days": 0}})
    res = run_backtest([Instrument("AAA.PA", "Alpha", "core", "EUR", compute_all(frame))], cfg, 10_000)
    opened = [t for t in res.trades if t["entry_date"] == nxt.isoformat()]
    assert len(opened) == 1
    assert opened[0]["entry"] == pytest.approx(last - 0.1)
    assert opened[0]["entry_rule"] == "pullback"


def test_backtest_without_enough_history():
    short = wave(date(2026, 11, 10), n=100)
    with pytest.raises(ValueError, match="history"):
        run_backtest([Instrument("A", "A", "core", "EUR", compute_all(short))], AppSettings(), 1000)
