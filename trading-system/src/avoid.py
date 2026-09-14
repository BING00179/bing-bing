"""피할 것 — 무엇을 사면 되는가가 아니라, 무엇을 사지 말아야 하는가.

"조용히 3~6배 깨어난 종목이 좋다" 는 창을 3년으로 바꾸니 판정이
뒤집혔습니다 (2026-09-14). 그런데 같은 자리에서 **피할 것 쪽은 두 창
모두에서 버텼습니다.**

                          5년치        3년치
    거래량 26배 이상       t -9.31      t -7.28
    거래대금 160억 이상    t -4.82      t -4.05
    아침 갭 +1.2% 이상     t -3.48      t -3.12

성격이 다릅니다.

    사는 조건은 틀리면 **돈을 잃습니다.**
    거르는 조건은 틀려도 **안 사는 것뿐입니다.**

그래서 위험이 작고, 그래서 먼저 봅니다.

## 이 모듈이 묻는 것

거르는 조건 하나에 대해 **"제외되는 쪽이 정말 나쁜가"** 를 묻습니다.
남는 쪽이 좋아 보이는 것으로는 부족합니다 — 아무거나 걸러내도 남는
쪽 평균은 흔들리니까요. 제외되는 쪽 자체가 시장보다 유의하게 나빠야
그 조건이 값을 합니다.

## 미리 정해 둔 합격선 (숫자를 보기 전에 적습니다)

    · 제외되는 쪽의 초과수익이 마이너스이고
    · 그 t 값이 조각 수만큼 올린 통과선을 넘고 (본페로니)
    · **모든 창(3년·5년)에서** 그러하고
    · 남는 신호가 40% 이상일 것 (너무 많이 버리면 쓸 수 없습니다)

넷을 다 만족해야 '버틴 조건' 입니다. 하나라도 어기면 미달입니다.

⚠️ **이것도 검증이 아닙니다.** 후보 조건 일부는 같은 자료를 보고
나온 것입니다. 여기서 버틴다고 우위가 증명되지는 않습니다. 새로운
것은 **창을 바꿔도 버티는지**를 요구한다는 점뿐입니다. 진짜 확인은
앞으로의 자료(장부)로 합니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .slices import required_t

MIN_KEPT_PCT = 40.0        # 이보다 많이 버리면 쓸 수 없습니다
MIN_EXCLUDED = 100         # 제외된 쪽이 이보다 적으면 판정하지 않습니다

ABOVE, BELOW = ">", "<"


@dataclass(frozen=True)
class Rule:
    """거르는 조건 하나. 이 조건에 걸리는 신호는 **사지 않습니다.**"""
    name: str
    column: str
    op: str                # ABOVE = 이 값보다 크면 제외, BELOW = 작으면 제외
    threshold: float
    why: str               # 왜 이걸 후보로 넣었나 — 출처를 남깁니다

    def excluded(self, values: pd.Series) -> pd.Series:
        숫자 = pd.to_numeric(values, errors="coerce")
        if self.op == ABOVE:
            return 숫자 > self.threshold
        return 숫자 < self.threshold

    def as_text(self) -> str:
        부호 = "이상" if self.op == ABOVE else "이하"
        return f"{self.column} {self.threshold:g} {부호}"


# 미리 정해 둔 후보들. 숫자를 보기 전에 적습니다.
#
# 앞의 셋은 slice-kr 에서 두 창 모두 나쁘게 나온 것들이라 **같은 자료를
# 보고 고른 것**입니다. 뒤의 넷은 아직 이런 식으로 본 적 없는 것들로,
# 이 시험이 통과만 찍어내는 도구가 되지 않도록 같이 넣습니다.
CANDIDATES: tuple[Rule, ...] = (
    Rule("거래량 폭증", "volume_mult", ABOVE, 12.0,
         "slice-kr 두 창 모두 t -7 이하 (같은 자료에서 고름)"),
    Rule("거래대금 폭증", "turnover", ABOVE, 1.44e10,
         "slice-kr 두 창 모두 t -4 이하 (같은 자료에서 고름)"),
    Rule("아침 갭 큼", "gap_pct", ABOVE, 1.2,
         "slice-kr 두 창 모두 t -3 이하 (같은 자료에서 고름)"),
    Rule("아침에 크게 빠짐", "gap_pct", BELOW, -1.0,
         "처음 보는 것 — 갭 하락 쪽도 나쁜지"),
    Rule("이미 많이 오름", "runup_pct", ABOVE, 30.0,
         "처음 보는 것 — 늦게 타면 나쁜지"),
    Rule("조용하지 않았음", "base_range_pct", ABOVE, 34.0,
         "처음 보는 것 — 원래 많이 흔들리던 종목"),
    Rule("동전주", "signal_close", BELOW, 3_000.0,
         "처음 보는 것 — 낮은 가격대가 나쁜지"),
)


@dataclass
class Side:
    """한쪽(제외된 쪽 또는 남은 쪽)의 성적."""
    count: int
    excess: float
    t_stat: float
    win_rate: float


@dataclass
class RuleResult:
    rule: Rule
    window: str            # 어느 창에서 잰 것인가 ("3년" 같은 것)
    excluded: Side
    kept: Side
    base_excess: float     # 거르기 전 전체

    @property
    def kept_pct(self) -> float:
        전체 = self.excluded.count + self.kept.count
        return self.kept.count / 전체 * 100.0 if 전체 else 0.0

    @property
    def gain(self) -> float:
        """거르고 나서 얼마나 나아졌나 (남은 쪽 − 거르기 전)."""
        return self.kept.excess - self.base_excess


def _side(part: pd.DataFrame, 값열: str, 시장열: str) -> Side:
    if part.empty:
        return Side(0, float("nan"), float("nan"), float("nan"))
    차 = part[값열] - part[시장열]
    표준편차 = float(차.std(ddof=1)) if len(차) > 1 else 0.0
    t = float(차.mean() / (표준편차 / np.sqrt(len(차)))) if 표준편차 > 0 else 0.0
    return Side(
        count=len(part), excess=float(차.mean()), t_stat=t,
        win_rate=float((part[값열] > 0).mean() * 100.0),
    )


def evaluate(signals: pd.DataFrame, market: pd.DataFrame, horizon: int,
             rule: Rule, window: str = "") -> RuleResult | None:
    """조건 하나를 한 창에서 재봅니다."""
    값열, 시장열 = f"fwd{horizon}", f"fwd{horizon}_mkt"
    if (signals.empty or market is None or market.empty
            or 값열 not in market or rule.column not in signals):
        return None

    붙임 = signals.merge(market, left_on="entry_date", right_index=True,
                        how="left", suffixes=("", "_mkt"))
    if 시장열 not in 붙임:
        return None
    쓸것 = 붙임.dropna(subset=[값열, 시장열, rule.column])
    if len(쓸것) < MIN_EXCLUDED * 2:
        return None

    걸림 = rule.excluded(쓸것[rule.column])
    제외 = _side(쓸것[걸림], 값열, 시장열)
    남음 = _side(쓸것[~걸림], 값열, 시장열)
    전체 = _side(쓸것, 값열, 시장열)
    return RuleResult(rule=rule, window=window, excluded=제외, kept=남음,
                      base_excess=전체.excess)


def passes(results: list[RuleResult], bar: float) -> bool:
    """미리 정해 둔 넷을 모두 만족하는가 — **모든 창에서**."""
    if not results:
        return False
    for r in results:
        if r.excluded.count < MIN_EXCLUDED:
            return False
        if not (r.excluded.excess < 0):
            return False
        if not (r.excluded.t_stat <= -bar):
            return False
        if r.kept_pct < MIN_KEPT_PCT:
            return False
    return True


def bar_for(rule_count: int) -> float:
    """조건을 여러 개 보면 그만큼 통과선을 올립니다."""
    return required_t(max(rule_count, 1))


def report(by_rule: dict[str, list[RuleResult]], bar: float,
           horizon: int) -> str:
    줄 = [f"🚫 피할 것 — 제외되는 쪽이 정말 나쁜가 ({horizon}일 초과수익)", ""]
    if not by_rule:
        return "\n".join(줄 + ["   잴 수 있는 조건이 없습니다."])

    줄 += [f"   조건 {len(by_rule)}개를 봤습니다. 통과선 **t ≤ -{bar:.2f}**"
           f" (모든 창에서), 남는 신호 {MIN_KEPT_PCT:g}% 이상.", ""]

    버틴것, 미달 = [], []
    for 이름, 결과들 in by_rule.items():
        (버틴것 if passes(결과들, bar) else 미달).append((이름, 결과들))

    for 제목, 묶음 in (("✅ 버틴 조건", 버틴것), ("❌ 미달", 미달)):
        if not 묶음:
            continue
        줄 += [f"   {제목} {len(묶음)}개", ""]
        for 이름, 결과들 in 묶음:
            r0 = 결과들[0]
            줄.append(f"   [{이름}]  {r0.rule.as_text()} 이면 사지 않음")
            줄.append(f"      후보로 넣은 이유: {r0.rule.why}")
            줄.append("      창     제외된 것        초과     t     남는 비율")
            for r in 결과들:
                줄.append(
                    f"      {r.window:<5s} {r.excluded.count:6,d}건  "
                    f"{r.excluded.excess:+7.2f}% {r.excluded.t_stat:6.2f}   "
                    f"{r.kept_pct:5.1f}%"
                )
            변화 = ", ".join(f"{r.window} {r.gain:+.2f}%p" for r in 결과들)
            줄 += [f"      거르고 나서 남은 쪽의 변화: {변화}", ""]

    줄 += ["", "   ⚠️ 이것도 **검증이 아닙니다.** 후보 일부는 같은 자료를 보고",
           "      고른 것입니다. 새로운 것은 '창을 바꿔도 버티는가' 를",
           "      요구한다는 점뿐입니다. 진짜 확인은 장부에 쌓아",
           "      앞으로의 자료로 합니다 (7번).", "",
           "   거르는 조건은 신호를 **만들지 않고 줄이기만** 합니다.",
           "   틀려도 안 사는 것뿐이라, 사는 조건보다 위험이 작습니다."]
    return "\n".join(줄)
