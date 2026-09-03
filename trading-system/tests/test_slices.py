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


# ────────── 줄이 서는가 ──────────
#
# t 값만으로는 부족합니다. 실제 결과에서 이 차이가 나왔습니다.
#
#   깨어난 세기  +1.39 → +1.64 → +0.60 → -0.49 → -2.94   줄이 섭니다
#   주가 수준    +0.37 → -0.50 → -0.49 → +1.82 → -0.99   혼자 튑니다
#
# 앞은 "세게 깨어날수록 나쁘다" 는 이야기가 되고, 뒤는 안 됩니다.

def _row(cut, excess, t=0.0, n=2800):
    return sl.SliceRow(cut=cut, label="", count=n, signal_mean=0.0,
                       market_mean=0.0, excess=excess, t_stat=t, win_rate=40.0)


def test_한_방향으로_이어지면_줄이_선다고_본다():
    깨어남 = [_row("깨어난 세기", v) for v in (1.39, 1.64, 0.60, -0.49, -2.94)]
    assert sl.trend(깨어남) == sl.MONO_DOWN


def test_혼자_튀면_들쭉날쭉이다():
    주가 = [_row("주가 수준", v) for v in (0.37, -0.50, -0.49, 1.82, -0.99)]
    assert sl.trend(주가) == sl.BUMPY


def test_보고서가_줄이_서는_것과_혼자_튀는_것을_갈라_말한다():
    rows = ([_row("깨어난 세기", v, t) for v, t in
             ((1.39, 4.06), (1.64, 4.22), (0.60, 1.53), (-0.49, -1.23),
              (-2.94, -9.31))]
            + [_row("주가 수준", v, t) for v, t in
               ((0.37, 0.93), (-0.50, -1.59), (-0.49, -1.37), (1.82, 3.94),
                (-0.99, -3.43))])
    글 = sl.report(rows, bar=3.14, horizon=20)
    assert "줄이 서 있습니다" in 글 and "깨어난 세기" in 글
    assert "혼자 튑니다" in 글


# ────────── 조건을 겹쳐서 ──────────

def test_겹치면_남는_표본이_줄어든다():
    s = _signals(3000, seed=1)
    m = _market(s)
    전체 = sl.combo(s, m, 20, ())
    좁힘 = sl.combo(s, m, 20, (("volume_mult", 3.0, 6.0),))
    assert 전체.kept == 3000
    assert 좁힘.kept < 전체.kept
    assert 좁힘.dropped == 전체.kept - 좁힘.kept


def test_남는_게_너무_적으면_판정하지_않는다():
    s = _signals(3000, seed=1)
    좁힘 = sl.combo(s, _market(s), 20, (("volume_mult", 19.99, 20.0),))
    assert 좁힘 is None
    assert "너무 적습니다" in sl.combo_report(좁힘, 20)


def test_거래대금이_작은_쪽만_남기면_비용_경고를_붙인다():
    """거래대금 작은 종목은 슬리피지가 훨씬 큽니다.

    거기서 나온 초과수익은 비용에 먹힐 수 있습니다. 그걸 안 적으면
    화면만 좋아 보이고 실제 돈은 그대로 잃습니다.
    """
    s = _signals(3000, seed=1)
    좁힘 = sl.combo(s, _market(s), 20, (("turnover", None, 2.8e9),))
    글 = sl.combo_report(좁힘, 20)
    assert "슬리피지" in 글 and "비용에 먹힐 수 있습니다" in 글


def test_큰_거래대금만_남기면_그_경고는_안_붙인다():
    s = _signals(3000, seed=1)
    좁힘 = sl.combo(s, _market(s), 20, (("turnover", 5e9, None),))
    assert "비용에 먹힐 수 있습니다" not in sl.combo_report(좁힘, 20)


def test_없는_열로_겹치려_하면_판정하지_않는다():
    s = _signals(3000, seed=1)
    assert sl.combo(s, _market(s), 20, (("없는열", 1.0, 2.0),)) is None


def test_조건_적는_법을_잘못_쓰면_알려준다():
    from src.cli import _parse_keep
    assert _parse_keep("volume_mult:3:6") == ("volume_mult", 3.0, 6.0)
    assert _parse_keep("turnover::2.8e9") == ("turnover", None, 2.8e9)
    for 틀린것 in ("volume_mult:3", ":3:6"):
        try:
            _parse_keep(틀린것)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"{틀린것} 을 걸러내지 못했습니다")


# ────────── 우연인지 아닌지 ──────────

def _dated(n=1200, seed=0, horizon=20, half_only=False, one_stock=False):
    """앞뒤 절반, 종목 쏠림을 만들어 볼 수 있는 자료."""
    rng = np.random.default_rng(seed)
    날 = pd.bdate_range("2023-01-02", periods=n)
    codes = [f"{i % 40:06d}" for i in range(n)]
    frame = pd.DataFrame({
        "entry_date": 날, "code": codes,
        "volume_mult": rng.uniform(1, 20, n),
    })
    값 = rng.normal(0, 5, n)
    if half_only:                       # 뒤 절반에서만 좋음
        값 = 값 + 6.0 * (np.arange(n) >= n // 2)
    else:
        값 = 값 + 3.0
    if one_stock:                       # 한 종목이 다 만듦
        값 = rng.normal(0, 5, n) + 200.0 * (np.array(codes) == "000007")
    frame[f"fwd{horizon}"] = 값
    return frame


def test_앞뒤_둘_다_되면_그렇게_말한다():
    s = _dated(1200, seed=5)
    굳음 = sl.stability(s, _market(s), 20, ())
    assert 굳음.both_halves
    assert "둘 다 됩니다" in sl.stability_report(굳음)


def test_한쪽에서만_되면_우연일_수_있다고_말한다():
    s = _dated(1200, seed=5, half_only=True)
    굳음 = sl.stability(s, _market(s), 20, ())
    assert not 굳음.both_halves
    assert "한쪽에서만 됩니다" in sl.stability_report(굳음)


def test_한_종목이_다_만들면_그것을_짚어준다():
    """우리기술 한 종목이 성적을 다 만들던 것과 같은 일입니다."""
    s = _dated(1200, seed=5, one_stock=True)
    굳음 = sl.stability(s, _market(s), 20, ())
    assert 굳음.top_code == "000007"
    assert 굳음.top_code_share >= 20.0
    assert "한 종목이" in sl.stability_report(굳음)


def test_중앙값이_마이너스면_숨기지_않는다():
    """승률이 절반 아래인데 평균만 플러스인 경우입니다."""
    rng = np.random.default_rng(1)
    n = 1200
    값 = np.where(rng.random(n) < 0.15, 40.0, -3.0)      # 15%만 크게 오름
    s = pd.DataFrame({"entry_date": pd.bdate_range("2023-01-02", periods=n),
                      "code": [f"{i%40:06d}" for i in range(n)],
                      "fwd20": 값})
    굳음 = sl.stability(s, _market(s), 20, ())
    assert 굳음.median_excess < 0
    글 = sl.stability_report(굳음)
    assert "중앙값은 마이너스입니다" in 글


def test_표본이_모자라면_판정하지_않는다():
    s = _dated(150)
    assert sl.stability(s, _market(s), 20, ()) is None
    assert "표본이 모자랍니다" in sl.stability_report(None)
