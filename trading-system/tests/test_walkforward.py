"""워크포워드 검증 — 과거에 맞춘 답을 걸러내는가."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.config import BacktestKrConfig, ScannerBConfig
from src.indicators import atr, atr_pct
from src.walkforward import evaluate_setting, make_splits, report
from tests.helpers import make_daily, rising

SB = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5)
DATES = pd.bdate_range("2021-01-04", periods=400)


def stock(seed=0, vol=0.02):
    rng = np.random.default_rng(seed)
    close = 30_000 * np.exp(np.cumsum(rng.normal(0.0008, vol, len(DATES))))
    opens = np.concatenate([[close[0]], close[:-1]])
    # 종가가 고가 근처여야 조건 4(신고가 갱신)가 통과합니다.
    # 변동폭은 저가 쪽으로 벌려 ATR 이 달라지게 합니다.
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(close * 1.002, opens),
            "low": np.minimum(close * (1 - vol * 2), opens),
            "close": close,
            "volume": np.full(len(DATES), 500_000.0),
        },
        index=DATES,
    )


# ── 구간 나누기 ──


def test_splits_do_not_overlap():
    train, test = make_splits(DATES, 0.6)
    assert train.end < test.start, "학습 구간과 검증 구간이 겹치면 안 됩니다"


def test_splits_keep_time_order():
    """섞으면 안 됩니다. 미래로 과거를 맞추는 셈이 됩니다."""
    train, test = make_splits(DATES, 0.6)
    assert train.start == DATES[0]
    assert test.end == DATES[-1]
    assert train.start < train.end < test.start < test.end


def test_split_ratio_is_respected():
    train, test = make_splits(DATES, 0.8)
    train_days = len(DATES[(DATES >= train.start) & (DATES <= train.end)])
    assert 0.75 < train_days / len(DATES) < 0.85


def test_too_short_data_raises():
    with pytest.raises(ValueError, match="너무 짧습니다"):
        make_splits(DATES[:50], 0.6)


# ── 판정 ──


def test_setting_is_evaluated_on_both_windows():
    frames = {f"{i:06d}": stock(seed=i) for i in range(6)}
    splits = make_splits(DATES, 0.6)
    r = evaluate_setting("테스트", frames, BacktestKrConfig(), SB, splits)
    assert r.train_trades > 0
    assert r.test_trades > 0


def test_a_setting_that_collapses_out_of_sample_is_not_marked():
    """검증 구간에서 무너지면 통과로 표시하면 안 됩니다."""
    from src.walkforward import WalkForwardResult

    r = WalkForwardResult(
        setting="과최적화",
        train={"profit_factor": 3.0, "win_rate_pct": 60.0},
        test={"profit_factor": 0.4, "win_rate_pct": 20.0},
        train_trades=200, test_trades=120,
    )
    assert r.decay < -50
    assert not r.survives


def test_a_stable_setting_is_marked():
    from src.walkforward import WalkForwardResult

    r = WalkForwardResult(
        setting="안정",
        train={"profit_factor": 1.6, "win_rate_pct": 40.0},
        test={"profit_factor": 1.4, "win_rate_pct": 38.0},
        train_trades=200, test_trades=150,
    )
    assert r.survives


def test_too_few_test_trades_is_not_marked():
    """검증 매매가 적으면 좋아 보여도 판단할 수 없습니다."""
    from src.walkforward import WalkForwardResult

    r = WalkForwardResult(
        setting="표본부족",
        train={"profit_factor": 1.5}, test={"profit_factor": 5.0},
        train_trades=100, test_trades=8,
    )
    assert not r.survives


def test_report_warns_the_test_window_is_single_use():
    from src.walkforward import WalkForwardResult

    r = WalkForwardResult("x", {"profit_factor": 1.2, "win_rate_pct": 40.0},
                          {"profit_factor": 1.1, "win_rate_pct": 39.0}, 100, 80)
    text = report([r], make_splits(DATES, 0.6))
    assert "한 번만 쓸 수 있는 카드" in text
    assert "과거에만 맞춘 답" in text


# ── ATR ──


def test_atr_is_larger_for_a_wilder_stock():
    calm = make_daily(rising(60), highs=rising(60) * 1.005, lows=rising(60) * 0.995)
    wild = make_daily(rising(60), highs=rising(60) * 1.06, lows=rising(60) * 0.94)
    assert atr_pct(wild).iloc[-1] > atr_pct(calm).iloc[-1] * 3


def test_atr_counts_the_gap():
    """전날 종가에서 훌쩍 뛴 날은 고가-저가가 좁아도 실제 움직임이 큽니다."""
    closes = [10_000] * 10 + [13_000] * 10
    highs = [10_050] * 10 + [13_050] * 10
    lows = [9_950] * 10 + [12_950] * 10
    frame = make_daily(closes, highs=highs, lows=lows)
    values = atr(frame, window=3)
    assert values.iloc[10] > 1_000, "갭을 반영하지 못했습니다"


def test_atr_rejects_bad_window():
    with pytest.raises(ValueError):
        atr(make_daily(rising(30)), window=0)


def test_volatility_stop_widens_for_wild_stocks():
    """변동성 손절을 켜면 출렁이는 종목의 손절이 넓어집니다."""
    from src.backtest import run

    wild = stock(seed=3, vol=0.05)
    fixed = run("W", wild, BacktestKrConfig(stop_loss_pct=3.0, atr_stop_mult=0.0), SB)
    banded = run("W", wild, BacktestKrConfig(stop_loss_pct=3.0, atr_stop_mult=2.0), SB)

    if not fixed or not banded:
        pytest.skip("이 데이터에서는 매매가 없습니다")
    fixed_one_day = sum(1 for t in fixed if t.hold_days <= 1)
    banded_one_day = sum(1 for t in banded if t.hold_days <= 1)
    assert banded_one_day <= fixed_one_day, (
        "손절을 넓혔는데 진입 당일 청산이 줄지 않았습니다"
    )


def test_volatility_stop_is_capped():
    """변동성이 아무리 커도 손절이 무한정 벌어지면 안 됩니다."""
    from src.backtest import run

    crazy = stock(seed=4, vol=0.15)
    cfg = replace(BacktestKrConfig(), atr_stop_mult=5.0, atr_stop_cap_pct=10.0)
    trades = run("C", crazy, cfg, SB)
    for t in trades:
        loss = (t.exit_price - t.entry_price) / t.entry_price * 100
        assert loss > -25, f"손절 상한을 넘었습니다: {loss:.1f}%"
