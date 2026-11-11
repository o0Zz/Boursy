"""Scheduled jobs. All times are in the configured market timezone (Europe/Paris)."""

import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import date

import exchange_calendars as xcals
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from boursy.config import Settings
from boursy.data.provider import MarketDataProvider
from boursy.data.service import last_bar_date, refresh_stocks
from boursy.db.models import JobRun, Stock
from boursy.db.session import new_session, session_scope
from boursy.timeutil import market_today, utcnow

log = logging.getLogger(__name__)

refresh_lock = threading.Lock()
BACKUPS_KEPT = 14


class JobBusy(Exception):
    pass


def run_job(name: str, fn: Callable[[], str]) -> None:
    """Run `fn`, recording a JobRun row with its status and message."""
    with session_scope() as s:
        run = JobRun(job=name)
        s.add(run)
        s.flush()
        run_id = run.id
    status, message = "ok", None
    try:
        message = fn()
    except Exception as exc:
        log.exception("Job %s failed", name)
        status, message = "error", str(exc)[:1000]
    with session_scope() as s:
        run = s.get(JobRun, run_id)
        run.status, run.message, run.finished_at = status, message, utcnow()
    log.info("Job %s finished: %s %s", name, status, message or "")


def is_trading_day(day: date, mic: str = "XPAR") -> bool:
    cal = xcals.get_calendar(mic)
    ts = pd.Timestamp(day)
    if ts < cal.first_session or ts > cal.last_session:
        return day.weekday() < 5
    return bool(cal.is_session(ts))


def refresh_data(settings: Settings, provider: MarketDataProvider, symbols: list[str] | None = None) -> str:
    """Download bars for active stocks (or the given symbols)."""
    if not refresh_lock.acquire(blocking=False):
        raise JobBusy("A data refresh is already running")
    try:
        session = new_session()
        try:
            q = select(Stock).order_by(Stock.symbol)
            q = q.where(Stock.symbol.in_(symbols)) if symbols else q.where(Stock.active.is_(True))
            stocks = list(session.scalars(q))
            summary = refresh_stocks(
                session,
                stocks,
                provider,
                market_today(settings.timezone),
                settings.history_years,
                settings.full_refresh_days,
            )
            return summary.message()
        finally:
            session.close()
    finally:
        refresh_lock.release()


def post_close(settings: Settings, provider: MarketDataProvider) -> str:
    today = market_today(settings.timezone)
    if not is_trading_day(today):
        return f"{today} is not a trading day, skipped"
    return refresh_data(settings, provider)


def backup_db(settings: Settings) -> str:
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"boursy-{market_today(settings.timezone).isoformat()}.db"
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(backup_dir.glob("boursy-*.db"))[:-BACKUPS_KEPT]
    for path in old:
        path.unlink()
    return f"{target.name} written, {len(old)} old backups removed"


def needs_initial_load() -> bool:
    with session_scope() as s:
        for stock in s.scalars(select(Stock).where(Stock.active.is_(True))):
            if last_bar_date(s, stock.id) is None:
                return True
    return False


def start_scheduler(settings: Settings, provider: MarketDataProvider) -> BackgroundScheduler:
    tz = settings.timezone
    sched = BackgroundScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1})
    sched.add_job(
        run_job,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=45, timezone=tz),
        args=["post_close", lambda: post_close(settings, provider)],
        id="post_close",
        name="Post-close data refresh",
        misfire_grace_time=3600,
    )
    sched.add_job(
        run_job,
        CronTrigger(hour=3, minute=0, timezone=tz),
        args=["backup", lambda: backup_db(settings)],
        id="backup",
        name="Database backup",
        misfire_grace_time=6 * 3600,
    )
    if needs_initial_load():
        sched.add_job(
            run_job,
            args=["initial_load", lambda: refresh_data(settings, provider)],
            id="initial_load",
            name="Initial history download",
        )
    sched.start()
    return sched
