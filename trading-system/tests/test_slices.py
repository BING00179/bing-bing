"""조각내서 보기 검사.

여기서 제일 중요한 것은 '좋은 조각을 찾아내는가' 가 아니라
**'없는데 있다고 하지 않는가'** 입니다. 조각을 많이 만들면 아무 뜻
없는 자료에서도 하나쯤은 반드시 좋아 보입니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import slices as sl


def _signals(n=1000, seed=0, horizon=20, effect=None):
    """신호 표를 만듭니다. effect 를 주면 그 열에 따라 수익이 달라집니다."""
    rng = np.random.default_rng(seed)
    날 = pd.bdate_range("2024-01-01", periods=n)
    frame = pd.DataFrame({
        "entry_date": 날,
        "turnover": rng.uniform(1e8, 1e10, n),
        "base_range_pct": rng.uniform(5, 60, n),
        "volume_mult": rng.uniform(1, 20, n),
        "runup_pct": rng.uniform(-10, 60, n),
        "signal_close": rng.uniform(500, 100_000, n),
        "gap_pct": rng.normal(0, 3, n),
    })
    값 = rng.normal(0, 8, n)
    if effect:
        열, 세기 = effect
        값 = 값 + 세기 * (frame[열] > frame[열].median())
    frame[f"fwd{horizon}"] = 값
    return frame


def _market(signals, horizon=20):
    return pd.DataFrame({f"fwd{horizon}": 0.0},
                        index=pd.DatetimeIndex(signals["entry_date"]))


# ────────────── 조각 수만큼 기준을 올리는가 ──────────────

def test_조각을_많이_볼수록_통과선이_올라간다():
    assert sl.required_t(1) < sl.required_t(6) < sl.required_t(30)
    assert abs(sl.required_t(1) - 1.96) < 0.01


def test_조각_하나면_보통_기준이다():
    assert abs(sl.required_t(1) - 1.9600) < 0.001


def test_본_조각_수를_실제로_세서_기준을_정한다():
    s = _signals(1200)
    rows, bar = sl.all_cuts(s, _market(s), 20)
    assert len(rows) > 6
    assert abs(bar - sl.required_t(len(rows))) < 1e-9


# ────────────── 없는 것을 있다고 하지 않는가 ──────────────

def test_아무_뜻_없는_자료에서는_통과가_없다():
    """이게 이 모듈의 존재 이유입니다.

    무작위 자료를 조각내면 t 1.96 을 넘는 조각이 심심찮게 나옵니다.
    올린 기준이 그걸 걸러야 합니다.
    """
    샜다 = 0
    for seed in range(12):
        s = _signals(1200, seed=seed)
        rows, bar = sl.all_cuts(s, _market(s), 20)
        if any(r.passes(bar) and r.excess > 0 for r in rows):
            샜다 += 1
    assert 샜다 <= 1, f"무작위 자료 12번 중 {샜다}번이나 통과했습니다"


def test_기준을_안_올리면_무작위에서도_통과가_나온다():
    """올려 잡는 게 왜 필요한지 보여주는 검사입니다."""
    샜다 = 0
    for seed in range(12):
        s = _signals(1200, seed=seed)
        rows, _ = sl.all_cuts(s, _market(s), 20)
        if any(r.passes(1.96) and r.excess > 0 for r in rows):
            샜다 += 1
    assert 샜다 >= 3, "기준을 안 올려도 안 새면 이 검사가 뜻이 없습니다"


def test_보고서가_통과_없음을_숨기지_않는다():
    s = _signals(1200, seed=3)
    rows, bar = sl.all_cuts(s, _market(s), 20)
    글 = sl.report(rows, bar, 20, total=len(s))
    if not any(r.passes(bar) and r.excess > 0 for r in rows):
        assert "통과한 조각이 없습니다" in 글


# ────────────── 있는 것은 찾아내는가 ──────────────

def test_진짜_차이가_있으면_찾아낸다():
    s = _signals(3000, seed=1, effect=("volume_mult", 4.0))
    rows, bar = sl.all_cuts(s, _market(s), 20)
    통과 = [r for r in rows if r.passes(bar) and r.excess > 0]
    assert 통과, "실제로 심어둔 차이를 못 찾았습니다"
    assert any(r.cut == "깨어난 세기" for r in 통과)


def test_반대로_나쁜_조각도_알려준다():
    s = _signals(3000, seed=2, effect=("gap_pct", -4.0))
    rows, bar = sl.all_cuts(s, _market(s), 20)
    나쁜 = [r for r in rows if r.passes(bar) and r.excess < 0]
    assert 나쁜
    글 = sl.report(rows, bar, 20)
    assert "피할 것" in 글


# ────────────── 자료가 모자랄 때 ──────────────

def test_조각이_작으면_보지_않는다():
    s = _signals(120)
    rows = sl.by_cut(s, _market(s), "turnover", "거래대금", 20, q=5)
    assert rows == []          # 120건을 5조각 내면 하나에 24건뿐


def test_없는_열은_건너뛴다():
    s = _signals(1200).drop(columns=["turnover"])
    rows = sl.by_cut(s, _market(s), "turnover", "거래대금", 20)
    assert rows == []


def test_시장자료가_비면_아무것도_못_잰다():
    s = _signals(1200)
    rows = sl.by_cut(s, pd.DataFrame(), "turnover", "거래대금", 20)
    assert rows == []


def test_보고서가_탐색이라고_못박는다():
    s = _signals(3000, seed=1, effect=("volume_mult", 4.0))
    rows, bar = sl.all_cuts(s, _market(s), 20)
    글 = sl.report(rows, bar, 20)
    assert "탐색이지 검증이 아닙니다" in 글
