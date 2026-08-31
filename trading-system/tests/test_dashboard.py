"""기업분석 화면 검사.

여기서 제일 중요한 것은 '없는 것을 있는 척하지 않는가' 입니다.
빈칸을 0 으로 채우면 화면은 그럴듯해지고 판단은 망가집니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import dashboard as dash


def _trend(**over):
    base = {"매출액": [1e11, 1.2e11], "영업이익": [1e10, 1.5e10],
            "당기순이익": [8e9, 1.2e10], "자산총계": [2e11, 2.4e11],
            "부채총계": [5e10, 6e10], "자본총계": [1.5e11, 1.8e11]}
    base.update(over)
    return pd.DataFrame(base, index=[2024, 2025])


def _snap(**over):
    base = dict(code="032820", name="우리기술", market="KOSDAQ",
                price=11600.0, price_date="2026-08-31", change_pct=-1.2,
                marcap=3.6e11, high_52w=29300.0, low_52w=3735.0,
                trend=_trend(), corp_code="00123456", fetched_at="2026-08-31")
    base.update(over)
    snap = dash.Snapshot(**base)
    if snap.ratios.empty and not snap.trend.empty:
        snap.ratios = pd.DataFrame({
            "영업이익률%": snap.trend["영업이익"] / snap.trend["매출액"] * 100,
            "부채비율%": snap.trend["부채총계"] / snap.trend["자본총계"] * 100,
        })
    return snap


# ────────────────────── 계산 ──────────────────────

def test_PBR은_시가총액을_최근_자본총계로_나눈다():
    snap = _snap()
    assert abs(snap.pbr - (3.6e11 / 1.8e11)) < 1e-9


def test_적자면_PER을_지어내지_않는다():
    snap = _snap(trend=_trend(당기순이익=[-1e9, -2e9]))
    assert pd.isna(snap.per)


def test_자본이_마이너스면_PBR도_ROE도_빈칸이다():
    snap = _snap(trend=_trend(자본총계=[1e11, -5e9]))
    assert pd.isna(snap.pbr) and pd.isna(snap.roe)


def test_시가총액을_못_받으면_비율을_만들지_않는다():
    snap = _snap(marcap=float("nan"))
    assert pd.isna(snap.per) and pd.isna(snap.pbr)


def test_52주_위치는_저점0_고점100이다():
    assert _snap(price=3735.0).position_52w == 0.0
    assert _snap(price=29300.0).position_52w == 100.0
    중간 = _snap(price=(3735.0 + 29300.0) / 2).position_52w
    assert abs(중간 - 50.0) < 1e-9


def test_고저가가_없으면_위치도_빈칸이다():
    assert pd.isna(_snap(high_52w=float("nan")).position_52w)


# ────────────────────── 요약 ──────────────────────

def test_요약은_계산된_사실만_잇는다():
    말 = dash.ten_second(_snap())
    붙임 = " ".join(말)
    assert "20.0%" in 붙임 or "20%" in 붙임      # 매출 1e11 → 1.2e11
    assert "PBR" in 붙임 or "배" in 붙임


def test_재무가_없으면_없다고_말한다():
    말 = dash.ten_second(_snap(trend=pd.DataFrame()))
    assert "재무 자료를 받지 못했습니다" in " ".join(말)


def test_적자면_적자라고_말한다():
    말 = dash.ten_second(_snap(trend=_trend(영업이익=[-1e9, -2e9])))
    assert "적자" in " ".join(말)


# ────────────────────── 화면 ──────────────────────

def test_한_장짜리_HTML이_나온다():
    page = dash.render(_snap())
    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")
    assert "우리기술" in page


def test_외부_스크립트나_스타일을_불러오지_않는다():
    """인터넷 없이도 열려야 합니다."""
    page = dash.render(_snap())
    assert "http://" not in page.replace("opendart.fss.or.kr", "")
    assert "<script src=" not in page
    assert "<link" not in page


def test_없는_항목은_확인_어려움이라고_적는다():
    page = dash.render(_snap())
    assert dash.MISSING in page
    assert "Forward PER" in page          # 없다고 밝히는 자리


def test_현금흐름이_없으면_0으로_채우지_않는다():
    """빈칸을 0 으로 채우면 '투자를 안 한 알짜 회사' 처럼 보입니다.

    ("0원" 을 통째로 찾으면 "11,600원" 같은 주가에도 걸립니다.
     현금흐름 칸만 따로 봅니다.)
    """
    현금칸 = dash._panel_cash(_snap(cash=pd.DataFrame()))
    assert dash.MISSING in 현금칸
    assert "본업에서 들어온 현금" not in 현금칸      # 큰 숫자 칸을 아예 안 그림
    assert "0" not in 현금칸.replace("확인 어려움", "")


def test_현금흐름이_있으면_세_숫자를_크게_보여준다():
    cash = pd.DataFrame({"영업활동현금흐름": [3e10], "설비투자": [1e10],
                         "잉여현금흐름": [2e10]}, index=[2025])
    현금칸 = dash._panel_cash(_snap(cash=cash))
    assert "본업에서 들어온 현금" in 현금칸
    assert "투자 후 남은 현금" in 현금칸
    assert "200억" in 현금칸


def test_사실과_해석을_갈라_적는다():
    page = dash.render(_snap())
    assert "확인된 사실" in page
    assert "계산에서 바로 나오는 해석" in page


def test_매수매도를_판단하지_않는다고_반드시_적는다():
    page = dash.render(_snap())
    assert "매수·매도를 판단하지 않습니다" in page


def test_공시가_늦다는_것을_적는다():
    assert "90일" in dash.render(_snap())


def test_출처를_밝힌다():
    page = dash.render(_snap())
    assert "opendart.fss.or.kr" in page
    assert "FinanceDataReader" in page


def test_계산식을_화면에_적는다():
    page = dash.render(_snap())
    assert "PBR = 시가총액" in page


def test_종목명에_들어간_꺾쇠가_화면을_깨지_않는다():
    page = dash.render(_snap(name="<script>alert(1)</script>"))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_자료가_하나도_없어도_화면이_만들어진다():
    빈것 = dash.Snapshot(code="000000", name="이름없음")
    page = dash.render(빈것)
    assert page.startswith("<!doctype html>")
    assert dash.MISSING in page


# ────────────────────── 그림 ──────────────────────

def test_막대는_값이_없으면_그리지_않는다():
    assert dash.MISSING in dash.bar_chart(pd.Series(dtype=float), "매출액")


def test_음수_막대를_따로_표시한다():
    바 = dash.bar_chart(pd.Series({2024: -1e10, 2025: 2e10}), "영업이익")
    assert "bar-fill neg" in 바


def test_금액은_조_억으로_줄여_쓴다():
    assert dash._fmt_money(3e14) == "300.00조"
    assert dash._fmt_money(-1e8) == "-1억"
    assert dash._fmt_money(float("nan")) == "—"
