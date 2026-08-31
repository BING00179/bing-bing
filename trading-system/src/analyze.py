"""이미 나온 백테스트 결과를 파헤칩니다.

백테스트는 '이 전략이 통했나' 에 답합니다. 이 모듈은 그다음 질문에
답합니다 — '왜 안 통했나, 어디를 고쳐야 하나'.

새로 데이터를 받지 않습니다. 저장된 매매 기록(CSV)만 읽습니다.
그래서 시세 조회가 막혀 있어도 돌아갑니다.

보는 것들.

    청산 사유별 성적    손절이 너무 빡빡했나, 익절이 일렀나
    보유 기간별 성적    짧게 끊은 게 문제였나
    진입 시점별 성적    특정 시기에만 나빴나
    종목별 쏠림         소수 종목이 결과를 좌우했나
    수익률 분포         큰 손실 몇 건이 전체를 망쳤나
    비용의 무게         거래비용이 얼마나 갉아먹었나
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ("ticker", "entry_date", "exit_date", "pnl", "return_pct",
            "exit_reason", "hold_days")


def load(path: str | Path) -> pd.DataFrame:
    """매매 기록 CSV 를 읽습니다."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"매매 기록이 없습니다: {path}")

    frame = pd.read_csv(path, dtype={"ticker": str, "code": str})
    if "code" in frame.columns and "ticker" not in frame.columns:
        frame = frame.rename(columns={"code": "ticker"})

    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ValueError(f"필요한 컬럼이 없습니다: {missing}")

    for col in ("entry_date", "exit_date"):
        frame[col] = pd.to_datetime(frame[col])
    return frame


def _pf(group: pd.DataFrame) -> float:
    wins = group.loc[group["pnl"] > 0, "pnl"].sum()
    losses = -group.loc[group["pnl"] <= 0, "pnl"].sum()
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def _stats(group: pd.DataFrame) -> dict:
    return {
        "건수": len(group),
        "승률": round((group["pnl"] > 0).mean() * 100, 1),
        "평균수익률": round(group["return_pct"].mean(), 2),
        "총손익": round(group["pnl"].sum(), 0),
        "PF": round(_pf(group), 3),
    }


def by_exit_reason(trades: pd.DataFrame) -> pd.DataFrame:
    """청산 사유별. 손절이 전체를 갉아먹는지 여기서 보입니다."""
    rows = {reason: _stats(g) for reason, g in trades.groupby("exit_reason")}
    return pd.DataFrame(rows).T.sort_values("건수", ascending=False)


def by_hold_days(trades: pd.DataFrame) -> pd.DataFrame:
    """보유 기간 구간별. 짧게 끊은 게 문제였는지."""
    bins = [0, 1, 3, 5, 10, 20, 10_000]
    labels = ["1일", "2-3일", "4-5일", "6-10일", "11-20일", "20일 초과"]
    grouped = pd.cut(trades["hold_days"], bins=bins, labels=labels, right=True)
    rows = {str(k): _stats(g) for k, g in trades.groupby(grouped, observed=True)}
    return pd.DataFrame(rows).T


def by_period(trades: pd.DataFrame, freq: str = "QE") -> pd.DataFrame:
    """진입 시점별. 특정 시기에만 나빴는지 확인합니다."""
    period = trades["entry_date"].dt.to_period("Q" if freq == "QE" else "M")
    rows = {str(k): _stats(g) for k, g in trades.groupby(period, observed=True)}
    return pd.DataFrame(rows).T


def concentration(trades: pd.DataFrame, top: int = 10) -> dict:
    """소수 종목이 결과를 좌우했는지.

    상위 몇 종목을 빼면 결과가 뒤집히는 전략은 신뢰할 수 없습니다.
    운 좋게 한두 개를 잡았을 뿐일 수 있습니다.
    """
    by_ticker = trades.groupby("ticker")["pnl"].sum().sort_values()
    total = float(trades["pnl"].sum())

    best = by_ticker.tail(top)
    worst = by_ticker.head(top)
    without_best = total - float(best.sum())
    without_worst = total - float(worst.sum())

    return {
        "총손익": round(total, 0),
        "종목수": int(trades["ticker"].nunique()),
        f"상위{top}종목_손익": round(float(best.sum()), 0),
        f"하위{top}종목_손익": round(float(worst.sum()), 0),
        f"상위{top}_제외시_총손익": round(without_best, 0),
        f"하위{top}_제외시_총손익": round(without_worst, 0),
        "최고종목": by_ticker.index[-1],
        "최고종목_손익": round(float(by_ticker.iloc[-1]), 0),
        "최악종목": by_ticker.index[0],
        "최악종목_손익": round(float(by_ticker.iloc[0]), 0),
    }


def return_distribution(trades: pd.DataFrame) -> pd.DataFrame:
    """수익률 구간별 분포. 꼬리가 어느 쪽으로 두꺼운지."""
    bins = [-100, -10, -5, -3, 0, 3, 5, 10, 20, 1000]
    labels = ["-10%↓", "-10~-5%", "-5~-3%", "-3~0%",
              "0~3%", "3~5%", "5~10%", "10~20%", "20%↑"]
    grouped = pd.cut(trades["return_pct"], bins=bins, labels=labels)
    counted = trades.groupby(grouped, observed=False).agg(
        건수=("pnl", "size"), 총손익=("pnl", "sum")
    )
    counted["비중"] = (counted["건수"] / len(trades) * 100).round(1)
    counted["총손익"] = counted["총손익"].round(0)
    return counted


def cost_weight(trades: pd.DataFrame, cost_pct_round_trip: float = 0.51) -> dict:
    """거래비용이 결과에서 차지하는 무게.

    매매 건수 × 왕복 비용률로 어림합니다. 비용을 빼기 전 수익률이
    양수인데 뺀 뒤 음수라면, 전략이 나쁜 게 아니라 너무 자주
    사고파는 것이 문제일 수 있습니다.
    """
    n = len(trades)
    gross = float(trades["return_pct"].sum()) + n * cost_pct_round_trip
    net = float(trades["return_pct"].sum())
    return {
        "매매건수": n,
        "비용차감전_누적수익률": round(gross, 1),
        "비용차감후_누적수익률": round(net, 1),
        "비용_누적": round(n * cost_pct_round_trip, 1),
        "비용이_먹은_비중": (
            round(n * cost_pct_round_trip / abs(gross) * 100, 1) if gross else 0.0
        ),
    }


def _table(frame: pd.DataFrame, title: str) -> list[str]:
    lines = [f"── {title} ──"]
    lines.append(frame.to_string(float_format=lambda v: f"{v:,.2f}"))
    return lines + [""]


def report(trades: pd.DataFrame, top: int = 10) -> str:
    """전체 분석을 한 번에."""
    lines = [
        "=" * 78,
        f"[매매 기록 분석] {len(trades):,}건 · "
        f"{trades['entry_date'].min():%Y-%m-%d} ~ {trades['exit_date'].max():%Y-%m-%d}",
        "=" * 78,
        "",
    ]
    lines += _table(by_exit_reason(trades), "청산 사유별")
    lines += _table(by_hold_days(trades), "보유 기간별")
    lines += _table(return_distribution(trades), "수익률 분포")

    conc = concentration(trades, top)
    lines += [f"── 종목 쏠림 (상·하위 {top}종목) ──"]
    for k, v in conc.items():
        lines.append(f"  {k:<24} {v:>18,}" if isinstance(v, (int, float)) else f"  {k:<24} {v:>18}")
    lines += [""]

    cost = cost_weight(trades)
    lines += ["── 거래비용의 무게 ──"]
    for k, v in cost.items():
        lines.append(f"  {k:<24} {v:>18,}")
    lines += [
        "",
        "=" * 78,
        "  ※ 이 분석은 이미 나온 결과를 뜯어보는 것입니다. 새 전략을 만들거나",
        "     조건을 바꿔 다시 돌리면 과거에만 맞는 답을 찾게 됩니다.",
        "     '어디가 문제였나' 를 아는 데까지만 쓰세요.",
        "=" * 78,
    ]
    return "\n".join(lines)
