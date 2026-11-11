"""Portfolios (paper / live): overview, positions, equity curve, journal, cash, manual trades."""

import csv
import datetime as dt
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.api.auth import require_user
from boursy.appconfig import load_app_settings
from boursy.db.models import CashMovement, EquitySnapshot, Portfolio, Position, Proposal, Stock, Trade
from boursy.db.session import get_db
from boursy.market import next_binary_event, trading_days_between, upcoming_events
from boursy.strategy.rules import initial_stop
from boursy.timeutil import market_today, to_iso_utc
from boursy.trading.portfolio import (
    TradingError,
    apply_buy,
    apply_sell,
    ensure_portfolios,
    get_portfolio,
    invested_capital,
    record_cash,
    reset_portfolio,
    valuation,
)

router = APIRouter(prefix="/api/portfolios", tags=["portfolio"], dependencies=[Depends(require_user)])


def today_for(request: Request) -> date:
    return market_today(request.app.state.settings.timezone)


def portfolio_or_404(db: Session, mode: str) -> Portfolio:
    pf = get_portfolio(db, mode)
    if pf is None:
        raise HTTPException(404, f"No {mode} portfolio. Enable it in Settings.")
    return pf


def position_out(db: Session, line: dict, today: date) -> dict:
    pos: Position = line["position"]
    stock: Stock = line["stock"]
    value = line["value_eur"]
    event = next_binary_event(db, stock.id, today)
    nxt = upcoming_events(db, stock.id, today, days=365)
    return {
        "id": pos.id,
        "symbol": stock.symbol,
        "name": stock.name,
        "bucket": stock.bucket,
        "currency": stock.currency,
        "qty": pos.qty,
        "avg_price": pos.avg_price,
        "price": line["price"],
        "price_date": line["price_date"].isoformat() if line["price_date"] else None,
        "value_eur": round(value, 2),
        "cost_eur": round(pos.cost_eur, 2),
        "pnl_eur": round(value - pos.cost_eur, 2),
        "pnl_pct": round((value / pos.cost_eur - 1) * 100, 2) if pos.cost_eur else 0.0,
        "stop": pos.stop,
        "initial_stop": pos.initial_stop,
        "trailing": pos.stop > pos.initial_stop,
        "stop_distance_pct": round((line["price"] / pos.stop - 1) * 100, 2) if pos.stop else None,
        "highest_close": pos.highest_close,
        "opened_on": pos.opened_on.isoformat(),
        "days_held": trading_days_between(pos.opened_on, today),
        "half_sold": pos.half_sold,
        "realized_pnl_eur": round(pos.realized_pnl_eur, 2),
        "next_event": (
            {
                "date": nxt[0].date.isoformat(),
                "title": nxt[0].title,
                "kind": nxt[0].kind,
                "binary": nxt[0].binary,
            }
            if nxt
            else None
        ),
        "binary_event_days": event[1] if event else None,
    }


def overview(db: Session, pf: Portfolio, today: date, risk_dd: float) -> dict:
    val = valuation(db, pf)
    invested = invested_capital(db, pf)
    prev = db.scalar(
        select(EquitySnapshot)
        .where(EquitySnapshot.portfolio_id == pf.id, EquitySnapshot.date < today)
        .order_by(EquitySnapshot.date.desc())
        .limit(1)
    )
    peak = max(pf.peak_value, val.value)
    realized = sum(
        t.realized_pnl_eur or 0 for t in db.scalars(select(Trade).where(Trade.portfolio_id == pf.id))
    )
    fees = sum(t.fees for t in db.scalars(select(Trade).where(Trade.portfolio_id == pf.id)))
    pending = db.scalars(
        select(Proposal).where(Proposal.portfolio_id == pf.id, Proposal.status == "pending")
    ).all()
    return {
        "mode": pf.mode,
        "name": pf.name,
        "started_on": pf.started_on.isoformat(),
        "value": round(val.value, 2),
        "cash": round(val.cash, 2),
        "positions_value": round(val.positions_value, 2),
        "invested": round(invested, 2),
        "pnl_total": round(val.value - invested, 2),
        "pnl_total_pct": round((val.value / invested - 1) * 100, 2) if invested else 0.0,
        "pnl_day": round(val.value - prev.value, 2) if prev else None,
        "pnl_day_pct": round((val.value / prev.value - 1) * 100, 2) if prev and prev.value else None,
        "realized_pnl": round(realized, 2),
        "fees_paid": round(fees, 2),
        "peak_value": round(peak, 2),
        "drawdown_pct": round((val.value / peak - 1) * 100, 2) if peak else 0.0,
        "kill_switch_level": round(peak * (1 - risk_dd), 2),
        "kill_switch_drawdown_pct": round(-risk_dd * 100, 1),
        "kill_switch": pf.kill_switch,
        "kill_switch_at": to_iso_utc(pf.kill_switch_at),
        "positions": [position_out(db, line, today) for line in val.lines],
        "pending_proposals": len(pending),
    }


@router.get("")
def list_portfolios(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    cfg = load_app_settings(db)
    today = today_for(request)
    ensure_portfolios(db, cfg, today)
    return [
        overview(db, pf, today, cfg.risk.kill_switch_drawdown)
        for pf in db.scalars(select(Portfolio).order_by(Portfolio.id))
    ]


@router.get("/{mode}")
def get_portfolio_overview(mode: str, request: Request, db: Session = Depends(get_db)) -> dict:
    cfg = load_app_settings(db)
    return overview(db, portfolio_or_404(db, mode), today_for(request), cfg.risk.kill_switch_drawdown)


@router.get("/{mode}/equity")
def equity(mode: str, db: Session = Depends(get_db)) -> list[dict]:
    pf = portfolio_or_404(db, mode)
    rows = db.scalars(
        select(EquitySnapshot).where(EquitySnapshot.portfolio_id == pf.id).order_by(EquitySnapshot.date)
    )
    return [
        {
            "time": r.date.isoformat(),
            "value": round(r.value, 2),
            "cash": round(r.cash, 2),
            "invested": r.invested,
        }
        for r in rows
    ]


def trade_out(db: Session, t: Trade) -> dict:
    stock = db.get(Stock, t.stock_id)
    return {
        "id": t.id,
        "date": t.executed_on.isoformat(),
        "symbol": stock.symbol,
        "name": stock.name,
        "currency": stock.currency,
        "side": t.side,
        "qty": t.qty,
        "price": t.price,
        "value_eur": round(t.qty * t.price * t.fx_rate, 2),
        "fees": t.fees,
        "realized_pnl_eur": t.realized_pnl_eur,
        "source": t.source,
        "proposal_id": t.proposal_id,
        "note": t.note,
    }


@router.get("/{mode}/trades")
def trades(mode: str, db: Session = Depends(get_db)) -> list[dict]:
    pf = portfolio_or_404(db, mode)
    rows = db.scalars(
        select(Trade).where(Trade.portfolio_id == pf.id).order_by(Trade.executed_on.desc(), Trade.id.desc())
    )
    return [trade_out(db, t) for t in rows]


@router.get("/{mode}/trades.csv")
def trades_csv(mode: str, db: Session = Depends(get_db)) -> StreamingResponse:
    rows = trades(mode, db)
    buf = io.StringIO()
    cols = [
        "date",
        "symbol",
        "name",
        "side",
        "qty",
        "price",
        "currency",
        "value_eur",
        "fees",
        "realized_pnl_eur",
        "source",
        "note",
    ]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="boursy-{mode}-journal.csv"'},
    )


@router.get("/{mode}/cash")
def cash_movements(mode: str, db: Session = Depends(get_db)) -> list[dict]:
    pf = portfolio_or_404(db, mode)
    rows = db.scalars(
        select(CashMovement).where(CashMovement.portfolio_id == pf.id).order_by(CashMovement.on.desc())
    )
    return [{"id": c.id, "date": c.on.isoformat(), "amount": c.amount, "note": c.note} for c in rows]


class CashIn(BaseModel):
    amount: float
    date: dt.date | None = None
    note: str | None = Field(None, max_length=200)


@router.post("/{mode}/cash", status_code=201)
def add_cash(mode: str, body: CashIn, request: Request, db: Session = Depends(get_db)) -> dict:
    pf = portfolio_or_404(db, mode)
    try:
        record_cash(db, pf, body.amount, body.date or today_for(request), body.note)
    except TradingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"cash": pf.cash}


class ManualTradeIn(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(0, ge=0)
    date: dt.date | None = None
    stop: float | None = Field(None, gt=0)
    note: str | None = Field(None, max_length=200)


@router.post("/{mode}/trades", status_code=201)
def manual_trade(mode: str, body: ManualTradeIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Record a trade the bot did not propose, so the portfolio matches the broker."""
    pf = portfolio_or_404(db, mode)
    cfg = load_app_settings(db)
    stock = db.scalar(select(Stock).where(Stock.symbol == body.symbol.upper()))
    if stock is None:
        raise HTTPException(404, f"Unknown stock {body.symbol}")
    day = body.date or today_for(request)
    try:
        if body.side == "buy":
            from boursy.trading.engine import signal_frame

            frame, _ = signal_frame(db, stock, cfg)
            atr = float(frame["atr14"].iloc[-1]) if frame is not None else None
            stop = body.stop or initial_stop(body.price, atr, stock.bucket, cfg.strategy)
            pos = apply_buy(
                db, pf, stock, body.qty, body.price, body.fees, day, "manual", stop, note=body.note
            )
        else:
            pos = db.scalar(
                select(Position).where(
                    Position.portfolio_id == pf.id, Position.stock_id == stock.id, Position.status == "open"
                )
            )
            if pos is None:
                raise TradingError(f"No open position on {stock.symbol}")
            apply_sell(db, pf, pos, body.qty, body.price, body.fees, day, "manual", "manual", note=body.note)
        db.commit()
    except TradingError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"position_id": pos.id}


class PositionPatch(BaseModel):
    stop: float = Field(gt=0)


@router.patch("/{mode}/positions/{position_id}")
def update_position(mode: str, position_id: int, body: PositionPatch, db: Session = Depends(get_db)) -> dict:
    pf = portfolio_or_404(db, mode)
    pos = db.get(Position, position_id)
    if pos is None or pos.portfolio_id != pf.id or pos.status != "open":
        raise HTTPException(404, "No such open position")
    pos.stop = body.stop
    db.commit()
    return {"stop": pos.stop}


@router.post("/{mode}/kill-switch/reset")
def reset_kill_switch(mode: str, db: Session = Depends(get_db)) -> dict:
    pf = portfolio_or_404(db, mode)
    pf.kill_switch, pf.kill_switch_at = False, None
    pf.peak_value = valuation(db, pf).value
    db.commit()
    return {"kill_switch": False, "peak_value": pf.peak_value}


class ResetIn(BaseModel):
    capital: float | None = Field(None, gt=0)
    confirm: str


@router.post("/{mode}/reset")
def reset(mode: str, body: ResetIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Start the portfolio again from scratch. Needs confirm = the mode name."""
    if body.confirm != mode:
        raise HTTPException(422, f'Type "{mode}" to confirm')
    pf = portfolio_or_404(db, mode)
    cfg = load_app_settings(db)
    capital = body.capital or (
        cfg.portfolios.paper_capital if mode == "paper" else cfg.portfolios.live_capital
    )
    pf = reset_portfolio(db, pf, capital, today_for(request))
    return {"mode": pf.mode, "cash": pf.cash}
