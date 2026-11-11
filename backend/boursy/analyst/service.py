"""Analyst: runs a task on the selected backend, enforces the budget and stores every review."""

import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boursy.analyst.backends import ApiBackend, BackendError, BackendResult, SubscriptionBackend
from boursy.analyst.prompts import (
    SCHEMAS,
    SYSTEM,
    news_check_prompt,
    screening_prompt,
    signal_review_prompt,
)
from boursy.appconfig import AIParams
from boursy.config import Settings
from boursy.data.service import load_bars
from boursy.db.models import AIReview, Position, Stock, StockEvent
from boursy.indicators.core import compute_all, snapshot
from boursy.market import upcoming_events
from boursy.timeutil import utcnow

log = logging.getLogger(__name__)


class Analyst:
    def __init__(self, settings: Settings, params: AIParams, api_backend=None, subscription_backend=None):
        self.settings = settings
        self.p = params
        self._api = api_backend
        self._sub = subscription_backend

    # ---------------------------------------------------------------- configuration

    @property
    def enabled(self) -> bool:
        return self.p.backend != "none"

    def api(self):
        if self._api is None and self.settings.anthropic_api_key:
            self._api = ApiBackend(self.settings.anthropic_api_key)
        return self._api

    def subscription(self):
        if self._sub is None and self.settings.claude_code_oauth_token:
            self._sub = SubscriptionBackend(
                self.settings.claude_code_oauth_token,
                self.settings.data_dir / "claude-home",
                self.settings.claude_bin,
                self.settings.claude_timeout_s,
            )
        return self._sub

    def backend_for(self, name: str):
        return self.api() if name == "api" else self.subscription() if name == "subscription" else None

    def month_cost(self, session: Session, backend: str = "api") -> float:
        start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return float(
            session.scalar(
                select(func.coalesce(func.sum(AIReview.cost_usd), 0.0)).where(
                    AIReview.created_at >= start, AIReview.backend == backend
                )
            )
        )

    def calls_today(self, session: Session, backend: str = "subscription") -> int:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return int(
            session.scalar(
                select(func.count(AIReview.id)).where(
                    AIReview.created_at >= start, AIReview.backend == backend
                )
            )
        )

    def blocked_reason(self, session: Session, backend: str) -> str | None:
        """Why `backend` cannot take a call right now, or None."""
        if backend == "api":
            if not self.settings.anthropic_api_key:
                return "ANTHROPIC_API_KEY is not set"
            if self.month_cost(session, "api") >= self.p.monthly_budget_usd:
                return f"monthly budget of {self.p.monthly_budget_usd:g} USD reached"
        elif backend == "subscription":
            if not self.settings.claude_code_oauth_token:
                return "CLAUDE_CODE_OAUTH_TOKEN is not set (run `claude setup-token`)"
            if self.calls_today(session, "subscription") >= self.p.daily_call_cap:
                return f"daily cap of {self.p.daily_call_cap} calls reached"
        else:
            return "AI is turned off"
        return None

    def status(self, session: Session) -> dict:
        return {
            "backend": self.p.backend,
            "available": self.enabled and self.blocked_reason(session, self.p.backend) is None,
            "reason": self.blocked_reason(session, self.p.backend) if self.enabled else "AI is turned off",
            "api_key_set": bool(self.settings.anthropic_api_key),
            "subscription_token_set": bool(self.settings.claude_code_oauth_token),
            "month_cost_usd": round(self.month_cost(session, "api"), 4),
            "month_cost_subscription_estimate_usd": round(self.month_cost(session, "subscription"), 4),
            "monthly_budget_usd": self.p.monthly_budget_usd,
            "calls_today": self.calls_today(session, "subscription") + self.calls_today(session, "api"),
            "daily_call_cap": self.p.daily_call_cap,
        }

    # ---------------------------------------------------------------- running a task

    def run(self, session: Session, task: str, stock: Stock | None, prompt: str) -> AIReview | None:
        """Run one task; store and return the review, or None when no backend can take the call."""
        cfg = getattr(self.p, task)
        order = [self.p.backend]
        if self.p.backend == "subscription" and self.p.fallback_to_api:
            order.append("api")
        last_error = None
        for name in order:
            reason = self.blocked_reason(session, name)
            if reason:
                last_error = reason
                continue
            backend = self.backend_for(name)
            try:
                result = backend.run(
                    SYSTEM, prompt, SCHEMAS[task], cfg.model, cfg.effort, self.p.web_search_max_uses
                )
            except BackendError as exc:
                log.warning("AI %s on %s failed: %s", task, name, exc)
                self._store(session, task, stock, name, cfg.model, None, str(exc))
                last_error = str(exc)
                continue
            except Exception as exc:  # network, SDK errors
                log.exception("AI %s on %s crashed", task, name)
                self._store(session, task, stock, name, cfg.model, None, f"{type(exc).__name__}: {exc}")
                last_error = str(exc)
                continue
            return self._store(session, task, stock, name, cfg.model, result, None)
        log.info("AI %s skipped: %s", task, last_error)
        return None

    def _store(
        self,
        session: Session,
        task: str,
        stock: Stock | None,
        backend: str,
        model: str,
        result: BackendResult | None,
        error: str | None,
    ) -> AIReview | None:
        review = AIReview(
            stock_id=stock.id if stock else None,
            task=task,
            backend=backend,
            model=result.model if result else model,
            ok=result is not None,
            error=error[:2000] if error else None,
        )
        if result is not None:
            out = result.output
            review.output = out
            review.summary = str(out.get("summary", ""))[:2000]
            if "score" in out:
                review.score = max(0.0, min(10.0, float(out["score"])))
            review.verdict = out.get("decision") or out.get("status") or None
            review.input_tokens = result.input_tokens + result.cache_read_tokens + result.cache_write_tokens
            review.output_tokens = result.output_tokens
            review.web_searches = result.web_searches
            review.cost_usd = round(result.cost_usd, 6)
            review.cost_is_estimate = result.cost_is_estimate
            review.duration_s = round(result.duration_s, 1)
        session.add(review)
        session.flush()
        if result is not None and stock is not None:
            self._store_events(session, stock, result.output.get("events") or [])
            if task == "screening" and result.output.get("bucket") in ("core", "growth"):
                note = f"AI suggests bucket {result.output['bucket']}"
                if result.output["bucket"] != stock.bucket and note not in (stock.notes or ""):
                    stock.notes = note if not stock.notes else f"{stock.notes}\n{note}"
        session.commit()
        return review if result is not None else None

    def _store_events(self, session: Session, stock: Stock, events: list[dict]) -> None:
        today = date.today()
        for ev in events:
            try:
                day = date.fromisoformat(str(ev["date"])[:10])
            except (KeyError, ValueError):
                continue
            if day < today - timedelta(days=1) or day > today + timedelta(days=400):
                continue
            title = str(ev.get("title", ""))[:256] or ev.get("kind", "event")
            exists = session.scalar(
                select(StockEvent.id).where(
                    StockEvent.stock_id == stock.id,
                    StockEvent.date == day,
                    StockEvent.kind == ev.get("kind", "other"),
                )
            )
            if exists:
                continue
            session.add(
                StockEvent(
                    stock_id=stock.id,
                    date=day,
                    kind=ev.get("kind", "other"),
                    title=title,
                    binary=bool(ev.get("binary")),
                    source="ai",
                )
            )

    # ---------------------------------------------------------------- tasks

    def latest(
        self, session: Session, stock_id: int, task: str, max_age_days: int | None = None
    ) -> AIReview | None:
        q = select(AIReview).where(
            AIReview.stock_id == stock_id, AIReview.task == task, AIReview.ok.is_(True)
        )
        if max_age_days is not None:
            q = q.where(AIReview.created_at >= utcnow() - timedelta(days=max_age_days))
        return session.scalar(q.order_by(AIReview.id.desc()).limit(1))

    def screen(self, session: Session, stock: Stock, today: date) -> AIReview | None:
        last = self.latest(session, stock.id, "screening")
        prompt = screening_prompt(
            today.isoformat(),
            stock_context(stock),
            market_context(session, stock),
            events_context(session, stock, today),
            _review_brief(last),
        )
        return self.run(session, "screening", stock, prompt)

    def review_signal(
        self, session: Session, stock: Stock, reasons: list[str], today: date
    ) -> AIReview | None:
        """Signal review, reused when one was already made for this stock today (paper + live)."""
        start = datetime.combine(today, datetime.min.time())
        done = session.scalar(
            select(AIReview)
            .where(
                AIReview.stock_id == stock.id,
                AIReview.task == "signal_review",
                AIReview.ok.is_(True),
                AIReview.created_at >= start,
            )
            .order_by(AIReview.id.desc())
            .limit(1)
        )
        if done:
            return done
        prompt = signal_review_prompt(
            today.isoformat(),
            stock_context(stock),
            market_context(session, stock),
            reasons,
            events_context(session, stock, today),
            _review_brief(self.latest(session, stock.id, "screening")),
        )
        return self.run(session, "signal_review", stock, prompt)

    def news_check(self, session: Session, pos: Position, today: date) -> AIReview | None:
        stock = session.get(Stock, pos.stock_id)
        last = self.latest(session, stock.id, "news_check")
        since = (last.created_at.date() if last else pos.opened_on - timedelta(days=7)).isoformat()
        position = {
            "opened_on": pos.opened_on.isoformat(),
            "avg_price": pos.avg_price,
            "stop": pos.stop,
            "qty": pos.qty,
        }
        prompt = news_check_prompt(
            today.isoformat(),
            stock_context(stock),
            market_context(session, stock),
            position,
            since,
            events_context(session, stock, today),
        )
        return self.run(session, "news_check", stock, prompt)


# ---------------------------------------------------------------- context builders


def stock_context(stock: Stock) -> dict:
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "country": stock.country,
        "exchange": stock.exchange,
        "currency": stock.currency,
        "bucket": stock.bucket,
        "notes": stock.notes,
    }


def market_context(session: Session, stock: Stock) -> dict:
    raw = load_bars(session, stock.id, limit=300)
    if raw.empty:
        return {}
    snap = snapshot(compute_all(raw), raw)
    close = raw["close"]

    def change(n: int) -> float | None:
        return round((close.iloc[-1] / close.iloc[-1 - n] - 1) * 100, 1) if len(close) > n else None

    keep = ("date", "close", "rsi14", "sma50", "sma200", "atr_pct", "above_sma200", "sma50_above_sma200")
    return {
        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in snap.items() if k in keep},
        "change_pct": {
            "1w": change(5),
            "1m": change(21),
            "3m": change(63),
            "6m": change(126),
            "1y": change(250),
        },
        "high_52w": round(float(raw["high"].tail(250).max()), 3),
        "low_52w": round(float(raw["low"].tail(250).min()), 3),
        "avg_daily_value_20d": round(float((raw["close"] * raw["volume"]).tail(20).mean()), 0)
        if not pd.isna((raw["close"] * raw["volume"]).tail(20).mean())
        else None,
    }


def events_context(session: Session, stock: Stock, today: date) -> list[dict]:
    return [
        {"date": e.date.isoformat(), "kind": e.kind, "title": e.title, "binary": e.binary}
        for e in upcoming_events(session, stock.id, today, days=365)
    ]


def _review_brief(review: AIReview | None) -> dict | None:
    if review is None or not review.output:
        return None
    out = review.output
    return {
        "date": review.created_at.date().isoformat(),
        "score": review.score,
        "summary": review.summary,
        "thesis": out.get("thesis"),
        "risks": out.get("risks"),
    }
