"""Portfolios, positions, fills and valuation (paper and live).

Cash and P&L are in EUR. Prices, limits and stops are in the stock's own currency, converted with
the EUR rate at the time of the fill.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from boursy.appconfig import AppSettings
from boursy.db.models import (
    CashMovement,
    EquitySnapshot,
    Portfolio,
    Position,
    Proposal,
    Stock,
    Trade,
)
from boursy.market import eur_per_unit, last_bar
from boursy.timeutil import utcnow

MODES = ("paper", "live")
NAMES = {"paper": "Paper (simulation)", "live": "PEA (live)"}


class TradingError(ValueError):
    pass


def get_portfolio(session: Session, mode: str) -> Portfolio | None:
    return session.scalar(select(Portfolio).where(Portfolio.mode == mode))


def create_portfolio(session: Session, mode: str, capital: float, today: date) -> Portfolio:
    pf = Portfolio(mode=mode, name=NAMES[mode], cash=capital, peak_value=capital, started_on=today)
    session.add(pf)
    session.flush()
    session.add(CashMovement(portfolio_id=pf.id, amount=capital, on=today, note="Starting capital"))
    session.commit()
    return pf


def ensure_portfolios(session: Session, cfg: AppSettings, today: date) -> list[Portfolio]:
    """Create the enabled portfolios that do not exist yet; return the enabled ones."""
    out = []
    for mode, enabled, capital in (
        ("paper", cfg.portfolios.paper_enabled, cfg.portfolios.paper_capital),
        ("live", cfg.portfolios.live_enabled, cfg.portfolios.live_capital),
    ):
        if not enabled:
            continue
        pf = get_portfolio(session, mode) or create_portfolio(session, mode, capital, today)
        out.append(pf)
    return out


def reset_portfolio(session: Session, pf: Portfolio, capital: float, today: date) -> Portfolio:
    """Delete every trade, position, proposal and snapshot of the portfolio and start again."""
    mode = pf.mode
    for model in (Trade, Proposal, EquitySnapshot, CashMovement):
        session.execute(delete(model).where(model.portfolio_id == pf.id))
    session.execute(delete(Position).where(Position.portfolio_id == pf.id))
    session.delete(pf)
    session.commit()
    return create_portfolio(session, mode, capital, today)


def open_positions(session: Session, pf: Portfolio) -> list[Position]:
    return list(
        session.scalars(
            select(Position)
            .where(Position.portfolio_id == pf.id, Position.status == "open")
            .order_by(Position.id)
        )
    )


def invested_capital(session: Session, pf: Portfolio, until: date | None = None) -> float:
    q = select(func.coalesce(func.sum(CashMovement.amount), 0.0)).where(CashMovement.portfolio_id == pf.id)
    if until:
        q = q.where(CashMovement.on <= until)
    return float(session.scalar(q))


@dataclass
class Valuation:
    value: float
    cash: float
    positions_value: float
    lines: list[dict]


def valuation(session: Session, pf: Portfolio) -> Valuation:
    lines = []
    total = 0.0
    for pos in open_positions(session, pf):
        stock = session.get(Stock, pos.stock_id)
        bar = last_bar(session, pos.stock_id)
        price = bar.close if bar else pos.avg_price
        fx = eur_per_unit(session, stock.currency)
        value = pos.qty * price * fx
        total += value
        lines.append(
            {
                "position": pos,
                "stock": stock,
                "price": price,
                "price_date": bar.date if bar else None,
                "value_eur": value,
                "fx": fx,
            }
        )
    return Valuation(pf.cash + total, pf.cash, total, lines)


def apply_buy(
    session: Session,
    pf: Portfolio,
    stock: Stock,
    qty: int,
    price: float,
    fees: float,
    day: date,
    source: str,
    stop: float,
    proposal: Proposal | None = None,
    note: str | None = None,
) -> Position:
    if qty <= 0 or price <= 0 or fees < 0:
        raise TradingError("Quantity and price must be positive, fees not negative")
    fx = eur_per_unit(session, stock.currency)
    cost = qty * price * fx + fees
    pos = session.scalar(
        select(Position).where(
            Position.portfolio_id == pf.id, Position.stock_id == stock.id, Position.status == "open"
        )
    )
    if pos is None:
        pos = Position(
            portfolio_id=pf.id,
            stock_id=stock.id,
            qty=qty,
            avg_price=price,
            cost_eur=cost,
            opened_on=day,
            initial_stop=stop,
            stop=stop,
            highest_close=price,
        )
        session.add(pos)
        session.flush()
    else:
        pos.avg_price = (pos.avg_price * pos.qty + price * qty) / (pos.qty + qty)
        pos.qty += qty
        pos.cost_eur += cost
    pf.cash -= cost
    session.add(
        Trade(
            portfolio_id=pf.id,
            stock_id=stock.id,
            position_id=pos.id,
            proposal_id=proposal.id if proposal else None,
            side="buy",
            qty=qty,
            price=price,
            fees=fees,
            fx_rate=fx,
            executed_on=day,
            source=source,
            note=note,
        )
    )
    if proposal is not None:
        proposal.status, proposal.decided_at, proposal.position_id = "executed", utcnow(), pos.id
    return pos


def apply_sell(
    session: Session,
    pf: Portfolio,
    pos: Position,
    qty: int,
    price: float,
    fees: float,
    day: date,
    source: str,
    reason: str,
    proposal: Proposal | None = None,
    note: str | None = None,
) -> Trade:
    if qty <= 0 or price <= 0 or fees < 0:
        raise TradingError("Quantity and price must be positive, fees not negative")
    if qty > pos.qty:
        raise TradingError(f"Cannot sell {qty} shares, the position holds {pos.qty}")
    stock = session.get(Stock, pos.stock_id)
    fx = eur_per_unit(session, stock.currency)
    proceeds = qty * price * fx - fees
    cost_part = pos.cost_eur * qty / pos.qty
    pnl = proceeds - cost_part
    pos.cost_eur -= cost_part
    pos.qty -= qty
    pos.realized_pnl_eur += pnl
    if reason in ("exhaustion", "event_protection"):
        pos.half_sold = True
    if pos.qty == 0:
        pos.status, pos.closed_on, pos.exit_reason = "closed", day, reason
        pos.cost_eur = 0.0
    pf.cash += proceeds
    trade = Trade(
        portfolio_id=pf.id,
        stock_id=stock.id,
        position_id=pos.id,
        proposal_id=proposal.id if proposal else None,
        side="sell",
        qty=qty,
        price=price,
        fees=fees,
        fx_rate=fx,
        executed_on=day,
        source=source,
        realized_pnl_eur=round(pnl, 2),
        note=note,
    )
    session.add(trade)
    if proposal is not None:
        proposal.status, proposal.decided_at = "executed", utcnow()
    return trade


def record_cash(session: Session, pf: Portfolio, amount: float, day: date, note: str | None) -> None:
    if amount == 0:
        raise TradingError("Amount must not be zero")
    if pf.cash + amount < 0:
        raise TradingError("Not enough cash for this withdrawal")
    pf.cash += amount
    pf.peak_value += max(amount, 0)
    session.add(CashMovement(portfolio_id=pf.id, amount=amount, on=day, note=note))
    session.commit()


def snapshot_equity(session: Session, pf: Portfolio, day: date) -> Valuation:
    val = valuation(session, pf)
    row = session.get(EquitySnapshot, (pf.id, day))
    invested = invested_capital(session, pf, day)
    if row is None:
        session.add(
            EquitySnapshot(portfolio_id=pf.id, date=day, value=val.value, cash=val.cash, invested=invested)
        )
    else:
        row.value, row.cash, row.invested = val.value, val.cash, invested
    session.commit()
    return val
