"""Day-by-day backtest of strategy v1 with the live fill, fee and risk rules (spec section 9).

Signals are computed on a session's close; orders are limit orders for the next session. Open
positions carry a resting stop order (the one the user places at the broker). No AI filter and no
event calendar exist historically: the report says so.
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from boursy.appconfig import AppSettings
from boursy.strategy.rules import (
    PositionState,
    evaluate_position,
    fill_buy,
    fill_sell,
    fill_stop,
    initial_stop,
    kill_switch_hit,
    max_positions,
    size_buy,
)
from boursy.strategy.signals import add_signals, entry_rule, strength

# EUR per unit. DKK is pegged to the euro; SEK moves, so its result is approximate.
BACKTEST_FX = {"EUR": 1.0, "DKK": 1 / 7.46, "SEK": 1 / 11.2, "NOK": 1 / 11.5}


@dataclass
class Instrument:
    symbol: str
    name: str
    bucket: str
    currency: str
    frame: pd.DataFrame  # compute_all output, indexed by date


@dataclass
class _Pos:
    symbol: str
    qty: int
    entry: float
    entry_date: date
    entry_fees: float
    cost_eur: float
    state: PositionState
    rule: str


@dataclass
class _Order:
    symbol: str
    side: str
    qty: int
    limit: float
    rule: str
    fraction: float = 1.0
    atr: float | None = None


@dataclass
class BacktestResult:
    summary: dict
    equity: list[dict]
    trades: list[dict]
    notes: list[str] = field(default_factory=list)


def run_backtest(
    instruments: list[Instrument],
    cfg: AppSettings,
    capital: float,
    start: date | None = None,
    end: date | None = None,
) -> BacktestResult:
    sp, rp, fees = cfg.strategy, cfg.risk, cfg.fees
    frames = {i.symbol: add_signals(i.frame, sp) for i in instruments if not i.frame.empty}
    info = {i.symbol: i for i in instruments}
    if not frames:
        raise ValueError("No price data to backtest")

    # First date with a defined SMA200 somewhere: before that no signal can fire.
    ready = [f["sma200"].first_valid_index() for f in frames.values()]
    ready = [d for d in ready if d is not None]
    if not ready:
        raise ValueError("Not enough history: SMA 200 needs 200 sessions")
    first = min(ready)
    calendar = sorted({d for f in frames.values() for d in f.index if d >= first})
    if start:
        calendar = [d for d in calendar if d >= start]
    if end:
        calendar = [d for d in calendar if d <= end]
    if len(calendar) < 2:
        raise ValueError("Backtest period is too short")

    cash = capital
    peak = capital
    kill = False
    killed_on: date | None = None
    positions: dict[str, _Pos] = {}
    orders: list[_Order] = []
    cooldown_until: dict[str, int] = {}
    last_close: dict[str, float] = {}
    trades: list[dict] = []
    equity: list[dict] = []
    fees_paid = 0.0
    exposure_days = 0

    def fx(sym: str) -> float:
        return BACKTEST_FX.get(info[sym].currency, 1.0)

    def close_position(pos: _Pos, qty: int, price: float, day: date, reason: str) -> None:
        nonlocal cash, fees_paid
        value = qty * price * fx(pos.symbol)
        fee = fees.fee(value)
        cost_part = pos.cost_eur * qty / pos.qty
        pnl = value - fee - cost_part
        cash += value - fee
        fees_paid += fee
        trades.append(
            {
                "symbol": pos.symbol,
                "name": info[pos.symbol].name,
                "bucket": info[pos.symbol].bucket,
                "entry_date": pos.entry_date.isoformat(),
                "exit_date": day.isoformat(),
                "entry": round(pos.entry, 4),
                "exit": round(price, 4),
                "qty": qty,
                "pnl_eur": round(pnl, 2),
                "pnl_pct": round(pnl / cost_part * 100, 2) if cost_part else 0.0,
                "days": int(np.busday_count(pos.entry_date, day)),
                "entry_rule": pos.rule,
                "exit_rule": reason,
            }
        )
        pos.cost_eur -= cost_part
        pos.qty -= qty
        if pos.qty <= 0:
            del positions[pos.symbol]

    for idx, day in enumerate(calendar):
        bars = {s: f.loc[day] for s, f in frames.items() if day in f.index}

        # 1. Yesterday's orders, at today's prices.
        for order in orders:
            row = bars.get(order.symbol)
            if row is None:
                continue
            if order.side == "buy":
                price = fill_buy(order.limit, row["open"], row["low"])
                if price is None or order.symbol in positions:
                    continue
                value = order.qty * price * fx(order.symbol)
                fee = fees.fee(value)
                if value + fee > cash:
                    continue
                cash -= value + fee
                fees_paid += fee
                stop = initial_stop(price, order.atr, info[order.symbol].bucket, sp)
                positions[order.symbol] = _Pos(
                    order.symbol,
                    order.qty,
                    price,
                    day,
                    fee,
                    value + fee,
                    PositionState(price, stop, stop, price),
                    order.rule,
                )
            else:
                pos = positions.get(order.symbol)
                if pos is None:
                    continue
                price = fill_sell(order.limit, row["open"], row["high"])
                if price is None:
                    continue
                qty = pos.qty if order.fraction >= 1 else max(1, pos.qty // 2)
                if order.fraction < 1:
                    pos.state.half_sold = True
                close_position(pos, qty, price, day, order.rule)
                if order.rule == "stop_loss" and order.symbol not in positions:
                    cooldown_until[order.symbol] = idx + rp.reentry_cooldown_days
        orders = []

        # 2. Resting stop orders.
        for sym, pos in list(positions.items()):
            row = bars.get(sym)
            if row is None:
                continue
            price = fill_stop(pos.state.stop, row["open"], row["low"])
            if price is not None:
                close_position(pos, pos.qty, price, day, "stop_loss")
                cooldown_until[sym] = idx + rp.reentry_cooldown_days

        # 3. Mark to market.
        for sym, row in bars.items():
            last_close[sym] = float(row["close"])
        invested = sum(p.qty * last_close.get(s, p.entry) * fx(s) for s, p in positions.items())
        value = cash + invested
        if positions:
            exposure_days += 1
        peak = max(peak, value)
        if not kill and kill_switch_hit(value, peak, rp):
            kill, killed_on = True, day
        equity.append({"time": day.isoformat(), "value": round(value, 2), "cash": round(cash, 2)})

        if idx == len(calendar) - 1:
            break

        # 4. Exits on today's close.
        for sym, pos in positions.items():
            row = bars.get(sym)
            if row is None:
                continue
            pos.state.bars_held += 1
            ev = evaluate_position(
                pos.state, float(row["close"]), _num(row["atr14"]), row, info[sym].bucket, sp
            )
            pos.state.stop, pos.state.highest_close = ev.stop, ev.highest_close
            if ev.exit:
                limit = float(row["close"]) * (1 - sp.sell_limit_offset)
                orders.append(_Order(sym, "sell", pos.qty, limit, ev.exit.rule, ev.exit.fraction))

        # 5. Entries on today's close.
        if kill:
            continue
        slots = max_positions(value, rp) - len(positions)
        candidates = [
            (sym, row)
            for sym, row in bars.items()
            if row["buy_setup"] and sym not in positions and cooldown_until.get(sym, -1) < idx
        ]
        candidates.sort(key=lambda c: strength(c[1]), reverse=True)
        free_cash = cash
        for sym, row in candidates[: max(0, min(slots, rp.max_buys_per_day))]:
            limit = float(row["close"]) * (1 + sp.buy_limit_offset)
            atr = _num(row["atr14"])
            stop = initial_stop(limit, atr, info[sym].bucket, sp)
            sizing = size_buy(value, free_cash, info[sym].bucket, limit, stop, fx(sym), fees, rp)
            if sizing.qty <= 0:
                continue
            free_cash -= sizing.order_value + sizing.fees
            orders.append(_Order(sym, "buy", sizing.qty, limit, entry_rule(row), atr=atr))

    # Open positions are valued at the last close; list them as open trades.
    for sym, pos in positions.items():
        price = last_close.get(sym, pos.entry)
        value = pos.qty * price * fx(sym)
        trades.append(
            {
                "symbol": sym,
                "name": info[sym].name,
                "bucket": info[sym].bucket,
                "entry_date": pos.entry_date.isoformat(),
                "exit_date": None,
                "entry": round(pos.entry, 4),
                "exit": round(price, 4),
                "qty": pos.qty,
                "pnl_eur": round(value - pos.cost_eur, 2),
                "pnl_pct": round((value / pos.cost_eur - 1) * 100, 2) if pos.cost_eur else 0.0,
                "days": int(np.busday_count(pos.entry_date, calendar[-1])),
                "entry_rule": pos.rule,
                "exit_rule": "open",
            }
        )

    bench = _benchmark(frames, calendar)
    for point, b in zip(equity, bench, strict=True):
        point["benchmark"] = round(capital * b, 2) if b is not None else None

    summary = _py(_summary(equity, trades, capital, fees_paid, exposure_days, killed_on))
    equity, trades = _py(equity), _py(trades)
    notes = [
        "No AI filter: historical AI scores do not exist, so every technical signal is taken.",
        "No event calendar: binary events (trial readouts, regulator decisions) are not avoided.",
        "Survivorship bias: the universe is today's list of stocks; companies that failed or were "
        "delisted over the period are missing, which flatters the result.",
        "Benchmark: equal-weight buy-and-hold of the same stocks (a proxy for a healthcare index).",
        "Prices adjusted for dividends and splits; DKK/SEK converted at fixed rates.",
    ]
    if killed_on:
        notes.append(f"Kill switch triggered on {killed_on.isoformat()}: no new buys after that date.")
    return BacktestResult(summary, equity, trades, notes)


def _py(obj):
    """numpy scalars to plain Python, so the report is JSON-serializable."""
    if isinstance(obj, dict):
        return {k: _py(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_py(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _num(value: object) -> float | None:
    if value is None:
        return None
    v = float(value)
    return None if math.isnan(v) else v


def _benchmark(frames: dict[str, pd.DataFrame], calendar: list[date]) -> list[float | None]:
    """Equal-weight buy-and-hold of every stock that has a price on the first day, as a growth factor."""
    start = calendar[0]
    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).reindex(calendar).ffill()
    base = closes.loc[start].dropna()
    if base.empty:
        return [None] * len(calendar)
    rel = closes[base.index].div(base)
    series = rel.mean(axis=1)
    return [None if math.isnan(v) else float(v) for v in series]


def _max_drawdown(values: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def _summary(
    equity: list[dict],
    trades: list[dict],
    capital: float,
    fees_paid: float,
    exposure_days: int,
    killed_on: date | None,
) -> dict:
    values = [p["value"] for p in equity]
    final = values[-1]
    first_day, last_day = date.fromisoformat(equity[0]["time"]), date.fromisoformat(equity[-1]["time"])
    years = max((last_day - first_day).days / 365.25, 1e-9)
    closed = [t for t in trades if t["exit_date"]]
    wins = [t for t in closed if t["pnl_eur"] > 0]
    losses = [t for t in closed if t["pnl_eur"] <= 0]
    gross_win = sum(t["pnl_eur"] for t in wins)
    gross_loss = -sum(t["pnl_eur"] for t in losses)
    bench = [p["benchmark"] for p in equity if p.get("benchmark") is not None]
    return {
        "start": first_day.isoformat(),
        "end": last_day.isoformat(),
        "years": round(years, 2),
        "capital": capital,
        "final_value": round(final, 2),
        "total_return_pct": round((final / capital - 1) * 100, 2),
        "cagr_pct": round(((final / capital) ** (1 / years) - 1) * 100, 2) if final > 0 else -100.0,
        "max_drawdown_pct": round(_max_drawdown(values) * 100, 2),
        "trades": len(closed),
        "open_positions": len(trades) - len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avg_win_pct": round(sum(t["pnl_pct"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss_pct": round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "fees_paid": round(fees_paid, 2),
        "exposure_pct": round(exposure_days / len(equity) * 100, 1),
        "benchmark_return_pct": round((bench[-1] / capital - 1) * 100, 2) if bench else None,
        "benchmark_max_drawdown_pct": round(_max_drawdown(bench) * 100, 2) if bench else None,
        "kill_switch_on": killed_on.isoformat() if killed_on else None,
    }
