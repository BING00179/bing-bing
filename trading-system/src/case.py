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
           trades: list | None = None, max_trades: int = 15,
           drops: pd.DataFrame | None = None,
           holds: list | None = None) -> str:
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
            for t in trades[:max_trades]:
                lines.append(
                    f"   {pd.Timestamp(t.entry_date).date()}  "
                    f"{pd.Timestamp(t.exit_date).date()}  "
                    f"{t.return_pct:>7.2f}%  {t.hold_days:>4}일   {t.exit_reason}"
                )
            if len(trades) > max_trades:
                lines.append(f"   ... 외 {len(trades) - max_trades}건 (--all 로 전부 보기)")
    lines.append("")

    if drops is not None and not drops.empty:
        lines.append("[사실] 그 상승 구간 안에서의 되돌림 — 추격손절이 견딜 수 있었나")
        lines.append("")
        lines.append("   " + drops.to_string(index=False).replace("\n", "\n   "))
        lines.append("")

    if holds:
        lines.append("[사실] 상승 시작일에 사서 추격손절만 걸었다면")
        lines.append("")
        lines.append("   추격손절    청산일        보유      먹은 배수   최대상승분의")
        for h in holds:
            날 = "—" if h.exit_date is None else str(pd.Timestamp(h.exit_date).date())
            잡은 = "—" if np.isnan(h.captured_pct) else f"{h.captured_pct:>6.1f}%"
            lines.append(
                f"   {h.trail_pct:>6.0f}%   {날:>12}  {h.days_held:>5}일"
                f"   {h.multiple:>8.2f}배   {잡은}"
            )
        lines.append("")
        lines.append("   '최대상승분의' = 그 구간에서 오를 수 있었던 것 중 몇 %를 먹었나.")
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

# ─────────────────── 그 상승을 우리 규칙으로 끝까지 들고 갈 수 있었나 ───────────────────
# 큰 상승은 곧게 올라가지 않습니다. 오르다 되돌리고, 또 오릅니다.
# 추격손절이 그 되돌림보다 좁으면, 종목을 아무리 잘 골라도
# 첫 되돌림에서 잘려 나갑니다. 종목 선정이 아니라 보유 규칙의 문제입니다.


@dataclass
class HoldTest:
    trail_pct: float
    exit_date: pd.Timestamp | None
    exit_price: float
    multiple: float               # 상승 시작가 대비 실제로 먹은 배수
    captured_pct: float           # 최대 상승분의 몇 %를 먹었나
    days_held: int


def pullbacks(daily: pd.DataFrame, runup: Runup | None) -> pd.Series:
    """상승 구간 안에서, 그때까지의 고점 대비 얼마나 되돌렸나(%)."""
    if runup is None:
        return pd.Series(dtype=float)
    window = daily.loc[runup.start:runup.end]
    if window.empty:
        return pd.Series(dtype=float)
    peak = window["high"].cummax()
    return (window["low"] / peak - 1.0) * 100.0


def pullback_summary(drops: pd.Series,
                     widths: tuple[float, ...] = (7.0, 10.0, 15.0, 20.0, 30.0)) -> pd.DataFrame:
    """되돌림이 각 폭을 몇 번 넘었나. 추격손절 폭을 고를 근거."""
    if drops.empty:
        return pd.DataFrame()
    rows = []
    for w in widths:
        touched = drops <= -w
        # 연속으로 걸린 날은 한 번으로 셉니다 (같은 되돌림이므로).
        starts = int((touched & ~touched.shift(1, fill_value=False)).sum())
        rows.append({"되돌림 폭%": w, "닿은 횟수": starts,
                     "닿은 날 수": int(touched.sum())})
    return pd.DataFrame(rows)


def hold_with_trailing(daily: pd.DataFrame, runup: Runup | None,
                       trail_pct: float, max_hold_days: int | None = None) -> HoldTest | None:
    """상승 시작일에 사서 추격손절만 걸었다면 언제 나갔을까.

    손절선은 '어제까지의 고점' 으로 계산합니다. 오늘 장중 고가를 쓰면
    미래를 보는 것이 됩니다 — 백테스트와 같은 규칙입니다.
    """
    if runup is None:
        return None
    window = daily.loc[runup.start:]
    if window.empty:
        return None

    entry = float(window["close"].iloc[0])
    if entry <= 0:
        return None

    peak = entry
    limit = len(window) if max_hold_days is None else min(len(window), max_hold_days)
    for i in range(limit):
        low = float(window["low"].iloc[i])
        stop = peak * (1.0 - trail_pct / 100.0)
        if i > 0 and low <= stop:
            return HoldTest(
                trail_pct=trail_pct,
                exit_date=window.index[i],
                exit_price=stop,
                multiple=stop / entry,
                captured_pct=(stop / entry - 1.0) / (runup.high / entry - 1.0) * 100.0
                if runup.high > entry else float("nan"),
                days_held=i,
            )
        peak = max(peak, float(window["high"].iloc[i]))

    last = float(window["close"].iloc[limit - 1])
    return HoldTest(
        trail_pct=trail_pct,
        exit_date=window.index[limit - 1],
        exit_price=last,
        multiple=last / entry,
        captured_pct=(last / entry - 1.0) / (runup.high / entry - 1.0) * 100.0
        if runup.high > entry else float("nan"),
        days_held=limit - 1,
    )

