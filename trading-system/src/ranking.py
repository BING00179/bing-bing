"""신호 점수 매기기 — 좋은 것 몇 개만 고르기.

조건을 통과한 종목이 하루에 여러 개 나올 수 있습니다. 전부 사면
자본이 흩어지고 거래비용만 늘어납니다. 그래서 점수를 매겨
상위 몇 개만 알림으로 내보냅니다.

점수는 0~100 이고, 네 항목의 가중 합입니다. 각 항목이 몇 점인지
그대로 보여주므로, 왜 이 종목이 1등인지 확인할 수 있습니다.
점수가 높다고 더 오른다는 보장은 없습니다. '같은 조건을 통과한
것들 중 상대적으로 더 뚜렷한 것' 을 고르는 장치입니다.

  갭 크기       오늘 얼마나 세게 출발했나
  거래대금      실제로 돈이 붙었나 (로그 척도)
  추세 강도     200일선에서 얼마나 위에 있나
  신고가 근접   지금도 고점을 갱신 중인가

가중치는 config.json 에서 바꿀 수 있습니다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import RankingConfig


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _scale(value: float, full_mark: float) -> float:
    """value 가 full_mark 에 닿으면 100점. 그 위는 100점으로 자릅니다."""
    if full_mark <= 0:
        return 0.0
    return _clamp(value / full_mark * 100.0)


@dataclass
class Score:
    total: float
    gap: float
    turnover: float
    trend: float
    near_high: float

    def as_line(self) -> str:
        return (
            f"점수 {self.total:>5.1f} "
            f"(갭 {self.gap:.0f} · 대금 {self.turnover:.0f} · "
            f"추세 {self.trend:.0f} · 신고가 {self.near_high:.0f})"
        )


def score(
    *,
    gap_pct: float,
    turnover: float,
    price: float,
    sma_slow: float,
    today_high: float,
    cfg: RankingConfig,
) -> Score:
    """네 항목을 0~100 으로 환산해 가중 평균합니다."""
    gap_score = _scale(gap_pct, cfg.gap_full_mark_pct)

    # 거래대금은 편차가 커서(10억 vs 5000억) 그대로 쓰면 한 종목이
    # 점수를 독식합니다. 로그를 씌워 자릿수 차이로 봅니다.
    if turnover > 0 and cfg.turnover_full_mark > 0:
        ratio = math.log10(max(turnover, 1.0)) / math.log10(cfg.turnover_full_mark)
        turnover_score = _clamp(ratio * 100.0)
    else:
        turnover_score = 0.0

    # 200일선 위 이격도. 너무 멀면 과열이라 감점합니다.
    if sma_slow > 0:
        above_pct = (price - sma_slow) / sma_slow * 100.0
        if above_pct <= cfg.trend_full_mark_pct:
            trend_score = _scale(above_pct, cfg.trend_full_mark_pct)
        else:
            over = above_pct - cfg.trend_full_mark_pct
            trend_score = _clamp(100.0 - over * cfg.trend_overheat_penalty)
    else:
        trend_score = 0.0

    # 지금 값이 오늘 고가에 얼마나 붙어 있나
    if today_high > 0:
        gap_from_high = (today_high - price) / today_high * 100.0
        near_high_score = _clamp(100.0 - gap_from_high * cfg.near_high_penalty)
    else:
        near_high_score = 0.0

    weights = (
        cfg.weight_gap,
        cfg.weight_turnover,
        cfg.weight_trend,
        cfg.weight_near_high,
    )
    parts = (gap_score, turnover_score, trend_score, near_high_score)
    total_weight = sum(weights)
    total = sum(w * p for w, p in zip(weights, parts)) / total_weight if total_weight else 0.0

    return Score(
        total=round(total, 1),
        gap=round(gap_score, 1),
        turnover=round(turnover_score, 1),
        trend=round(trend_score, 1),
        near_high=round(near_high_score, 1),
    )
