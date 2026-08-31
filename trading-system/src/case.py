"""한 종목을 통째로 뜯어보기 — "그때 우리 시스템은 뭐라고 했나".

사장님이 실제로 크게 번 종목이 있다면, 그것보다 좋은 시험지는 없습니다.
답을 아는 문제니까요. 물어볼 것은 하나입니다.

    그 상승이 시작되기 전에, 우리 시스템은 그 종목을 골랐는가?

  · 골랐다      → 신호는 맞았고 우리 매도 규칙이 4배를 3%로 잘라먹은 것
  · 못 골랐다   → 우리 신호로는 이런 종목을 찾을 수 없다
  · 골랐는데 늦었다 → 이미 다 오른 뒤에 들어간 것

셋 중 무엇인지에 따라 고칠 곳이 완전히 달라집니다. 그래서 먼저 봅니다.

여기서는 판단하지 않습니다. 무슨 일이 있었는지만 늘어놓습니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Runup:
    """저점에서 고점까지 가장 크게 오른 구간."""
    start: pd.Timestamp
    end: pd.Timestamp
    low: float
    high: float

    @property
    def multiple(self) -> float:
        return self.high / self.low if self.low > 0 else float("nan")

    @property
    def days(self) -> int:
        return int((self.end - self.start).days)


def biggest_runup(close: pd.Series) -> Runup | None:
    """가장 크게 오른 구간(저점→그 이후 고점)을 찾습니다.

    '언제 사서 언제 팔았으면 최대였나' 와 같은 문제입니다.
    앞에서부터 훑으며 지금까지의 최저가를 기억하면 한 번에 구해집니다.
    """
    values = close.dropna()
    if len(values) < 2:
        return None

    prices = values.to_numpy(dtype=float)
    dates = values.index

    best_ratio, best = 0.0, None
    low_idx = 0
    for j in range(1, len(prices)):
        if prices[j] < prices[low_idx]:
            low_idx = j
            continue
        if prices[low_idx] <= 0:
            continue
        ratio = prices[j] / prices[low_idx]
        if ratio > best_ratio:
            best_ratio, best = ratio, (low_idx, j)

    if best is None:
        return None
    i, j = best
    return Runup(start=dates[i], end=dates[j], low=float(prices[i]), high=float(prices[j]))


def yearly(daily: pd.DataFrame) -> pd.DataFrame:
    """연도별 최저·최고·종가와 상승배수."""
    close = daily["close"].dropna()
    if close.empty:
        return pd.DataFrame()
    grouped = close.groupby(close.index.year)
    table = pd.DataFrame({
        "최저": grouped.min(),
        "최고": grouped.max(),
        "종가": grouped.last(),
    })
    table["고저배수"] = table["최고"] / table["최저"]
    table.index.name = "연도"
    return table


@dataclass
class SignalTiming:
    """신호가 상승 구간 어디쯤에서 났는가."""
    total: int = 0
    before_runup: int = 0            # 상승 시작 전 (아직 싸다)
    during_runup: int = 0            # 상승 중
    after_runup: int = 0             # 고점 지난 뒤
    first_signal: pd.Timestamp | None = None
    price_at_first: float = float("nan")
    dates: list[pd.Timestamp] = field(default_factory=list)


def timing(signal_dates: pd.DatetimeIndex, close: pd.Series,
           runup: Runup | None) -> SignalTiming:
    """신호 날짜들을 상승 구간 기준으로 분류합니다."""
    out = SignalTiming(total=len(signal_dates), dates=list(signal_dates))
    if len(signal_dates) == 0:
        return out
    out.first_signal = signal_dates[0]
    if out.first_signal in close.index:
        out.price_at_first = float(close.loc[out.first_signal])

    if runup is None:
        return out
    for date in signal_dates:
        if date < runup.start:
            out.before_runup += 1
        elif date <= runup.end:
            out.during_runup += 1
        else:
            out.after_runup += 1
    return out


def position_in_runup(price: float, runup: Runup | None) -> float:
    """상승 구간에서 그 가격이 몇 %쯤 되는 위치인가. 0=저점, 100=고점."""
    if runup is None or not np.isfinite(price):
        return float("nan")
    span = runup.high - runup.low
    if span <= 0:
        return float("nan")
    return (price - runup.low) / span * 100.0


def report(code: str, name: str, daily: pd.DataFrame, runup: Runup | None,
           years: pd.DataFrame, timing_info: SignalTiming,
           trades: list | None = None) -> str:
    """무슨 일이 있었는지만 늘어놓습니다."""
    close = daily["close"]
    lines = [
        "=" * 78,
        f"[사례 분석] {name} ({code})",
        f"   {daily.index.min().date()} ~ {daily.index.max().date()}"
        f" · {len(daily):,}거래일",
        "=" * 78,
        "",
    ]

    lines.append("[사실] 연도별 가격")
    if years.empty:
        lines.append("   자료 없음")
    else:
        lines.append("   연도      최저        최고        종가    고저배수")
        for year, row in years.iterrows():
            lines.append(
                f"   {year}  {row['최저']:>9,.0f}  {row['최고']:>10,.0f}"
                f"  {row['종가']:>10,.0f}  {row['고저배수']:>8.2f}배"
            )
    lines.append("")

    lines.append("[사실] 가장 크게 오른 구간")
    if runup is None:
        lines.append("   찾지 못했습니다.")
    else:
        lines.append(
            f"   {runup.start.date()} {runup.low:,.0f}원"
            f"  →  {runup.end.date()} {runup.high:,.0f}원"
        )
        lines.append(f"   {runup.multiple:.2f}배 · {runup.days:,}일 ({runup.days / 365:.1f}년)")
    lines.append("")

    lines.append("[사실] 우리 전략 스캐너가 이 종목에 신호를 낸 횟수")
    if timing_info.total == 0:
        lines.append("   0건. 이 종목은 우리 신호에 한 번도 걸리지 않았습니다.")
    else:
        lines.append(f"   전체 {timing_info.total}건")
        if runup is not None:
            lines.append(f"     상승 시작 전  {timing_info.before_runup:>4}건   ← 쌀 때 잡았나")
            lines.append(f"     상승 도중     {timing_info.during_runup:>4}건")
            lines.append(f"     고점 지난 뒤  {timing_info.after_runup:>4}건   ← 늦게 들어갔나")
        if timing_info.first_signal is not None:
            자리 = position_in_runup(timing_info.price_at_first, runup)
            자리말 = "" if np.isnan(자리) else f" (상승 구간의 {자리:.0f}% 지점)"
            lines.append(
                f"   첫 신호: {timing_info.first_signal.date()}"
                f"  {timing_info.price_at_first:,.0f}원{자리말}"
            )
    lines.append("")

    if trades is not None:
        lines.append("[사실] 그 신호대로 사고팔았다면 (손절·익절·비용 포함)")
        if not trades:
            lines.append("   매매 0건.")
        else:
            총손익 = sum(t.pnl for t in trades)
            이긴것 = sum(1 for t in trades if t.pnl > 0)
            lines.append(f"   매매 {len(trades)}건 · 이긴 매매 {이긴것}건 "
                         f"· 손익 {총손익:+,.0f}원")
            lines.append("")
            lines.append("   진입일        청산일       수익률    보유   청산사유")
            for t in trades[:15]:
                lines.append(
                    f"   {pd.Timestamp(t.entry_date).date()}  "
                    f"{pd.Timestamp(t.exit_date).date()}  "
                    f"{t.return_pct:>7.2f}%  {t.hold_days:>4}일   {t.exit_reason}"
                )
            if len(trades) > 15:
                lines.append(f"   ... 외 {len(trades) - 15}건")
    lines.append("")

    lines.append("[해석] 여기서부터는 사람이 봅니다.")
    lines.append("   · 신호가 0건이면 → 우리 신호로는 이런 종목을 찾을 수 없습니다.")
    lines.append("   · 상승 시작 전 신호가 있었는데 매매 손익이 나쁘면")
    lines.append("     → 신호는 맞았고 파는 규칙이 잘라먹은 것입니다.")
    lines.append("   · 신호가 전부 고점 근처면 → 이미 오른 뒤에 들어간 것입니다.")
    lines.append("")
    lines.append("   ⚠️ 종목 하나는 증거가 아닙니다. 결과를 알고 되돌아보는 것이라")
    lines.append("      무엇이든 그럴듯해 보입니다. 여기서 얻을 것은 '무엇을 고칠까'")
    lines.append("      의 힌트이지, '이 방법이 통한다' 는 확인이 아닙니다.")
    lines.append("=" * 78)
    return "\n".join(lines)
