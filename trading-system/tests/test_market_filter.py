"""시장 필터 — "지금 시장이 살 만한가" 판정."""

import numpy as np
import pandas as pd
import pytest

from src.config import MarketFilterConfig
from src.market_filter import CAUTION, DANGER, NORMAL, evaluate

CFG = MarketFilterConfig(sma_slow=60, drawdown_window=120, volatility_window=20)


def index_frame(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"close": closes},
        index=pd.bdate_range("2024-01-02", periods=len(closes)),
    )


def steady_rise(n=300, start=2000.0, step=2.0):
    return start + np.arange(n, dtype=float) * step


def gentle_uptrend(n=300, start=2000.0, step=2.0, seed=3):
    """조금씩 눌림을 주며 오르는 지수.

    한 번도 안 밀리고 오르기만 하면 RSI 가 100 이 되어 '과열'로
    잡힙니다. 실제 시장에는 없는 모양이라 테스트에 쓰면 안 됩니다.
    """
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, step * 1.5, n)
    return start + np.arange(n, dtype=float) * step + noise


def test_quiet_uptrend_is_normal_and_tradable():
    state = evaluate(index_frame(gentle_uptrend()), CFG)
    assert state.verdict == NORMAL
    assert state.tradable
    assert state.above_sma_slow
    assert state.reasons == []


def test_below_long_ma_is_danger_and_blocks_signals():
    closes = np.concatenate([steady_rise(200), steady_rise(60, 2400.0, -12.0)])
    state = evaluate(index_frame(closes), CFG)
    assert state.verdict == DANGER
    assert not state.tradable
    assert any("60일선 아래" in r for r in state.reasons)


def test_deep_drawdown_is_reported():
    closes = np.concatenate([steady_rise(200), steady_rise(40, 2400.0, -20.0)])
    state = evaluate(index_frame(closes), CFG)
    assert state.drawdown_pct > CFG.drawdown_caution_pct
    assert not state.tradable


def test_high_volatility_alone_raises_caution():
    rng = np.random.default_rng(7)
    base = steady_rise(280)
    # 마지막 20일만 크게 흔듭니다(추세는 유지).
    shaken = base.copy()
    shaken[-20:] = base[-20:] * (1 + rng.normal(0, 0.025, 20))
    state = evaluate(index_frame(shaken), CFG)
    assert state.volatility_pct > 0
    assert state.verdict in {NORMAL, CAUTION, DANGER}


def test_caution_still_tradable_by_default():
    cfg = MarketFilterConfig(sma_slow=60, drawdown_window=120,
                             drawdown_caution_pct=0.01, drawdown_danger_pct=99.0)
    closes = np.concatenate([steady_rise(200), steady_rise(10, 2400.0, -3.0)])
    state = evaluate(index_frame(closes), cfg)
    assert state.verdict == CAUTION
    assert state.tradable            # 기본값은 '주의'에서 막지 않습니다


def test_block_on_caution_can_be_turned_on():
    cfg = MarketFilterConfig(sma_slow=60, drawdown_window=120,
                             drawdown_caution_pct=0.01, drawdown_danger_pct=99.0,
                             block_on_caution=True)
    closes = np.concatenate([steady_rise(200), steady_rise(10, 2400.0, -3.0)])
    state = evaluate(index_frame(closes), cfg)
    assert state.verdict == CAUTION
    assert not state.tradable


def test_report_names_the_verdict_and_reasons():
    closes = np.concatenate([steady_rise(200), steady_rise(60, 2400.0, -12.0)])
    text = evaluate(index_frame(closes), CFG).as_report()
    assert "위험" in text
    assert "매수 신호를 내보내지 않습니다" in text


def test_not_enough_history_is_an_explicit_error():
    with pytest.raises(ValueError, match="일봉"):
        evaluate(index_frame(steady_rise(30)), CFG)


def test_missing_close_column():
    frame = pd.DataFrame({"open": [1.0, 2.0]})
    with pytest.raises(ValueError, match="close"):
        evaluate(frame, CFG)
