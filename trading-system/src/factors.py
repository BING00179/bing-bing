"""요인 검증 — "이 기준이 국내장에서 실제로 통했나"

전략을 만들어놓고 검증하면 이미 편향이 들어갑니다. 그 반대로 갑니다.
하나의 기준(요인)으로 종목을 줄 세우고, 상위 그룹과 하위 그룹의
이후 수익률을 비교합니다. 차이가 없으면 그 기준은 쓸모가 없습니다.

이 방식을 '분위 검정' 이라고 부릅니다. 학계와 퀀트 업계에서 요인의
유효성을 볼 때 쓰는 기본 방법입니다.

    매 리밸런싱 날마다
      1. 모든 종목을 그 기준으로 줄 세운다
      2. 5개 그룹으로 나눈다 (Q1 = 상위 20%, Q5 = 하위 20%)
      3. 각 그룹을 동일 비중으로 사서 다음 리밸런싱까지 보유
      4. 그룹별 수익률을 기록한다

    Q1 이 Q5 보다 꾸준히 높으면 그 기준은 예측력이 있습니다.
    뒤죽박죽이면 없습니다.

⚠️ 이 방식으로 좋게 나와도 그대로 돈을 벌 수 있다는 뜻은 아닙니다.
   거래비용, 유동성, 실제 체결이 빠져 있습니다. '방향이 있는가'
   만 봅니다. 방향조차 없으면 더 볼 것이 없습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FactorResult:
    name: str
    higher_is_better: bool
    periods: int                    # 리밸런싱 횟수
    quantile_returns: pd.DataFrame  # 행=리밸런싱일, 열=Q1..Q5, 값=기간수익률(%)
    spread: pd.Series               # Q1 - Q5 (%)
    coverage: pd.Series             # 회차별 종목 수
    market: pd.Series               # 회차별 전 종목 평균 수익률 (건전성 확인용)

    @property
    def looks_broken(self) -> bool:
        """전 종목 평균이 상식 밖이면 데이터를 의심해야 합니다.

        월 단위 리밸런싱에서 전 종목 평균이 매달 -20% 라면 몇 년 뒤
        시장 전체가 0 이 됩니다. 그런 값이 나오면 요인 결과가 아니라
        가격 데이터부터 확인해야 합니다.
        """
        if self.market.empty:
            return False
        return bool(abs(self.market.mean()) > 20.0)

    @property
    def mean_by_quantile(self) -> pd.Series:
        return self.quantile_returns.mean()

    @property
    def mean_spread(self) -> float:
        return float(self.spread.mean())

    @property
    def hit_rate(self) -> float:
        """Q1 이 Q5 를 이긴 회차의 비율 (%)."""
        if self.spread.empty:
            return 0.0
        return float((self.spread > 0).mean() * 100.0)

    @property
    def t_stat(self) -> float:
        """스프레드가 0 과 다르다고 말할 수 있는가.

        |t| 가 2 를 넘으면 우연으로 보기 어렵다고 봅니다. 표본이
        작으면 이 값도 못 믿으니 periods 를 함께 보세요.
        """
        n = len(self.spread)
        if n < 2:
            return 0.0
        sd = float(self.spread.std(ddof=1))
        if sd == 0:
            return 0.0
        return float(self.spread.mean() / (sd / np.sqrt(n)))

    @property
    def monotonic(self) -> bool:
        """Q1 → Q5 로 갈수록 수익률이 계단처럼 낮아지는가.

        한두 그룹이 우연히 튀는 것과, 요인이 진짜 작동하는 것을
        구분하는 데 쓰입니다. 계단 모양이면 신뢰도가 올라갑니다.
        """
        means = self.mean_by_quantile.to_numpy()
        return bool(np.all(np.diff(means) <= 0))

    def as_report(self) -> str:
        means = self.mean_by_quantile
        direction = "높을수록 좋다" if self.higher_is_better else "낮을수록 좋다"
        lines = [
            f"[{self.name}] ({direction} 가정)",
            f"  리밸런싱 {self.periods}회 · 평균 {self.coverage.mean():.0f}종목",
            "  그룹별 평균 수익률 (Q1=가장 유리한 쪽)",
        ]
        for q, v in means.items():
            bar = "█" * max(0, int(abs(v) * 2))
            sign = "+" if v >= 0 else "-"
            lines.append(f"    {q}  {v:>+7.2f}%  {sign}{bar}")
        lines += [
            f"  Q1-Q5 스프레드   {self.mean_spread:>+7.2f}%",
            f"  Q1 승률          {self.hit_rate:>7.1f}%  (Q1 이 Q5 를 이긴 회차)",
            f"  t값              {self.t_stat:>7.2f}   (|t|>2 면 우연으로 보기 어려움)",
            f"  계단 모양        {'예' if self.monotonic else '아니오'}",
        ]
        if not self.market.empty:
            lines.append(f"  전 종목 평균     {self.market.mean():>+7.2f}%  (회차당)")
        if self.looks_broken:
            lines.append(
                "  ⚠️ 전 종목 평균이 상식 밖입니다. 가격 데이터를 먼저 확인하세요."
            )
        return "\n".join(lines)


def _forward_returns(
    prices: pd.DataFrame, dates: list[pd.Timestamp]
) -> list[pd.Series]:
    """각 리밸런싱일에서 다음 리밸런싱일까지의 수익률."""
    out = []
    for start, end in zip(dates, dates[1:]):
        if start not in prices.index or end not in prices.index:
            out.append(pd.Series(dtype=float))
            continue
        begin, finish = prices.loc[start], prices.loc[end]
        ret = (finish - begin) / begin * 100.0
        out.append(ret.replace([np.inf, -np.inf], np.nan).dropna())
    return out


def evaluate(
    name: str,
    factor: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    higher_is_better: bool,
    quantiles: int = 5,
    min_names: int = 30,
) -> FactorResult:
    """요인 하나를 분위로 나눠 검정합니다.

    factor  행=날짜, 열=종목코드, 값=그날의 요인값
    prices  행=날짜, 열=종목코드, 값=종가
            둘의 날짜는 리밸런싱일만 있으면 됩니다.
    """
    dates = [d for d in factor.index if d in prices.index]
    if len(dates) < 2:
        raise ValueError(f"{name}: 리밸런싱일이 2개 이상 필요합니다.")

    labels = [f"Q{i + 1}" for i in range(quantiles)]
    rows: list[dict] = []
    used_dates: list[pd.Timestamp] = []
    coverage: list[int] = []

    forwards = _forward_returns(prices, dates)

    for date, fwd in zip(dates[:-1], forwards):
        values = factor.loc[date].dropna()
        common = values.index.intersection(fwd.index)
        if len(common) < min_names:
            continue

        values, fwd = values.loc[common], fwd.loc[common]
        # 좋은 쪽이 항상 Q1 이 되도록 방향을 맞춥니다.
        ordered = values.rank(ascending=not higher_is_better, method="first")
        try:
            groups = pd.qcut(ordered, quantiles, labels=labels)
        except ValueError:
            continue                       # 값이 뭉쳐 있어 나눌 수 없음

        rows.append(fwd.groupby(groups, observed=True).mean().to_dict())
        used_dates.append(date)
        coverage.append(len(common))

    if not rows:
        raise ValueError(f"{name}: 검정할 수 있는 회차가 없습니다.")

    # 전 종목 평균. 요인과 무관하게 시장 전체가 어떻게 움직였나.
    market = pd.Series(
        [float(f.mean()) for f in forwards if not f.empty],
        index=pd.DatetimeIndex([d for d, f in zip(dates[:-1], forwards) if not f.empty]),
    )

    table = pd.DataFrame(rows, index=pd.DatetimeIndex(used_dates))[labels]
    return FactorResult(
        name=name,
        higher_is_better=higher_is_better,
        periods=len(table),
        quantile_returns=table,
        spread=table[labels[0]] - table[labels[-1]],
        coverage=pd.Series(coverage, index=pd.DatetimeIndex(used_dates)),
        market=market,
    )


def compare(results: list[FactorResult]) -> str:
    """여러 요인을 한 표로. 스프레드가 큰 순으로."""
    if not results:
        return "검정된 요인이 없습니다."

    ordered = sorted(results, key=lambda r: r.mean_spread, reverse=True)
    lines = [
        "=" * 74,
        "[요인 검정 결과] Q1(유리한 쪽) - Q5(불리한 쪽) 수익률 차이",
        "=" * 74,
        f"  {'요인':<20}{'스프레드':>10}{'t값':>8}{'승률':>8}{'계단':>6}{'회차':>6}",
        "-" * 74,
    ]
    for r in ordered:
        mark = "★" if abs(r.t_stat) >= 2 and r.monotonic else " "
        lines.append(
            f"{mark} {r.name:<20}{r.mean_spread:>+9.2f}%{r.t_stat:>8.2f}"
            f"{r.hit_rate:>7.1f}%{'예' if r.monotonic else '아니오':>6}{r.periods:>6}"
        )
    broken = [r for r in ordered if r.looks_broken]
    lines.append("-" * 74)
    if broken:
        lines += [
            f"  ⚠️ 전 종목 평균 수익률이 회차당 {broken[0].market.mean():+.1f}% 로 나옵니다.",
            "     월 단위 리밸런싱에서 나올 수 없는 값입니다. 위 스프레드는",
            "     그룹 간 차이라 어느 정도 살아 있지만, 절대 수익률은 믿지 마세요.",
            "     가격 데이터를 먼저 점검해야 합니다.",
            "-" * 74,
        ]
    lines += [
        "  ★ = t값 2 이상이고 계단 모양. 그나마 볼 만한 후보입니다.",
        "",
        "  ※ 거래비용·유동성·체결이 빠진 계산입니다. '방향이 있는가' 만 봅니다.",
        "  ※ 여러 요인을 한꺼번에 보면 그중 하나는 우연히 좋아 보입니다.",
        "     후보가 나오면 기간을 나눠 다시 확인해야 합니다.",
        "=" * 74,
    ]
    return "\n".join(lines)
