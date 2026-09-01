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
    """자본잠식 회사가 '빈칸이니까 조건 통과' 로 올라오면 안 됩니다.

    (사유 이름은 'PBR높음' 이 아니라 '순재산자료없음' 입니다 —
     비싸서 떨어진 것과 계산이 안 돼서 떨어진 것을 갈라 적기 때문입니다.)
    """
    out = _screen(fin=_fin(자본총계=[-1e10]))
    assert not bool(out.iloc[0]["통과"])
    assert "순재산자료없음" in out.iloc[0]["탈락사유"]
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


# ────────────── 자료가 없어서 떨어진 것과 비싸서 떨어진 것 ──────────────
# 둘을 뭉뚱그리면, 숫자가 안 들어온 것을 시장이 비싼 것으로 오해합니다.
# 실제로 코스닥 99종목이 전부 'PER높음' 으로 떨어진 적이 있습니다.

def test_이익을_못_읽으면_비싸다고_하지_않는다():
    out = _screen(fin=_fin(당기순이익=[np.nan]))
    사유 = out.iloc[0]["탈락사유"]
    assert "이익자료없음" in 사유
    assert "PER높음" not in 사유


def test_진짜_비싸면_비싸다고_한다():
    out = _screen(listing=_listing(marcap=[1e13]))   # PER 500배
    사유 = out.iloc[0]["탈락사유"]
    assert "PER높음" in 사유
    assert "이익자료없음" not in 사유


def test_자본을_못_읽으면_PBR도_갈라_적는다():
    out = _screen(fin=_fin(자본총계=[np.nan]))
    사유 = out.iloc[0]["탈락사유"]
    assert "순재산자료없음" in 사유
    assert "PBR높음" not in 사유


def test_항목별로_숫자가_들어온_비율을_센다():
    val = v.valuation(_listing(code=["A", "B"], name=["가", "나"],
                               close=[1.0, 2.0], marcap=[1e11, 1e11],
                               turnover=[1e9, 1e9]),
                      _fin(code=["A", "B"], bsns_year=[2025, 2025],
                           rcept_dt=["20260315"] * 2,
                           매출액=[1e11, 2e11], 영업이익=[1e10, 2e10],
                           당기순이익=[1e10, np.nan],
                           자산총계=[2e11, 3e11], 부채총계=[5e10, 6e10],
                           자본총계=[1.5e11, 2e11]))
    표 = v.completeness(val)
    이익 = 표[표["항목"] == "당기순이익"].iloc[0]
    assert 이익["값이 있는 종목"] == 1 and 이익["비율%"] == 50.0


def test_자료가_모자라면_보고서가_경고한다():
    out = _screen(fin=_fin(당기순이익=[np.nan]))
    text = v.report(out, v.Screen())
    assert "자료가 덜 들어온 항목" in text
    assert "조건을 풀어도 안 나옵니다" in text


def test_자료탓일_때는_조건을_풀라고_하지_않는다():
    text = v.report(_screen(fin=_fin(당기순이익=[np.nan])), v.Screen())
    assert "조건을 조금 풀어보세요" not in text


# ────────────── 계정명 변형 ──────────────

def test_계정명이_조금_달라도_같은_뜻으로_읽는다():
    assert v._canonical("당기순이익(손실)") == "당기순이익"
    assert v._canonical("수익(매출액)") == "매출액"
    assert v._canonical("영업이익(손실)") == "영업이익"
    assert v._canonical("자본 총계") == "자본총계"      # 띄어쓰기 무시


def test_모르는_계정은_읽지_않는다():
    assert v._canonical("이연법인세자산") is None


# ────────────────────── 20~40분짜리 작업이 살아남는가 ──────────────────────

def test_한_종목이_끊겨도_나머지는_지킨다(monkeypatch):
    """종목 하나 때문에 1,800종목이 통째로 날아가면 안 됩니다."""
    from src import dart_kr

    index = pd.DataFrame([{"corp_code": f"C{i}", "corp_name": f"회사{i}",
                           "stock_code": f"00000{i}"} for i in range(3)])

    def 가짜재무(key, corp, year, report="11011"):
        if corp == "C1":
            raise dart_kr.DartUnreachable("DART 에 3번 시도했지만 닿지 못했습니다")
        return pd.DataFrame([{"account_nm": "매출액", "fs_div": "CFS",
                              "thstrm_amount": "1000", "rcept_no": "20260315000001"}])

    monkeypatch.setattr(dart_kr, "finstate", 가짜재무)
    fin, 실패 = v.latest_financials("키", index, ["000000", "000001", "000002"],
                                    progress=0)
    assert list(fin["code"]) == ["000000", "000002"]     # 가운데만 빠짐
    assert 실패 == ["000001"]


def test_중간_저장을_불러준다(monkeypatch):
    """끊겨도 받은 데까지는 파일에 남아야 이어받을 수 있습니다."""
    from src import dart_kr

    index = pd.DataFrame([{"corp_code": f"C{i}", "corp_name": f"회사{i}",
                           "stock_code": f"00000{i}"} for i in range(3)])
    monkeypatch.setattr(dart_kr, "finstate", lambda *a, **k: pd.DataFrame(
        [{"account_nm": "매출액", "fs_div": "CFS", "thstrm_amount": "1000",
          "rcept_no": "20260315000001"}]))

    저장된것 = []
    v.latest_financials("키", index, ["000000", "000001", "000002"],
                        progress=2, on_partial=저장된것.append)
    assert 저장된것                                   # 중간에 한 번은 불렀어야 함
    assert len(저장된것[-1]) >= 2


def test_계정이_하나도_안_맞아도_표는_모양을_지킨다():
    frame = v._to_frame([{"code": "A", "bsns_year": 2025, "rcept_dt": "20260315"}])
    assert list(frame.columns) == list(v.FIN_COLUMNS)
    assert pd.isna(frame.iloc[0]["매출액_y0"])       # 3년치 형식


def test_예전_형식의_재무_파일도_읽힌다():
    """열 이름이 바뀌었다고 옛 파일을 가진 사람이 갑자기 못 쓰면 안 됩니다."""
    옛것 = pd.DataFrame({"code": ["000001"], "bsns_year": [2025],
                       "rcept_dt": ["20260315"],
                       "매출액": [3e11], "영업이익": [3e10],
                       "당기순이익": [2e10], "자산총계": [4e11],
                       "부채총계": [1e11], "자본총계": [3e11]})
    val = v.valuation(_listing(), 옛것)
    assert abs(val.iloc[0]["PBR"] - (1e11 / 3e11)) < 1e-12


def test_새_형식의_재무_파일도_읽힌다():
    새것 = pd.DataFrame({"code": ["000001"], "bsns_year": [2025],
                       "rcept_dt": ["20260315"],
                       "매출액_y0": [3e11], "영업이익_y0": [3e10],
                       "당기순이익_y0": [2e10], "자산총계_y0": [4e11],
                       "부채총계_y0": [1e11], "자본총계_y0": [3e11]})
    val = v.valuation(_listing(), 새것)
    assert abs(val.iloc[0]["PBR"] - (1e11 / 3e11)) < 1e-12
