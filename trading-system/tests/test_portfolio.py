"""포트폴리오 백테스트 — 자본과 자리 제한이 실제로 지켜지는가."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import BacktestKrConfig
from src.portfolio import run, summarize

DATES = pd.bdate_range("2024-01-01", periods=120)


def frame(start: float, drift: float = 0.002, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, 0.015, len(DATES))))
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(close * 1.01, opens),
            "low": np.minimum(close * 0.99, opens),
            "close": close,
            "volume": np.full(len(DATES), 500_000.0),
        },
        index=DATES,
    )


def signals_on(day_idx: int, codes_scores: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": [c for c, _ in codes_scores],
         "score": [s for _, s in codes_scores]},
        index=[DATES[day_idx]] * len(codes_scores),
    )


CFG = BacktestKrConfig(stop_loss_pct=5.0, trailing_stop_pct=0.0,
                       take_profit_pct=0.0, max_hold_days=10,
                       commission_pct=0.0, sell_tax_pct=0.0, slippage_pct=0.0)


def test_never_holds_more_than_the_limit():
    """같은 날 신호가 10개여도 3종목까지만 삽니다."""
    frames = {f"{i:06d}": frame(10_000 + i * 100, seed=i) for i in range(10)}
    sig = signals_on(5, [(c, 100 - i) for i, c in enumerate(frames)])

    result = run(sig, frames, CFG, start_cash=10_000_000, max_positions=3)
    entries = [t for t in result.trades]
    same_day = {}
    for t in entries:
        same_day.setdefault(t.entry_date, []).append(t.code)
    for day, codes in same_day.items():
        assert len(codes) <= 3, f"{day.date()} 에 {len(codes)}종목 진입"
    assert result.skipped_no_slot > 0, "자리가 없어 넘긴 신호가 있어야 합니다"


def test_highest_score_is_bought_first():
    """자리가 모자라면 점수 높은 것부터 삽니다."""
    frames = {f"{i:06d}": frame(10_000, seed=i) for i in range(5)}
    codes = list(frames)
    sig = signals_on(5, [(codes[0], 10), (codes[1], 90), (codes[2], 50),
                         (codes[3], 20), (codes[4], 70)])

    result = run(sig, frames, CFG, start_cash=10_000_000, max_positions=2)
    bought = {t.code for t in result.trades}
    assert codes[1] in bought, "점수 90짜리를 샀어야 합니다"
    assert codes[4] in bought, "점수 70짜리를 샀어야 합니다"
    assert codes[0] not in bought, "점수 10짜리를 사면 안 됩니다"


def test_cannot_spend_more_than_it_has():
    """가진 돈보다 많이 쓸 수 없습니다."""
    frames = {f"{i:06d}": frame(1_000_000, seed=i) for i in range(5)}
    sig = signals_on(5, [(c, 50) for c in frames])

    result = run(sig, frames, CFG, start_cash=1_000_000, max_positions=3)
    for t in result.trades:
        assert t.entry_price * t.shares <= 1_000_000 * 1.001


def test_expensive_stock_is_skipped_when_cash_is_short():
    frames = {"000001": frame(50_000_000, seed=1)}
    sig = signals_on(5, [("000001", 50)])
    result = run(sig, frames, CFG, start_cash=1_000_000, max_positions=3)
    assert result.trades == []
    assert result.skipped_no_cash > 0


def test_slot_frees_up_after_selling():
    """팔고 나면 자리가 나서 다음 종목을 살 수 있어야 합니다."""
    frames = {"000001": frame(10_000, seed=1), "000002": frame(10_000, seed=2)}
    sig = pd.concat([
        signals_on(5, [("000001", 90)]),
        signals_on(40, [("000002", 90)]),   # 첫 종목이 청산된 뒤
    ])
    result = run(sig, frames, CFG, start_cash=10_000_000, max_positions=1)
    assert len(result.trades) >= 2, "자리가 나면 다음 종목을 사야 합니다"


def test_no_signals_returns_starting_cash():
    frames = {"000001": frame(10_000)}
    result = run(pd.DataFrame(), frames, CFG, start_cash=10_000_000)
    assert result.end_value == 10_000_000
    assert result.trades == []


def test_summary_reports_what_the_money_became():
    frames = {f"{i:06d}": frame(10_000, drift=0.004, seed=i) for i in range(4)}
    sig = signals_on(5, [(c, 50 + i) for i, c in enumerate(frames)])
    result = run(sig, frames, CFG, start_cash=10_000_000, max_positions=3)
    st = summarize(result)

    assert st["start_cash"] == 10_000_000
    assert st["end_value"] > 0
    assert st["max_drawdown_pct"] <= 0, "낙폭은 0 이하로 표시됩니다"
    assert "cagr_pct" in st


def test_entry_is_the_day_after_the_signal():
    """신호 다음 날 시가에 진입해야 합니다."""
    frames = {"000001": frame(10_000, seed=1)}
    sig = signals_on(5, [("000001", 90)])
    result = run(sig, frames, CFG, start_cash=10_000_000, max_positions=1)
    assert result.trades
    assert result.trades[0].entry_date == DATES[6]


def test_costs_reduce_the_final_value():
    frames = {f"{i:06d}": frame(10_000, seed=i) for i in range(3)}
    sig = signals_on(5, [(c, 50) for c in frames])

    free = run(sig, frames, CFG, start_cash=10_000_000, max_positions=3)
    costly = run(
        sig, frames,
        BacktestKrConfig(stop_loss_pct=5.0, trailing_stop_pct=0.0,
                         take_profit_pct=0.0, max_hold_days=10,
                         commission_pct=0.5, sell_tax_pct=0.5, slippage_pct=0.5),
        start_cash=10_000_000, max_positions=3,
    )
    assert costly.end_value < free.end_value
