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

def test_보고서는_먼저_한_줄로_답한다():
    """숫자를 늘어놓기 전에 결론을 말합니다."""
    글 = mo.report(_scored(40), "2026-08", 20, recorded=50, waiting=10)
    assert "한 줄로 말하면" in 글
    assert "코스닥 평균보다" in 글


def test_초과수익이_무슨_말인지_풀어_쓴다():
    """주식을 잘 모르는 사람이 읽어도 알 수 있어야 합니다."""
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "'초과수익' 이란" in 글
    assert "지수를 사는 게 나았다" in 글


def test_모양마다_무슨_뜻인지_붙인다():
    글 = mo.report(_scored(60), "2026-08", 20)
    assert "고르자마자 올랐습니다" in 글 or "먼저 빠졌다가 되돌아왔습니다" in 글


def test_모양에서_무엇을_고쳐야_하는지_알려준다():
    글 = mo.report(_scored(80, seed=5), "2026-08", 20)
    배움 = ["손절 3% 였다면", "오르기 전에 잘려나갑니다",
          "파는 규칙이 없어서", "이미 오른 뒤에 들어가고"]
    assert any(b in 글 for b in 배움)


def test_쪼갠_표에는_무엇을_보는_것인지_설명을_붙인다():
    글 = mo.report(_scored(80), "2026-08", 20)
    assert "거래량이 몇 배로 늘었을 때" in 글 or "얼마나 비싸게 시작했나" in 글


def test_보고서는_쪼갠_표를_믿지_말라고_반드시_말한다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "참고만" in 글
    assert "우연히" in 글


def test_보고서는_조건을_바꾸면_기록이_증거가_안_된다고_말한다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "증거가 되지 못합니다" in 글
    assert "처음부터 다시 쌓아야" in 글


def test_표본이_적으면_판정하지_말라고_말한다():
    글 = mo.report(_scored(12), "2026-08", 20)
    assert "아무 뜻이 없습니다" in 글


def test_충분히_모이면_비용을_빼라고_말한다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "왕복 0.51%" in 글


def test_보고서는_돈이_안_들어갔음을_밝힌다():
    글 = mo.report(_scored(40), "2026-08", 20)
    assert "돈은 아직 한 푼도 안 들어갔습니다" in 글
    assert "수익 보고서가 아닙니다" in 글


def test_채점할_것이_없으면_얼마나_기다려야_하는지_말한다():
    글 = mo.report(pd.DataFrame(), "2026-08", 20, recorded=5, waiting=5)
    assert "아직 성적을 매길 수 있는 게 없습니다" in 글
    assert "한 달쯤 기다리셔야" in 글


def test_계산_기준을_같이_남긴다():
    """나중에 '그때 어떻게 쟀지?' 를 물을 수 있어야 합니다."""
    글 = mo.report(_scored(40), "2026-08", 20,
                  basis="보유 20거래일 · 지수 KQ11 · 판 v1")
    assert "계산 기준:" in 글
    assert "판 v1" in 글


def test_텔레그램_한_건에_들어간다():
    """한 건 제한이 4096자입니다. 넘으면 잘려서 갑니다."""
    글 = mo.report(_scored(200), "2026-08", 20, recorded=300, waiting=100,
                  basis="보유 20거래일 · 지수 KQ11")
    assert len(글) < 4000


# ────────────────── 다음 달 준비 ──────────────────
# 지난달을 돌아보는 것만으로는 부족합니다. 다음 달에 무엇을 봐야
# 하는지까지 있어야 방향을 다시 잡을 수 있습니다.

def _ledger(n=10, target=3, invalid=2):
    return pd.DataFrame({
        "entry_date": ["2026-08-03"] * n,
        "target_hit_date": ["2026-08-20"] * target + [""] * (n - target),
        "invalid_hit_date": [""] * (n - invalid) + ["2026-08-15"] * invalid,
    })


def test_목표와_무효선_도달_현황을_센다():
    앞날 = mo.next_month(_ledger(10, target=3, invalid=2), scored_total=12)
    assert 앞날.target_hit == 3
    assert 앞날.invalid_hit == 2
    assert 앞날.still_open == 5          # 둘 다 아직인 것


def test_판정까지_몇_개_더_필요한지_알려준다():
    assert mo.next_month(pd.DataFrame(), scored_total=12).need_more == 18
    assert mo.next_month(pd.DataFrame(), scored_total=40).need_more == 0


def test_장부가_비어도_터지지_않는다():
    앞날 = mo.next_month(pd.DataFrame(), scored_total=0)
    assert 앞날.target_hit == 0 and 앞날.still_open == 0


def test_브리핑에_다음_달_볼_것이_들어간다():
    앞날 = mo.next_month(_ledger(10, 3, 2), scored_total=15)
    앞날.waiting = 7
    글 = mo.report(_scored(15), "2026-08", 20, recorded=22, waiting=7,
                  ahead=앞날, target_pct=20.0, invalid_pct=-12.0)
    assert "다음 달에 볼 것" in 글
    assert "아직 성적이 안 나온 것 7개" in 글
    assert "판정까지" in 글


def test_목표_퍼센트는_정한_값을_그대로_쓴다():
    앞날 = mo.next_month(_ledger(10, 3, 2), scored_total=15)
    글 = mo.report(_scored(15), "2026-08", 20, ahead=앞날,
                  target_pct=25.0, invalid_pct=-15.0)
    # 기본값(-20%)이 아니라 넘겨준 값이 나와야 합니다
    assert "25%" in 글 and "-15%" in 글


def test_다음_달에도_규칙을_그대로_두라고_말한다():
    앞날 = mo.next_month(_ledger(), scored_total=15)
    글 = mo.report(_scored(15), "2026-08", 20, ahead=앞날)
    assert "규칙은 그대로 둡니다" in 글


def test_표본이_찼으면_비용을_따질_때라고_말한다():
    앞날 = mo.next_month(_ledger(), scored_total=40)
    글 = mo.report(_scored(40), "2026-08", 20, ahead=앞날)
    assert "넘겼습니다" in 글
    assert "비용을 뺀 실제 손익" in 글


def test_아직_성적이_없어도_다음_달_안내는_나온다():
    앞날 = mo.next_month(pd.DataFrame(), scored_total=0)
    앞날.waiting = 12
    글 = mo.report(pd.DataFrame(), "2026-08", 20, recorded=12, waiting=12,
                  ahead=앞날)
    assert "다음 달에 볼 것" in 글
    assert "12개의 점수가 나옵니다" in 글
