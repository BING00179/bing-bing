"""신호에 우위가 있는가 — 규칙을 다 걷어내고 맨눈으로.

백테스트는 '신호 + 손절 + 익절 + 비용' 을 한 덩어리로 평가합니다.
그래서 결과가 나빠도 어디가 나쁜지 모릅니다. 손절이 잘못됐나?
익절이 일렀나? 아니면 신호 자체가 쓸모없나?

이 모듈은 규칙을 전부 걷어냅니다. 신호가 난 다음날 시가에 사서,
아무것도 하지 않고 N일 뒤 종가를 봅니다. 손절도 익절도 없습니다.

    신호에 우위가 있다  →  그냥 들고만 있어도 평균이 플러스
    신호에 우위가 없다  →  뭘 해도 플러스가 안 나옴

여기서 두 번째로 나오면, 손절폭을 아무리 손봐도 소용없습니다.
반대로 첫 번째로 나오면 문제는 신호가 아니라 우리 규칙입니다.

한 가지 더 중요한 것 — **비교 대상**.

  "신호 종목이 5일 뒤 +1.2%" 는 그 자체로 아무 뜻이 없습니다.
  그날 코스닥 아무 종목이나 샀어도 +2.0% 였다면, 우리 신호는
  무작위보다 나쁜 겁니다. 그래서 같은 날 전 종목 평균을 같이 재고
  그 차이(초과수익)를 봅니다. 이게 진짜 숫자입니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20)


@dataclass
class ForwardTable:
    """신호별 앞으로의 수익률과, 같은 날 전 종목 평균."""
    rows: pd.DataFrame                    # 신호 한 건 = 한 행
    horizons: tuple[int, ...] = HORIZONS


def _forward_returns(daily: pd.DataFrame, entry_idx: np.ndarray,
                     horizons: tuple[int, ...]) -> dict[int, np.ndarray]:
    """진입일 시가 대비 N일 뒤 종가 수익률(%). 데이터가 모자라면 nan."""
    opens = daily["open"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    n = len(daily)

    out: dict[int, np.ndarray] = {}
    for h in horizons:
        target = entry_idx + h - 1        # 진입일 포함 h일째 종가
        valid = (target < n) & (entry_idx < n)
        values = np.full(len(entry_idx), np.nan)
        if valid.any():
            base = opens[entry_idx[valid]]
            end = closes[target[valid]]
            with np.errstate(divide="ignore", invalid="ignore"):
                values[valid] = (end / base - 1.0) * 100.0
        out[h] = values
    return out


def signal_forward(code: str, daily: pd.DataFrame, signal_dates: pd.DatetimeIndex,
                   horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """한 종목의 신호들에 대해 '사고 나서 어떻게 됐나' 를 표로.

    신호는 D일 종가로 나고, 매수는 D+1일 시가입니다. 백테스트와 같은
    규칙이라야 비교가 됩니다.
    """
    if len(signal_dates) == 0:
        return pd.DataFrame()

    positions = daily.index.get_indexer(signal_dates)
    positions = positions[positions >= 0]
    entry_idx = positions + 1                       # D+1 시가에 진입
    keep = entry_idx < len(daily)
    positions, entry_idx = positions[keep], entry_idx[keep]
    if len(entry_idx) == 0:
        return pd.DataFrame()

    opens = daily["open"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    lows = daily["low"].to_numpy(dtype=float)
    highs = daily["high"].to_numpy(dtype=float)

    entry_open = opens[entry_idx]
    frame = pd.DataFrame({
        "code": code,
        "signal_date": daily.index[positions],
        "entry_date": daily.index[entry_idx],
        # 어제 종가 → 오늘 시가. 얼마나 비싸게 시작했나.
        "gap_pct": (entry_open / closes[positions] - 1.0) * 100.0,
        # 진입일 하루 동안 시가에서 얼마나 빠졌나. 손절선이 닿는 이유.
        "day1_low_pct": (lows[entry_idx] / entry_open - 1.0) * 100.0,
        "day1_high_pct": (highs[entry_idx] / entry_open - 1.0) * 100.0,
        "day1_close_pct": (closes[entry_idx] / entry_open - 1.0) * 100.0,
    })
    for h, values in _forward_returns(daily, entry_idx, horizons).items():
        frame[f"fwd{h}"] = values
    return frame


def market_forward(frames: dict[str, pd.DataFrame],
                   horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """비교 기준 — 날짜별로 '그날 아무 종목이나 샀을 때' 의 평균 수익률.

    이게 없으면 신호 성적이 좋은지 나쁜지 판단할 수 없습니다.
    """
    parts = []
    for code, daily in frames.items():
        if len(daily) < max(horizons) + 2:
            continue
        idx = np.arange(len(daily) - 1)
        entry_idx = idx + 1
        piece = pd.DataFrame({"entry_date": daily.index[entry_idx]})
        for h, values in _forward_returns(daily, entry_idx, horizons).items():
            piece[f"fwd{h}"] = values
        parts.append(piece)

    if not parts:
        return pd.DataFrame()
    everything = pd.concat(parts, ignore_index=True)
    return everything.groupby("entry_date").mean(numeric_only=True)


@dataclass
class EdgeResult:
    horizon: int
    signal_mean: float
    signal_median: float
    market_mean: float
    excess: float                 # 신호 평균 − 같은 날 시장 평균
    win_rate: float               # 신호가 플러스로 끝난 비율
    market_win_rate: float
    count: int
    t_stat: float                 # 초과수익이 0과 다른가


def edge(signals: pd.DataFrame, market: pd.DataFrame,
         horizons: tuple[int, ...] = HORIZONS) -> list[EdgeResult]:
    """신호가 같은 날 시장 평균을 이겼는가."""
    results: list[EdgeResult] = []
    if signals.empty:
        return results

    joined = signals.merge(
        market, left_on="entry_date", right_index=True,
        how="left", suffixes=("", "_mkt"),
    )

    for h in horizons:
        col, mkt_col = f"fwd{h}", f"fwd{h}_mkt"
        if col not in joined or mkt_col not in joined:
            continue
        part = joined[[col, mkt_col]].dropna()
        if len(part) < 30:
            continue
        diff = part[col] - part[mkt_col]
        std = float(diff.std(ddof=1))
        t = float(diff.mean() / (std / np.sqrt(len(diff)))) if std > 0 else 0.0
        results.append(EdgeResult(
            horizon=h,
            signal_mean=float(part[col].mean()),
            signal_median=float(part[col].median()),
            market_mean=float(part[mkt_col].mean()),
            excess=float(diff.mean()),
            win_rate=float((part[col] > 0).mean() * 100.0),
            market_win_rate=float((part[mkt_col] > 0).mean() * 100.0),
            count=len(part),
            t_stat=t,
        ))
    return results


GAP_BINS = (-np.inf, 0.0, 2.0, 5.0, 10.0, np.inf)
GAP_LABELS = ("갭 없음/하락", "0~2%", "2~5%", "5~10%", "10%+")


def by_gap(signals: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    """진입 갭 크기별 성적. '비싸게 시작할수록 나쁜가' 를 봅니다."""
    col = f"fwd{horizon}"
    if signals.empty or col not in signals:
        return pd.DataFrame()
    part = signals[["gap_pct", "day1_low_pct", col]].dropna()
    if part.empty:
        return pd.DataFrame()

    bucket = pd.cut(part["gap_pct"], bins=list(GAP_BINS), labels=list(GAP_LABELS))
    grouped = part.groupby(bucket, observed=False)
    table = pd.DataFrame({
        "건수": grouped.size(),
        "평균수익%": grouped[col].mean(),
        "중앙값%": grouped[col].median(),
        "승률%": grouped[col].apply(lambda s: (s > 0).mean() * 100.0),
        "진입일저가%": grouped["day1_low_pct"].mean(),
    })
    return table


def stop_reach(signals: pd.DataFrame, widths: tuple[float, ...] = (3, 5, 8, 10, 15)) -> pd.DataFrame:
    """손절폭별로 '진입 첫날에 닿았을 비율'.

    거래 기록만으로는 알 수 없던 것입니다. 여기서는 진입일 저가를
    직접 보고 세므로, 3% 손절이 왜 그렇게 많이 걸렸는지 알 수 있습니다.
    """
    if signals.empty or "day1_low_pct" not in signals:
        return pd.DataFrame()
    low = signals["day1_low_pct"].dropna()
    if low.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "손절폭%": list(widths),
        "첫날 닿는 비율%": [float((low <= -w).mean() * 100.0) for w in widths],
    })


def report(edges: list[EdgeResult], gaps: pd.DataFrame, stops: pd.DataFrame,
           signal_count: int) -> str:
    """사실과 해석을 갈라 적습니다."""
    lines = ["=" * 78,
             "[신호 진단] 손절·익절·비용을 전부 끄고, 신호만 봅니다",
             "=" * 78, ""]

    lines.append(f"[사실] 신호 {signal_count:,}건. 다음날 시가에 사서 그냥 들고 있었다면:")
    lines.append("")
    if not edges:
        lines.append("   비교할 표본이 부족합니다 (구간당 30건 이상 필요).")
    else:
        lines.append("   기간   신호평균   시장평균   초과    신호승률  시장승률   t값")
        lines.append("   " + "-" * 66)
        for e in edges:
            lines.append(
                f"   {e.horizon:>2}일  {e.signal_mean:>8.2f}%  {e.market_mean:>8.2f}%"
                f"  {e.excess:>+6.2f}%   {e.win_rate:>6.1f}%  {e.market_win_rate:>6.1f}%"
                f"  {e.t_stat:>6.2f}"
            )
        lines.append("")
        lines.append("   초과 = 신호평균 − 같은 날 전 종목 평균.")
        lines.append("   이 값이 0 이하면, 신호가 무작위보다 나은 게 없다는 뜻입니다.")
        lines.append("   t값은 그 차이가 우연인지 봅니다. |t| < 2 면 우연과 구분되지 않습니다.")
    lines.append("")

    if not gaps.empty:
        lines.append("[사실] 진입 갭 크기별 5일 성적 — 비싸게 시작할수록 어떤가")
        lines.append("")
        lines.append("   " + gaps.to_string().replace("\n", "\n   "))
        lines.append("")

    if not stops.empty:
        lines.append("[사실] 손절폭별 '진입 첫날에 닿았을' 비율")
        lines.append("")
        lines.append("   " + stops.to_string(index=False).replace("\n", "\n   "))
        lines.append("")

    lines.append("[해석] 판단은 아래 기준으로만 하십시오.")
    lines.append("   · 초과수익이 0 이하  → 신호에 우위가 없습니다. 손절을 고쳐도 안 됩니다.")
    lines.append("   · 초과수익이 +이고 t > 2 → 신호는 살아 있고, 규칙이 망친 겁니다.")
    lines.append("   · 초과수익이 +인데 t < 2 → 있는지 없는지 알 수 없습니다. 표본이 부족합니다.")
    lines.append("=" * 78)
    return "\n".join(lines)
