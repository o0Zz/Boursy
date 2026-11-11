"""Load data for a backtest, run it in the background and store the report."""

import logging
import threading
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.appconfig import AppSettings, load_app_settings
from boursy.backtest.engine import Instrument, run_backtest
from boursy.data.service import load_bars
from boursy.db.models import BacktestRun, Stock
from boursy.db.session import session_scope
from boursy.indicators.core import compute_all
from boursy.timeutil import utcnow

log = logging.getLogger(__name__)

backtest_lock = threading.Lock()


def load_instruments(session: Session, symbols: list[str] | None = None) -> list[Instrument]:
    q = select(Stock).where(Stock.active.is_(True))
    if symbols:
        q = select(Stock).where(Stock.symbol.in_(symbols))
    out = []
    for stock in session.scalars(q.order_by(Stock.symbol)):
        raw = load_bars(session, stock.id)
        if len(raw) < 220:
            continue
        out.append(Instrument(stock.symbol, stock.name, stock.bucket, stock.currency, compute_all(raw)))
    return out


def merged_settings(base: AppSettings, overrides: dict) -> AppSettings:
    """Apply {"strategy": {...}, "risk": {...}, "fees": {...}} overrides on top of the saved settings."""
    data = base.model_dump(mode="json")
    for section in ("strategy", "risk", "fees"):
        if overrides.get(section):
            data[section] = {**data[section], **overrides[section]}
    return AppSettings.model_validate(data)


def start_backtest(session: Session, params: dict) -> int:
    run = BacktestRun(params=params)
    session.add(run)
    session.commit()
    thread = threading.Thread(target=execute_backtest, args=(run.id,), name=f"backtest-{run.id}", daemon=True)
    thread.start()
    return run.id


def execute_backtest(run_id: int) -> None:
    with backtest_lock:
        try:
            with session_scope() as s:
                run = s.get(BacktestRun, run_id)
                params = dict(run.params)
                cfg = merged_settings(load_app_settings(s), params)
                instruments = load_instruments(s, params.get("symbols"))
            result = run_backtest(
                instruments,
                cfg,
                capital=float(params.get("capital", 10_000)),
                start=date.fromisoformat(params["start"]) if params.get("start") else None,
                end=date.fromisoformat(params["end"]) if params.get("end") else None,
            )
            with session_scope() as s:
                run = s.get(BacktestRun, run_id)
                run.status = "ok"
                run.summary = result.summary
                run.report = {
                    "equity": result.equity,
                    "trades": result.trades,
                    "notes": result.notes,
                    "settings": cfg.model_dump(mode="json", include={"strategy", "risk", "fees"}),
                    "symbols": [i.symbol for i in instruments],
                }
                run.finished_at = utcnow()
        except Exception as exc:
            log.exception("Backtest %s failed", run_id)
            with session_scope() as s:
                run = s.get(BacktestRun, run_id)
                run.status, run.error, run.finished_at = "error", str(exc)[:1000], utcnow()
