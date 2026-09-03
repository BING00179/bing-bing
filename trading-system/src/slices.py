"""어디가 다른가 — 14,247건을 갈라서 봅니다.

깨어나는 종목(breakout) 신호 전체에는 우위가 없었습니다. 20일 초과
+0.04%, t = 0.24. 60일에서는 오히려 시장보다 유의하게 나빴습니다.

그런데 "전체 평균이 0" 은 "안에 아무것도 없다" 와 같은 말이 아닙니다.
좋은 조각과 나쁜 조각이 섞여 상쇄됐을 수도 있습니다. 그래서 갈라 봅니다.

    거래대금이 큰 것과 작은 것
    조용했던 정도 (기저 변동폭)
    깨어난 세기 (거래량 배수)
    이미 오른 정도 (직전 상승률)
    주가 수준
    시장이 좋을 때와 나쁠 때

⚠️ **여기가 제일 위험한 자리입니다.** 조각을 스무 개 만들어 놓고
제일 좋은 걸 고르면, 아무 뜻 없는 자료에서도 하나쯤은 반드시
"유의하게" 나옵니다. 동전 스무 개를 던져 앞면 열 번 나온 걸 고르는
것과 같습니다.

그래서 이 모듈은 **몇 개를 봤는지 세고, 그만큼 기준을 올립니다.**
조각을 많이 볼수록 통과선이 높아집니다. 그게 정직한 셈법입니다.

그리고 여기서 살아남은 조각도 **탐색이지 검증이 아닙니다.** 같은
자료에서 찾은 것이라 그 자료에 맞춘 것일 수 있습니다. 앞으로의
자료(장부)로 다시 확인해야 합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

MIN_SAMPLE = 100        # 조각 하나가 이보다 작으면 보지 않습니다
ALPHA = 0.05            # 전체를 통틀어 허용하는 헛짚을 확률

# 미리 정해 둔 조각들. 숫자를 보기 전에 적습니다.
#
#   (열 이름, 화면에 쓸 이름, 몇 조각으로 나눌지)
CUTS = (
    ("turnover", "거래대금", 5),
    ("base_range_pct", "조용했던 정도", 5),
    ("volume_mult", "깨어난 세기", 5),
    ("runup_pct", "이미 오른 정도", 5),
    ("signal_close", "주가 수준", 5),
    ("gap_pct", "다음날 아침 갭", 5),
)


def required_t(n_slices: int, alpha: float = ALPHA) -> float:
    """조각을 n개 봤을 때 필요한 t 값.

    하나만 볼 때는 t ≥ 1.96 이면 5% 기준을 넘습니다. 그런데 스무 개를
    보면 그중 하나가 우연히 넘을 확률이 64% 나 됩니다. 그래서 허용
    확률을 조각 수로 나눕니다 (본페로니).

        조각  1개 → t 1.96
        조각  6개 → t 2.64
        조각 30개 → t 3.09
    """
    n_slices = max(int(n_slices), 1)
    p = alpha / n_slices
    return float(NormalDist().inv_cdf(1.0 - p / 2.0))


@dataclass
class SliceRow:
    cut: str                 # 무엇으로 갈랐나
    label: str               # 그 안의 어느 조각인가
    count: int
    signal_mean: float
    market_mean: float
    excess: float
    t_stat: float
    win_rate: float

    def passes(self, bar: float) -> bool:
        return self.count >= MIN_SAMPLE and abs(self.t_stat) >= bar


def _bins(values: pd.Series, q: int) -> pd.Series:
    """값을 q개 조각으로. 같은 값이 많아 못 나누면 있는 만큼만 나눕니다."""
    깨끗 = values.replace([np.inf, -np.inf], np.nan)
    try:
        return pd.qcut(깨끗, q, duplicates="drop")
    except (ValueError, IndexError):
        return pd.Series(pd.NA, index=values.index)


def by_cut(signals: pd.DataFrame, market: pd.DataFrame, column: str,
           label: str, horizon: int, q: int = 5) -> list[SliceRow]:
    """한 가지 기준으로 갈라서 조각마다 초과수익을 잽니다."""
    값열, 시장열 = f"fwd{horizon}", f"fwd{horizon}_mkt"
    if signals.empty or column not in signals or 값열 not in signals:
        return []

    # 비교 기준이 없으면 아무것도 재지 않습니다. "신호 종목이 +1.2%" 는
    # 그 자체로 뜻이 없습니다 — 그날 아무거나 샀어도 +2% 였을 수 있습니다.
    if market is None or market.empty or 값열 not in market:
        return []

    붙임 = signals.merge(market, left_on="entry_date", right_index=True,
                        how="left", suffixes=("", "_mkt"))
    if 시장열 not in 붙임:
        return []
    쓸것 = 붙임[[column, 값열, 시장열]].dropna()
    if len(쓸것) < MIN_SAMPLE:
        return []

    조각 = _bins(쓸것[column], q)
    if 조각.isna().all():
        return []

    rows: list[SliceRow] = []
    for 이름, 묶음 in 쓸것.groupby(조각, observed=True):
        if len(묶음) < MIN_SAMPLE:
            continue
        차 = 묶음[값열] - 묶음[시장열]
        표준편차 = float(차.std(ddof=1))
        t = (float(차.mean() / (표준편차 / np.sqrt(len(차))))
             if 표준편차 > 0 else 0.0)
        rows.append(SliceRow(
            cut=label, label=_pretty(이름), count=len(묶음),
            signal_mean=float(묶음[값열].mean()),
            market_mean=float(묶음[시장열].mean()),
            excess=float(차.mean()), t_stat=t,
            win_rate=float((묶음[값열] > 0).mean() * 100.0),
        ))
    return rows


def _pretty(interval) -> str:
    """구간을 읽을 수 있게. 1억 넘는 값은 억 단위로 줄입니다."""
    if not hasattr(interval, "left"):
        return str(interval)

    def 짧게(x: float) -> str:
        if abs(x) >= 1e8:
            return f"{x / 1e8:,.0f}억"
        if abs(x) >= 1e4:
            return f"{x / 1e4:,.0f}만"
        return f"{x:,.1f}"

    return f"{짧게(float(interval.left))}~{짧게(float(interval.right))}"


def all_cuts(signals: pd.DataFrame, market: pd.DataFrame, horizon: int,
             cuts: tuple = CUTS) -> tuple[list[SliceRow], float]:
    """정해 둔 기준을 전부 돌리고, 본 조각 수만큼 기준을 올립니다."""
    rows: list[SliceRow] = []
    for column, label, q in cuts:
        rows.extend(by_cut(signals, market, column, label, horizon, q))
    return rows, required_t(len(rows))


def report(rows: list[SliceRow], bar: float, horizon: int,
           total: int = 0) -> str:
    """살아남은 조각이 있는가. 없으면 없다고 씁니다."""
    줄 = [f"🔍 어디가 다른가 — {horizon}일 초과수익을 조각내서", ""]
    if total:
        줄 += [f"   신호 {total:,}건", ""]

    if not rows:
        return "\n".join(줄 + ["   볼 수 있는 조각이 없습니다 "
                              f"(조각 하나에 {MIN_SAMPLE}건 이상 필요)."])

    줄 += [f"   조각 {len(rows)}개를 봤습니다. 그래서 통과선을 "
           f"**t {bar:.2f}** 로 올립니다.",
           f"   (하나만 봤다면 1.96 이면 됐습니다. {len(rows)}개를 보면 그중",
           "    하나가 우연히 넘을 확률이 커지므로 그만큼 올려 잡습니다.)", ""]

    통과 = [r for r in rows if r.passes(bar)]
    좋은쪽 = [r for r in 통과 if r.excess > 0]
    나쁜쪽 = [r for r in 통과 if r.excess < 0]

    줄 += ["   기준     조각                 표본     초과     t     승률"]
    for r in sorted(rows, key=lambda x: x.excess, reverse=True):
        표 = ""
        if r.passes(bar):
            표 = "  ← 통과" if r.excess > 0 else "  ← 반대로 유의"
        줄.append(f"   {r.cut:<10s} {r.label:<18s} {r.count:6,d} "
                  f"{r.excess:+7.2f}% {r.t_stat:6.2f} {r.win_rate:5.1f}%{표}")

    줄 += [""]
    if 좋은쪽:
        제일 = max(좋은쪽, key=lambda r: r.excess)
        줄 += [f"   ✅ 통과한 조각 {len(좋은쪽)}개. 제일 나은 것은 "
               f"{제일.cut} {제일.label} — 초과 {제일.excess:+.2f}%, "
               f"t {제일.t_stat:.2f}, 표본 {제일.count:,}건.",
               "",
               "   ⚠️ 그래도 이건 **탐색이지 검증이 아닙니다.** 같은 자료에서",
               "      찾은 조각이라 그 자료에 맞춘 것일 수 있습니다. 조건으로",
               "      넣기 전에 장부에 쌓아 앞으로의 자료로 다시 확인합니다."]
    else:
        줄 += ["   ❌ 통과한 조각이 없습니다. 어느 조각에서도 우위가",
               "      확인되지 않았습니다. 이 신호를 조건으로 좁혀서는",
               "      살릴 수 없다는 뜻입니다."]
    if 나쁜쪽:
        제일나쁜 = min(나쁜쪽, key=lambda r: r.excess)
        줄 += ["",
               f"   반대로 유의하게 나쁜 조각도 {len(나쁜쪽)}개 있습니다 "
               f"(제일 나쁜 것 {제일나쁜.cut} {제일나쁜.label}, "
               f"{제일나쁜.excess:+.2f}%).",
               "      이건 '피할 것' 을 알려줍니다. 거르는 조건은 될 수 있습니다."]
    return "\n".join(줄)
