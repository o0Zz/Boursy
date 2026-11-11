"""Trade proposals: list, detail, confirm the real fill, reject (semi-automatic workflow)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.api.auth import require_user
from boursy.appconfig import load_app_settings
from boursy.db.models import AIReview, Portfolio, Position, Proposal, Stock
from boursy.db.session import get_db
from boursy.market import eur_per_unit
from boursy.timeutil import market_today, to_iso_utc, utcnow
from boursy.trading.engine import RULE_LABELS
from boursy.trading.portfolio import TradingError, apply_buy, apply_sell

router = APIRouter(prefix="/api/proposals", tags=["proposals"], dependencies=[Depends(require_user)])


def review_out(r: AIReview | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id,
        "task": r.task,
        "backend": r.backend,
        "model": r.model,
        "ok": r.ok,
        "score": r.score,
        "verdict": r.verdict,
        "summary": r.summary,
        "output": r.output,
        "error": r.error,
        "cost_usd": r.cost_usd,
        "cost_is_estimate": r.cost_is_estimate,
        "web_searches": r.web_searches,
        "created_at": to_iso_utc(r.created_at),
    }


def proposal_out(db: Session, p: Proposal, detail: bool = False) -> dict:
    stock = db.get(Stock, p.stock_id)
    pf = db.get(Portfolio, p.portfolio_id)
    fx = eur_per_unit(db, stock.currency)
    out = {
        "id": p.id,
        "mode": pf.mode,
        "symbol": stock.symbol,
        "name": stock.name,
        "bucket": stock.bucket,
        "currency": stock.currency,
        "side": p.side,
        "qty": p.qty,
        "limit_price": p.limit_price,
        "stop_price": p.stop_price,
        "order_value_eur": round(p.qty * p.limit_price * fx, 2),
        "created_on": p.created_on.isoformat(),
        "valid_until": p.valid_until.isoformat(),
        "status": p.status,
        "rule": p.rule,
        "rule_label": RULE_LABELS.get(p.rule, p.rule),
        "reasons": p.reasons,
        "ai_status": p.ai_status,
        "expected_fees": p.expected_fees,
        "risk_eur": p.risk_eur,
        "note": p.note,
        "decided_at": to_iso_utc(p.decided_at),
        "position_id": p.position_id,
    }
    if detail:
        out["snapshot"] = p.snapshot
        out["ai_review"] = review_out(db.get(AIReview, p.ai_review_id) if p.ai_review_id else None)
        if p.position_id:
            pos = db.get(Position, p.position_id)
            out["position"] = {
                "qty": pos.qty,
                "avg_price": pos.avg_price,
                "stop": pos.stop,
                "status": pos.status,
            }
    return out


@router.get("")
def list_proposals(
    mode: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(Proposal).order_by(Proposal.id.desc()).limit(limit)
    if mode:
        q = q.join(Portfolio, Portfolio.id == Proposal.portfolio_id).where(Portfolio.mode == mode)
    if status:
        q = q.where(Proposal.status == status)
    return [proposal_out(db, p) for p in db.scalars(q)]


def proposal_or_404(db: Session, proposal_id: int) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(404, "No such proposal")
    return p


@router.get("/{proposal_id}")
def get_proposal(proposal_id: int, db: Session = Depends(get_db)) -> dict:
    return proposal_out(db, proposal_or_404(db, proposal_id), detail=True)


class FillIn(BaseModel):
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(ge=0)
    date: dt.date | None = None
    stop: float | None = Field(None, gt=0, description="Stop actually placed at the broker (buy)")


@router.post("/{proposal_id}/fill")
def confirm_fill(proposal_id: int, body: FillIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Record the real execution of a proposal (partial fills allowed)."""
    p = proposal_or_404(db, proposal_id)
    if p.status != "pending":
        raise HTTPException(409, f"Proposal is {p.status}")
    pf = db.get(Portfolio, p.portfolio_id)
    stock = db.get(Stock, p.stock_id)
    day = body.date or market_today(request.app.state.settings.timezone)
    try:
        if p.side == "buy":
            stop = body.stop or p.stop_price or body.price * 0.9
            apply_buy(db, pf, stock, body.qty, body.price, body.fees, day, "confirmed", stop, p)
        else:
            pos = db.get(Position, p.position_id) if p.position_id else None
            if pos is None or pos.status != "open":
                raise TradingError("The position of this proposal is already closed")
            apply_sell(db, pf, pos, body.qty, body.price, body.fees, day, "confirmed", p.rule, p)
        if body.qty < p.qty:
            p.note = f"Partial fill: {body.qty} of {p.qty}. " + (p.note or "")
        db.commit()
    except TradingError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return proposal_out(db, p, detail=True)


class RejectIn(BaseModel):
    reason: str | None = Field(None, max_length=300)


@router.post("/{proposal_id}/reject")
def reject(proposal_id: int, body: RejectIn, db: Session = Depends(get_db)) -> dict:
    p = proposal_or_404(db, proposal_id)
    if p.status != "pending":
        raise HTTPException(409, f"Proposal is {p.status}")
    p.status, p.decided_at = "rejected", utcnow()
    if body.reason:
        p.note = f"Rejected: {body.reason}"
    db.commit()
    return proposal_out(db, p, detail=True)


@router.get("/fees/estimate")
def estimate_fee(value: float = Query(gt=0), db: Session = Depends(get_db)) -> dict:
    return {"value": value, "fee": load_app_settings(db).fees.fee(value)}
