"""Exit rules, stops, position sizing and simulated fills (spec sections 6, 7 and 9).

Shared by the backtest and by paper/live trading, so both apply exactly the same logic.
"""

import math
from dataclasses import dataclass, field

from boursy.appconfig import FeeModel, RiskParams, StrategyParams

# ---------------------------------------------------------------- stops


def initial_stop(entry: float, atr: float | None, bucket: str, p: StrategyParams) -> float:
    """entry - k x ATR, but never further than the bucket cap (-10 % core, -15 % growth)."""
    cap = p.stop_cap_core if bucket == "core" else p.stop_cap_growth
    floor = entry * (1 - cap)
    if atr is None or math.isnan(atr) or atr <= 0:
        return round(floor, 4)
    return round(max(entry - p.stop_atr_mult * atr, floor), 4)


@dataclass
class PositionState:
    entry: float
    initial_stop: float
    stop: float
    highest_close: float
    bars_held: int = 0
    half_sold: bool = False

    @property
    def initial_risk(self) -> float:
        return max(self.entry - self.initial_stop, 1e-9)


@dataclass
class Exit:
    rule: str
    fraction: float  # 1.0 = whole position, 0.5 = half
    reason: str


@dataclass
class Evaluation:
    stop: float
    highest_close: float
    exits: list[Exit] = field(default_factory=list)

    @property
    def exit(self) -> Exit | None:
        """The exit to act on: a full exit first, otherwise a partial one."""
        full = [e for e in self.exits if e.fraction >= 1]
        return full[0] if full else (self.exits[0] if self.exits else None)


def evaluate_position(
    state: PositionState,
    close: float,
    atr: float | None,
    signals: dict,
    bucket: str,
    p: StrategyParams,
    binary_event_in_days: int | None = None,
    thesis_break: str | None = None,
) -> Evaluation:
    """Update the trailing stop and list the sell rules that fire on today's close.

    `close` and the stops use the position's own price basis (raw prices live, adjusted in the
    backtest). `signals` holds the boolean columns of `add_signals` for today (trend_break, exhaustion).
    """
    highest = max(state.highest_close, close)
    stop = state.stop
    if atr and not math.isnan(atr) and highest - state.entry >= p.trail_trigger_r * state.initial_risk:
        stop = max(stop, round(highest - p.trail_atr_mult * atr, 4))

    ev = Evaluation(stop=stop, highest_close=highest)
    gain = close / state.entry - 1
    if close < stop:
        kind = "trailing stop" if stop > state.initial_stop else "stop-loss"
        ev.exits.append(Exit("stop_loss", 1.0, f"Close {close:.2f} below the {kind} {stop:.2f}"))
    if thesis_break:
        ev.exits.append(Exit("thesis_break", 1.0, f"AI thesis break: {thesis_break}"))
    if signals.get("trend_break"):
        ev.exits.append(Exit("trend_break", 1.0, f"Close below SMA50 for {p.trend_break_days} sessions"))
    if state.bars_held >= p.time_stop_days and gain < p.time_stop_min_gain:
        ev.exits.append(
            Exit(
                "time_stop",
                1.0,
                f"{state.bars_held} sessions held with {gain:+.1%} (below {p.time_stop_min_gain:+.0%})",
            )
        )
    if not state.half_sold:
        if (
            bucket == "growth"
            and binary_event_in_days is not None
            and binary_event_in_days <= p.event_protect_days
        ):
            ev.exits.append(
                Exit("event_protection", 0.5, f"Binary event in {binary_event_in_days} trading days")
            )
        if signals.get("exhaustion"):
            ev.exits.append(
                Exit("exhaustion", 0.5, f"RSI above {p.exhaustion_rsi:g} and MACD crossed below its signal")
            )
    return ev


# ---------------------------------------------------------------- sizing


@dataclass
class Sizing:
    qty: int
    reason: str | None  # why the trade is refused (qty 0), else None
    order_value: float = 0.0  # EUR
    fees: float = 0.0  # EUR, buy side
    risk_eur: float = 0.0


def is_small(value: float, r: RiskParams) -> bool:
    return value < r.small_capital


def max_positions(value: float, r: RiskParams) -> int:
    return r.max_positions_small if is_small(value, r) else r.max_positions


def size_buy(
    value: float,
    cash: float,
    bucket: str,
    entry: float,
    stop: float,
    fx: float,
    fees: FeeModel,
    r: RiskParams,
) -> Sizing:
    """Shares to buy under the weight, risk-per-trade, cash-buffer and fee rules.

    `value` and `cash` are the portfolio value and free cash in EUR; `entry`/`stop` are in the
    stock's currency, `fx` converts it to EUR.
    """
    if entry <= 0 or stop >= entry:
        return Sizing(0, "Invalid entry or stop price")
    small = is_small(value, r)
    if bucket == "core":
        weight = r.max_weight_core_small if small else r.max_weight_core
    else:
        weight = r.max_weight_growth_small if small else r.max_weight_growth
    price_eur = entry * fx
    risk_per_share = (entry - stop) * fx
    available = cash - r.min_cash_buffer * value

    by_weight = math.floor(weight * value / price_eur)
    by_risk = math.floor(r.max_risk_per_trade * value / risk_per_share)
    qty = min(by_weight, by_risk)
    # Leave room for the fee.
    while qty > 0 and qty * price_eur + fees.fee(qty * price_eur) > available:
        qty -= 1
    if qty <= 0:
        limits = {
            "weight": by_weight,
            "risk per trade": by_risk,
            "cash": math.floor(max(available, 0) / price_eur),
        }
        binding = min(limits, key=limits.get)
        return Sizing(0, f"Not even one share fits the {binding} limit ({price_eur:.2f} EUR per share)")

    order_value = qty * price_eur
    buy_fee = fees.fee(order_value)
    round_trip = buy_fee + fees.fee(order_value)
    if round_trip / order_value > r.max_fee_pct:
        return Sizing(
            0,
            f"Round-trip fees {round_trip:.2f} EUR are {round_trip / order_value:.1%} of the order "
            f"(max {r.max_fee_pct:.1%})",
        )
    return Sizing(qty, None, round(order_value, 2), buy_fee, round(qty * risk_per_share, 2))


def kill_switch_hit(value: float, peak: float, r: RiskParams) -> bool:
    return peak > 0 and value <= peak * (1 - r.kill_switch_drawdown)


# ---------------------------------------------------------------- fills (paper and backtest)


def fill_buy(limit: float, open_: float, low: float) -> float | None:
    """A buy limit fills at the open if the open is at or below the limit, else at the limit if the
    session trades down to it, else not at all."""
    if open_ <= limit:
        return open_
    if low <= limit:
        return limit
    return None


def fill_sell(limit: float, open_: float, high: float) -> float | None:
    if open_ >= limit:
        return open_
    if high >= limit:
        return limit
    return None


def fill_stop(stop: float, open_: float, low: float) -> float | None:
    """A resting stop order (the one the user places at the broker): a gap below it fills at the open."""
    if open_ <= stop:
        return open_
    if low <= stop:
        return stop
    return None
