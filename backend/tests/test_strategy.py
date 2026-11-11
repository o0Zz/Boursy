from datetime import date

import pandas as pd
import pytest

from boursy.appconfig import FEE_PRESETS, AppSettings, FeeModel, RiskParams, StrategyParams
from boursy.indicators.core import compute_all
from boursy.strategy.rules import (
    PositionState,
    evaluate_position,
    fill_buy,
    fill_sell,
    fill_stop,
    initial_stop,
    kill_switch_hit,
    size_buy,
)
from boursy.strategy.signals import add_signals, buy_reasons
from tests.helpers import uptrend_with_pullback

SP = StrategyParams()
RP = RiskParams()
BOURSO = FEE_PRESETS["boursobank_decouverte"]


@pytest.mark.parametrize(
    ("value", "fee"),
    [
        (200, 1.0),  # 1.99 capped at 0.5 % (PEA legal cap)
        (450, 1.99),  # under the cap
        (2000, 10.0),  # 0.6 % = 12, capped at 0.5 % = 10
        (0, 0.0),
    ],
)
def test_boursobank_fees(value, fee):
    assert BOURSO.fee(value) == fee


def test_other_presets():
    assert FEE_PRESETS["trade_republic"].fee(5000) == 1.0
    assert FEE_PRESETS["bourse_direct"].fee(800) == 1.90
    assert FEE_PRESETS["bourse_direct"].fee(10_000) == 9.0  # 0.09 %


def test_settings_defaults_and_partial_json():
    cfg = AppSettings.model_validate({"risk": {"max_positions": 4}})
    assert cfg.risk.max_positions == 4
    assert cfg.risk.max_positions_small == 2
    assert cfg.strategy.rsi_pullback == 45
    assert cfg.fees.preset == "boursobank_decouverte"


def test_initial_stop_uses_atr_but_caps_distance():
    assert initial_stop(100, 2, "core", SP) == 94  # 100 - 3 x 2
    assert initial_stop(100, 5, "core", SP) == 90  # capped at -10 %
    assert initial_stop(100, 5, "growth", SP) == 85  # capped at -15 %
    assert initial_stop(100, None, "growth", SP) == 85


def test_buy_setup_on_pullback_bounce():
    df = add_signals(compute_all(uptrend_with_pullback(date(2026, 11, 10))), SP)
    last = df.iloc[-1]
    assert last["trend_ok"] and last["pullback"] and last["volume_ok"] and last["buy_setup"]
    assert not df["buy_setup"].iloc[-2]
    reasons = buy_reasons(last, SP)
    assert reasons[0].startswith("Uptrend") and any("Pullback" in r for r in reasons)


def test_momentum_cross_requires_positive_macd():
    idx = pd.RangeIndex(4)
    frame = pd.DataFrame(
        {
            "close": [10, 10, 10, 10],
            "ema20": 9,
            "sma50": 9,
            "sma200": 8,
            "rsi14": 55,
            "macd": [0.1, 0.1, 0.3, -0.2],
            "macd_signal": [0.2, 0.2, 0.2, -0.1],
            "volume": 100,
            "vol_avg20": 100,
        },
        index=idx,
    )
    out = add_signals(frame, SP)
    assert list(out["momentum"]) == [False, False, True, False]


def state(entry=100.0, stop=94.0, highest=100.0, bars=1, half=False):
    return PositionState(entry, stop, stop, highest, bars, half)


def test_stop_loss_and_priority_of_full_exits():
    ev = evaluate_position(state(), 93.5, 2.0, {"exhaustion": True}, "core", SP)
    assert ev.exit.rule == "stop_loss" and ev.exit.fraction == 1
    assert {e.rule for e in ev.exits} == {"stop_loss", "exhaustion"}


def test_trailing_stop_starts_after_gain_of_1_5_r():
    # Initial risk 6 -> trailing starts at +9.
    ev = evaluate_position(state(), 108.0, 2.0, {}, "core", SP)
    assert ev.stop == 94.0
    ev = evaluate_position(state(), 110.0, 2.0, {}, "core", SP)
    assert ev.stop == pytest.approx(110 - 3.5 * 2)
    assert ev.highest_close == 110
    # The stop never moves down.
    ev2 = evaluate_position(state(stop=104, highest=112), 109.0, 4.0, {}, "core", SP)
    assert ev2.stop == 104


def test_time_stop_and_half_exits():
    ev = evaluate_position(state(bars=130), 101.0, 2.0, {}, "core", SP)
    assert ev.exit.rule == "time_stop"
    ev = evaluate_position(state(), 101.0, 2.0, {}, "growth", SP, binary_event_in_days=1)
    assert ev.exit.rule == "event_protection" and ev.exit.fraction == 0.5
    ev = evaluate_position(
        state(half=True), 101.0, 2.0, {"exhaustion": True}, "growth", SP, binary_event_in_days=1
    )
    assert ev.exit is None
    ev = evaluate_position(state(), 101.0, 2.0, {}, "core", SP, thesis_break="failed trial")
    assert ev.exit.rule == "thesis_break"


def test_sizing_small_account():
    # 200 EUR account, core stock at 10 EUR, stop 9: risk 2 % = 4 EUR -> 4 shares.
    s = size_buy(200, 200, "core", 10, 9, 1.0, BOURSO, RP)
    assert s.qty == 4 and s.risk_eur == 4 and s.fees == 0.2


def test_sizing_weight_cap_large_account():
    # 10 000 EUR, growth max 12 % = 1200 EUR -> 12 shares at 100 even though risk allows more.
    s = size_buy(10_000, 10_000, "growth", 100, 99, 1.0, BOURSO, RP)
    assert s.qty == 12


def test_sizing_refusals():
    s = size_buy(200, 200, "core", 500, 450, 1.0, BOURSO, RP)
    assert s.qty == 0 and "one share" in s.reason
    s = size_buy(200, 5, "core", 10, 9, 1.0, BOURSO, RP)
    assert s.qty == 0 and "cash" in s.reason
    expensive = FeeModel(preset="x", tiers=[], pct_above=0.01, cap_pct=None)
    s = size_buy(10_000, 10_000, "core", 10, 9, 1.0, expensive, RP)
    assert s.qty == 0 and "Round-trip fees" in s.reason


def test_dkk_conversion_in_sizing():
    s = size_buy(10_000, 10_000, "core", 700, 650, 1 / 7.46, BOURSO, RP)
    assert s.order_value == pytest.approx(s.qty * 700 / 7.46, abs=0.01)


def test_kill_switch():
    assert not kill_switch_hit(81, 100, RP)
    assert kill_switch_hit(80, 100, RP)


def test_fills():
    assert fill_buy(10, 9.8, 9.5) == 9.8
    assert fill_buy(10, 10.2, 9.9) == 10
    assert fill_buy(10, 10.2, 10.1) is None
    assert fill_sell(10, 10.3, 10.5) == 10.3
    assert fill_sell(10, 9.8, 10.1) == 10
    assert fill_sell(10, 9.8, 9.9) is None
    assert fill_stop(9, 8.5, 8.2) == 8.5
    assert fill_stop(9, 9.5, 8.9) == 9
    assert fill_stop(9, 9.5, 9.1) is None
