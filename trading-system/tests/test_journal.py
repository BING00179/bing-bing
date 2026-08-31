"""판단 기록장 검사.

가장 중요한 검사는 '좋게 말해주지 않는가' 입니다. 표본이 적을 때
좋아 보이는 숫자를 근거처럼 내놓으면, 그 기록장은 없느니만 못합니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import journal as jn


def _entry(**kw):
    base = dict(recorded_at="2026-01-02", code="032820", name="우리기술",
                price=7000.0, conviction="중", horizon_days=90,
                why="분할 매수 중 거래량이 늘었다")
    base.update(kw)
    return jn.Entry(**base)


# ────────────────────── 기록 ──────────────────────

def test_이유를_안_적으면_기록하지_않는다(tmp_path):
    with pytest.raises(ValueError) as caught:
        jn.append(_entry(why="   "), tmp_path / "j.csv")
    assert "왜" in str(caught.value)


def test_확신도는_상중하만_받는다(tmp_path):
    with pytest.raises(ValueError):
        jn.append(_entry(conviction="아주높음"), tmp_path / "j.csv")


def test_기록하고_다시_읽으면_그대로다(tmp_path):
    path = tmp_path / "j.csv"
    jn.append(_entry(), path)
    frame = jn.load(path)
    assert len(frame) == 1
    assert frame.iloc[0]["code"] == "032820"
    assert frame.iloc[0]["price"] == 7000.0


def test_종목코드_앞자리_0이_사라지지_않는다(tmp_path):
    path = tmp_path / "j.csv"
    jn.append(_entry(code="005930", name="삼성전자"), path)
    assert jn.load(path).iloc[0]["code"] == "005930"


def test_덧붙일_뿐_기존_기록을_덮지_않는다(tmp_path):
    path = tmp_path / "j.csv"
    jn.append(_entry(), path)
    jn.append(_entry(code="005930", name="삼성전자"), path)
    frame = jn.load(path)
    assert len(frame) == 2
    assert set(frame["code"]) == {"032820", "005930"}


def test_기록이_없으면_빈_표를_준다(tmp_path):
    assert jn.load(tmp_path / "없는파일.csv").empty


# ────────────────────── 채점 시점 ──────────────────────

def test_기간이_안_차면_채점_대상이_아니다():
    frame = pd.DataFrame([{"recorded_at": "2026-08-01", "horizon_days": 90}])
    assert jn.due(frame, today=pd.Timestamp("2026-08-31")).empty


def test_기간이_차면_채점_대상이다():
    frame = pd.DataFrame([{"recorded_at": "2026-01-01", "horizon_days": 90}])
    assert len(jn.due(frame, today=pd.Timestamp("2026-08-31"))) == 1


# ────────────────────── 채점 ──────────────────────

def _prices(values, start="2026-01-02"):
    return pd.DataFrame(
        {"close": [float(v) for v in values]},
        index=pd.bdate_range(start, periods=len(values)),
    )


def _row(**kw):
    base = dict(recorded_at="2026-01-02", code="A", name="A", conviction="중",
                horizon_days=10, why="이유", price=100.0)
    base.update(kw)
    return pd.Series(base)


def test_초과수익은_지수를_뺀_값이다():
    stock = _prices([100, 120])          # +20%
    index = _prices([100, 105])          # +5%
    s = jn.score_one(_row(), stock, index, today=pd.Timestamp("2026-01-20"))
    assert abs(s.stock_pct - 20.0) < 1e-9
    assert abs(s.index_pct - 5.0) < 1e-9
    assert abs(s.excess - 15.0) < 1e-9


def test_올랐어도_지수보다_덜_오르면_진_것이다():
    stock = _prices([100, 115])          # +15%
    index = _prices([100, 120])          # +20%
    s = jn.score_one(_row(), stock, index, today=pd.Timestamp("2026-01-20"))
    assert s.stock_pct > 0
    assert s.excess < 0                   # 올랐지만 초과수익은 마이너스


def test_기간_밖의_시세는_쓰지_않는다():
    """채점 기간이 지난 뒤의 가격을 쓰면 미래를 본 것입니다.

    2026-01-02 는 금요일이라 거래일은 01-02, 01-05, 01-06 입니다.
    보유기간 3일(달력 기준)이면 01-05 까지만 봐야 합니다.
    """
    stock = _prices([100, 110, 999])      # 셋째 날(01-06)은 기간 밖
    s = jn.score_one(_row(horizon_days=3), stock, _prices([100, 100, 100]),
                     today=pd.Timestamp("2026-01-20"))
    assert s.end_price == 110.0           # 999 를 쓰면 미래를 본 것


def test_기간_안에_거래일이_하나뿐이면_채점하지_않는다():
    """휴장으로 비교할 거래일이 없으면 없는 대로 둡니다. 지어내지 않습니다."""
    stock = _prices([100, 110, 999])
    assert jn.score_one(_row(horizon_days=1), stock, _prices([100, 100, 100]),
                        today=pd.Timestamp("2026-01-20")) is None


def test_시세가_모자라면_채점하지_않는다():
    assert jn.score_one(_row(), _prices([100]), _prices([100])) is None


# ────────────────────── 판정 ──────────────────────

def _scored(excesses):
    return [
        jn.Scored(code="A", name="A", recorded_at="2026-01-02", conviction="중",
                  days=90, entry_price=100, end_price=100 + e,
                  stock_pct=e, index_pct=0.0, excess=e, why="이유")
        for e in excesses
    ]


def test_표본이_적으면_판정하지_않는다():
    v = jn.summarize(_scored([50.0] * 5))    # 평균 +50%인데도
    assert not v.enough
    assert not v.significant


def test_표본이_적으면_보고서가_그렇게_말한다():
    scored = _scored([50.0] * 5)
    text = jn.report(scored, jn.summarize(scored))
    assert "30건은 넘어야" in text
    assert "아무 뜻이 없습니다" in text


def test_충분하고_뚜렷하면_이겼다고_말한다():
    rng = np.random.default_rng(0)
    scored = _scored(list(rng.normal(8.0, 5.0, 60)))
    v = jn.summarize(scored)
    assert v.enough and v.significant and v.mean_excess > 0
    assert "우연으로 보기 어렵" in jn.report(scored, v)


def test_충분한데_지고_있으면_그것도_말한다():
    rng = np.random.default_rng(1)
    scored = _scored(list(rng.normal(-8.0, 5.0, 60)))
    v = jn.summarize(scored)
    assert v.significant and v.mean_excess < 0
    assert "다행인 사실" in jn.report(scored, v)


def test_표본은_찼는데_애매하면_애매하다고_말한다():
    rng = np.random.default_rng(2)
    scored = _scored(list(rng.normal(0.0, 20.0, 40)))
    v = jn.summarize(scored)
    text = jn.report(scored, v)
    if not v.significant:
        assert "구분되지 않습니다" in text


def test_보고서는_부분집합만_보지_말라고_경고한다():
    scored = _scored([1.0] * 40)
    assert "부분집합" in jn.report(scored, jn.summarize(scored))


def test_기록이_없으면_기록하는_법을_알려준다():
    text = jn.report([], jn.summarize([]), pending=0)
    assert "journal-add" in text


def test_확신도별로_나눠_보여준다():
    scored = _scored([10.0, -5.0])
    scored[0].conviction = "상"
    scored[1].conviction = "하"
    v = jn.summarize(scored)
    assert set(v.by_conviction.index) == {"상", "하"}
