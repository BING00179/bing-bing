"""나가는 규칙 검사.

여기서 봐야 할 것은 '숫자가 나오나' 가 아니라 '거짓말을 하지 않나' 입니다.
특히 두 가지 — 미래를 당겨쓰지 않는가, 자료가 모자랄 때 입을 다무는가.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import exits as ex


def _daily(closes, start="2026-01-02", lows=None, highs=None, opens=None):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series([float(x) for x in closes], index=idx)
    return pd.DataFrame({
        "open": pd.Series([float(x) for x in opens], index=idx) if opens else c,
        "high": pd.Series([float(x) for x in highs], index=idx) if highs else c,
        "low": pd.Series([float(x) for x in lows], index=idx) if lows else c,
        "close": c,
        "volume": 1_000,
    })


def _straight(n, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


def _paths_from(closes, signal_i=0, max_days=5, **kw):
    d = _daily(closes, **kw)
    sig = pd.DatetimeIndex([d.index[signal_i]])
    return ex.build_paths({"A": d}, {"A": sig}, max_days=max_days), d


# ────────────────── 미래를 당겨쓰지 않는가 ──────────────────

def test_신호_다음날_시가부터_센다():
    """신호는 D일 종가, 매수는 D+1일 시가입니다."""
    paths, d = _paths_from([100, 110, 121, 133, 146], signal_i=0, max_days=4)
    assert len(paths) == 1
    assert paths.entry_date[0] == d.index[1]        # D+1
    # 진입 시가(=110) 대비이므로 첫날 종가는 0%
    assert abs(paths.close[0, 0] - 0.0) < 1e-9


def test_신호일_이전은_아예_담지_않는다():
    paths, d = _paths_from(_straight(10), signal_i=5, max_days=4)
    # 담긴 첫 값이 진입일이라야 합니다 — 그 앞을 보면 미래가 아니라 과거지만,
    # 과거를 담으면 '진입 전에 이미 알고 있었다' 는 계산이 섞입니다.
    assert paths.entry_date[0] == d.index[6]
    assert paths.alive[0].sum() == 4


def test_자료가_모자라면_뒤쪽은_빈칸이다():
    """0 으로 채우면 손절에 안 닿은 것처럼 보입니다."""
    paths, _ = _paths_from(_straight(4), signal_i=0, max_days=10)
    assert paths.alive[0].sum() == 3            # 진입일 포함 3일치뿐
    assert np.isnan(paths.close[0, 5])


# ────────────────── ① 며칠 들고 있어야 하나 ──────────────────

def _many(n_signals=60, days=130, drift=0.4):
    """오르는 종목 여러 개. 표본을 채우려고 만듭니다."""
    frames, signals = {}, {}
    for k in range(n_signals):
        code = f"{k:06d}"
        frames[code] = _daily(_straight(days + 2, 100.0, drift))
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    return frames, signals


def test_표본이_모자라면_판정하지_않는다():
    paths, _ = _paths_from(_straight(30), max_days=20)
    assert ex.hold_curve(paths, pd.DataFrame()) == []


def test_시장자료가_없으면_판정하지_않는다():
    """비교 대상 없이 '평균 +2%' 는 아무 뜻이 없습니다."""
    frames, signals = _many()
    paths = ex.build_paths(frames, signals, max_days=120)
    assert ex.hold_curve(paths, pd.DataFrame()) == []


def test_오래_들고_있을수록_좋으면_그렇게_말한다():
    frames, signals = _many()
    paths = ex.build_paths(frames, signals, max_days=120)
    시장 = pd.DataFrame(
        {f"fwd{n}": 0.0 for n in ex.HOLDS},
        index=pd.DatetimeIndex(sorted(set(paths.entry_date))),
    )
    curve = ex.hold_curve(paths, 시장)
    assert len(curve) >= 5
    assert curve[-1].excess > curve[0].excess      # 계속 오르는 종목이므로
    assert "이른 것으로 보입니다" in ex._hold_lesson(curve, now_hold=20)


def test_우위가_없으면_신호를_바꾸라고_말한다():
    frames, signals = _many(drift=0.4)
    paths = ex.build_paths(frames, signals, max_days=120)
    # 시장이 똑같이 올랐다면 초과수익은 0 입니다
    같이오름 = pd.DataFrame(
        {f"fwd{n}": [(1.004 ** n - 1) * 100.0] * 1 for n in ex.HOLDS},
        index=pd.DatetimeIndex(sorted(set(paths.entry_date))),
    )
    curve = ex.hold_curve(paths, 같이오름)
    말 = ex._hold_lesson(curve, now_hold=20) if curve else ""
    assert not curve or "신호를 바꿔야" in 말 or not any(r.passes for r in curve)


# ────────────────── ② 손절폭 ──────────────────

def test_손절선에_닿으면_거기서_끝난_것으로_본다():
    # 진입 시가 100, 둘째 날 저가 90 → -10%
    d = _daily([100, 100, 95, 130, 130],
               lows=[100, 100, 90, 130, 130],
               opens=[100, 100, 100, 100, 100])
    paths = ex.build_paths({"A": d}, {"A": pd.DatetimeIndex([d.index[0]])},
                           max_days=4)
    # 손절 5% 면 잘리고, 20% 면 안 잘립니다
    assert (paths.low[0] <= -5.0).any()
    assert not (paths.low[0] <= -20.0).any()


def test_손절이_넓으면_첫날에_덜_잘린다():
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        # 진입 첫날 -6% 를 찍고 회복
        frames[code] = _daily([100, 100, 105, 110, 115],
                              lows=[100, 94, 100, 105, 110],
                              opens=[100, 100, 100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=4)
    grid = ex.exit_grid(paths, stops=(3.0, 10.0), holds=(4,), cost_pct=0.0)
    좁은 = grid[grid["stop_pct"] == 3.0].iloc[0]
    넓은 = grid[grid["stop_pct"] == 10.0].iloc[0]
    assert 좁은["stopped_pct"] == 100.0
    assert 넓은["stopped_pct"] == 0.0
    assert 넓은["mean"] > 좁은["mean"]


def test_비용을_빼고_계산한다():
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        frames[code] = _daily([100, 100, 100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=4)
    공짜 = ex.exit_grid(paths, stops=(10.0,), holds=(4,), cost_pct=0.0)
    실제 = ex.exit_grid(paths, stops=(10.0,), holds=(4,), cost_pct=0.51)
    assert abs(공짜.iloc[0]["mean"] - 0.0) < 1e-9
    assert abs(실제.iloc[0]["mean"] + 0.51) < 1e-9


def test_전부_지면_규칙_문제가_아니라고_말한다():
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        frames[code] = _daily([100, 100, 90, 85, 80],
                              lows=[100, 95, 88, 83, 78],
                              opens=[100, 100, 100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=4)
    grid = ex.exit_grid(paths, stops=(3.0, 10.0), holds=(4,))
    assert "나가는 규칙 문제가 아닙니다" in ex._grid_lesson(grid, 3.0, 4)


# ────────────────── ③ 나간 뒤에 더 갔나 ──────────────────

def test_나간_뒤에_크게_오르면_그렇게_말한다():
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        # 첫날 -5% 로 잘리고 그 뒤로 크게 오릅니다 (우리기술 모양)
        frames[code] = _daily([100, 95, 120, 150, 180],
                              lows=[100, 94, 115, 145, 175],
                              highs=[100, 100, 125, 155, 185],
                              opens=[100, 100, 100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=4)
    결과 = ex.missed_upside(paths, stop_pct=3.0, hold_days=2, look_days=4)
    assert 결과["나간_뒤_10퍼_넘게_오른_비율"] > 90.0
    assert "나가는 손이 돈을 버리고" in ex._missed_lesson(결과)


def test_나간_뒤에_더_빠지면_나간_게_옳았다고_말한다():
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        frames[code] = _daily([100, 95, 90, 85, 80],
                              lows=[100, 94, 89, 84, 79],
                              highs=[100, 100, 95, 90, 85],
                              opens=[100, 100, 100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=4)
    결과 = ex.missed_upside(paths, stop_pct=3.0, hold_days=2, look_days=4)
    assert 결과["나간_뒤_10퍼_넘게_오른_비율"] < 15.0
    assert "나간 판단은 대체로 옳았습니다" in ex._missed_lesson(결과)


def test_표본이_모자라면_빈_결과다():
    paths, _ = _paths_from(_straight(10), max_days=5)
    assert ex.missed_upside(paths, 3.0, 3) == {}


# ────────────────── 보고서 ──────────────────

def test_보고서가_탐색이라고_못박는다():
    """제일 좋은 조합을 골라 놓고 '검증됐다' 고 하면 안 됩니다."""
    글 = ex.report([], pd.DataFrame(), {})
    assert "탐색이지 검증이 아닙니다" in 글


def test_보고서가_모자란_자료를_숨기지_않는다():
    글 = ex.report([], pd.DataFrame(), {})
    assert 글.count("자료가 모자라 판정하지 않습니다") == 3


def test_우위가_없으면_손절표를_믿지_말라고_경고한다():
    """①이 미달인데 ②에서 PF 가 좋아 보이면, 그건 시장이 오른 것뿐입니다.

    이 경고가 없으면 '손절을 넓히면 된다' 는 엉뚱한 결론으로 갑니다.
    """
    curve = [ex.HoldRow(days=20, mean=1.0, market=1.0, excess=0.0,
                        win_rate=50.0, t_stat=0.1, count=500)]
    grid = pd.DataFrame([{"stop_pct": 20.0, "target_pct": 0.0, "hold_days": 60,
                          "mean": 5.0, "win_rate": 55.0, "stopped_pct": 20.0,
                          "stopped_day1_pct": 0.0, "target_hit_pct": 0.0,
                          "profit_factor": 1.9, "count": 500}])
    글 = ex.report(curve, grid, {})
    assert "그냥 시장이" in 글 and "그건 우위가 아닙니다" in 글


def test_우위가_있으면_그_경고를_붙이지_않는다():
    curve = [ex.HoldRow(days=20, mean=3.0, market=1.0, excess=2.0,
                        win_rate=55.0, t_stat=3.5, count=500)]
    grid = pd.DataFrame([{"stop_pct": 20.0, "target_pct": 0.0, "hold_days": 60,
                          "mean": 5.0, "win_rate": 55.0, "stopped_pct": 20.0,
                          "stopped_day1_pct": 0.0, "target_hit_pct": 0.0,
                          "profit_factor": 1.9, "count": 500}])
    assert "그건 우위가 아닙니다" not in ex.report(curve, grid, {})


# ────────── 목표에 닿으면 파는 규칙 ──────────
#
# 사장님 질문 — "일정 목표 금액에 닿으면 20일 전에도 팔아야 하지 않나".
# 백테스트에는 그 규칙이 없었고(take_profit_pct=0), 장부에는 있었습니다.
# 같은 시스템이 두 규칙으로 돌고 있었습니다.

def _rising(n_signals=60, days=10):
    """진입 뒤 꾸준히 오르는 종목들. 목표에 닿습니다."""
    frames, signals = {}, {}
    for k in range(n_signals):
        code = f"{k:06d}"
        closes = [100, 100, 105, 112, 120, 128, 136, 145, 155, 165][:days]
        frames[code] = _daily(closes,
                              lows=[c * 0.995 for c in closes],
                              highs=[c * 1.005 for c in closes],
                              opens=[100.0] * len(closes))
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    return ex.build_paths(frames, signals, max_days=days - 1)


def test_목표에_닿으면_기간이_남아도_거기서_끝난다():
    paths = _rising()
    grid = ex.exit_grid(paths, stops=(20.0,), holds=(9,),
                        targets=(0.0, 20.0), cost_pct=0.0)
    없음 = grid[grid["target_pct"] == 0.0].iloc[0]
    있음 = grid[grid["target_pct"] == 20.0].iloc[0]
    assert 있음["target_hit_pct"] == 100.0
    assert abs(있음["mean"] - 20.0) < 1e-9        # 정확히 목표에서 끝남
    assert 없음["mean"] > 있음["mean"]            # 계속 올랐으니 안 판 쪽이 더 벎


def test_목표를_끄면_목표도달이_0이다():
    grid = ex.exit_grid(_rising(), stops=(20.0,), holds=(9,),
                        targets=(0.0,), cost_pct=0.0)
    assert grid.iloc[0]["target_hit_pct"] == 0.0


def test_같은_날_둘_다_닿으면_손절_쪽으로_본다():
    """일봉만 보면 그날 어느 쪽이 먼저였는지 모릅니다.

    모르는 것을 유리하게 가정하면 백테스트만 좋아집니다.
    """
    frames, signals = {}, {}
    for k in range(60):
        code = f"{k:06d}"
        # 진입 다음 날 저가 -10%, 고가 +30% — 같은 날 둘 다 닿습니다
        frames[code] = _daily([100, 100, 100],
                              lows=[100, 90, 100],
                              highs=[100, 130, 100],
                              opens=[100, 100, 100])
        signals[code] = pd.DatetimeIndex([frames[code].index[0]])
    paths = ex.build_paths(frames, signals, max_days=2)
    grid = ex.exit_grid(paths, stops=(5.0,), holds=(2,),
                        targets=(20.0,), cost_pct=0.0)
    r = grid.iloc[0]
    assert r["stopped_pct"] == 100.0        # 손절로 봤다
    assert r["target_hit_pct"] == 0.0
    assert abs(r["mean"] + 5.0) < 1e-9


def test_목표를_켜는_게_나은지_아닌지_말해_준다():
    좋음 = pd.DataFrame([
        {"stop_pct": 5.0, "target_pct": 0.0, "hold_days": 20, "mean": 1.0,
         "win_rate": 50.0, "stopped_pct": 10.0, "stopped_day1_pct": 0.0,
         "target_hit_pct": 0.0, "profit_factor": 1.1, "count": 500},
        {"stop_pct": 5.0, "target_pct": 20.0, "hold_days": 20, "mean": 2.0,
         "win_rate": 60.0, "stopped_pct": 10.0, "stopped_day1_pct": 0.0,
         "target_hit_pct": 30.0, "profit_factor": 1.5, "count": 500},
    ])
    assert "목표를 켠 쪽이 낫습니다" in ex._grid_lesson(좋음, 5.0, 20)

    나쁨 = 좋음.copy()
    나쁨.loc[1, "profit_factor"] = 0.9
    나쁨.loc[1, "mean"] = 0.1
    assert "목표를 끄는 쪽이 낫습니다" in ex._grid_lesson(나쁨, 5.0, 20)


def test_목표별로_한_줄씩만_보여준다():
    """조합이 백 개가 넘습니다. 전부 찍으면 아무것도 안 보입니다."""
    paths = _rising()
    grid = ex.exit_grid(paths, stops=(3.0, 5.0, 20.0), holds=(5, 9),
                        targets=(0.0, 10.0, 20.0))
    줄 = ex._grid_lines(grid)
    assert len(줄) == 1 + 3 + 2          # 머리 + 목표 3개 + 안내 2줄
    assert "없음" in 줄[1]
