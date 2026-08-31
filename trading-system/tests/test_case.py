"""사례 분석 검사 — 되돌아보기가 거짓말하지 않도록.

결과를 알고 과거를 보면 무엇이든 그럴듯해 보입니다. 그래서 여기서는
'가장 크게 오른 구간' 같은 계산이 실제로 맞는지, 그리고 신호의 시점을
정직하게 분류하는지만 봅니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import case


def _close(values, start="2020-01-01"):
    return pd.Series(
        [float(v) for v in values],
        index=pd.bdate_range(start, periods=len(values)),
    )


# ────────────────────── 최대 상승 구간 ──────────────────────

def test_저점에서_고점까지_제대로_찾는다():
    c = _close([100, 80, 50, 60, 200, 150])
    r = case.biggest_runup(c)
    assert r.low == 50 and r.high == 200
    assert r.multiple == 4.0


def test_고점이_저점보다_앞서면_그_짝은_안_고른다():
    """300 이 50 보다 앞에 있으므로 50→300 은 성립하지 않습니다.

    (앞선 실패: 처음 쓴 예시가 [100, 300, 50, 90] 이었는데 100→300 이
     3배로 유효한 구간이라 검사가 되지 않았습니다. 300 을 맨 앞에 둡니다.)
    """
    c = _close([300, 50, 90])
    r = case.biggest_runup(c)
    assert r.low == 50 and r.high == 90     # 50→300 을 고르면 미래를 산 것
    assert abs(r.multiple - 1.8) < 1e-9


def test_계속_내려가기만_하면_상승배수가_1_이하다():
    r = case.biggest_runup(_close([100, 90, 80, 70]))
    assert r is None or r.multiple <= 1.0


def test_자료가_모자라면_없다고_한다():
    assert case.biggest_runup(_close([100])) is None
    assert case.biggest_runup(pd.Series(dtype=float)) is None


def test_빈칸이_섞여도_터지지_않는다():
    c = _close([100, np.nan, 50, np.nan, 200])
    r = case.biggest_runup(c)
    assert r.low == 50 and r.high == 200


# ────────────────────── 신호 시점 분류 ──────────────────────

def _runup(start, end):
    return case.Runup(start=pd.Timestamp(start), end=pd.Timestamp(end),
                      low=50.0, high=200.0)


def test_상승_전_중_후를_갈라_센다():
    c = _close([100] * 40)
    r = _runup("2020-01-20", "2020-02-10")
    dates = pd.DatetimeIndex(["2020-01-10", "2020-01-25", "2020-02-20"])
    t = case.timing(dates, c, r)
    assert (t.before_runup, t.during_runup, t.after_runup) == (1, 1, 1)


def test_상승_시작일_당일은_상승_도중으로_센다():
    c = _close([100] * 40)
    r = _runup("2020-01-20", "2020-02-10")
    t = case.timing(pd.DatetimeIndex(["2020-01-20"]), c, r)
    assert t.during_runup == 1 and t.before_runup == 0


def test_신호가_없으면_0건이라고_말한다():
    t = case.timing(pd.DatetimeIndex([]), _close([100] * 10), None)
    assert t.total == 0 and t.first_signal is None


def test_첫_신호의_가격을_같이_적는다():
    c = _close([10, 20, 30, 40])
    t = case.timing(pd.DatetimeIndex([c.index[2]]), c, None)
    assert t.price_at_first == 30.0


def test_상승_구간에서의_위치를_퍼센트로_알려준다():
    r = _runup("2020-01-01", "2020-02-01")     # 50 → 200
    assert case.position_in_runup(50.0, r) == 0.0
    assert case.position_in_runup(200.0, r) == 100.0
    assert case.position_in_runup(125.0, r) == 50.0
    assert np.isnan(case.position_in_runup(100.0, None))


# ────────────────────── 연도별 표 ──────────────────────

def test_연도별로_최저_최고를_나눈다():
    days = pd.bdate_range("2023-11-01", periods=60)
    daily = pd.DataFrame({"close": np.arange(60, dtype=float) + 100}, index=days)
    table = case.yearly(daily)
    assert set(table.index) == {2023, 2024}
    assert table.loc[2023, "최저"] == 100.0


# ────────────────────── 보고서 ──────────────────────

def _daily(n=30):
    days = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"close": np.linspace(100, 200, n)}, index=days)


def test_보고서는_사실과_해석을_가른다():
    daily = _daily()
    text = case.report("032820", "우리기술", daily,
                       case.biggest_runup(daily["close"]),
                       case.yearly(daily),
                       case.timing(pd.DatetimeIndex([]), daily["close"], None))
    assert "[사실]" in text and "[해석]" in text


def test_보고서는_종목_하나가_증거가_아님을_반드시_적는다():
    daily = _daily()
    text = case.report("032820", "우리기술", daily, None, pd.DataFrame(),
                       case.timing(pd.DatetimeIndex([]), daily["close"], None))
    assert "증거가 아닙니다" in text
    assert "결과를 알고 되돌아보는" in text


def test_신호가_0건이면_그렇게_말한다():
    daily = _daily()
    text = case.report("A", "A", daily, None, pd.DataFrame(),
                       case.timing(pd.DatetimeIndex([]), daily["close"], None))
    assert "한 번도 걸리지 않았습니다" in text
