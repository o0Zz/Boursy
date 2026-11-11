"""Scheduled jobs (spec section 10). Times are in the market timezone (Europe/Paris).

| Time                 | Job                                                                 |
|----------------------|---------------------------------------------------------------------|
| 08:30 trading days   | Pre-open: AI news check on open positions                           |
| 12:30 trading days   | Midday: prices of open positions vs stops, large moves, expiring    |
| 17:45 trading days   | Post-close: bars, FX, paper fills, signals, proposals, equity, push |
| Saturday 09:00       | Weekly: AI screening, reconciliation reminder, weekly summary       |
| Every day 03:00      | Database backup                                                     |
"""

import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from boursy.analyst.service import Analyst
from boursy.appconfig import AppSettings, load_app_settings
from boursy.config import Settings
from boursy.data.provider import MarketDataProvider
from boursy.data.service import last_bar_date, refresh_stocks
from boursy.db.models import AIReview, EquitySnapshot, JobRun, Portfolio, Position, Proposal, Stock
from boursy.db.session import new_session, session_scope
from boursy.market import is_trading_day, refresh_fx
from boursy.notifier import Notifier
from boursy.timeutil import market_today, utcnow
from boursy.trading.engine import RULE_LABELS, run_day
from boursy.trading.portfolio import ensure_portfolios, open_positions, valuation

log = logging.getLogger(__name__)

refresh_lock = threading.Lock()
trading_lock = threading.Lock()
BACKUPS_KEPT = 14

# Called with (job name, error message) when a job fails; set by start_scheduler.
failure_hook: Callable[[str, str], None] | None = None


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
    if status == "error" and failure_hook is not None:
        try:
            failure_hook(name, message or "")
        except Exception:
            log.exception("Failure notification failed")


class Context:
    """Settings, dashboard settings, analyst and notifier for one job run."""

    def __init__(self, settings: Settings, session: Session):
        self.settings = settings
        self.cfg: AppSettings = load_app_settings(session)
        self.analyst = Analyst(settings, self.cfg.ai)
        self.notifier = Notifier(settings, self.cfg.notify)


# ---------------------------------------------------------------- data


def refresh_data(settings: Settings, provider: MarketDataProvider, symbols: list[str] | None = None) -> str:
    """Download bars for active stocks and held stocks (or the given symbols), then FX rates."""
    if not refresh_lock.acquire(blocking=False):
        raise JobBusy("A data refresh is already running")
    try:
        session = new_session()
        try:
            if symbols:
                stocks = list(session.scalars(select(Stock).where(Stock.symbol.in_(symbols))))
            else:
                held = select(Position.stock_id).where(Position.status == "open")
                stocks = list(
                    session.scalars(
                        select(Stock)
                        .where(Stock.active.is_(True) | Stock.id.in_(held))
                        .order_by(Stock.symbol)
                    )
                )
            summary = refresh_stocks(
                session,
                stocks,
                provider,
                market_today(settings.timezone),
                settings.history_years,
                settings.full_refresh_days,
            )
            refresh_fx(session, provider, {s.currency for s in stocks})
            return summary.message()
        finally:
            session.close()
    finally:
        refresh_lock.release()


# ---------------------------------------------------------------- trading


def proposal_text(session: Session, prop: Proposal, mode: str) -> tuple[str, str]:
    stock = session.get(Stock, prop.stock_id)
    tag = "[Paper] " if mode == "paper" else ""
    title = (
        f"{tag}{prop.side.upper()} {prop.qty} {stock.symbol} limit {prop.limit_price:.2f} {stock.currency}"
    )
    lines = [
        f"{stock.name} - {RULE_LABELS.get(prop.rule, prop.rule)}",
        f"Limit {prop.limit_price:.2f} {stock.currency}, valid until {prop.valid_until.isoformat()}",
    ]
    if prop.stop_price:
        lines.append(f"Stop {prop.stop_price:.2f} {stock.currency}, risk {prop.risk_eur or 0:.2f} EUR")
    lines.append(f"Estimated fees {prop.expected_fees:.2f} EUR")
    lines += [f"- {r}" for r in prop.reasons[:4]]
    if prop.note:
        lines.append(prop.note)
    return title, "\n".join(lines)


def run_trading(settings: Settings, today: date) -> str:
    if not trading_lock.acquire(blocking=False):
        raise JobBusy("The trading loop is already running")
    try:
        with session_scope() as s:
            ctx = Context(settings, s)
            messages = []
            for pf in ensure_portfolios(s, ctx.cfg, today):
                report = run_day(s, pf, ctx.cfg, today, ctx.analyst)
                messages.append(report.message())
                if report.kill_switch_triggered:
                    ctx.notifier.send(
                        s,
                        "kill_switch",
                        f"Kill switch: {pf.name}",
                        f"Portfolio value {report.value:.2f} EUR is {ctx.cfg.risk.kill_switch_drawdown:.0%} below "
                        f"its peak {pf.peak_value:.2f} EUR. No new buys until you reset it in Settings.",
                        "/settings",
                        dedupe_key=f"kill:{pf.id}:{today}",
                    )
                if pf.mode == "live" or ctx.cfg.notify.paper_proposals:
                    for prop in report.proposals:
                        title, body = proposal_text(s, prop, pf.mode)
                        ctx.notifier.send(
                            s,
                            "proposal",
                            title,
                            body,
                            f"/proposals?id={prop.id}",
                            dedupe_key=f"proposal:{prop.id}",
                        )
            return " | ".join(messages) or "No portfolio enabled"
    finally:
        trading_lock.release()


def post_close(settings: Settings, provider: MarketDataProvider) -> str:
    today = market_today(settings.timezone)
    if not is_trading_day(today):
        return f"{today} is not a trading day, skipped"
    data = refresh_data(settings, provider)
    return f"{data} || {run_trading(settings, today)}"


# ---------------------------------------------------------------- midday


def midday(settings: Settings, provider: MarketDataProvider) -> str:
    today = market_today(settings.timezone)
    if not is_trading_day(today):
        return f"{today} is not a trading day, skipped"
    quote = getattr(provider, "quote", None)
    alerts = 0
    with session_scope() as s:
        ctx = Context(settings, s)
        seen: set[int] = set()
        for pf in s.scalars(select(Portfolio)):
            for pos in open_positions(s, pf):
                stock = s.get(Stock, pos.stock_id)
                if quote is None:
                    continue
                try:
                    q = quote(stock.symbol)
                except Exception as exc:
                    log.warning("Quote %s failed: %s", stock.symbol, exc)
                    continue
                last, prev = q.get("last"), q.get("previous_close")
                if not last:
                    continue
                tag = "[Paper] " if pf.mode == "paper" else ""
                if last <= pos.stop:
                    alerts += 1
                    ctx.notifier.send(
                        s,
                        "stop_hit",
                        f"{tag}Stop reached: {stock.symbol} {last:.2f}",
                        f"{stock.name} trades at {last:.2f} {stock.currency}, at or below the stop {pos.stop:.2f}. "
                        "Check that your broker stop order executed, then record the fill.",
                        "/positions",
                        dedupe_key=f"stop:{pos.id}:{today}",
                    )
                threshold = (
                    ctx.cfg.notify.large_move_growth
                    if stock.bucket == "growth"
                    else ctx.cfg.notify.large_move_core
                )
                if prev and stock.id not in seen and abs(last / prev - 1) >= threshold:
                    seen.add(stock.id)
                    alerts += 1
                    ctx.notifier.send(
                        s,
                        "large_move",
                        f"{tag}{stock.symbol} {last / prev - 1:+.1%} today",
                        f"{stock.name}: {prev:.2f} -> {last:.2f} {stock.currency}. Stop {pos.stop:.2f}.",
                        f"/stocks/{stock.symbol}",
                        dedupe_key=f"move:{stock.id}:{today}",
                    )
            if pf.mode == "live":
                for prop in s.scalars(
                    select(Proposal).where(
                        Proposal.portfolio_id == pf.id,
                        Proposal.status == "pending",
                        Proposal.valid_until == today,
                    )
                ):
                    stock = s.get(Stock, prop.stock_id)
                    alerts += 1
                    ctx.notifier.send(
                        s,
                        "expiring",
                        f"Expires today: {prop.side.upper()} {prop.qty} {stock.symbol}",
                        "Place the order or reject the proposal before the close.",
                        f"/proposals?id={prop.id}",
                        dedupe_key=f"expiring:{prop.id}",
                    )
    return f"{alerts} alerts"


# ---------------------------------------------------------------- pre-open and weekly (AI)


def pre_open(settings: Settings) -> str:
    today = market_today(settings.timezone)
    if not is_trading_day(today):
        return f"{today} is not a trading day, skipped"
    with session_scope() as s:
        ctx = Context(settings, s)
        if not ctx.analyst.enabled:
            return "AI is turned off"
        checked, breaks, done = 0, 0, set()
        for pos in s.scalars(select(Position).where(Position.status == "open")):
            if pos.stock_id in done:
                continue
            done.add(pos.stock_id)
            review = ctx.analyst.news_check(s, pos, today)
            if review is None:
                continue
            checked += 1
            stock = s.get(Stock, pos.stock_id)
            if review.verdict in ("thesis_break", "warning"):
                breaks += review.verdict == "thesis_break"
                ctx.notifier.send(
                    s,
                    "thesis_break" if review.verdict == "thesis_break" else "large_move",
                    f"{'Thesis break' if review.verdict == 'thesis_break' else 'News'}: {stock.symbol}",
                    review.summary or "",
                    f"/stocks/{stock.symbol}",
                    dedupe_key=f"news:{review.id}",
                )
        return f"{checked} positions checked, {breaks} thesis breaks"


def weekly(settings: Settings) -> str:
    today = market_today(settings.timezone)
    parts = []
    with session_scope() as s:
        ctx = Context(settings, s)
        if ctx.analyst.enabled:
            stocks = list(s.scalars(select(Stock).where(Stock.active.is_(True)).order_by(Stock.symbol)))
            done = 0
            for stock in stocks[: ctx.cfg.ai.screening_max_stocks]:
                reason = ctx.analyst.blocked_reason(s, ctx.cfg.ai.backend)
                if reason:
                    parts.append(f"screening stopped: {reason}")
                    break
                if ctx.analyst.screen(s, stock, today) is not None:
                    done += 1
            parts.append(f"{done} stocks screened")
        parts.append(weekly_summary(s, ctx, today))
    return "; ".join(parts)


def weekly_summary(s: Session, ctx: Context, today: date) -> str:
    lines = []
    week_ago = today - timedelta(days=7)
    for pf in s.scalars(select(Portfolio)):
        val = valuation(s, pf)
        prev = s.scalar(
            select(EquitySnapshot)
            .where(EquitySnapshot.portfolio_id == pf.id, EquitySnapshot.date <= week_ago)
            .order_by(EquitySnapshot.date.desc())
            .limit(1)
        )
        week = f" ({val.value / prev.value - 1:+.1%} this week)" if prev and prev.value else ""
        lines.append(
            f"{pf.name}: {val.value:.2f} EUR{week}, cash {val.cash:.2f} EUR, {len(val.lines)} positions"
        )
        for line in val.lines:
            pos, stock = line["position"], line["stock"]
            pnl = line["value_eur"] - pos.cost_eur
            lines.append(
                f"  {stock.symbol}: {pos.qty} @ {pos.avg_price:.2f}, now {line['price']:.2f}, P&L {pnl:+.2f} EUR"
            )
        if pf.mode == "live":
            ctx.notifier.send(
                s,
                "reconciliation",
                "Weekly check: does Boursy match your PEA?",
                f"Boursy shows {val.cash:.2f} EUR cash and {len(val.lines)} positions. Compare with your broker and "
                "record any missing trade or cash movement.",
                "/positions",
                dedupe_key=f"reconcile:{today}",
            )
    cost = ctx.analyst.month_cost(s, "api")
    calls = s.scalar(select(AIReview.id).where(AIReview.created_at >= utcnow() - timedelta(days=7)).limit(1))
    lines.append(f"AI cost this month (API): {cost:.2f} USD{'' if calls else ' - no AI calls this week'}")
    ctx.notifier.send(
        s, "weekly_summary", "Weekly summary", "\n".join(lines), "/", dedupe_key=f"weekly:{today}"
    )
    return "weekly summary sent"


# ---------------------------------------------------------------- maintenance


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


def notify_failure(settings: Settings) -> Callable[[str, str], None]:
    def hook(job: str, message: str) -> None:
        with session_scope() as s:
            ctx = Context(settings, s)
            ctx.notifier.send(
                s,
                "job_failure",
                f"Job failed: {job}",
                message[:500],
                "/system",
                dedupe_key=f"fail:{job}:{market_today(settings.timezone)}",
            )

    return hook


def start_scheduler(settings: Settings, provider: MarketDataProvider) -> BackgroundScheduler:
    global failure_hook
    failure_hook = notify_failure(settings)
    tz = settings.timezone
    sched = BackgroundScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1})

    def add(job_id: str, name: str, trigger, fn: Callable[[], str], grace: int = 3600) -> None:
        sched.add_job(run_job, trigger, args=[job_id, fn], id=job_id, name=name, misfire_grace_time=grace)

    weekdays = {"day_of_week": "mon-fri", "timezone": tz}
    add(
        "pre_open",
        "Pre-open news check (AI)",
        CronTrigger(hour=8, minute=30, **weekdays),
        lambda: pre_open(settings),
    )
    add(
        "midday",
        "Midday monitor",
        CronTrigger(hour=12, minute=30, **weekdays),
        lambda: midday(settings, provider),
    )
    add(
        "post_close",
        "Post-close: data, signals, proposals",
        CronTrigger(hour=17, minute=45, **weekdays),
        lambda: post_close(settings, provider),
    )
    add(
        "weekly",
        "Weekly screening and summary",
        CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=tz),
        lambda: weekly(settings),
        grace=6 * 3600,
    )
    add(
        "backup",
        "Database backup",
        CronTrigger(hour=3, minute=0, timezone=tz),
        lambda: backup_db(settings),
        6 * 3600,
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
