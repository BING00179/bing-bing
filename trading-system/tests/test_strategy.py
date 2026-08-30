import pytest

from src.config import ScannerBConfig
from src.strategy import evaluate, signals_from_daily
from tests.helpers import make_daily, rising

CFG = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5)


def test_evaluate_passes_when_all_conditions_met():
    daily = make_daily(rising(60))          # 어제 종가 159, 어제 고가 159
    result = evaluate(
        ticker="TEST",
        daily=daily,
        price=165.0,                        # 전날 고가·프리마켓 고가·오늘 고가 위
        today_high=165.0,
        premarket_high=162.0,
        cfg=CFG,
    )
    assert result.passed
    assert result.failed_conditions == []


def test_evaluate_fails_when_below_prev_high():
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=100.0, today_high=100.0,
                      premarket_high=99.0, cfg=CFG)
    assert not result.passed
    assert "1_전날고가돌파" in result.failed_conditions


def test_evaluate_fails_when_below_premarket_high():
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=165.0, today_high=165.0,
                      premarket_high=170.0, cfg=CFG)
    assert not result.passed
    assert "3_프리마켓고가돌파" in result.failed_conditions


def test_missing_premarket_high_is_not_treated_as_pass():
    """프리마켓 데이터가 없으면 '판정 불가'이지 '통과'가 아닙니다."""
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=165.0, today_high=165.0,
                      premarket_high=None, cfg=CFG)
    assert result.c3_above_premarket_high is None
    assert not result.passed


def test_premarket_condition_can_be_disabled():
    cfg = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5,
                         require_premarket_high=False)
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=165.0, today_high=165.0,
                      premarket_high=None, cfg=cfg)
    assert result.c3_above_premarket_high is True
    assert result.passed


def test_evaluate_fails_in_downtrend():
    daily = make_daily(rising(60, start=200.0, step=-1.0))
    result = evaluate("TEST", daily, price=500.0, today_high=500.0,
                      premarket_high=400.0, cfg=CFG)
    assert not result.passed
    assert "5_상승추세정렬" in result.failed_conditions


def test_evaluate_requires_enough_history():
    daily = make_daily(rising(10))
    with pytest.raises(ValueError, match="일봉"):
        evaluate("TEST", daily, price=120.0, today_high=120.0,
                 premarket_high=110.0, cfg=CFG)


def test_signals_fire_in_uptrend():
    daily = make_daily(rising(60))
    sig = signals_from_daily(daily, CFG)
    assert sig["signal"].iloc[-1]
    assert sig.loc[:, ["c1", "c2", "c4", "c5"]].iloc[-1].all()


def test_signals_silent_in_downtrend():
    daily = make_daily(rising(60, start=200.0, step=-1.0))
    sig = signals_from_daily(daily, CFG)
    assert not sig["signal"].any()


def test_signals_never_use_future_data():
    """뒤쪽 데이터를 잘라내도 앞부분 신호는 그대로여야 합니다."""
    daily = make_daily(rising(80))
    full = signals_from_daily(daily, CFG)
    truncated = signals_from_daily(daily.iloc[:60], CFG)
    assert full["signal"].iloc[:60].tolist() == truncated["signal"].tolist()


def test_signal_requires_close_near_the_day_high():
    """종가가 그날 고가에서 멀면 조건 4가 깨집니다."""
    closes = rising(60)
    highs = closes * 1.05                   # 고가보다 5% 아래에서 마감
    daily = make_daily(closes, highs=highs)
    sig = signals_from_daily(daily, CFG)
    assert not sig["c4"].any()
    assert not sig["signal"].any()


def test_signals_reject_frame_without_required_columns():
    daily = make_daily(rising(60)).drop(columns=["volume"])
    with pytest.raises(ValueError, match="volume"):
        signals_from_daily(daily, CFG)


def test_condition4_allows_a_small_pullback_from_the_session_high():
    """'오늘 고가'는 현재가가 갱신하는 값이라 완전 일치를 요구하면 안 됩니다."""
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=164.8, today_high=165.0,
                      premarket_high=162.0, cfg=CFG)   # 고가에서 0.12% 아래
    assert result.c4_above_today_high
    assert result.passed


def test_condition4_rejects_a_deep_pullback():
    daily = make_daily(rising(60))
    result = evaluate("TEST", daily, price=161.0, today_high=170.0,
                      premarket_high=160.0, cfg=CFG)   # 고가에서 5% 아래
    assert not result.c4_above_today_high
    assert "4_오늘고가돌파" in result.failed_conditions
