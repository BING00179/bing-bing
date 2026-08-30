import numpy as np
import pytest

from src.backtest import run, summarize, trades_to_frame
from src.strategy import signals_from_daily
from src.config import BacktestConfig, ScannerBConfig
from tests.helpers import make_daily, rising

SB = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5)
# 비용 0 으로 두면 진입·청산 가격을 손으로 검산할 수 있습니다.
# 청산 방식은 테스트마다 명시합니다(기본값이 바뀌어도 테스트 의도가 흔들리지 않게).
NO_COST = BacktestConfig(
    commission_per_trade=0.0, slippage_pct=0.0,
    take_profit_pct=6.0, trailing_stop_pct=0.0, max_hold_days=5,
)
TRAILING = BacktestConfig(
    commission_per_trade=0.0, slippage_pct=0.0,
    take_profit_pct=0.0, trailing_stop_pct=7.0, max_hold_days=20,
)


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
        BacktestConfig(
            commission_per_trade=5.0, slippage_pct=0.5,
            take_profit_pct=6.0, trailing_stop_pct=0.0, max_hold_days=5,
        ),
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


# ── 추격 손절 (오르는 동안 따라 올라가고, 꺾이면 나온다) ──


def test_trailing_stop_lets_a_winner_run_past_the_fixed_target():
    """고정 익절 6% 였다면 끊겼을 상승을 추격 손절은 계속 끌고 갑니다."""
    daily = make_daily(rising(60, step=5.0))     # 하루 5씩 꾸준히 상승
    fixed = run("TEST", daily, NO_COST, SB)
    trailed = run("TEST", daily, TRAILING, SB)

    assert fixed and trailed
    assert fixed[0].exit_reason == "target"
    assert trailed[0].return_pct > fixed[0].return_pct


def test_trailing_stop_exits_after_the_peak_rolls_over():
    """고점을 찍고 밀리면 추격 손절선에 걸려 나옵니다."""
    closes = list(rising(50, step=4.0))
    peak = closes[-1]
    closes += [peak * 0.80] * 5                  # 고점에서 20% 하락
    lows = [c * 0.99 for c in closes]
    lows[50] = peak * 0.80
    daily = make_daily(closes, lows=lows)

    trades = run("TEST", daily, TRAILING, SB)
    assert trades
    # 상승 구간에서는 최대보유일로 끊기고, 폭락 구간을 지나는 매매가
    # 추격 손절에 걸려야 합니다.
    assert any(t.exit_reason == "trail" for t in trades), (
        f"추격 손절이 한 번도 걸리지 않았습니다: "
        f"{[t.exit_reason for t in trades]}"
    )


def test_trailing_stop_never_sits_below_the_initial_stop():
    """진입 직후 바로 빠지면, 추격선이 아니라 최초 손절선이 지킵니다."""
    closes = list(rising(60))
    daily = make_daily(closes)
    entry = _first_entry_index(daily)
    lows = [c * 0.99 for c in closes]
    lows[entry] = closes[entry - 1] * 0.90       # 진입가 대비 -10%
    daily = make_daily(closes, lows=lows)

    cfg = BacktestConfig(commission_per_trade=0.0, slippage_pct=0.0,
                         stop_loss_pct=3.0, take_profit_pct=0.0, trailing_stop_pct=7.0)
    trades = run("TEST", daily, cfg, SB)
    assert trades
    # -3% 손절선에서 나와야 합니다. -7% 추격선까지 밀리면 안 됩니다.
    assert trades[0].return_pct == pytest.approx(-3.0, abs=0.01)


def test_trailing_stop_uses_only_yesterdays_peak():
    """오늘 장중 고가를 오늘 손절선에 쓰면 미래를 미리 본 것이 됩니다.

    진입 당일에 크게 위로 찔렀다가 되돌린 봉을 넣습니다. 오늘 고가를
    그날 손절선에 반영했다면 그 자리에서 청산됐을 텐데, 어제까지의
    최고가만 쓰므로 그렇게 되지 않아야 합니다.
    """
    closes = list(rising(60))
    daily = make_daily(closes)
    entry = _first_entry_index(daily)
    entry_open = closes[entry - 1]

    highs = list(closes)
    lows = [c * 0.99 for c in closes]
    highs[entry] = entry_open * 1.50             # 장중 +50% 찔렀다가
    lows[entry] = entry_open * 0.99              # 종가 부근으로 되돌림
    daily = make_daily(closes, highs=highs, lows=lows)

    trades = run("TEST", daily, TRAILING, SB)
    assert trades
    assert trades[0].entry_date != trades[0].exit_date or trades[0].exit_reason != "trail"


def test_ma_break_exit():
    """종가가 지정한 이동평균선 아래로 마감하면 청산합니다."""
    closes = list(rising(50, step=3.0))
    closes += [closes[-1] * 0.70] * 8            # 추세 이탈
    daily = make_daily(closes)

    cfg = BacktestConfig(commission_per_trade=0.0, slippage_pct=0.0,
                         stop_loss_pct=50.0, take_profit_pct=0.0,
                         trailing_stop_pct=0.0, exit_on_ma_break=5, max_hold_days=30)
    trades = run("TEST", daily, cfg, SB)
    assert trades
    assert any(t.exit_reason == "ma_break" for t in trades)
