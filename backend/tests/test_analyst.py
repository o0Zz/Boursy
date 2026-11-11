import json
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from boursy.analyst.backends import (
    ApiBackend,
    BackendError,
    BackendResult,
    SubscriptionBackend,
    estimate_cost,
)
from boursy.analyst.prompts import SCHEMAS
from boursy.analyst.service import Analyst
from boursy.appconfig import AIParams, NotifyParams
from boursy.config import Settings
from boursy.db.models import AIReview, Notification, StockEvent
from boursy.db.session import init_db, new_session
from boursy.notifier import Notifier
from boursy.universe.seed import make_stock
from tests.helpers import store_bars, uptrend_with_pullback

TODAY = date(2026, 11, 10)


@pytest.fixture
def session(tmp_path):
    init_db(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    s = new_session()
    stock = make_stock("MEDCL.PA", "Medincell", "FR", "growth")
    s.add(stock)
    s.commit()
    store_bars(s, stock, uptrend_with_pullback(TODAY))
    yield s
    s.close()


class FakeBackend:
    name = "api"

    def __init__(self, output=None, error=None):
        self.output, self.error, self.prompts = output, error, []

    def run(self, system, prompt, schema, model, effort, web_search_max_uses):
        self.prompts.append((system, prompt, schema, model, effort))
        if self.error:
            raise BackendError(self.error)
        return BackendResult(self.output, model, 1000, 200, web_searches=2, cost_usd=0.05)


def analyst(tmp_path, backend, **params):
    settings = Settings(data_dir=tmp_path, anthropic_api_key="sk-test", claude_code_oauth_token="tok")
    return Analyst(settings, AIParams(backend="api", **params), api_backend=backend)


SCREEN = {
    "score": 7.2,
    "bucket": "growth",
    "summary": "Solid royalty growth.",
    "thesis": "Long-acting injectables platform.",
    "risks": ["dilution"],
    "events": [
        {"date": "2026-12-03", "kind": "earnings", "title": "H1 results", "binary": True},
        {"date": "2019-01-01", "kind": "other", "title": "too old", "binary": False},
        {"date": "not a date", "kind": "other", "title": "bad", "binary": False},
    ],
    "confidence": "medium",
}


def test_screening_review_is_stored_with_events(session, tmp_path):
    fake = FakeBackend(SCREEN)
    a = analyst(tmp_path, fake)
    from boursy.db.models import Stock

    stock = session.scalar(select(Stock))
    review = a.screen(session, stock, TODAY)
    assert review.ok and review.score == 7.2 and review.cost_usd == 0.05 and review.web_searches == 2
    events = session.scalars(select(StockEvent)).all()
    assert [(e.date, e.kind, e.source) for e in events] == [(date(2026, 12, 3), "earnings", "ai")]
    system, prompt, schema, model, effort = fake.prompts[0]
    assert "Medincell" in prompt and "change_pct" in prompt and schema == SCHEMAS["screening"]
    assert (model, effort) == ("claude-opus-5-5", "high")
    # Same event again is not duplicated.
    a.screen(session, stock, TODAY)
    assert len(session.scalars(select(StockEvent)).all()) == 1


def test_budget_cap_blocks_calls(session, tmp_path):
    from boursy.db.models import Stock

    a = analyst(tmp_path, FakeBackend(SCREEN), monthly_budget_usd=0.06)
    stock = session.scalar(select(Stock))
    assert a.screen(session, stock, TODAY) is not None  # 0.05 spent
    assert a.screen(session, stock, TODAY) is not None  # 0.10 spent, over the cap now
    assert a.screen(session, stock, TODAY) is None
    assert "budget" in a.status(session)["reason"]


def test_failed_call_is_logged(session, tmp_path):
    from boursy.db.models import Stock

    a = analyst(tmp_path, FakeBackend(error="overloaded"))
    assert a.screen(session, session.scalar(select(Stock)), TODAY) is None
    row = session.scalar(select(AIReview))
    assert not row.ok and row.error == "overloaded"


def test_signal_review_is_reused_the_same_day(session, tmp_path):
    from boursy.db.models import Stock

    fake = FakeBackend({"decision": "confirm", "score": 8, "summary": "ok", "risks": [], "events": []})
    a = analyst(tmp_path, fake)
    stock = session.scalar(select(Stock))
    r1 = a.review_signal(session, stock, ["Uptrend"], TODAY)
    r2 = a.review_signal(session, stock, ["Uptrend"], TODAY)
    assert r1.id == r2.id and len(fake.prompts) == 1 and r1.verdict == "confirm"


def test_turned_off(tmp_path):
    a = Analyst(Settings(data_dir=tmp_path), AIParams())
    assert not a.enabled


def test_cost_estimate():
    assert estimate_cost("claude-opus-5-5", 1_000_000, 100_000, 0, 0, 3) == pytest.approx(4 + 2 + 0.03)


# ---------------------------------------------------------------- API backend (SDK mocked)


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def response(stop, blocks, inp=100, out=50, searches=0):
    usage = SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=searches),
    )
    return SimpleNamespace(stop_reason=stop, content=blocks, usage=usage)


def text(t):
    return SimpleNamespace(type="text", text=t)


def test_api_backend_request_and_pause_turn():
    msgs = FakeMessages(
        [
            response("pause_turn", [SimpleNamespace(type="server_tool_use")], searches=3),
            response("end_turn", [text("Searching..."), text(json.dumps({"x": 1}))], searches=1),
        ]
    )
    backend = ApiBackend("k", client=SimpleNamespace(messages=msgs))
    result = backend.run("sys", "prompt", {"type": "object"}, "claude-opus-5-5", "medium", 5)
    assert result.output == {"x": 1} and result.web_searches == 4 and result.input_tokens == 200
    first = msgs.calls[0]
    assert first["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert first["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert len(msgs.calls[1]["messages"]) == 2  # resumed with the assistant turn


def test_api_backend_refusal():
    msgs = FakeMessages([response("refusal", [])])
    with pytest.raises(BackendError, match="declined"):
        ApiBackend("k", client=SimpleNamespace(messages=msgs)).run("s", "p", {}, "claude-opus-5-5", "low", 0)


# ---------------------------------------------------------------- subscription backend (CLI mocked)


def test_subscription_backend_env_and_parsing(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-leak")
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"], seen["env"] = cmd, kwargs["env"]
        out = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": {"status": "nothing", "summary": "quiet", "items": [], "events": []},
            "total_cost_usd": 0.12,
            "usage": {"input_tokens": 10, "output_tokens": 20, "server_tool_use": {"web_search_requests": 2}},
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    b = SubscriptionBackend("oauth-token", tmp_path / "home", runner=runner)
    r = b.run("sys", "prompt", SCHEMAS["news_check"], "claude-opus-5-5", "medium", 5)
    assert r.output["status"] == "nothing" and r.cost_is_estimate and r.web_searches == 2
    env = seen["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and "--bare" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "WebSearch,WebFetch"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMAS["news_check"]


def test_subscription_backend_errors(tmp_path):
    def limit(cmd, **kw):
        out = {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "limit"}
        return subprocess.CompletedProcess(cmd, 1, json.dumps(out), "")

    with pytest.raises(BackendError, match="error_max_turns"):
        SubscriptionBackend("t", tmp_path, runner=limit).run("s", "p", {}, "m", "low", 0)

    def garbage(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Invalid API key")

    with pytest.raises(BackendError, match="Invalid API key"):
        SubscriptionBackend("t", tmp_path, runner=garbage).run("s", "p", {}, "m", "low", 0)

    def missing(cmd, **kw):
        raise FileNotFoundError

    with pytest.raises(BackendError, match="not found"):
        SubscriptionBackend("t", tmp_path, runner=missing).run("s", "p", {}, "m", "low", 0)


# ---------------------------------------------------------------- notifier


def test_notifier_push_email_and_dedupe(session, tmp_path, monkeypatch):
    sent = {"push": [], "email": []}
    settings = Settings(
        data_dir=tmp_path,
        ntfy_topic="boursy-test",
        smtp_host="smtp.test",
        mail_to="me@test",
        public_url="https://b.test",
    )
    n = Notifier(settings, NotifyParams())
    monkeypatch.setattr(n, "_push", lambda title, body, prio, link: sent["push"].append((title, prio, link)))
    monkeypatch.setattr(n, "_email", lambda subject, body: sent["email"].append(subject))

    row = n.send(session, "proposal", "BUY 3 SAN.PA", "body", "/proposals?id=1", dedupe_key="p1")
    assert (row.push_status, row.email_status) == ("sent", "sent")
    assert sent["push"] == [("BUY 3 SAN.PA", "high", "https://b.test/proposals?id=1")]
    assert n.send(session, "proposal", "BUY 3 SAN.PA", "body", dedupe_key="p1") is None
    n.send(session, "expiring", "x", "y")  # push only
    assert len(sent["email"]) == 1 and len(sent["push"]) == 2

    def boom(*a):
        raise RuntimeError("ntfy down")

    monkeypatch.setattr(n, "_push", boom)
    row = n.send(session, "job_failure", "Job failed", "x")
    assert row.push_status == "failed" and "ntfy down" in row.error
    assert len(session.scalars(select(Notification)).all()) == 3
