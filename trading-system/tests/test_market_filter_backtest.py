"""시장 필터를 백테스트에 적용했을 때 신호가 실제로 걸러지는가."""

import numpy as np
import pandas as pd

from src.backtest import run
from src.config import BacktestConfig, MarketFilterConfig, ScannerBConfig
from src.market_filter import tradable_series
from src.strategy import signals_from_daily
from tests.helpers import make_daily, rising

SB = ScannerBConfig(sma_slow=20, sma_mid=10, sma_fast=5)
BT = BacktestConfig(commission_per_trade=0.0, slippage_pct=0.0,
                    take_profit_pct=0.0, trailing_stop_pct=7.0, max_hold_days=20)


def test_blocking_every_day_removes_all_trades():
    daily = make_daily(rising(80, step=3.0))
    assert run("TEST", daily, BT, SB), "필터 없이는 매매가 있어야 합니다"

    never = pd.Series(False, index=daily.index)
    assert run("TEST", daily, BT, SB, never) == []


def test_allowing_every_day_matches_no_filter():
    daily = make_daily(rising(80, step=3.0))
    always = pd.Series(True, index=daily.index)
    assert run("TEST", daily, BT, SB, always) == run("TEST", daily, BT, SB)


def test_every_filtered_trade_was_signalled_on_an_allowed_day():
    """필터를 켜면 허용된 날의 신호로만 진입해야 합니다.

    매매 자체는 늘어날 수도 있습니다. 앞의 신호가 막히면 그동안
    포지션이 비어 있어서, 원래라면 보유 중이라 못 잡았을 뒤쪽 신호를
    잡게 되기 때문입니다. 그건 정상 동작입니다. 확인할 것은
    '막힌 날의 신호로 산 매매가 없는가' 입니다.
    """
    daily = make_daily(rising(120, step=2.0))
    rng = np.random.default_rng(7)
    partial = pd.Series(rng.random(len(daily)) > 0.5, index=daily.index)

    for t in run("TEST", daily, BT, SB, partial):
        # 진입은 신호 다음 날 시가입니다. 신호일은 진입일 직전 거래일.
        signal_day = daily.index[daily.index.get_loc(t.entry_date) - 1]
        assert partial[signal_day], f"막힌 날({signal_day.date()})의 신호로 진입했습니다"


def test_missing_dates_are_treated_as_not_tradable():
    """지수 데이터에 없는 날짜는 판정 불가 → 매수하지 않습니다."""
    daily = make_daily(rising(80, step=3.0))
    half = pd.Series(True, index=daily.index[:40])      # 뒤쪽 날짜가 없음
    trades = run("TEST", daily, BT, SB, half)
    assert all(t.entry_date in half.index for t in trades)


def test_tradable_series_marks_a_crash_as_not_tradable():
    """지수가 200일선 아래로 무너지면 매수 금지로 나와야 합니다."""
    # 200일선이 만들어지려면 200일이 필요하므로 상승 구간을 넉넉히 둡니다.
    up = np.linspace(2000, 3000, 400)
    crash = np.linspace(3000, 1800, 200)
    index = pd.DataFrame(
        {"close": np.concatenate([up, crash])},
        index=pd.bdate_range("2023-01-02", periods=600),
    )
    ok = tradable_series(index, MarketFilterConfig())
    assert not ok.iloc[-1], "폭락 구간은 매수 금지여야 합니다"
    assert ok.iloc[390], "상승 구간은 매수 허용이어야 합니다"


def test_tradable_series_warmup_is_not_tradable():
    """지표가 만들어지기 전 구간은 매수하지 않습니다."""
    index = pd.DataFrame(
        {"close": np.linspace(2000, 2500, 300)},
        index=pd.bdate_range("2023-01-02", periods=300),
    )
    ok = tradable_series(index, MarketFilterConfig())
    assert not ok.iloc[:199].any(), "200일선이 만들어지기 전에는 매수 금지"


def test_tradable_series_does_not_look_ahead():
    """뒤쪽 데이터를 잘라내도 앞부분 판정은 그대로여야 합니다."""
    rng = np.random.default_rng(3)
    n = 500
    closes = 2000 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    index = pd.DataFrame({"close": closes},
                         index=pd.bdate_range("2023-01-02", periods=n))
    cfg = MarketFilterConfig()
    full = tradable_series(index, cfg)
    cut = tradable_series(index.iloc[:400], cfg)
    assert full.iloc[:400].tolist() == cut.tolist()


def test_signals_are_unchanged_when_no_filter_given():
    daily = make_daily(rising(80, step=3.0))
    before = signals_from_daily(daily, SB)["signal"].sum()
    run("TEST", daily, BT, SB)
    after = signals_from_daily(daily, SB)["signal"].sum()
    assert before == after, "필터 적용이 원본 신호를 건드리면 안 됩니다"
