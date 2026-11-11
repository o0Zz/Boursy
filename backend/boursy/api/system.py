"""Health, status, jobs and manual data refresh."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boursy import __version__
from boursy.api.auth import require_user
from boursy.db.models import DailyBar, JobRun, Stock
from boursy.db.session import get_db
from boursy.scheduler.jobs import (
    midday,
    post_close,
    pre_open,
    refresh_data,
    refresh_lock,
    run_job,
    run_trading,
    trading_lock,
    weekly,
)
from boursy.timeutil import market_today, to_iso_utc, utcnow

public = APIRouter(prefix="/api", tags=["system"])
router = APIRouter(prefix="/api/system", tags=["system"], dependencies=[Depends(require_user)])


@public.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "time": to_iso_utc(utcnow())}


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict:
    sched = getattr(request.app.state, "scheduler", None)
    jobs = []
    if sched is not None:
        jobs = [
            {"id": j.id, "name": j.name, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in sched.get_jobs()
        ]
    return {
        "version": __version__,
        "stocks": db.scalar(select(func.count(Stock.id))),
        "active_stocks": db.scalar(select(func.count(Stock.id)).where(Stock.active.is_(True))),
        "bars": db.scalar(select(func.count()).select_from(DailyBar)),
        "last_bar_date": (d.isoformat() if (d := db.scalar(select(func.max(DailyBar.date)))) else None),
        "stocks_with_errors": db.scalar(select(func.count(Stock.id)).where(Stock.last_error.is_not(None))),
        "refresh_running": refresh_lock.locked(),
        "trading_running": trading_lock.locked(),
        "scheduler_running": bool(sched and sched.running),
        "scheduled_jobs": jobs,
        "data_provider": request.app.state.provider.name,
    }


@router.get("/jobs")
def jobs(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    runs = db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(min(limit, 500))).all()
    return [
        {
            "id": r.id,
            "job": r.job,
            "status": r.status,
            "message": r.message,
            "started_at": to_iso_utc(r.started_at),
            "finished_at": to_iso_utc(r.finished_at),
        }
        for r in runs
    ]


class RefreshIn(BaseModel):
    symbols: list[str] | None = None


@router.post("/refresh", status_code=202)
def refresh(body: RefreshIn, request: Request, background: BackgroundTasks) -> dict:
    if refresh_lock.locked():
        raise HTTPException(status_code=409, detail="A data refresh is already running")
    settings, provider = request.app.state.settings, request.app.state.provider
    symbols = [s.upper() for s in body.symbols] if body.symbols else None
    background.add_task(run_job, "manual_refresh", lambda: refresh_data(settings, provider, symbols))
    return {"started": True}


JOBS = {
    "post_close": "Post-close: data, signals, proposals",
    "trading": "Signals and proposals only (no download)",
    "midday": "Midday monitor",
    "pre_open": "Pre-open news check (AI)",
    "weekly": "Weekly screening and summary",
}


@router.post("/run/{job}", status_code=202)
def run_now(job: str, request: Request, background: BackgroundTasks) -> dict:
    """Run a scheduled job now, in the background. Trading days are not checked for `trading`."""
    settings, provider = request.app.state.settings, request.app.state.provider
    fns = {
        "post_close": lambda: post_close(settings, provider),
        "trading": lambda: run_trading(settings, market_today(settings.timezone)),
        "midday": lambda: midday(settings, provider),
        "pre_open": lambda: pre_open(settings),
        "weekly": lambda: weekly(settings),
    }
    if job not in fns:
        raise HTTPException(status_code=404, detail=f"Unknown job {job}")
    if job in ("post_close", "trading") and (trading_lock.locked() or refresh_lock.locked()):
        raise HTTPException(status_code=409, detail="A data refresh or trading run is already running")
    background.add_task(run_job, f"manual_{job}", fns[job])
    return {"started": True, "job": job}
