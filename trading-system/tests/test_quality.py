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

def test_터미널_보고서는_두_축_점수를_따로_적는다():
    글 = q.report(q.evaluate(_fin(), _prices()))
    assert "기업" in 글 and "가격" in 글
    assert "점" in 글


def test_왜_따로_보는지는_한_장짜리_화면에_적는다():
    """터미널은 짧게, 설명은 브라우저로 여는 화면에."""
    page = q.render_html(q.evaluate(_fin(), _prices()))
    assert "너무 비싸게 사면" in page
    assert "계속 싸집니다" in page
    assert "합치면" in page


def test_점수를_믿지_말라는_말은_화면에_남긴다():
    page = q.render_html(q.evaluate(_fin(), _prices()))
    assert "0.779" in page and "0.626" in page
    assert "근거는 아직 없습니다" in page


def test_고를_것이_없으면_어느_쪽이_모자라는지_보라고_한다():
    비쌈 = q.evaluate(_fin(marcap=[3e12]), _prices(close=80000.0,
                                                high=90000.0, low=40000.0))
    글 = q.report(비쌈)
    assert "비쌈" in 글 or "함정" in 글


def test_빈_표여도_터지지_않는다():
    assert "볼 종목이 없습니다" in q.report(pd.DataFrame(columns=["판정"]))


# ────────────────── 눈에 들어오는가 ──────────────────
# 73종목을 표로 쏟아내면 아무것도 안 보입니다. 사장님이 원하신 것은
# 목록이 아니라 '확실한 2~3종목' 입니다.

def _many(n=60, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "code": [f"{i:06d}" for i in range(n)],
        "name": [f"가나다{i}" for i in range(n)],
        "marcap": rng.uniform(5e10, 5e11, n),
        "매출액_y0": rng.uniform(1e11, 4e11, n),
        "매출액_y2": rng.uniform(0.8e11, 3e11, n),
        "영업이익_y0": rng.uniform(1e9, 6e10, n),
        "영업이익_y2": rng.uniform(1e9, 4e10, n),
        "당기순이익_y0": rng.uniform(1e9, 4e10, n),
        "자본총계_y0": rng.uniform(5e10, 4e11, n),
        "부채총계_y0": rng.uniform(2e10, 2e11, n),
        "영업활동현금흐름_y0": rng.uniform(1e9, 5e10, n),
        "설비투자_y0": rng.uniform(1e9, 1e10, n),
    }), pd.DataFrame({
        "close": rng.uniform(3000, 50000, n),
        "high_52w": rng.uniform(50000, 90000, n),
        "low_52w": rng.uniform(2000, 3000, n),
    })


def test_양쪽_다_높은_것만_따로_골라낸다():
    frame, prices = _many()
    결과 = q.evaluate(frame, prices)
    좁힘 = q.shortlist(결과)
    assert len(좁힘) < len(결과[결과["판정"] == "후보"])
    assert (좁힘["기업점수"] >= q.STRICT_BUSINESS).all()
    assert (좁힘["가격점수"] >= q.STRICT_PRICE).all()


def test_터미널_보고서는_짧게_유지한다():
    """표를 쏟아내면 아무것도 눈에 안 들어옵니다."""
    frame, prices = _many(60)
    글 = q.report(q.evaluate(frame, prices))
    assert len(글.splitlines()) < 60


def test_좁혀서_없으면_어느_쪽이_모자라는지_말한다():
    frame, prices = _many(20, seed=7)
    결과 = q.evaluate(frame, prices)
    결과["기업점수"] = 10.0          # 아무것도 못 넘게
    글 = q.report(결과)
    assert "없습니다" in 글


# ────────────────── 보기 좋은 한 장 ──────────────────

def test_한_장짜리_HTML이_나온다():
    frame, prices = _many()
    page = q.render_html(q.evaluate(frame, prices))
    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")


def test_외부에서_아무것도_불러오지_않는다():
    """인터넷 없이도 열려야 합니다."""
    frame, prices = _many()
    page = q.render_html(q.evaluate(frame, prices))
    assert "<script src=" not in page and "<link" not in page
    assert "http://" not in page and "https://" not in page


def test_두_축을_막대로_따로_보여준다():
    frame, prices = _many()
    page = q.render_html(q.evaluate(frame, prices))
    assert "기업이 좋은가" in page and "값이 괜찮은가" in page


def test_HTML도_점수를_믿지_말라고_말한다():
    frame, prices = _many()
    page = q.render_html(q.evaluate(frame, prices))
    assert "0.779" in page and "0.626" in page
    assert "매수·매도를 판단하지 않습니다" in page


def test_종목명에_꺾쇠가_들어와도_화면이_안_깨진다():
    frame, prices = _many(10)
    frame.loc[0, "name"] = "<script>alert(1)</script>"
    page = q.render_html(q.evaluate(frame, prices))
    assert "<script>alert(1)</script>" not in page


# ────────────── 숫자를 주는 게 아니라 무엇을 할지 알려주는가 ──────────────
# 표만 드리고 '알아서 판단하세요' 하는 건 도움이 아닙니다.

def _row(**over):
    base = dict(name="어떤회사", code="108380", 기업점수=87.0, 가격점수=90.0,
                 매출성장=22.1, 영업이익률=11.8, 부채비율=20.0,
                 현금전환배수=0.63, PBR=0.64, PER=7.0, 영업PER=7.5,
                 위치=20.0, close=18800.0, low_52w=15500.0, high_52w=32000.0)
    base.update(over)
    return pd.Series({
        "name": base["name"], "code": base["code"],
        "기업점수": base["기업점수"], "가격점수": base["가격점수"],
        "매출성장%": base["매출성장"], "영업이익률%": base["영업이익률"],
        "부채비율%": base["부채비율"], "현금전환배수": base["현금전환배수"],
        "PBR": base["PBR"], "PER": base["PER"], "영업PER": base["영업PER"],
        "1년위치%": base["위치"], "close": base["close"],
        "low_52w": base["low_52w"], "high_52w": base["high_52w"],
    })


def test_한_문장으로_어떤_회사인지_말한다():
    말 = q.one_line(_row())
    assert "매출이 해마다 늘고" in 말
    assert "빚도 적은" in 말
    assert "싸게 거래" in 말


def test_좋은_점을_숫자에서_뽑아_말로_적는다():
    좋은것 = q.good_points(_row())
    assert any("매출이 3년째" in x for x in 좋은것)
    assert any("빚이 자기 돈의" in x for x in 좋은것)


def test_걸리는_점도_이유와_함께_적는다():
    나쁨 = _row(매출성장=-8.0, 영업이익률=2.0, 부채비율=250.0, 현금전환배수=0.2)
    걸림 = q.worry_points(나쁨)
    assert any("줄고 있습니다" in x for x in 걸림)
    assert any("이자 부담" in x for x in 걸림)
    assert any("돈을 못 받았을" in x for x in 걸림)


def test_일회성_이익이_섞였으면_짚어준다():
    """PER 이 싸 보이는데 본업만 보면 비싼 경우."""
    걸림 = q.worry_points(_row(PER=2.0, 영업PER=15.0))
    assert any("일회성 이익이 섞였을" in x for x in 걸림)


def test_걸리는_게_없어도_숫자가_전부는_아니라고_말한다():
    걸림 = q.worry_points(_row())
    assert any("숫자로 안 보이는 것이 더 많습니다" in x for x in 걸림)


def test_무엇을_하면_되는지_순서대로_알려준다():
    단계 = q.next_steps(_row())
    assert any("뭘 파는 회사인지" in x for x in 단계)
    assert any("dart-dashboard --code 108380" in x for x in 단계)


def test_마지막은_언제나_사지_말고_기록만이다():
    단계 = q.next_steps(_row())
    assert "사지 마시고 먼저 기록만" in 단계[-1]
    assert "journal-add" in 단계[-1]


def test_빚이_많으면_확인할_것을_더_붙인다():
    단계 = q.next_steps(_row(부채비율=250.0))
    assert any("이자를 감당하는지" in x for x in 단계)


# ────────────── 얼마에 사면 어떻게 되나 ──────────────

def test_목표와_무효선을_지금_값에서_계산한다():
    선 = q.price_levels(_row(close=10000.0))
    assert 선["목표가"] == 12000.0          # +20%
    assert 선["무효선"] == 8800.0           # -12%


def test_회사_재산만큼의_값을_알려준다():
    선 = q.price_levels(_row(close=10000.0, PBR=0.5))
    assert 선["재산값"] == 20000.0          # 현재가 ÷ PBR


def test_값이_없으면_계산하지_않는다():
    assert q.price_levels(_row(close=float("nan"))) == {}


def test_화면에_예측이_아니라고_반드시_적는다():
    """산수를 예측으로 읽으면 안 됩니다.

    (표본이 작으면 고른 종목이 하나도 안 남아 카드가 안 그려집니다.
     넉넉히 잡습니다.)
    """
    frame, prices = _many(80)
    결과 = q.evaluate(frame, prices)
    assert not q.shortlist(결과).empty, "고른 종목이 없어 검사가 되지 않습니다"
    page = q.render_html(결과)
    assert "오른다는 예측이 아닙니다" in page
    assert "목표" in page and "무효선" in page


def test_공시_위험이_있으면_카드에_같이_보인다():
    frame, prices = _many(80)
    결과 = q.evaluate(frame, prices)
    좁힘 = q.shortlist(결과)
    assert not 좁힘.empty
    코드 = str(좁힘.iloc[0]["code"])
    page = q.render_html(결과, risks={코드: [{
        "label": "횡령·배임", "severity": "위험", "rcept_dt": "20260702",
        "report_nm": "횡령·배임혐의진행사항",
        "why": "상장적격성 실질심사 대상이 될 수 있습니다."}]})
    assert "횡령·배임" in page
    assert "실질심사" in page
