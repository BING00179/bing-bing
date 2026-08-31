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


# ── 진입 당일 손절 원인 분석 ──


def _mixed_trades():
    """1일 손절 다수 + 오래 버틴 이익 소수. 실제 결과와 비슷한 모양."""
    rng = np.random.default_rng(5)
    same_day = pd.DataFrame({
        "ticker": [f"{i:06d}" for i in range(300)],
        "entry_date": pd.to_datetime("2023-01-02") + pd.to_timedelta(range(300), "D"),
        "pnl": -np.abs(rng.normal(300_000, 50_000, 300)),
        "return_pct": -np.abs(rng.normal(3.1, 0.4, 300)),
        "exit_reason": "stop",
        "hold_days": 1,
    })
    rest = pd.DataFrame({
        "ticker": [f"{i:06d}" for i in range(100)],
        "entry_date": pd.to_datetime("2023-01-02") + pd.to_timedelta(range(100), "D"),
        "pnl": rng.normal(400_000, 150_000, 100),
        "return_pct": rng.normal(9.0, 3.0, 100),
        "exit_reason": "target",
        "hold_days": rng.integers(5, 20, 100),
    })
    trades = pd.concat([same_day, rest], ignore_index=True)
    trades["exit_date"] = trades["entry_date"] + pd.to_timedelta(trades["hold_days"], "D")
    return trades


def test_same_day_losses_are_separated_from_the_rest():
    from src.analyze import same_day_losses

    stats = same_day_losses(_mixed_trades())
    assert stats["1일_건수"] == 300
    assert stats["1일_승률"] == 0.0
    assert stats["1일_손익"] < 0
    assert stats["나머지_손익"] > 0, "나머지는 이익이어야 합니다"


def test_report_points_out_that_the_signal_may_be_fine():
    """1일 매매를 빼면 이익인 경우, 손절이 문제라고 짚어야 합니다."""
    from src.analyze import report

    text = report(_mixed_trades())
    assert "1일 매매를 빼면 나머지는 이익입니다" in text
    assert "손절선이 너무 가까웠을 수 있습니다" in text


def test_no_such_hint_when_the_rest_also_loses():
    """나머지도 손해면 손절 탓으로 돌리면 안 됩니다."""
    from src.analyze import report

    trades = _mixed_trades()
    trades.loc[trades["hold_days"] > 1, ["pnl", "return_pct"]] = [-500_000, -5.0]
    assert "손절선이 너무 가까웠을 수 있습니다" not in report(trades)


def test_stop_width_table_counts_survivors():
    from src.analyze import stop_width_needed

    table = stop_width_needed(_mixed_trades(), widths=(3, 5, 10))
    assert "5%" in table.index
    # 손실이 평균 3.1% 이므로 5% 손절이면 대부분 살아남습니다.
    assert table.loc["5%", "비중"] > 90
    assert table.loc["3%", "비중"] < table.loc["10%", "비중"]


def test_loss_depth_shows_where_losses_cluster():
    from src.analyze import loss_depth

    depth = loss_depth(_mixed_trades())
    assert depth.loc["건수", "값"] >= 300
    # 손절선 근처(3%대)에 몰려 있어야 합니다.
    assert 2.5 < depth.loc["중앙", "값"] < 4.0


def test_stop_width_table_is_empty_without_same_day_losses():
    from src.analyze import stop_width_needed

    trades = make_trades(n=50)
    trades["hold_days"] = 10
    assert stop_width_needed(trades).empty
