"""Health, status, jobs and manual data refresh."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boursy import __version__
from boursy.api.auth import require_user
from boursy.db.models import DailyBar, JobRun, Stock
from boursy.db.session import get_db
from boursy.scheduler.jobs import refresh_data, refresh_lock, run_job
from boursy.timeutil import to_iso_utc, utcnow

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
