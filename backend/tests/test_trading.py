from datetime import date

import pytest
from sqlalchemy import select

from boursy.appconfig import AppSettings, save_app_settings
from boursy.db.models import AIReview, EquitySnapshot, Position, Proposal, Trade
from boursy.db.session import init_db, new_session
from boursy.scheduler.jobs import run_trading
from boursy.trading.engine import run_day
from boursy.trading.portfolio import ensure_portfolios, get_portfolio, valuation
from boursy.universe.seed import make_stock
from tests.helpers import add_bar, store_bars, uptrend_with_pullback

D0 = date(2026, 11, 10)  # Tuesday: buy setup on the close
D1 = date(2026, 11, 11)
D2 = date(2026, 11, 12)


@pytest.fixture
def session(tmp_path):
    init_db(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    s = new_session()
    yield s
    s.close()


def paper_setup(session, capital=10_000.0, **overrides):
    cfg = AppSettings.model_validate({"portfolios": {"paper_capital": capital}, **overrides})
    save_app_settings(session, cfg)
    stock = make_stock("SAN.PA", "Sanofi", "FR", "core")
    session.add(stock)
    session.commit()
    store_bars(session, stock, uptrend_with_pullback(D0))
    pf = ensure_portfolios(session, cfg, D0)[0]
    return cfg, stock, pf


def test_paper_buy_fill_then_stop(session):
    cfg, stock, pf = paper_setup(session)
    report = run_day(session, pf, cfg, D0)
    assert len(report.proposals) == 1
    prop = report.proposals[0]
    assert (prop.side, prop.rule, prop.status, prop.ai_status) == ("buy", "pullback", "pending", "not_used")
    assert prop.valid_until == D1
    assert prop.stop_price < prop.limit_price
    assert prop.qty > 0 and prop.risk_eur <= 0.02 * 10_000 + 0.01

    # Next session opens below the limit: filled at the open.
    limit = prop.limit_price
    add_bar(session, stock, D1, limit - 0.5, limit + 1, limit - 1, limit + 0.5)
    report = run_day(session, pf, cfg, D1)
    assert report.fills and report.fills[0].startswith("bought")
    session.refresh(prop)
    assert prop.status == "executed"
    pos = session.scalar(select(Position).where(Position.portfolio_id == pf.id))
    assert pos.status == "open" and pos.qty == prop.qty and pos.avg_price == pytest.approx(limit - 0.5)
    fee = cfg.fees.fee(prop.qty * (limit - 0.5))
    assert pf.cash == pytest.approx(10_000 - prop.qty * (limit - 0.5) - fee)

    # The session after gaps below the stop: the resting stop order fills at the open.
    stop = pos.stop
    add_bar(session, stock, D2, stop - 2, stop - 1, stop - 3, stop - 2.5)
    report = run_day(session, pf, cfg, D2)
    session.refresh(pos)
    assert pos.status == "closed" and pos.exit_reason == "stop_loss"
    sell = session.scalar(select(Trade).where(Trade.side == "sell"))
    assert sell.price == pytest.approx(stop - 2) and sell.realized_pnl_eur < 0
    assert pf.cash == pytest.approx(valuation(session, pf).value)
    # Re-entry cooldown and snapshots for the three days.
    assert session.scalar(select(Proposal).where(Proposal.created_on == D2, Proposal.side == "buy")) is None
    assert len(session.scalars(select(EquitySnapshot)).all()) == 3


def test_paper_unfilled_buy_expires(session):
    cfg, stock, pf = paper_setup(session)
    prop = run_day(session, pf, cfg, D0).proposals[0]
    high = prop.limit_price + 5
    add_bar(session, stock, D1, high, high + 1, high - 1, high)  # never trades down to the limit
    report = run_day(session, pf, cfg, D1)
    session.refresh(prop)
    assert prop.status == "expired" and report.expired == 1
    assert pf.cash == 10_000


def test_kill_switch_blocks_buys(session):
    cfg, stock, pf = paper_setup(session)
    pf.peak_value = 20_000  # value 10 000 is 50 % below the peak
    session.commit()
    report = run_day(session, pf, cfg, D0)
    assert report.kill_switch_triggered and pf.kill_switch
    assert report.proposals == []


def test_binary_event_blocks_growth_buy(session):
    from boursy.db.models import StockEvent

    cfg, stock, pf = paper_setup(session)
    stock.bucket = "growth"
    session.add(StockEvent(stock_id=stock.id, date=D2, kind="trial", title="Phase 3 readout", binary=True))
    session.commit()
    report = run_day(session, pf, cfg, D0)
    assert report.proposals == []
    assert "Phase 3" in report.skipped["SAN.PA"]


class FakeAnalyst:
    enabled = True

    def __init__(self, session, verdict="confirm", score=7.5, fail=False):
        self.session, self.verdict, self.score, self.fail = session, verdict, score, fail
        self.calls = 0

    def review_signal(self, session, stock, reasons, today):
        self.calls += 1
        if self.fail:
            return None
        r = AIReview(
            stock_id=stock.id,
            task="signal_review",
            backend="api",
            model="m",
            score=self.score,
            verdict=self.verdict,
            summary="checked",
        )
        session.add(r)
        session.flush()
        return r


def test_ai_confirm_veto_and_unavailable(session):
    cfg, stock, pf = paper_setup(session)
    report = run_day(session, pf, cfg, D0, FakeAnalyst(session, "veto", 3))
    assert report.proposals == [] and "AI veto" in report.skipped["SAN.PA"]

    report = run_day(session, pf, cfg, D0, FakeAnalyst(session, "confirm", 7.5))
    assert report.proposals[0].ai_status == "confirmed"
    assert any("AI score 7.5" in r for r in report.proposals[0].reasons)

    session.delete(report.proposals[0])
    session.commit()
    report = run_day(session, pf, cfg, D0, FakeAnalyst(session, fail=True))
    assert report.proposals[0].ai_status == "unavailable"


def test_live_workflow_through_the_api(auth_client, settings):
    from boursy.db.models import Stock

    s = new_session()
    stock = s.scalar(select(Stock).where(Stock.symbol == "SAN.PA"))
    store_bars(s, stock, uptrend_with_pullback(D0))
    r = auth_client.get("/api/settings")
    cfg = r.json()["settings"]
    cfg["portfolios"].update({"paper_enabled": False, "live_enabled": True, "live_capital": 10_000})
    assert auth_client.put("/api/settings", json=cfg).status_code == 200

    msg = run_trading(settings, D0)
    assert "live" in msg
    props = auth_client.get("/api/proposals?mode=live&status=pending").json()
    assert len(props) == 1
    p = props[0]
    assert p["side"] == "buy" and p["symbol"] == "SAN.PA"
    detail = auth_client.get(f"/api/proposals/{p['id']}").json()
    assert "After the buy, place a stop order" in detail["note"]

    # Partial fill confirmed by the user.
    qty = max(1, p["qty"] - 1)
    r = auth_client.post(
        f"/api/proposals/{p['id']}/fill",
        json={"qty": qty, "price": p["limit_price"], "fees": 4.5, "date": D1.isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert auth_client.post(f"/api/proposals/{p['id']}/reject", json={}).status_code == 409

    ov = auth_client.get("/api/portfolios/live").json()
    assert len(ov["positions"]) == 1 and ov["positions"][0]["qty"] == qty
    assert ov["cash"] == pytest.approx(10_000 - qty * p["limit_price"] - 4.5)

    # Manual sell of one share, deposit, journal.
    r = auth_client.post(
        "/api/portfolios/live/trades",
        json={
            "symbol": "SAN.PA",
            "side": "sell",
            "qty": 1,
            "price": p["limit_price"] + 2,
            "fees": 1,
            "date": D2.isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    assert (
        auth_client.post("/api/portfolios/live/cash", json={"amount": 500, "note": "top-up"}).status_code
        == 201
    )
    journal = auth_client.get("/api/portfolios/live/trades").json()
    assert [t["side"] for t in journal] == ["sell", "buy"]
    assert journal[0]["realized_pnl_eur"] is not None
    csv_text = auth_client.get("/api/portfolios/live/trades.csv").text
    assert csv_text.startswith("date;symbol") and "SAN.PA" in csv_text
    assert auth_client.get("/api/portfolios/live").json()["invested"] == 10_500

    # Stop edit and kill-switch reset.
    pos_id = auth_client.get("/api/portfolios/live").json()["positions"][0]["id"]
    assert (
        auth_client.patch(f"/api/portfolios/live/positions/{pos_id}", json={"stop": 100}).json()["stop"]
        == 100
    )
    assert auth_client.post("/api/portfolios/live/kill-switch/reset").json()["kill_switch"] is False

    # Reset needs the confirmation word.
    assert auth_client.post("/api/portfolios/live/reset", json={"confirm": "nope"}).status_code == 422
    s.close()


def test_reject_and_watchlist_research(auth_client, settings):
    from boursy.db.models import Stock

    s = new_session()
    stock = s.scalar(select(Stock).where(Stock.symbol == "SAN.PA"))
    store_bars(s, stock, uptrend_with_pullback(D0))
    run_trading(settings, D0)  # paper portfolio, enabled by default
    p = auth_client.get("/api/proposals?mode=paper").json()[0]
    r = auth_client.post(f"/api/proposals/{p['id']}/reject", json={"reason": "not convinced"})
    assert r.json()["status"] == "rejected" and "not convinced" in r.json()["note"]
    san = next(x for x in auth_client.get("/api/stocks").json() if x["symbol"] == "SAN.PA")
    assert san["last_signal"]["side"] == "buy" and san["trend"] == "up"
    s.close()
    pf = get_portfolio(new_session(), "paper")
    assert pf is not None
