"""매매 기록 분석 — 이미 나온 결과에서 원인을 짚어내는가."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analyze import (
    by_exit_reason,
    by_hold_days,
    by_period,
    concentration,
    cost_weight,
    load,
    report,
    return_distribution,
)


def make_trades(n=300, seed=0, win_rate=0.3):
    rng = np.random.default_rng(seed)
    win = rng.random(n) < win_rate
    ret = np.where(win, rng.gamma(2, 4, n), -np.abs(rng.normal(3, 1, n)))
    hold = np.where(win, rng.integers(5, 20, n), rng.integers(1, 5, n))
    entry = pd.to_datetime("2023-01-02") + pd.to_timedelta(rng.integers(0, 700, n), "D")
    return pd.DataFrame({
        "ticker": [f"{rng.integers(0, 30):06d}" for _ in range(n)],
        "entry_date": entry,
        "exit_date": entry + pd.to_timedelta(hold, "D"),
        "pnl": ret * 100_000,
        "return_pct": ret,
        "exit_reason": np.where(win, "target", "stop"),
        "hold_days": hold,
    })


def test_exit_reason_separates_wins_and_losses():
    stats = by_exit_reason(make_trades())
    assert "stop" in stats.index and "target" in stats.index
    assert stats.loc["stop", "총손익"] < 0
    assert stats.loc["target", "총손익"] > 0


def test_hold_days_buckets_cover_every_trade():
    trades = make_trades()
    stats = by_hold_days(trades)
    assert stats["건수"].sum() == len(trades)


def test_concentration_shows_what_happens_without_the_best():
    """상위 종목을 빼면 결과가 어떻게 되는지 보여야 합니다."""
    trades = make_trades()
    conc = concentration(trades, top=5)
    assert conc["상위5_제외시_총손익"] < conc["총손익"]
    assert conc["하위5_제외시_총손익"] > conc["총손익"]


def test_a_single_stock_carrying_everything_is_visible():
    """한 종목이 전부를 만든 경우가 드러나야 합니다."""
    trades = make_trades(n=100, seed=3)
    trades.loc[:, "pnl"] = -10_000.0            # 전부 소액 손실
    trades.loc[0, ["ticker", "pnl"]] = ["999999", 5_000_000.0]

    conc = concentration(trades, top=1)
    assert conc["최고종목"] == "999999"
    assert conc["총손익"] > 0
    assert conc["상위1_제외시_총손익"] < 0, "그 종목을 빼면 손해여야 합니다"


def test_return_distribution_counts_all_trades():
    trades = make_trades()
    dist = return_distribution(trades)
    assert dist["건수"].sum() == len(trades)
    assert abs(dist["비중"].sum() - 100.0) < 1.0


def test_cost_weight_shows_gross_versus_net():
    trades = make_trades(n=500)
    cost = cost_weight(trades, cost_pct_round_trip=0.5)
    assert cost["매매건수"] == 500
    assert cost["비용_누적"] == pytest.approx(250.0)
    assert cost["비용차감전_누적수익률"] > cost["비용차감후_누적수익률"]


def test_period_breakdown_splits_by_quarter():
    stats = by_period(make_trades())
    assert len(stats) >= 4
    assert stats["건수"].sum() == 300


def test_report_warns_against_refitting():
    text = report(make_trades())
    assert "과거에만 맞는 답" in text
    assert "어디가 문제였나" in text


def test_load_accepts_code_column(tmp_path):
    """포트폴리오 결과는 컬럼 이름이 ticker 가 아니라 code 입니다."""
    trades = make_trades(n=50).rename(columns={"ticker": "code"})
    path = tmp_path / "t.csv"
    trades.to_csv(path, index=False)
    assert "ticker" in load(path).columns


def test_load_rejects_a_file_without_the_needed_columns(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="컬럼"):
        load(path)


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.csv")
