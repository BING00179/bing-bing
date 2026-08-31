"""요인 검정 — 예측력이 있는 요인과 없는 요인을 구분하는가."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors import compare, evaluate

DATES = pd.bdate_range("2023-01-02", periods=24, freq="ME")
CODES = [f"{i:06d}" for i in range(100)]


def make_data(seed=0, signal_strength=0.0):
    """signal_strength 가 0 이면 요인에 예측력이 없습니다."""
    rng = np.random.default_rng(seed)
    factor = pd.DataFrame(
        rng.normal(0, 1, (len(DATES), len(CODES))), index=DATES, columns=CODES
    )

    prices = pd.DataFrame(index=DATES, columns=CODES, dtype=float)
    prices.iloc[0] = 10_000.0
    for i in range(1, len(DATES)):
        noise = rng.normal(0, 0.08, len(CODES))
        edge = factor.iloc[i - 1].to_numpy() * signal_strength
        prices.iloc[i] = prices.iloc[i - 1].to_numpy() * (1 + noise + edge)
    return factor, prices


def test_a_useless_factor_shows_no_spread():
    """예측력이 없는 요인은 스프레드가 0 근처여야 합니다."""
    factor, prices = make_data(seed=1, signal_strength=0.0)
    r = evaluate("무작위", factor, prices, higher_is_better=True)
    assert abs(r.t_stat) < 2.5, f"우연한 요인에 t={r.t_stat:.2f} 가 나왔습니다"


def test_a_real_factor_is_detected():
    """예측력이 있는 요인은 스프레드와 t값이 뚜렷해야 합니다."""
    factor, prices = make_data(seed=2, signal_strength=0.05)
    r = evaluate("진짜신호", factor, prices, higher_is_better=True)
    assert r.mean_spread > 0
    assert r.t_stat > 2, f"진짜 신호인데 t={r.t_stat:.2f} 밖에 안 됩니다"
    assert r.monotonic, "예측력이 있으면 계단 모양이어야 합니다"


def test_direction_is_respected():
    """'낮을수록 좋다' 요인은 방향을 뒤집어 계산해야 합니다."""
    factor, prices = make_data(seed=3, signal_strength=0.05)
    high = evaluate("높을수록", factor, prices, higher_is_better=True)
    low = evaluate("낮을수록", factor, prices, higher_is_better=False)
    assert high.mean_spread > 0
    assert low.mean_spread < 0, "방향을 뒤집으면 부호도 뒤집혀야 합니다"


def test_quantiles_are_ordered_best_first():
    factor, prices = make_data(seed=4, signal_strength=0.06)
    r = evaluate("테스트", factor, prices, higher_is_better=True)
    means = r.mean_by_quantile
    assert means["Q1"] > means["Q5"], "Q1 이 유리한 쪽이어야 합니다"


def test_thin_periods_are_skipped():
    """종목이 모자란 회차는 건너뜁니다."""
    factor, prices = make_data(seed=5)
    factor.iloc[3, 5:] = np.nan          # 그 회차엔 5종목만 남음
    r = evaluate("테스트", factor, prices, higher_is_better=True, min_names=30)
    assert DATES[3] not in r.quantile_returns.index


def test_too_few_dates_raises():
    factor, prices = make_data(seed=6)
    with pytest.raises(ValueError, match="2개 이상"):
        evaluate("테스트", factor.iloc[:1], prices.iloc[:1], higher_is_better=True)


def test_no_lookahead_factor_uses_only_past():
    """요인은 그 시점 값으로, 수익률은 그 이후 구간으로 계산됩니다."""
    factor, prices = make_data(seed=7, signal_strength=0.05)
    full = evaluate("테스트", factor, prices, higher_is_better=True)
    cut = evaluate("테스트", factor.iloc[:15], prices.iloc[:15], higher_is_better=True)
    # 앞부분 회차의 결과는 뒤 데이터를 잘라내도 같아야 합니다.
    common = cut.quantile_returns.index
    pd.testing.assert_frame_equal(
        full.quantile_returns.loc[common], cut.quantile_returns, check_exact=False
    )


def test_report_warns_about_multiple_testing():
    factor, prices = make_data(seed=8, signal_strength=0.05)
    r = evaluate("테스트", factor, prices, higher_is_better=True)
    text = compare([r])
    assert "우연히 좋아 보입니다" in text
    assert "거래비용" in text


def test_report_marks_only_strong_candidates():
    strong_f, strong_p = make_data(seed=9, signal_strength=0.06)
    weak_f, weak_p = make_data(seed=10, signal_strength=0.0)
    strong = evaluate("강한요인", strong_f, strong_p, higher_is_better=True)
    weak = evaluate("약한요인", weak_f, weak_p, higher_is_better=True)

    text = compare([weak, strong])
    strong_line = [l for l in text.splitlines() if "강한요인" in l][0]
    weak_line = [l for l in text.splitlines() if "약한요인" in l][0]
    assert strong_line.startswith("★")
    assert not weak_line.startswith("★")


def test_market_average_is_recorded():
    """전 종목 평균 수익률을 함께 남겨 데이터 이상을 잡습니다."""
    factor, prices = make_data(seed=11, signal_strength=0.03)
    r = evaluate("테스트", factor, prices, higher_is_better=True)
    assert not r.market.empty
    assert not r.looks_broken, "정상 데이터인데 이상으로 판정했습니다"


def test_absurd_returns_are_flagged():
    """전 종목이 매달 -40% 면 데이터를 의심해야 합니다."""
    factor, prices = make_data(seed=12)
    # 매 회차 -40% 가 되도록 가격을 깎습니다.
    for i in range(1, len(prices)):
        prices.iloc[i] = prices.iloc[i - 1] * 0.6

    r = evaluate("망가진데이터", factor, prices, higher_is_better=True)
    assert r.looks_broken, "상식 밖 수익률을 잡아내지 못했습니다"
    assert "가격 데이터를 먼저 확인" in r.as_report()
    assert "믿지 마세요" in compare([r])
