import numpy as np
import pytest

from src.backtest import run, summarize, trades_to_frame
from src.strategy import signals_from_daily
from src.config import BacktestConfig, ScannerBConfig
from tests.helpers import make_daily, rising

SB = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5)
# 비용 0 으로 두면 진입·청산 가격을 손으로 검산할 수 있습니다.
NO_COST = BacktestConfig(commission_per_trade=0.0, slippage_pct=0.0)


def test_no_trades_in_downtrend():
    daily = make_daily(rising(60, start=200.0, step=-1.0))
    assert run("TEST", daily, NO_COST, SB) == []


def test_entry_happens_on_the_day_after_the_signal():
    """신호는 D일 종가로 나고, 진입은 D+1일 시가여야 합니다."""
    daily = make_daily(rising(60))
    trades = run("TEST", daily, NO_COST, SB)
    assert trades
    first = trades[0]
    entry_row = daily.loc[first.entry_date]
    assert first.entry_price == pytest.approx(float(entry_row["open"]), rel=1e-9)


def test_target_exit_is_taken_when_price_runs_up():
    daily = make_daily(rising(60, step=5.0))    # 하루 5씩 급등 → 익절 도달
    trades = run("TEST", daily, NO_COST, SB)
    assert trades
    assert trades[0].exit_reason == "target"
    assert trades[0].pnl > 0


def _first_entry_index(daily):
    """첫 신호 다음 봉(= 첫 진입 봉)의 위치를 찾습니다."""
    sig = signals_from_daily(daily, SB)["signal"].to_numpy()
    hits = np.flatnonzero(sig)
    assert hits.size, "합성 데이터에서 신호가 하나도 나오지 않았습니다"
    return int(hits[0]) + 1


def test_stop_exit_when_price_collapses_after_entry():
    closes = list(rising(60))
    daily = make_daily(closes)
    entry = _first_entry_index(daily)

    lows = [c * 0.99 for c in closes]
    lows[entry] = closes[entry - 1] * 0.70      # 진입 당일 저가가 손절선을 뚫음
    daily = make_daily(closes, lows=lows)

    trades = run("TEST", daily, NO_COST, SB)
    assert trades
    assert trades[0].exit_reason == "stop"
    assert trades[0].pnl < 0


def test_stop_wins_over_target_on_the_same_day():
    """손절·익절이 같은 날 둘 다 닿으면 보수적으로 손절 처리."""
    closes = list(rising(60))
    daily = make_daily(closes)
    entry = _first_entry_index(daily)
    entry_open = closes[entry - 1]              # 진입 봉 시가 = 직전 종가

    highs = list(closes)
    lows = [c * 0.99 for c in closes]
    highs[entry] = entry_open * 1.20            # 익절선 위
    lows[entry] = entry_open * 0.80             # 손절선 아래
    daily = make_daily(closes, highs=highs, lows=lows)

    trades = run("TEST", daily, NO_COST, SB)
    assert trades
    assert trades[0].exit_reason == "stop"


def test_timeout_exit_respects_max_hold_days():
    cfg = BacktestConfig(commission_per_trade=0.0, slippage_pct=0.0,
                         stop_loss_pct=50.0, take_profit_pct=50.0, max_hold_days=3)
    daily = make_daily(rising(60, step=0.5))
    trades = run("TEST", daily, cfg, SB)
    assert trades
    assert all(t.hold_days <= 3 for t in trades)
    assert trades[0].exit_reason in {"timeout", "end_of_data"}


def test_costs_reduce_profit():
    daily = make_daily(rising(60, step=5.0))
    free = run("TEST", daily, NO_COST, SB)
    costly = run(
        "TEST",
        daily,
        BacktestConfig(commission_per_trade=5.0, slippage_pct=0.5),
        SB,
    )
    assert free and costly
    assert summarize(costly)["total_pnl"] < summarize(free)["total_pnl"]


def test_positions_do_not_overlap():
    daily = make_daily(rising(120, step=2.0))
    trades = run("TEST", daily, NO_COST, SB)
    for earlier, later in zip(trades, trades[1:]):
        assert later.entry_date > earlier.exit_date


def test_skips_ticker_more_expensive_than_capital_per_trade():
    cfg = BacktestConfig(capital_per_trade=10.0)   # 주가 100달러 이상인 종목
    daily = make_daily(rising(60))
    assert run("TEST", daily, cfg, SB) == []


def test_summarize_on_empty_trades():
    stats = summarize([])
    assert stats["trades"] == 0
    assert stats["total_pnl"] == 0.0
    assert stats["profit_factor"] == 0.0


def test_summarize_reports_win_rate_and_drawdown():
    daily = make_daily(rising(120, step=2.0))
    trades = run("TEST", daily, NO_COST, SB)
    stats = summarize(trades)
    assert stats["trades"] == len(trades)
    assert 0.0 <= stats["win_rate_pct"] <= 100.0
    assert stats["max_drawdown"] >= 0.0


def test_trades_to_frame_has_stable_columns_when_empty():
    frame = trades_to_frame([])
    assert "ticker" in frame.columns and "pnl" in frame.columns
    assert len(frame) == 0
