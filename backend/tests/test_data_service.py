from datetime import date, timedelta

from sqlalchemy import func, select

from boursy.data.service import load_bars, refresh_stock, refresh_stocks
from boursy.db.models import DailyBar, Stock
from boursy.db.session import init_db, new_session
from boursy.timeutil import utcnow
from boursy.universe.seed import make_stock
from tests.conftest import FakeProvider

TODAY = date(2026, 11, 10)


def _setup(tmp_path):
    init_db(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    s = new_session()
    stock = make_stock("MEDCL.PA", "Medincell", "FR", "growth")
    s.add(stock)
    s.commit()
    return s, stock


def test_first_refresh_is_full(tmp_path):
    s, stock = _setup(tmp_path)
    p = FakeProvider()
    written = refresh_stock(s, stock, p, TODAY, history_years=1)
    assert written > 250
    assert p.calls[0][1] <= TODAY - timedelta(days=365)
    assert stock.last_full_refresh is not None
    df = load_bars(s, stock.id)
    assert df.index.is_monotonic_increasing
    assert df.index[-1] == TODAY


def test_second_refresh_is_incremental_and_idempotent(tmp_path):
    s, stock = _setup(tmp_path)
    p = FakeProvider()
    refresh_stock(s, stock, p, TODAY, history_years=1)
    count1 = s.scalar(select(func.count()).select_from(DailyBar))
    refresh_stock(s, stock, p, TODAY + timedelta(days=1), history_years=1)
    start = p.calls[1][1]
    assert start == TODAY - timedelta(days=10)
    count2 = s.scalar(select(func.count()).select_from(DailyBar))
    assert count2 == count1 + 1  # 2026-11-11 is a Wednesday


def test_stale_full_refresh_redownloads_history(tmp_path):
    s, stock = _setup(tmp_path)
    p = FakeProvider()
    refresh_stock(s, stock, p, TODAY, history_years=1)
    stock.last_full_refresh = utcnow() - timedelta(days=8)
    s.commit()
    refresh_stock(s, stock, p, TODAY, history_years=1, full_refresh_days=7)
    assert p.calls[1][1] <= TODAY - timedelta(days=365)


def test_refresh_stocks_records_errors(tmp_path):
    s, stock = _setup(tmp_path)
    other = make_stock("VLA.PA", "Valneva", "FR", "growth")
    s.add(other)
    s.commit()
    p = FakeProvider(fail={"VLA.PA"})
    summary = refresh_stocks(s, [stock, other], p, TODAY, history_years=1, pause_seconds=0)
    assert summary.ok == ["MEDCL.PA"]
    assert "VLA.PA" in summary.errors
    assert s.scalar(select(Stock).where(Stock.symbol == "VLA.PA")).last_error
