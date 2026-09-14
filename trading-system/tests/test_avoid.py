"""피할 것 검사.

제일 중요한 것은 **아무 조건이나 통과시키지 않는가** 입니다.
남는 쪽만 보면 아무거나 걸러내도 평균이 흔들립니다. 제외되는 쪽
자체가 나빠야 그 조건이 값을 합니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import avoid as av


def _signals(n=2000, seed=0, horizon=20, bad_when=None):
    """bad_when=(열, 임계) 를 주면 그 위쪽만 실제로 나쁘게 만듭니다."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "entry_date": pd.bdate_range("2023-01-02", periods=n),
        # 거래량 배수는 오른쪽으로 긴 꼬리를 갖습니다. 균등분포로 만들면
        # 12배 넘는 것이 70% 가 되어 현실과 딴판이 됩니다.
        "volume_mult": rng.lognormal(1.3, 0.9, n),
        "turnover": rng.uniform(1e8, 5e10, n),
        "gap_pct": rng.normal(0, 3, n),
        "runup_pct": rng.uniform(-10, 60, n),
        "base_range_pct": rng.uniform(5, 45, n),
        "signal_close": rng.uniform(500, 100_000, n),
    })
    값 = rng.normal(0, 6, n)
    if bad_when:
        열, 임계 = bad_when
        값 = 값 - 8.0 * (frame[열] > 임계)
    frame[f"fwd{horizon}"] = 값
    return frame


def _market(signals, horizon=20):
    return pd.DataFrame({f"fwd{horizon}": 0.0},
                        index=pd.DatetimeIndex(signals["entry_date"]))


# ────────── 제외되는 쪽을 보는가 ──────────

def test_제외되는_쪽이_나쁘면_찾아낸다():
    s = _signals(3000, seed=1, bad_when=("volume_mult", 12.0))
    규칙 = av.CANDIDATES[0]           # 거래량 폭증 12배 이상
    결과 = av.evaluate(s, _market(s), 20, 규칙, "시험")
    assert 결과.excluded.excess < -3.0
    assert 결과.excluded.t_stat < -5.0
    assert av.passes([결과], bar=2.5)


def test_아무_뜻_없는_조건은_통과시키지_않는다():
    """이게 이 검사의 존재 이유입니다."""
    샜다 = 0
    for seed in range(12):
        s = _signals(3000, seed=seed)          # 아무 관계 없음
        bar = av.bar_for(len(av.CANDIDATES))
        결과들 = [av.evaluate(s, _market(s), 20, r, "시험")
                for r in av.CANDIDATES]
        if any(av.passes([r], bar) for r in 결과들 if r):
            샜다 += 1
    assert 샜다 <= 1, f"무작위 자료 12번 중 {샜다}번이나 통과했습니다"


def test_남는_쪽이_좋아_보이는_것만으로는_통과가_아니다():
    """아무거나 걸러내도 남는 쪽 평균은 흔들립니다.

    제외되는 쪽 자체가 유의하게 나빠야 조건이 값을 합니다.
    """
    s = _signals(3000, seed=3)
    규칙 = av.Rule("아무거나", "signal_close", av.ABOVE, 50_000.0, "시험용")
    결과 = av.evaluate(s, _market(s), 20, 규칙, "시험")
    assert not av.passes([결과], bar=av.bar_for(7))


# ────────── 모든 창에서 버텨야 한다 ──────────

def test_한_창에서만_되면_통과가_아니다():
    """3년에서는 되고 5년에서는 안 되면 미달입니다."""
    좋은창 = _signals(3000, seed=1, bad_when=("volume_mult", 12.0))
    나쁜창 = _signals(3000, seed=2)
    규칙 = av.CANDIDATES[0]
    결과들 = [av.evaluate(좋은창, _market(좋은창), 20, 규칙, "3년"),
            av.evaluate(나쁜창, _market(나쁜창), 20, 규칙, "5년")]
    assert av.passes([결과들[0]], bar=2.5)      # 한쪽만 보면 통과
    assert not av.passes(결과들, bar=2.5)       # 둘 다 보면 미달


def test_두_창_모두_되면_통과다():
    창들 = [_signals(3000, seed=s, bad_when=("volume_mult", 12.0))
           for s in (1, 2)]
    결과들 = [av.evaluate(f, _market(f), 20, av.CANDIDATES[0], f"창{i}")
            for i, f in enumerate(창들)]
    assert av.passes(결과들, bar=2.5)


# ────────── 너무 많이 버리면 안 된다 ──────────

def test_신호를_너무_많이_버리면_통과가_아니다():
    """남는 게 40% 미만이면 쓸 수 있는 조건이 아닙니다."""
    s = _signals(3000, seed=1, bad_when=("volume_mult", 2.0))
    많이버림 = av.Rule("과하게", "volume_mult", av.ABOVE, 2.0, "시험용")
    결과 = av.evaluate(s, _market(s), 20, 많이버림, "시험")
    assert 결과.kept_pct < av.MIN_KEPT_PCT
    assert not av.passes([결과], bar=2.0)


def test_제외된_것이_너무_적으면_판정하지_않는다():
    s = _signals(3000, seed=1)
    거의없음 = av.Rule("거의없음", "volume_mult", av.ABOVE, 500.0, "시험용")
    결과 = av.evaluate(s, _market(s), 20, 거의없음, "시험")
    assert 결과.excluded.count < av.MIN_EXCLUDED
    assert not av.passes([결과], bar=2.0)


# ────────── 조건을 여러 개 보면 기준을 올린다 ──────────

def test_조건이_많을수록_통과선이_올라간다():
    assert av.bar_for(1) < av.bar_for(7) < av.bar_for(30)


# ────────── 자료가 모자랄 때 ──────────

def test_비교_기준이_없으면_재지_않는다():
    s = _signals(3000)
    assert av.evaluate(s, pd.DataFrame(), 20, av.CANDIDATES[0]) is None


def test_없는_열로는_재지_않는다():
    s = _signals(3000).drop(columns=["volume_mult"])
    assert av.evaluate(s, _market(s), 20, av.CANDIDATES[0]) is None


def test_표본이_적으면_재지_않는다():
    s = _signals(150)
    assert av.evaluate(s, _market(s), 20, av.CANDIDATES[0]) is None


# ────────── 보고서 ──────────

def test_보고서가_검증이_아니라고_못박는다():
    s = _signals(3000, seed=1, bad_when=("volume_mult", 12.0))
    결과 = {"거래량 폭증": [av.evaluate(s, _market(s), 20, av.CANDIDATES[0], "3년")]}
    글 = av.report(결과, av.bar_for(7), 20)
    assert "검증이 아닙니다" in 글
    assert "같은 자료를 보고" in 글


def test_보고서가_후보로_넣은_이유를_밝힌다():
    """같은 자료에서 고른 것과 처음 보는 것을 갈라 적습니다."""
    s = _signals(3000, seed=1, bad_when=("volume_mult", 12.0))
    결과 = {"거래량 폭증": [av.evaluate(s, _market(s), 20, av.CANDIDATES[0], "3년")]}
    글 = av.report(결과, av.bar_for(7), 20)
    assert "후보로 넣은 이유" in 글 and "같은 자료에서 고름" in 글


def test_후보에_처음_보는_것이_섞여_있다():
    """전부 같은 자료에서 고른 것만 넣으면 통과만 찍어내는 도구가 됩니다."""
    이유들 = [r.why for r in av.CANDIDATES]
    assert sum("처음 보는 것" in w for w in 이유들) >= 3
