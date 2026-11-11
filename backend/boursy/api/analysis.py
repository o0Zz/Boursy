"""Backtests, settings, AI reviews and costs, stock events."""

import datetime as dt
import threading
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from boursy.analyst.backends import PRICES
from boursy.analyst.service import Analyst
from boursy.api.auth import require_user
from boursy.api.proposals import review_out
from boursy.api.stocks import get_stock_or_404
from boursy.appconfig import FEE_PRESETS, MODELS, AppSettings, load_app_settings, save_app_settings
from boursy.backtest.service import backtest_lock, start_backtest
from boursy.db.models import AIReview, BacktestRun, Notification, Stock, StockEvent
from boursy.db.session import get_db, session_scope
from boursy.notifier import Notifier
from boursy.timeutil import market_today, to_iso_utc
from boursy.trading.portfolio import ensure_portfolios

router = APIRouter(prefix="/api", tags=["analysis"], dependencies=[Depends(require_user)])


# ---------------------------------------------------------------- backtests


class BacktestIn(BaseModel):
    capital: float = Field(10_000, gt=0, le=10_000_000)
    start: date | None = None
    end: date | None = None
    symbols: list[str] | None = None
    strategy: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    fees: dict = Field(default_factory=dict)
    label: str | None = Field(None, max_length=80)


def run_out(r: BacktestRun, full: bool = False) -> dict:
    out = {
        "id": r.id,
        "status": r.status,
        "params": r.params,
        "summary": r.summary,
        "error": r.error,
        "created_at": to_iso_utc(r.created_at),
        "finished_at": to_iso_utc(r.finished_at),
    }
    if full:
        out["report"] = r.report
    return out


@router.post("/backtests", status_code=202)
def create_backtest(body: BacktestIn, db: Session = Depends(get_db)) -> dict:
    params = body.model_dump(mode="json", exclude_none=True)
    try:
        from boursy.backtest.service import merged_settings

        merged_settings(load_app_settings(db), params)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid parameters: {exc.errors()[0]['msg']}") from exc
    return {"id": start_backtest(db, params)}


@router.get("/backtests")
def list_backtests(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit))
    return [run_out(r) for r in rows]


@router.get("/backtests/{run_id}")
def get_backtest(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(BacktestRun, run_id)
    if r is None:
        raise HTTPException(404, "No such backtest")
    return {**run_out(r, full=True), "running": backtest_lock.locked() and r.status == "running"}


@router.delete("/backtests/{run_id}", status_code=204)
def delete_backtest(run_id: int, db: Session = Depends(get_db)) -> None:
    db.execute(delete(BacktestRun).where(BacktestRun.id == run_id))
    db.commit()


# ---------------------------------------------------------------- settings


def env_status(request: Request) -> dict:
    s = request.app.state.settings
    return {
        "anthropic_api_key": bool(s.anthropic_api_key),
        "claude_code_oauth_token": bool(s.claude_code_oauth_token),
        "ntfy_topic": bool(s.ntfy_topic),
        "ntfy_url": s.ntfy_url,
        "smtp": bool(s.smtp_host and s.mail_to),
        "public_url": s.public_url,
    }


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)) -> dict:
    return {
        "settings": load_app_settings(db).model_dump(mode="json"),
        "defaults": AppSettings().model_dump(mode="json"),
        "fee_presets": {k: v.model_dump(mode="json") for k, v in FEE_PRESETS.items()},
        "models": MODELS,
        "prices": {m: {"input": p[0], "output": p[1]} for m, p in PRICES.items()},
        "env": env_status(request),
    }


@router.put("/settings")
def put_settings(body: dict, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        cfg = AppSettings.model_validate(body)
    except ValidationError as exc:
        err = exc.errors()[0]
        raise HTTPException(422, f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}") from exc
    save_app_settings(db, cfg)
    ensure_portfolios(db, cfg, market_today(request.app.state.settings.timezone))
    return get_settings(request, db)


@router.post("/settings/test-notification")
def test_notification(request: Request, db: Session = Depends(get_db)) -> dict:
    cfg = load_app_settings(db)
    n = Notifier(request.app.state.settings, cfg.notify)
    row = n.send(db, "test", "Test notification", "Boursy can reach you. Nothing to do.", "/settings")
    return {"push": row.push_status, "email": row.email_status, "error": row.error}


@router.get("/notifications")
def notifications(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(limit))
    return [
        {
            "id": n.id,
            "kind": n.kind,
            "title": n.title,
            "body": n.body,
            "push": n.push_status,
            "email": n.email_status,
            "error": n.error,
            "created_at": to_iso_utc(n.created_at),
        }
        for n in rows
    ]


# ---------------------------------------------------------------- AI


@router.get("/ai/status")
def ai_status(request: Request, db: Session = Depends(get_db)) -> dict:
    cfg = load_app_settings(db)
    status = Analyst(request.app.state.settings, cfg.ai).status(db)
    months = db.execute(
        select(
            func.strftime("%Y-%m", AIReview.created_at),
            AIReview.backend,
            AIReview.task,
            func.count(AIReview.id),
            func.sum(AIReview.cost_usd),
            func.sum(AIReview.web_searches),
        )
        .group_by(func.strftime("%Y-%m", AIReview.created_at), AIReview.backend, AIReview.task)
        .order_by(func.strftime("%Y-%m", AIReview.created_at).desc())
    ).all()
    status["costs"] = [
        {
            "month": m,
            "backend": b,
            "task": t,
            "calls": c,
            "cost_usd": round(cost or 0, 4),
            "web_searches": ws or 0,
        }
        for m, b, t, c, cost, ws in months
    ]
    return status


@router.get("/ai/reviews")
def ai_reviews(
    symbol: str | None = None,
    task: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(AIReview).order_by(AIReview.id.desc()).limit(limit)
    if symbol:
        q = q.where(AIReview.stock_id == get_stock_or_404(db, symbol).id)
    if task:
        q = q.where(AIReview.task == task)
    out = []
    for r in db.scalars(q):
        item = review_out(r)
        stock = db.get(Stock, r.stock_id) if r.stock_id else None
        item["symbol"] = stock.symbol if stock else None
        out.append(item)
    return out


ai_lock = threading.Lock()


@router.post("/ai/screen/{symbol}", status_code=202)
def screen_now(symbol: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Run an AI screening review of one stock now (in the background)."""
    stock = get_stock_or_404(db, symbol)
    cfg = load_app_settings(db)
    analyst = Analyst(request.app.state.settings, cfg.ai)
    reason = analyst.blocked_reason(db, cfg.ai.backend)
    if reason:
        raise HTTPException(409, f"AI unavailable: {reason}")
    if not ai_lock.acquire(blocking=False):
        raise HTTPException(409, "An AI review is already running")
    settings, stock_id = request.app.state.settings, stock.id
    today = market_today(settings.timezone)

    def work() -> None:
        try:
            with session_scope() as s:
                Analyst(settings, load_app_settings(s).ai).screen(s, s.get(Stock, stock_id), today)
        finally:
            ai_lock.release()

    threading.Thread(target=work, name=f"screen-{symbol}", daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------- events


class EventIn(BaseModel):
    date: dt.date
    kind: str = Field(pattern="^(earnings|trial|regulatory|agm|other)$")
    title: str = Field(min_length=1, max_length=256)
    binary: bool = False


def event_out(e: StockEvent) -> dict:
    return {
        "id": e.id,
        "date": e.date.isoformat(),
        "kind": e.kind,
        "title": e.title,
        "binary": e.binary,
        "source": e.source,
    }


@router.get("/stocks/{symbol}/events")
def list_events(symbol: str, db: Session = Depends(get_db)) -> list[dict]:
    stock = get_stock_or_404(db, symbol)
    rows = db.scalars(
        select(StockEvent).where(StockEvent.stock_id == stock.id).order_by(StockEvent.date.desc())
    )
    return [event_out(e) for e in rows]


@router.post("/stocks/{symbol}/events", status_code=201)
def add_event(symbol: str, body: EventIn, db: Session = Depends(get_db)) -> dict:
    stock = get_stock_or_404(db, symbol)
    ev = StockEvent(stock_id=stock.id, source="manual", **body.model_dump())
    db.add(ev)
    db.commit()
    return event_out(ev)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db)) -> None:
    db.execute(delete(StockEvent).where(StockEvent.id == event_id))
    db.commit()
