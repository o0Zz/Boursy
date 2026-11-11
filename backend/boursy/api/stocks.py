"""Stock universe, bars and indicators."""

import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.api.auth import require_user
from boursy.data.service import load_bars
from boursy.db.models import Stock
from boursy.db.session import get_db
from boursy.indicators.core import INDICATOR_COLUMNS, compute_all, snapshot, trend_label
from boursy.timeutil import to_iso_utc
from boursy.universe.seed import make_stock

router = APIRouter(prefix="/api/stocks", tags=["stocks"], dependencies=[Depends(require_user)])

# Enough history for SMA200 to be defined on the latest bar.
SUMMARY_BARS = 260
# Extra bars loaded before the requested window so indicators are warmed up.
WARMUP_BARS = 250


def stock_out(stock: Stock) -> dict:
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "country": stock.country,
        "exchange": stock.exchange,
        "currency": stock.currency,
        "bucket": stock.bucket,
        "pea_eligible": stock.pea_eligible,
        "active": stock.active,
        "notes": stock.notes,
        "last_full_refresh": to_iso_utc(stock.last_full_refresh),
        "last_error": stock.last_error,
    }


def summarize(session: Session, stock: Stock) -> dict:
    raw = load_bars(session, stock.id, limit=SUMMARY_BARS)
    if raw.empty:
        return {**stock_out(stock), "snapshot": None, "trend": "n/a"}
    snap = snapshot(compute_all(raw), raw)
    return {**stock_out(stock), "snapshot": snap, "trend": trend_label(snap)}


def get_stock_or_404(session: Session, symbol: str) -> Stock:
    stock = session.scalar(select(Stock).where(Stock.symbol == symbol.upper()))
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Unknown stock {symbol}")
    return stock


@router.get("")
def list_stocks(db: Session = Depends(get_db)) -> list[dict]:
    stocks = db.scalars(select(Stock).order_by(Stock.bucket, Stock.name)).all()
    return [summarize(db, s) for s in stocks]


class StockIn(BaseModel):
    symbol: str = Field(min_length=3, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    country: str = Field(min_length=2, max_length=2)
    bucket: Literal["core", "growth"]


@router.post("", status_code=201)
def add_stock(body: StockIn, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(Stock).where(Stock.symbol == body.symbol.upper())):
        raise HTTPException(status_code=409, detail="Stock already exists")
    try:
        stock = make_stock(body.symbol, body.name, body.country, body.bucket)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(stock)
    db.commit()
    return stock_out(stock)


class StockPatch(BaseModel):
    active: bool | None = None
    bucket: Literal["core", "growth"] | None = None
    notes: str | None = None


@router.patch("/{symbol}")
def update_stock(symbol: str, body: StockPatch, db: Session = Depends(get_db)) -> dict:
    stock = get_stock_or_404(db, symbol)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(stock, key, value)
    db.commit()
    return stock_out(stock)


@router.get("/{symbol}")
def get_stock(symbol: str, db: Session = Depends(get_db)) -> dict:
    return summarize(db, get_stock_or_404(db, symbol))


def _clean(value: float) -> float | None:
    return None if value is None or math.isnan(value) else round(float(value), 6)


@router.get("/{symbol}/bars")
def get_bars(symbol: str, days: int = Query(365, ge=20, le=3000), db: Session = Depends(get_db)) -> dict:
    """Adjusted daily bars with indicators for the last `days` trading days."""
    stock = get_stock_or_404(db, symbol)
    raw = load_bars(db, stock.id, limit=days + WARMUP_BARS)
    if raw.empty:
        return {"symbol": stock.symbol, "bars": []}
    ind = compute_all(raw).tail(days)
    cols = ["open", "high", "low", "close", *INDICATOR_COLUMNS]
    bars = [
        {"time": d.isoformat(), "volume": int(row["volume"]), **{c: _clean(row[c]) for c in cols}}
        for d, row in ind.iterrows()
    ]
    return {"symbol": stock.symbol, "currency": stock.currency, "bars": bars}
