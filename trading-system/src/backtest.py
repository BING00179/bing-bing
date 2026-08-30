"""백테스트 — 전략이 과거에 통했는지 검증합니다.

설계 원칙(결과를 부풀리지 않기 위한 것들):

  * 신호는 D일 종가로 판정하고 진입은 D+1일 시가에서 합니다.
    같은 날 종가로 판정해서 같은 날 종가에 사는 것은 미래를 미리 본
    것(look-ahead bias)이라 실거래에서 재현되지 않습니다.
  * 수수료와 슬리피지를 왕복으로 뺍니다. 갭 상승 종목은 호가 스프레드가
    넓어서 이 항목을 빼면 백테스트가 크게 낙관적으로 나옵니다.
  * 손절과 익절이 같은 날 둘 다 닿았으면 '손절 먼저'로 처리합니다.
    일봉만으로는 어느 쪽이 먼저였는지 알 수 없으므로 불리한 쪽을 택합니다.
  * 한 종목에서 포지션이 겹치지 않습니다(청산 전 재진입 없음).
  * 추격 손절선은 '어제까지의 최고가'로 계산합니다. 오늘 장중에
    찍은 고가를 오늘의 손절선에 쓰면, 하루 안에 고점을 찍고 되돌린
    움직임을 미리 알고 판 셈이 되어 결과가 부풀려집니다.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .config import BacktestConfig, ScannerBConfig
from .indicators import sma
from .strategy import signals_from_daily


@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    exit_reason: str        # stop / target / timeout / end_of_data
    pnl: float              # 수수료·슬리피지 반영 후 손익 ($)
    return_pct: float       # 투입금 대비 수익률 (%)
    hold_days: int


def _apply_costs(price: float, side: str, slippage_pct: float) -> float:
    """슬리피지 반영 체결가. 매수는 불리하게 위로, 매도는 아래로."""
    factor = 1.0 + slippage_pct / 100.0 if side == "buy" else 1.0 - slippage_pct / 100.0
    return price * factor


def run(
    ticker: str,
    daily: pd.DataFrame,
    bt: BacktestConfig,
    sb: ScannerBConfig,
) -> list[Trade]:
    """한 종목의 일봉 전체에 대해 매매를 시뮬레이션합니다."""
    sig = signals_from_daily(daily, sb)
    trades: list[Trade] = []

    ma_break = None
    if bt.exit_on_ma_break > 0:
        ma_break = sma(daily["close"], bt.exit_on_ma_break).to_numpy(dtype=float)

    opens = daily["open"].to_numpy(dtype=float)
    highs = daily["high"].to_numpy(dtype=float)
    lows = daily["low"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    dates = daily.index
    signals = sig["signal"].to_numpy(dtype=bool)
    n = len(daily)

    i = 0
    while i < n - 1:
        if not signals[i]:
            i += 1
            continue

        entry_idx = i + 1                      # 신호 다음 날 시가 진입
        entry_price = _apply_costs(opens[entry_idx], "buy", bt.slippage_pct)
        if entry_price <= 0:
            i += 1
            continue

        shares = int(bt.capital_per_trade // entry_price)
        if shares < 1:
            i += 1                             # 주가가 투입금보다 비싸면 건너뜀
            continue

        initial_stop = entry_price * (1.0 - bt.stop_loss_pct / 100.0)
        use_target = bt.take_profit_pct > 0
        use_trailing = bt.trailing_stop_pct > 0
        target_price = (
            entry_price * (1.0 + bt.take_profit_pct / 100.0) if use_target else None
        )

        exit_idx = None
        exit_price = None
        exit_reason = ""
        last_idx = min(entry_idx + bt.max_hold_days - 1, n - 1)
        peak = entry_price                     # 진입 후 최고가 (어제까지)

        for j in range(entry_idx, last_idx + 1):
            # 오늘의 손절선은 어제까지의 정보로만 정합니다.
            stop_price = initial_stop
            if use_trailing:
                trail = peak * (1.0 - bt.trailing_stop_pct / 100.0)
                stop_price = max(stop_price, trail)

            if lows[j] <= stop_price:          # 손절 우선(보수적)
                exit_idx = j
                exit_price = stop_price
                exit_reason = "trail" if use_trailing and stop_price > initial_stop else "stop"
                break
            if use_target and highs[j] >= target_price:
                exit_idx, exit_price, exit_reason = j, target_price, "target"
                break
            if ma_break is not None and j > entry_idx and closes[j] < ma_break[j]:
                exit_idx, exit_price, exit_reason = j, closes[j], "ma_break"
                break

            peak = max(peak, highs[j])         # 다음 날 손절선에 반영

        if exit_idx is None:
            exit_idx = last_idx
            exit_price = closes[last_idx]
            exit_reason = "timeout" if last_idx < n - 1 else "end_of_data"

        fill = _apply_costs(float(exit_price), "sell", bt.slippage_pct)
        gross = (fill - entry_price) * shares
        pnl = gross - bt.commission_per_trade * 2   # 왕복 수수료
        invested = entry_price * shares

        trades.append(
            Trade(
                ticker=ticker,
                entry_date=dates[entry_idx],
                exit_date=dates[exit_idx],
                entry_price=round(entry_price, 4),
                exit_price=round(fill, 4),
                shares=shares,
                exit_reason=exit_reason,
                pnl=round(pnl, 2),
                return_pct=round(pnl / invested * 100.0, 4),
                hold_days=exit_idx - entry_idx + 1,
            )
        )
        i = exit_idx + 1                        # 청산 다음 날부터 다시 탐색

    return trades


def summarize(trades: list[Trade]) -> dict:
    """매매 목록에서 성과 지표를 뽑습니다."""
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "avg_return_pct": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy_pct": 0.0,
            "max_drawdown": 0.0,
            "avg_hold_days": 0.0,
        }

    pnl = np.array([t.pnl for t in trades], dtype=float)
    ret = np.array([t.return_pct for t in trades], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]

    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))
    drawdown = peak - np.concatenate([[0.0], equity])

    gross_loss = -losses.sum()
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 2),
        "total_pnl": round(float(pnl.sum()), 2),
        "avg_return_pct": round(float(ret.mean()), 3),
        "avg_win_pct": round(float(ret[pnl > 0].mean()), 3) if wins.size else 0.0,
        "avg_loss_pct": round(float(ret[pnl <= 0].mean()), 3) if losses.size else 0.0,
        "profit_factor": (
            round(float(wins.sum() / gross_loss), 3) if gross_loss > 0 else float("inf")
        ),
        "expectancy_pct": round(float(ret.mean()), 3),
        "max_drawdown": round(float(drawdown.max()), 2),
        "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 2),
    }


def trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=[f.name for f in Trade.__dataclass_fields__.values()]
        )
    return pd.DataFrame([asdict(t) for t in trades])
