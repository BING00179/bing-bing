"""두 축 검사 — 좋은 기업인가, 값이 괜찮은가.

가장 중요한 검사는 '두 축이 섞이지 않는가' 입니다. 하나로 합치면
'싸지만 망해가는 회사' 와 '좋지만 너무 비싼 회사' 가 같은 점수가 되어
무엇이 문제인지 알 수 없게 됩니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import quality as q


def _fin(**over):
    base = dict(
        code=["000001"], name=["가나"], marcap=[1e11],
        매출액_y0=[3e11], 매출액_y1=[2.7e11], 매출액_y2=[2.4e11],
        영업이익_y0=[4.5e10], 영업이익_y1=[3.8e10], 영업이익_y2=[3.0e10],
        당기순이익_y0=[3.5e10], 당기순이익_y1=[3e10], 당기순이익_y2=[2.5e10],
        자산총계_y0=[4e11], 부채총계_y0=[1e11], 자본총계_y0=[3e11],
        영업활동현금흐름_y0=[3.8e10], 설비투자_y0=[1e10],
    )
    base.update(over)
    return pd.DataFrame(base)


def _prices(close=5000.0, high=9000.0, low=4200.0):
    return pd.DataFrame({"close": [close], "high_52w": [high], "low_52w": [low]})


# ────────────────────── 기업이 좋은가 ──────────────────────

def test_매출과_이익_성장을_3년으로_잰다():
    m = q.business_metrics(_fin())
    assert m.iloc[0]["매출성장%"] > 0
    assert m.iloc[0]["영업이익성장%"] > 0


def test_매출이_줄면_성장이_마이너스다():
    m = q.business_metrics(_fin(매출액_y0=[2.4e11], 매출액_y2=[3e11]))
    assert m.iloc[0]["매출성장%"] < 0


def test_옛날_매출이_0이면_성장률을_지어내지_않는다():
    m = q.business_metrics(_fin(매출액_y2=[0.0]))
    assert pd.isna(m.iloc[0]["매출성장%"])


def test_장부이익이_현금으로_들어오는지_본다():
    좋음 = q.business_metrics(_fin())                       # 현금 380억 / 순이익 350억
    나쁨 = q.business_metrics(_fin(영업활동현금흐름_y0=[1e9]))   # 현금이 순이익의 3%
    assert 좋음.iloc[0]["현금전환배수"] > 1.0
    assert 나쁨.iloc[0]["현금전환배수"] < 0.2


def test_현금흐름이_없으면_빈칸으로_둔다():
    m = q.business_metrics(_fin(영업활동현금흐름_y0=[np.nan]))
    assert pd.isna(m.iloc[0]["현금전환배수"])


def test_세_해_모두_흑자였는지_센다():
    assert q.business_metrics(_fin()).iloc[0]["흑자연수"] == 3
    한해적자 = _fin(영업이익_y1=[-1e9])
    assert q.business_metrics(한해적자).iloc[0]["흑자연수"] == 2


def test_기업점수는_항목이_모자라면_적게_계산된다():
    빠짐 = _fin(영업활동현금흐름_y0=[np.nan], 매출액_y2=[np.nan])
    점수 = q.business_score(q.business_metrics(빠짐))
    assert 점수.iloc[0]["기업항목수"] < 5


# ────────────────────── 값이 괜찮은가 ──────────────────────

def test_PBR과_PER을_최근_연도로_잰다():
    m = q.price_metrics(_fin())
    assert abs(m.iloc[0]["PBR"] - (1e11 / 3e11)) < 1e-12
    assert abs(m.iloc[0]["PER"] - (1e11 / 3.5e10)) < 1e-12


def test_적자면_PER을_지어내지_않는다():
    m = q.price_metrics(_fin(당기순이익_y0=[-1e9]))
    assert pd.isna(m.iloc[0]["PER"])


def test_성장률에_견주어도_싼지_본다():
    m = q.price_metrics(_fin())
    assert m.iloc[0]["성장대비PER"] > 0


def test_성장이_마이너스면_성장대비PER을_내지_않는다():
    m = q.price_metrics(_fin(영업이익_y0=[1e10], 영업이익_y2=[4e10]))
    assert pd.isna(m.iloc[0]["성장대비PER"])


def test_최근_1년에서_어디쯤인지_잰다():
    아래 = q.price_metrics(_fin(), _prices(close=4200.0))
    위 = q.price_metrics(_fin(), _prices(close=9000.0))
    assert 아래.iloc[0]["1년위치%"] == 0.0
    assert 위.iloc[0]["1년위치%"] == 100.0


def test_저점까지_얼마나_남았는지_잰다():
    m = q.price_metrics(_fin(), _prices(close=5000.0, low=4000.0))
    assert abs(m.iloc[0]["저점까지%"] - (-20.0)) < 1e-9


def test_시세가_없으면_가격_위치를_비워_둔다():
    m = q.price_metrics(_fin(), None)
    assert "1년위치%" not in m.columns


# ────────────────────── 두 축이 섞이지 않는가 ──────────────────────

def test_좋고_싸면_후보다():
    결과 = q.evaluate(_fin(), _prices())
    assert 결과.iloc[0]["판정"] == "후보"


def test_좋은데_비싸면_비쌈이다():
    """좋은 기업도 너무 비싸게 사면 오래 손실을 봅니다."""
    결과 = q.evaluate(_fin(marcap=[3e12]), _prices(close=80000.0,
                                                 high=90000.0, low=40000.0))
    assert 결과.iloc[0]["판정"] == "비쌈"


def test_싼데_기업이_약하면_함정으로_본다():
    """싼 주식도 기업이 나쁘면 계속 싸집니다."""
    약함 = _fin(marcap=[2e10],
              매출액_y0=[1e11], 매출액_y2=[1.5e11],       # 매출 감소
              영업이익_y0=[1e9], 영업이익_y2=[6e9],        # 이익 감소
              당기순이익_y0=[3e9],
              부채총계_y0=[1.4e11], 자본총계_y0=[6e10],   # 부채비율 233%
              영업활동현금흐름_y0=[-2e9])                  # 현금 유출
    결과 = q.evaluate(약함, _prices(close=900.0, high=3000.0, low=800.0))
    assert 결과.iloc[0]["판정"] in ("함정?", "제외")
    assert 결과.iloc[0]["기업점수"] < q.GOOD_BUSINESS


def test_항목이_모자라면_판단을_보류한다():
    """모르는 것을 좋다고도 나쁘다고도 하지 않습니다."""
    거의없음 = pd.DataFrame({"code": ["000001"], "name": ["가"], "marcap": [1e11]})
    결과 = q.evaluate(거의없음, None)
    assert 결과.iloc[0]["판정"] == "판단보류"


def test_점수를_하나로_합치지_않는다():
    결과 = q.evaluate(_fin(), _prices())
    assert "기업점수" in 결과.columns and "가격점수" in 결과.columns
    assert "종합점수" not in 결과.columns


# ────────────────────── 보고서 ──────────────────────

def test_보고서는_두_축을_나눠_보여준다():
    글 = q.report(q.evaluate(_fin(), _prices()))
    assert "좋은 기업인가" in 글 and "값이 괜찮은가" in 글
    assert "기업" in 글 and "가격" in 글


def test_보고서는_왜_따로_보는지_설명한다():
    글 = q.report(q.evaluate(_fin(), _prices()))
    assert "너무 비싸게 사면" in 글
    assert "계속 싸집니다" in 글
    assert "합치지 않습니다" in 글


def test_보고서는_점수를_믿지_말라고_말한다():
    글 = q.report(q.evaluate(_fin(), _prices()))
    assert "0.779" in 글 and "0.626" in 글       # 전에 실패한 점수 체계
    assert "근거는 아직 없습니다" in 글


def test_후보가_없으면_어느_쪽이_모자라는지_보라고_한다():
    비쌈 = q.evaluate(_fin(marcap=[3e12]), _prices(close=80000.0,
                                                high=90000.0, low=40000.0))
    글 = q.report(비쌈)
    assert "어느 쪽이 모자라는지" in 글


def test_빈_표여도_터지지_않는다():
    assert "볼 종목이 없습니다" in q.report(pd.DataFrame(columns=["판정"]))
