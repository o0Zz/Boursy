"""Daily trading loop for the paper and live portfolios (spec sections 6 to 9).

Post-close, for each enabled portfolio:
1. paper only: fill yesterday's proposals and the resting stop orders at today's prices;
2. expire proposals past their validity;
3. update trailing stops and propose sells for open positions;
4. check the kill switch;
5. propose buys (signal -> event filter -> AI review -> risk sizing);
6. record the day's portfolio value.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boursy.appconfig import AppSettings
from boursy.data.service import load_bars
from boursy.db.models import AIReview, Portfolio, Position, Proposal, Stock
from boursy.indicators.core import compute_all
from boursy.market import (
    bar_on,
    eur_per_unit,
    next_binary_event,
    next_trading_day,
    trading_days_between,
)
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
from boursy.strategy.signals import add_signals, buy_reasons, entry_rule, row_snapshot, strength
from boursy.timeutil import utcnow
from boursy.trading.portfolio import apply_buy, apply_sell, open_positions, snapshot_equity, valuation

log = logging.getLogger(__name__)

FRAME_BARS = 320
RULE_LABELS = {
    "pullback": "Pullback in uptrend",
    "momentum": "MACD momentum",
    "stop_loss": "Stop-loss",
    "trend_break": "Trend break",
    "time_stop": "Time stop",
    "exhaustion": "Exhaustion (sell half)",
    "event_protection": "Event protection (sell half)",
    "thesis_break": "AI thesis break",
    "manual": "Manual",
}


@dataclass
class DayReport:
    mode: str
    fills: list[str] = field(default_factory=list)
    expired: int = 0
    proposals: list[Proposal] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    kill_switch: bool = False
    kill_switch_triggered: bool = False
    value: float = 0.0

    def message(self) -> str:
        parts = [f"{self.mode}: value {self.value:.2f} EUR"]
        if self.fills:
            parts.append(f"fills {', '.join(self.fills)}")
        if self.expired:
            parts.append(f"{self.expired} expired")
        if self.proposals:
            parts.append(
                "proposals "
                + ", ".join(f"{p.side} {p.qty} {p.snapshot.get('symbol')}" for p in self.proposals)
            )
        if self.kill_switch:
            parts.append("KILL SWITCH")
        return "; ".join(parts)


def signal_frame(session: Session, stock: Stock, cfg: AppSettings):
    raw = load_bars(session, stock.id, limit=FRAME_BARS)
    if len(raw) < 210:
        return None, raw
    return add_signals(compute_all(raw), cfg.strategy), raw


# ---------------------------------------------------------------- fills (paper)


def process_paper_fills(
    session: Session, pf: Portfolio, cfg: AppSettings, today: date, report: DayReport
) -> None:
    pending = session.scalars(
        select(Proposal).where(
            Proposal.portfolio_id == pf.id, Proposal.status == "pending", Proposal.created_on < today
        )
    ).all()
    for prop in sorted(pending, key=lambda p: p.side != "sell"):  # sells first, they free cash
        stock = session.get(Stock, prop.stock_id)
        bar = bar_on(session, prop.stock_id, today)
        if bar is None:
            continue
        if prop.side == "buy":
            price = fill_buy(prop.limit_price, bar.open, bar.low)
            if price is None:
                continue
            value = prop.qty * price * eur_per_unit(session, stock.currency)
            fees = cfg.fees.fee(value)
            if value + fees > pf.cash:
                prop.status, prop.note = "cancelled", "Not enough cash at fill time"
                continue
            stop = initial_stop(price, prop.snapshot.get("atr14"), stock.bucket, cfg.strategy)
            apply_buy(session, pf, stock, prop.qty, price, fees, today, "simulated", stop, prop)
            report.fills.append(f"bought {prop.qty} {stock.symbol} @ {price:.2f}")
        else:
            pos = session.get(Position, prop.position_id) if prop.position_id else None
            if pos is None or pos.status != "open":
                prop.status, prop.note = "cancelled", "Position already closed"
                continue
            price = fill_sell(prop.limit_price, bar.open, bar.high)
            if price is None:
                continue
            qty = min(prop.qty, pos.qty)
            value = qty * price * eur_per_unit(session, stock.currency)
            apply_sell(session, pf, pos, qty, price, cfg.fees.fee(value), today, "simulated", prop.rule, prop)
            report.fills.append(f"sold {qty} {stock.symbol} @ {price:.2f}")

    # Resting stop orders, as placed at the broker after each buy.
    for pos in open_positions(session, pf):
        bar = bar_on(session, pos.stock_id, today)
        if bar is None:
            continue
        price = fill_stop(pos.stop, bar.open, bar.low)
        if price is None:
            continue
        stock = session.get(Stock, pos.stock_id)
        value = pos.qty * price * eur_per_unit(session, stock.currency)
        qty = pos.qty
        apply_sell(session, pf, pos, qty, price, cfg.fees.fee(value), today, "simulated", "stop_loss")
        for prop in _pending_for_position(session, pos):
            prop.status, prop.note = "cancelled", "Position closed by its stop order"
        report.fills.append(f"stop {qty} {stock.symbol} @ {price:.2f}")
    session.commit()


def expire_proposals(session: Session, pf: Portfolio, today: date) -> int:
    """Paper proposals get one session to fill; live ones stay open until their validity date passes."""
    q = select(Proposal).where(Proposal.portfolio_id == pf.id, Proposal.status == "pending")
    q = (
        q.where(Proposal.valid_until <= today)
        if pf.mode == "paper"
        else q.where(Proposal.valid_until < today)
    )
    if pf.mode == "paper":
        q = q.where(Proposal.created_on < today)
    count = 0
    for prop in session.scalars(q):
        prop.status, prop.decided_at = "expired", utcnow()
        count += 1
    session.commit()
    return count


def _pending_for_position(session: Session, pos: Position) -> list[Proposal]:
    return list(
        session.scalars(select(Proposal).where(Proposal.position_id == pos.id, Proposal.status == "pending"))
    )


# ---------------------------------------------------------------- sells


def recent_thesis_break(session: Session, stock_id: int, since: date) -> AIReview | None:
    return session.scalar(
        select(AIReview)
        .where(
            AIReview.stock_id == stock_id,
            AIReview.task == "news_check",
            AIReview.verdict == "thesis_break",
            AIReview.created_at >= since,
        )
        .order_by(AIReview.id.desc())
        .limit(1)
    )


def propose_sells(session: Session, pf: Portfolio, cfg: AppSettings, today: date, report: DayReport) -> None:
    sp = cfg.strategy
    for pos in open_positions(session, pf):
        stock = session.get(Stock, pos.stock_id)
        frame, raw = signal_frame(session, stock, cfg)
        if frame is None or raw.index[-1] != today:
            continue
        row = frame.iloc[-1]
        close = float(raw["close"].iloc[-1])
        atr = row["atr14"] if row["atr14"] == row["atr14"] else None
        event = next_binary_event(session, stock.id, today)
        since = max(pos.opened_on, today - timedelta(days=3))
        thesis = recent_thesis_break(session, stock.id, since)
        state = PositionState(
            entry=pos.avg_price,
            initial_stop=pos.initial_stop,
            stop=pos.stop,
            highest_close=pos.highest_close,
            bars_held=trading_days_between(pos.opened_on, today),
            half_sold=pos.half_sold,
        )
        ev = evaluate_position(
            state,
            close,
            atr,
            row,
            stock.bucket,
            sp,
            binary_event_in_days=event[1] if event else None,
            thesis_break=thesis.summary if thesis else None,
        )
        pos.stop, pos.highest_close = ev.stop, ev.highest_close
        exit_ = ev.exit
        if exit_ is None or _pending_for_position(session, pos):
            continue
        qty = pos.qty if exit_.fraction >= 1 else max(1, pos.qty // 2)
        limit = round(close * (1 - sp.sell_limit_offset), 4)
        reasons = [exit_.reason] + [e.reason for e in ev.exits if e is not exit_]
        note = None
        if exit_.rule == "stop_loss" and pf.mode == "live":
            note = "If your broker stop order already executed, record that fill instead of this order."
        prop = Proposal(
            portfolio_id=pf.id,
            stock_id=stock.id,
            position_id=pos.id,
            side="sell",
            qty=qty,
            limit_price=limit,
            created_on=today,
            valid_until=next_trading_day(today),
            rule=exit_.rule,
            reasons=reasons,
            snapshot={"symbol": stock.symbol, **row_snapshot(row), "raw_close": close},
            ai_status="not_used",
            ai_review_id=thesis.id if thesis else None,
            expected_fees=cfg.fees.fee(qty * limit * eur_per_unit(session, stock.currency)),
            note=note,
        )
        session.add(prop)
        report.proposals.append(prop)
    session.commit()


# ---------------------------------------------------------------- buys


def in_cooldown(session: Session, pf: Portfolio, stock_id: int, today: date, days: int) -> bool:
    last = session.scalar(
        select(func.max(Position.closed_on)).where(
            Position.portfolio_id == pf.id, Position.stock_id == stock_id, Position.exit_reason == "stop_loss"
        )
    )
    return last is not None and trading_days_between(last, today) < days


def propose_buys(
    session: Session, pf: Portfolio, cfg: AppSettings, today: date, analyst, report: DayReport
) -> None:
    sp, rp = cfg.strategy, cfg.risk
    if pf.kill_switch:
        report.skipped["*"] = "kill switch active"
        return
    val = valuation(session, pf)
    held = {p.stock_id for p in open_positions(session, pf)}
    pending = session.scalars(
        select(Proposal).where(Proposal.portfolio_id == pf.id, Proposal.status == "pending")
    ).all()
    pending_buys = {p.stock_id for p in pending if p.side == "buy"}
    reserved = sum(
        p.qty * p.limit_price * eur_per_unit(session, session.get(Stock, p.stock_id).currency)
        for p in pending
        if p.side == "buy"
    )
    bought_today = session.scalar(
        select(func.count(Proposal.id)).where(
            Proposal.portfolio_id == pf.id, Proposal.side == "buy", Proposal.created_on == today
        )
    )
    slots = min(
        max_positions(val.value, rp) - len(held) - len(pending_buys),
        rp.max_buys_per_day - bought_today,
    )
    if slots <= 0:
        report.skipped["*"] = "no free position slot or daily buy limit reached"
        return

    candidates = []
    for stock in session.scalars(select(Stock).where(Stock.active.is_(True))):
        if stock.id in held or stock.id in pending_buys:
            continue
        frame, raw = signal_frame(session, stock, cfg)
        if frame is None or raw.index[-1] != today or not frame["buy_setup"].iloc[-1]:
            continue
        candidates.append((stock, frame.iloc[-1], float(raw["close"].iloc[-1])))
    candidates.sort(key=lambda c: strength(c[1]), reverse=True)

    free_cash = val.cash - reserved
    for stock, row, close in candidates:
        if slots <= 0:
            break
        sym = stock.symbol
        if in_cooldown(session, pf, stock.id, today, rp.reentry_cooldown_days):
            report.skipped[sym] = "re-entry cooldown after a stop-loss"
            continue
        ignore_earnings = stock.bucket == "core" and sp.core_allow_earnings
        event = next_binary_event(session, stock.id, today, ignore_earnings=ignore_earnings)
        if event and event[1] <= sp.event_block_days:
            report.skipped[sym] = f"binary event in {event[1]} trading days: {event[0].title}"
            continue

        limit = round(close * (1 + sp.buy_limit_offset), 4)
        atr = row["atr14"] if row["atr14"] == row["atr14"] else None
        stop = initial_stop(limit, atr, stock.bucket, sp)
        fx = eur_per_unit(session, stock.currency)
        sizing = size_buy(val.value, free_cash, stock.bucket, limit, stop, fx, cfg.fees, rp)
        if sizing.qty <= 0:
            report.skipped[sym] = sizing.reason or "sizing"
            continue

        reasons = buy_reasons(row, sp)
        ai_status, review = "not_used", None
        if analyst is not None and analyst.enabled:
            review = analyst.review_signal(session, stock, list(reasons), today)
            if review is None:
                ai_status = "unavailable"
                reasons.append("AI review unavailable: proposed on technical signals only")
            elif review.verdict == "veto" or (review.score or 0) < sp.ai_min_score:
                report.skipped[sym] = f"AI veto (score {review.score}): {review.summary}"
                continue
            else:
                ai_status = "confirmed"
                reasons.append(f"AI score {review.score:g}/10: {review.summary}")

        prop = Proposal(
            portfolio_id=pf.id,
            stock_id=stock.id,
            side="buy",
            qty=sizing.qty,
            limit_price=limit,
            stop_price=stop,
            created_on=today,
            valid_until=next_trading_day(today),
            rule=entry_rule(row),
            reasons=reasons,
            snapshot={"symbol": sym, **row_snapshot(row), "raw_close": close},
            ai_status=ai_status,
            ai_review_id=review.id if review else None,
            expected_fees=sizing.fees,
            risk_eur=sizing.risk_eur,
            note="After the buy, place a stop order at the broker at the stop price."
            if pf.mode == "live"
            else None,
        )
        session.add(prop)
        report.proposals.append(prop)
        free_cash -= sizing.order_value + sizing.fees
        slots -= 1
    session.commit()


# ---------------------------------------------------------------- day


def check_kill_switch(session: Session, pf: Portfolio, cfg: AppSettings, report: DayReport) -> bool:
    """Update the peak; return True when the kill switch has just been triggered."""
    val = valuation(session, pf)
    report.value = val.value
    if val.value > pf.peak_value:
        pf.peak_value = val.value
    triggered = False
    if not pf.kill_switch and kill_switch_hit(val.value, pf.peak_value, cfg.risk):
        pf.kill_switch, pf.kill_switch_at, triggered = True, utcnow(), True
    report.kill_switch = pf.kill_switch
    session.commit()
    return triggered


def run_day(session: Session, pf: Portfolio, cfg: AppSettings, today: date, analyst=None) -> DayReport:
    report = DayReport(mode=pf.mode)
    if pf.mode == "paper":
        process_paper_fills(session, pf, cfg, today, report)
    report.expired = expire_proposals(session, pf, today)
    propose_sells(session, pf, cfg, today, report)
    report.kill_switch_triggered = check_kill_switch(session, pf, cfg, report)
    propose_buys(session, pf, cfg, today, analyst, report)
    report.value = snapshot_equity(session, pf, today).value
    return report
