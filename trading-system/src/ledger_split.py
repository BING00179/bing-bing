"""장부를 '피할 것' 조건으로 갈라 본다 — avoid-kr 의 앞으로의 자료판.

avoid-kr(2026-09-14)에서 두 창 모두 버틴 조건이 셋 있었다.

    거래량 12배 이상 · 거래대금 144억 이상 · 아침 갭 +1.2% 이상

셋 다 slice-kr 에서 같은 자료를 보고 고른 것이라 순환논리에 가깝다.
그래서 **조건에 넣지 않는다**(2026-09-15 사장님 결정, LEDGER_VERSION 그대로).
대신 장부에 이미 적히는 volume_mult·turnover·gap_pct 로 앞으로의 기록을
갈라 본다. 조건을 안 바꿨으니 시계도 안 멈춘다.

아래 문턱·합격선은 **숫자를 보기 전에** 적은 것이다(7번). 결과를 보고
나서 고치면 그 순간 자기합리화가 된다.

    무엇을      장부 v1 의 유효 기록 중 '산 것'(bought=예), 기간이 찬 것
    비교 대상   같은 날 산 코스닥 지수 (초과수익, score_rows 와 같은 잣대)
    보유 기간   20 거래일
    최소 표본   제외되는 쪽 30건 — 그 전에는 "아직 모릅니다"
    근거 있음   제외되는 쪽 초과수익 < 0 이고 t ≤ -BAR (셋을 보므로 보정한
                통과선, avoid-kr 과 같은 식) 이고 남는 신호 40% 이상
    미달        표본은 찼는데 위 셋 중 하나라도 어김
    판정 시점   제외 쪽 30건이 찬 뒤. 그 전의 중간 숫자로 조건을 바꾸지 않는다
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .avoid import (ABOVE, CANDIDATES, MIN_KEPT_PCT, Rule, RuleResult, _side,
                    bar_for)
from . import livetest as lt

# 미리 정해 둔 세 조건 — avoid.CANDIDATES 의 앞 셋과 같은 것이어야 한다.
PRE_REGISTERED: tuple[tuple[str, str, float], ...] = (
    ("volume_mult", ABOVE, 12.0),
    ("turnover", ABOVE, 1.44e10),
    ("gap_pct", ABOVE, 1.2),
)
MIN_EXCLUDED = 30                   # 7번: 표본 30건 전에는 판정하지 않는다
BAR = bar_for(len(PRE_REGISTERED))  # 셋을 보므로 통과선을 올린다 (≈2.39)
WINDOW = "앞으로"

UNKNOWN, SUPPORTED, FAILED = "아직 모릅니다", "근거 있음", "미달"


def pre_registered_rules() -> tuple[Rule, ...]:
    """avoid-kr 의 후보 중 미리 정한 셋을 **같은 객체로** 가져온다.

    여기서 문턱을 다시 적지 않는다 — 두 곳의 숫자가 어긋나면 어느 쪽이
    맞는지 알 수 없게 된다.
    """
    찾은것 = []
    for column, op, threshold in PRE_REGISTERED:
        맞는것 = [r for r in CANDIDATES
                if r.column == column and r.op == op and r.threshold == threshold]
        if len(맞는것) != 1:
            raise RuntimeError(f"avoid.CANDIDATES 에 {column} {op} {threshold} 가 "
                               f"{len(맞는것)}개 있습니다 — 한 개여야 합니다")
        찾은것.append(맞는것[0])
    return tuple(찾은것)


def attach(scored: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """채점 결과에 장부의 조건값(volume_mult·turnover)을 붙인다.

    Scored 에는 gap_pct 만 있고 거래량 배수·거래대금은 없다. (signal_date, code)
    로 장부 유효 줄과 맞춘다. gap_pct 는 채점 쪽 값을 그대로 둔다.
    """
    if scored.empty:
        return scored
    유효 = lt.active(ledger) if not ledger.empty else ledger
    붙일칸 = [c for c in ("volume_mult", "turnover") if c in 유효.columns]
    if not 붙일칸:
        return scored
    키 = ["signal_date", "code"]
    오른쪽 = 유효[키 + 붙일칸].copy()
    for k in 키:
        오른쪽[k] = 오른쪽[k].astype(str)
    왼쪽 = scored.copy()
    for k in 키:
        왼쪽[k] = 왼쪽[k].astype(str)
    오른쪽 = 오른쪽.drop_duplicates(subset=키, keep="last")
    return 왼쪽.merge(오른쪽, on=키, how="left")


def evaluate(table: pd.DataFrame, rule: Rule) -> RuleResult | None:
    """조건 하나로 제외/남음을 갈라 각각의 초과수익·t 를 낸다.

    avoid.evaluate 와 달리 표본이 적어도 결과를 돌려준다 — 판정은 judge 가
    표본 수를 보고 한다. '아직 모릅니다' 도 보여줘야 하기 때문이다.
    """
    if table is None or table.empty:
        return None
    필요 = ["stock_pct", "index_pct", rule.column]
    if any(c not in table.columns for c in 필요):
        return None
    쓸것 = table.dropna(subset=필요)
    if 쓸것.empty:
        return None
    걸림 = rule.excluded(쓸것[rule.column])
    return RuleResult(
        rule=rule, window=WINDOW,
        excluded=_side(쓸것[걸림], "stock_pct", "index_pct"),
        kept=_side(쓸것[~걸림], "stock_pct", "index_pct"),
        base_excess=_side(쓸것, "stock_pct", "index_pct").excess,
    )


@dataclass(frozen=True)
class Judgement:
    status: str      # UNKNOWN / SUPPORTED / FAILED
    reason: str


def judge(result: RuleResult | None, bar: float = BAR) -> Judgement:
    """미리 적어 둔 합격선대로만 판정한다."""
    if result is None:
        return Judgement(UNKNOWN, f"잴 자료가 없습니다 (제외 0건 / 최소 {MIN_EXCLUDED}건)")
    n = result.excluded.count
    if n < MIN_EXCLUDED:
        return Judgement(UNKNOWN, f"제외되는 쪽 {n}건 — 최소 {MIN_EXCLUDED}건이 차야 판정합니다")
    if not (result.excluded.excess < 0):
        return Judgement(FAILED, f"제외되는 쪽 초과수익이 {result.excluded.excess:+.2f}% 로 나쁘지 않습니다")
    if not (result.excluded.t_stat <= -bar):
        return Judgement(FAILED, f"t {result.excluded.t_stat:.2f} 가 통과선 -{bar:.2f} 에 못 미칩니다")
    if result.kept_pct < MIN_KEPT_PCT:
        return Judgement(FAILED, f"남는 신호가 {result.kept_pct:.1f}% 뿐입니다 (최소 {MIN_KEPT_PCT:g}%)")
    return Judgement(SUPPORTED, f"제외되는 쪽 {n}건 초과수익 {result.excluded.excess:+.2f}% · "
                                f"t {result.excluded.t_stat:.2f} ≤ -{bar:.2f} · 남는 비율 {result.kept_pct:.1f}%")


def report(rows: list[tuple[Rule, RuleResult | None, Judgement]],
           horizon: int, bar: float = BAR) -> str:
    줄 = [f"🚫 피할 것 — 앞으로의 장부로 다시 봄 ({horizon}일 초과수익)", "",
          "   미리 적어 둔 합격선(2026-09-15, 숫자를 보기 전):",
          f"     제외되는 쪽 {MIN_EXCLUDED}건 이상 · 초과수익 < 0 · t ≤ -{bar:.2f}"
          f" · 남는 신호 {MIN_KEPT_PCT:g}% 이상",
          "   이 조건들은 장부 규칙에 **넣지 않았습니다** — LEDGER_VERSION 은 그대로입니다.", ""]
    for rule, result, verdict in rows:
        표시 = {UNKNOWN: "⏳", SUPPORTED: "✅", FAILED: "❌"}[verdict.status]
        줄.append(f"   {표시} [{rule.name}]  {rule.as_text()} 이면 사지 않음 → {verdict.status}")
        줄.append(f"      {verdict.reason}")
        if result is not None:
            def 쪽(side) -> str:
                if side.count == 0:
                    return "0건"
                return f"{side.count:,}건 {side.excess:+.2f}% (t {side.t_stat:.2f})"
            줄.append(f"      제외 {쪽(result.excluded)} · 남음 {쪽(result.kept)} · "
                      f"남는 비율 {result.kept_pct:.1f}%")
        줄.append("")
    줄 += ["   ⚠️ 중간 숫자를 보고 조건을 바꾸지 않습니다. 표본이 차기 전의 값은",
           "      방향조차 믿을 수 없습니다 (7번)."]
    return "\n".join(줄)
