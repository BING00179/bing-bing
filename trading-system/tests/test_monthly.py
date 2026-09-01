"""월말 브리핑 검사.

여기서 제일 위험한 것은 '표본을 여러 조각으로 나누면 그중 하나는
우연히 좋아 보인다' 는 것입니다. 그래서 건수가 적은 칸은 아예 내지
않고, 보고서가 그 위험을 반드시 말하는지 검사합니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import monthly as mo


def _bars(closes, start="2026-01-05"):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series([float(x) for x in closes], index=idx)
    return pd.DataFrame({"open": c, "high": c * 1.005,
                         "low": c * 0.995, "close": c})


# ────────────────────── 값이 움직인 모양 ──────────────────────

def test_바로_오른_것을_알아본다():
    daily = _bars([100, 108, 110, 112, 113] + [113] * 15)
    assert mo.path_shape(daily, "2026-01-05").shape == "바로 상승"


def test_횡보하다_오른_것을_알아본다():
    daily = _bars([100, 100, 101, 100, 100] + list(np.linspace(101, 120, 15)))
    assert mo.path_shape(daily, "2026-01-05").shape == "횡보 후 상승"


def test_빠졌다_돌아온_것을_알아본다():
    daily = _bars([100, 94, 90, 92, 95] + list(np.linspace(96, 112, 15)))
    길 = mo.path_shape(daily, "2026-01-05")
    assert 길.shape == "손실 후 반등"
    assert 길.max_loss_pct < -5.0
    assert 길.final_pct > 0


def test_고점_찍고_되돌린_것을_알아본다():
    daily = _bars([100, 110, 120, 125, 124] + list(np.linspace(120, 101, 15)))
    길 = mo.path_shape(daily, "2026-01-05")
    assert 길.shape == "고점 후 반락"
    assert 길.max_gain_pct > 20


def test_바로_빠져서_못_돌아온_것을_알아본다():
    daily = _bars([100, 93, 90, 88, 87] + [86] * 15)
    assert mo.path_shape(daily, "2026-01-05").shape == "선정 직후 하락"


def test_진입일이_없으면_모양을_지어내지_않는다():
    daily = _bars([100] * 20)
    assert mo.path_shape(daily, "2020-01-01") is None


def test_자료가_하루뿐이면_모양을_내지_않는다():
    assert mo.path_shape(_bars([100]), "2026-01-05") is None


def test_고점까지_며칠_걸렸는지_센다():
    daily = _bars([100, 101, 102, 130, 120] + [118] * 15)
    assert mo.path_shape(daily, "2026-01-05").days_to_peak == 4


# ────────────────────── 조건별 쪼개기 ──────────────────────

def _scored(n=40, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "code": [f"{i:06d}" for i in range(n)],
        "name": [f"종목{i}" for i in range(n)],
        "setup": ["breakout"] * n,
        "excess": rng.normal(1.0, 8.0, n),
        "거래량배수": rng.uniform(2.0, 15.0, n),
        "갭%": rng.uniform(-3.0, 8.0, n),
        "모양": rng.choice(list(mo.SHAPES), n),
        "최대손실%": rng.uniform(-15, 0, n),
        "최대이익%": rng.uniform(0, 20, n),
    })


def test_건수가_적은_칸은_아예_내지_않는다():
    """10건짜리 칸이 우연히 좋게 나오면 그걸 근거처럼 읽게 됩니다."""
    frame = _scored(12)
    조각들 = mo.by_condition(frame, "거래량배수")
    assert all(s.count >= mo.MIN_FOR_HINT for s in 조각들)


def test_쪼갠_칸마다_건수를_반드시_같이_낸다():
    for s in mo.by_condition(_scored(80), "거래량배수"):
        assert s.count > 0


def test_모르는_열은_쪼개지_않는다():
    assert mo.by_condition(_scored(40), "없는열") == []


def test_빈_표는_조용히_넘어간다():
    assert mo.by_condition(pd.DataFrame(), "거래량배수") == []


# ────────────────────── 모양별 표 ──────────────────────

def test_모양별로_묶어_센다():
    표 = mo.by_shape(_scored(60))
    assert not 표.empty
    assert "건수" in 표.columns and "평균초과%" in 표.columns


def test_모양_열이_없으면_빈_표다():
    frame = _scored(20).drop(columns=["모양"])
    assert mo.by_shape(frame).empty


# ────────────────────── 보고서 ──────────────────────

def test_보고서는_사실과_해석을_가른다():
    글 = mo.report(_scored(40), "2026-08", 20, recorded=50, waiting=10)
    assert "[사실]" in 글 and "[해석]" in 글


def test_보고서는_쪼갠_표를_믿지_말라고_반드시_말한다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "참고만" in 글
    assert "우연히 좋아 보입니다" in 글


def test_보고서는_규칙을_바꾸면_시계가_다시_간다고_말한다():
    assert "시계가 다시 갑니다" in mo.report(_scored(40), "2026-08", 20)


def test_표본이_적으면_판정하지_말라고_말한다():
    글 = mo.report(_scored(12), "2026-08", 20)
    assert "아무 뜻이 없습니다" in 글


def test_보고서는_돈이_안_들어갔음을_밝힌다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "돈은 한 푼도 들어가지 않았습니다" in 글
    assert "수익 보고서가" in 글


def test_채점할_것이_없으면_그렇게_말한다():
    글 = mo.report(pd.DataFrame(), "2026-08", 20, recorded=5, waiting=5)
    assert "아직 채점할 것이 없습니다" in 글


def test_모양별_해석을_같이_적는다():
    글 = mo.report(_scored(60), "2026-08", 20)
    assert "손절이 좁아서" in 글
    assert "익절 규칙이 없어서" in 글
