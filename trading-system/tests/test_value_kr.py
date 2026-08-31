"""저평가 스크리너 검사.

제일 중요한 검사는 '모르는 것을 통과시키지 않는가' 입니다.
PBR 이 계산 안 된 종목을 통과시키면, 자본잠식 회사가 후보 목록
맨 위에 올라옵니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import value_kr as v


def _listing(**over):
    base = dict(code=["000001"], name=["가나"], close=[5000.0],
                marcap=[1e11], turnover=[2e9])
    base.update(over)
    return pd.DataFrame(base)


def _fin(**over):
    base = dict(code=["000001"], bsns_year=[2025], rcept_dt=["20260315"],
                매출액=[3e11], 영업이익=[3e10], 당기순이익=[2e10],
                자산총계=[4e11], 부채총계=[1e11], 자본총계=[3e11])
    base.update(over)
    return pd.DataFrame(base)


# ────────────────────── 계산 ──────────────────────

def test_PBR은_시가총액을_자본총계로_나눈_것이다():
    val = v.valuation(_listing(), _fin())
    assert abs(val.iloc[0]["PBR"] - (1e11 / 3e11)) < 1e-12


def test_PER은_시가총액을_당기순이익으로_나눈_것이다():
    val = v.valuation(_listing(), _fin())
    assert abs(val.iloc[0]["PER"] - (1e11 / 2e10)) < 1e-12


def test_자본이_마이너스면_PBR을_지어내지_않는다():
    val = v.valuation(_listing(), _fin(자본총계=[-1e10]))
    assert pd.isna(val.iloc[0]["PBR"])          # 음수로 나누면 마이너스 PBR


def test_적자면_PER이_빈칸이다():
    val = v.valuation(_listing(), _fin(당기순이익=[-1e10]))
    assert pd.isna(val.iloc[0]["PER"])


def test_자본이_0이어도_터지지_않는다():
    val = v.valuation(_listing(), _fin(자본총계=[0.0]))
    assert pd.isna(val.iloc[0]["PBR"])


def test_재무가_없는_종목은_빠진다():
    val = v.valuation(_listing(code=["000001", "000002"], name=["가", "나"],
                               close=[1.0, 2.0], marcap=[1e11, 1e11],
                               turnover=[1e9, 1e9]),
                      _fin())
    assert list(val["code"]) == ["000001"]


# ────────────────────── 거르기 ──────────────────────

def _screen(listing=None, fin=None, rule=None):
    # DataFrame 에 `or` 를 쓰면 진위 판정이 모호하다며 터집니다. is None 으로.
    listing = _listing() if listing is None else listing
    fin = _fin() if fin is None else fin
    return v.screen(v.valuation(listing, fin), rule or v.Screen())


def test_조건에_다_맞으면_통과한다():
    assert bool(_screen().iloc[0]["통과"])


def test_계산이_안_된_PBR은_통과시키지_않는다():
    """자본잠식 회사가 '빈칸이니까 조건 통과' 로 올라오면 안 됩니다."""
    out = _screen(fin=_fin(자본총계=[-1e10]))
    assert not bool(out.iloc[0]["통과"])
    assert "PBR높음" in out.iloc[0]["탈락사유"]
    assert "자본잠식" in out.iloc[0]["탈락사유"]


def test_영업적자를_거른다():
    out = _screen(fin=_fin(영업이익=[-1.0]))
    assert "영업적자" in out.iloc[0]["탈락사유"]


def test_영업적자_허용을_켜면_그_이유로는_안_거른다():
    out = _screen(fin=_fin(영업이익=[-1.0]),
                  rule=v.Screen(require_profit=False))
    assert "영업적자" not in out.iloc[0]["탈락사유"]


def test_부채비율_상한을_지킨다():
    out = _screen(fin=_fin(부채총계=[9e11]))       # 부채비율 300%
    assert "부채과다" in out.iloc[0]["탈락사유"]


def test_거래가_적으면_거른다():
    out = _screen(listing=_listing(turnover=[1e7]))
    assert "거래부족" in out.iloc[0]["탈락사유"]


def test_시가총액이_작으면_거른다():
    out = _screen(listing=_listing(marcap=[1e9]))
    assert "너무작음" in out.iloc[0]["탈락사유"]


def test_탈락_사유가_여러_개면_다_적는다():
    out = _screen(listing=_listing(marcap=[1e9], turnover=[1e7]))
    사유 = out.iloc[0]["탈락사유"]
    assert "너무작음" in 사유 and "거래부족" in 사유


def test_PER_조건을_끄면_적자도_PER로는_안_거른다():
    out = _screen(fin=_fin(당기순이익=[-1e10]),
                  rule=v.Screen(max_per=0, require_profit=False))
    assert "PER높음" not in out.iloc[0]["탈락사유"]


# ────────────────────── 순위 ──────────────────────

def test_PBR과_PER_순위를_같이_본다():
    """한 지표만 극단적으로 좋은 종목이 1등을 하면 안 됩니다."""
    frame = pd.DataFrame({
        "code": ["A", "B"],
        "PBR": [0.1, 0.5],      # A 가 훨씬 쌈
        "PER": [30.0, 6.0],     # 그런데 이익 대비로는 B 가 훨씬 나음
    })
    ranked = v.rank(frame)
    assert set(ranked["저평가점수"]) == {1.5, 1.5}    # 둘의 평균 순위가 같음


def test_양쪽_다_좋은_종목이_위로_온다():
    frame = pd.DataFrame({
        "code": ["A", "B", "C"],
        "PBR": [0.2, 0.5, 0.9],
        "PER": [4.0, 8.0, 20.0],
    })
    assert list(v.rank(frame)["code"]) == ["A", "B", "C"]


# ────────────────────── 보고서 ──────────────────────

def test_보고서는_사실과_해석을_가른다():
    text = v.report(_screen(), v.Screen())
    assert "[사실]" in text and "[해석]" in text


def test_보고서는_검증되지_않았음을_반드시_말한다():
    text = v.report(_screen(), v.Screen())
    assert "검증된 것이 아닙니다" in text
    assert "싼 데는 이유가 있습니다" in text


def test_보고서는_건_조건을_먼저_적는다():
    text = v.report(_screen(), v.Screen(max_pbr=0.7))
    assert "PBR ≤ 0.7" in text


def test_보고서는_탈락_사유를_세어_보여준다():
    out = _screen(fin=_fin(영업이익=[-1.0]))
    assert "영업적자" in v.report(out, v.Screen())


def test_통과가_없으면_조건을_풀라고_한다():
    out = _screen(rule=v.Screen(max_pbr=0.01))
    assert "조건을 조금 풀어보세요" in v.report(out, v.Screen(max_pbr=0.01))


def test_빈_표여도_터지지_않는다():
    assert "재무를 붙일 수 있는 종목이 없습니다" in v.report(pd.DataFrame(), v.Screen())
