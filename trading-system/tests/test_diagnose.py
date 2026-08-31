"""신호 진단 검사.

여기서 검사하는 것은 '숫자가 나오나' 가 아니라 '거짓말을 하지 않나' 입니다.
우위가 없는 신호를 우위가 있다고 말하면 사장님 돈이 들어갑니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import diagnose as dg


def _bars(n=300, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(drift, 0.02, n)), index=days)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 100_000,
    })


# ────────────────────── 앞으로의 수익률 ──────────────────────

def test_진입은_신호_다음날_시가다():
    daily = _bars(50)
    signal_date = daily.index[10]
    out = dg.signal_forward("T", daily, pd.DatetimeIndex([signal_date]))
    assert out.iloc[0]["entry_date"] == daily.index[11]      # D+1


def test_갭은_어제_종가_대비_오늘_시가다():
    daily = _bars(50)
    daily.iloc[11, daily.columns.get_loc("open")] = daily["close"].iloc[10] * 1.05
    out = dg.signal_forward("T", daily, pd.DatetimeIndex([daily.index[10]]))
    assert abs(out.iloc[0]["gap_pct"] - 5.0) < 1e-6


def test_1일_수익률은_진입일_시가에서_진입일_종가까지다():
    daily = _bars(50)
    out = dg.signal_forward("T", daily, pd.DatetimeIndex([daily.index[10]]))
    기대 = (daily["close"].iloc[11] / daily["open"].iloc[11] - 1) * 100
    assert abs(out.iloc[0]["fwd1"] - 기대) < 1e-9


def test_데이터가_모자라면_숫자를_지어내지_않는다():
    daily = _bars(30)
    out = dg.signal_forward("T", daily, pd.DatetimeIndex([daily.index[-2]]))
    assert pd.isna(out.iloc[0]["fwd20"])       # 20일치가 없으므로 nan


def test_마지막날_신호는_살_수_없으니_버린다():
    daily = _bars(30)
    out = dg.signal_forward("T", daily, pd.DatetimeIndex([daily.index[-1]]))
    assert out.empty


def test_신호가_없으면_빈_표다():
    assert dg.signal_forward("T", _bars(50), pd.DatetimeIndex([])).empty


# ────────────────────── 비교 기준 ──────────────────────

def test_시장_평균은_날짜별로_모든_종목을_평균한다():
    frames = {"A": _bars(120, seed=1), "B": _bars(120, seed=2)}
    market = dg.market_forward(frames)
    assert not market.empty
    assert "fwd5" in market.columns
    # 같은 날짜에 두 종목이 있으면 그 평균이어야 합니다.
    날 = market.index[10]
    각각 = []
    for daily in frames.values():
        pos = daily.index.get_loc(날)
        각각.append((daily["close"].iloc[pos + 4] / daily["open"].iloc[pos] - 1) * 100)
    assert abs(market.loc[날, "fwd5"] - np.mean(각각)) < 1e-9


# ────────────────────── 우위 판정 ──────────────────────

def _signals_from(frames, picker):
    parts = []
    for code, daily in frames.items():
        dates = picker(daily)
        if len(dates):
            parts.append(dg.signal_forward(code, daily, dates))
    return pd.concat(parts, ignore_index=True)


def test_무작위_신호는_우위가_없다고_말한다():
    """아무 날이나 고른 신호는 시장 평균과 같아야 합니다."""
    rng = np.random.default_rng(7)
    frames = {f"S{i}": _bars(400, seed=i) for i in range(12)}
    market = dg.market_forward(frames)
    signals = _signals_from(
        frames, lambda d: d.index[rng.choice(len(d) - 25, 40, replace=False)]
    )
    results = dg.edge(signals, market)
    assert results
    for r in results:
        assert abs(r.t_stat) < 3.5          # 우연 범위. 크게 벗어나면 계산이 틀린 것


def test_진짜_우위가_있으면_찾아낸다():
    """신호 다음날 반드시 오르게 만든 자료에서는 초과수익이 잡혀야 합니다."""
    frames, signal_map = {}, {}
    rng = np.random.default_rng(11)
    for i in range(12):
        daily = _bars(400, seed=100 + i).copy()
        picks = np.sort(rng.choice(np.arange(50, 360), 30, replace=False))
        # 진입일(D+1) 종가만 5% 올려 둡니다.
        for p in picks:
            for col in ("close", "high"):
                daily.iloc[p + 1, daily.columns.get_loc(col)] *= 1.05
        frames[f"S{i}"] = daily
        signal_map[f"S{i}"] = daily.index[picks]

    market = dg.market_forward(frames)
    parts = [dg.signal_forward(c, frames[c], signal_map[c]) for c in frames]
    signals = pd.concat(parts, ignore_index=True)

    results = {r.horizon: r for r in dg.edge(signals, market)}
    assert results[1].excess > 2.0          # 심어놓은 우위를 못 찾으면 도구가 쓸모없음
    assert results[1].t_stat > 3


def test_표본이_모자라면_판정하지_않는다():
    frames = {"A": _bars(200, seed=3)}
    market = dg.market_forward(frames)
    signals = dg.signal_forward("A", frames["A"], frames["A"].index[50:60])
    assert dg.edge(signals, market) == []   # 10건 → 판정 거부


# ────────────────────── 갭·손절 ──────────────────────

def test_갭이_클수록_따로_묶인다():
    frame = pd.DataFrame({
        "gap_pct": [-1.0, 1.0, 3.0, 7.0, 20.0],
        "day1_low_pct": [-1.0] * 5,
        "fwd5": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    table = dg.by_gap(frame, horizon=5)
    assert list(table["건수"]) == [1, 1, 1, 1, 1]
    assert table.loc["10%+", "평균수익%"] == 5.0


def test_손절폭별_첫날_도달비율을_직접_센다():
    frame = pd.DataFrame({"day1_low_pct": [-1.0, -4.0, -9.0, -20.0]})
    table = dg.stop_reach(frame, widths=(3.0, 8.0))
    비율 = dict(zip(table["손절폭%"], table["첫날 닿는 비율%"]))
    assert 비율[3.0] == 75.0        # -4, -9, -20 → 3건/4건
    assert 비율[8.0] == 50.0        # -9, -20 → 2건/4건


# ────────────────────── 보고서 ──────────────────────

def _edge(excess, t):
    return dg.EdgeResult(5, 1.0, 0.5, 1.0 - excess, excess, 50.0, 50.0, 500, t)


def test_보고서는_사실과_해석을_가른다():
    text = dg.report([_edge(0.5, 3.0)], pd.DataFrame(), pd.DataFrame(), 500)
    assert "[사실]" in text and "[해석]" in text


def test_보고서는_초과수익_해석_기준을_먼저_적어둔다():
    text = dg.report([_edge(0.5, 3.0)], pd.DataFrame(), pd.DataFrame(), 500)
    assert "초과수익이 0 이하" in text
    assert "t > 2" in text


def test_표본이_없으면_없다고_말한다():
    text = dg.report([], pd.DataFrame(), pd.DataFrame(), 5)
    assert "표본이 부족" in text
