"""포트폴리오 백테스트 — 실제로 돈을 굴리듯 계산합니다.

지금까지의 백테스트는 종목마다 따로 계산했습니다. 신호가 나면
무조건 샀고, 하루에 20종목이 걸리면 20종목을 다 산 것으로
쳤습니다. 그러려면 자본이 수십억 필요합니다.

실제로는 이렇습니다.

    자본 1,000만원, 동시에 3종목까지
    → 3종목을 들고 있으면 네 번째 신호는 못 삽니다
    → 하나를 팔아야 자리가 납니다
    → 어느 것을 먼저 골랐느냐가 결과를 좌우합니다

그래서 '총 손익' 이 아니라 '1,000만원이 얼마가 됐나' 가 나옵니다.
이게 실제로 알고 싶은 숫자입니다.

날짜 순서대로 하루씩 진행하며, 하루에 이 순서로 처리합니다.

    1. 보유 종목 중 청산 조건에 닿은 것을 팝니다 (현금 회수)
    2. 빈 자리가 있으면 그날 신호 중 점수 높은 순으로 채웁니다
    3. 자리가 없으면 신호가 와도 못 삽니다

⚠️ 미래를 보지 않습니다. 신호는 D일 종가로 판정하고 진입은
   D+1일 시가입니다. 청산 판정도 그날 고가·저가만 씁니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BacktestConfig


@dataclass
class Position:
    code: str
    name: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop_price: float
    peak_price: float          # 추격 손절용 최고가
    bars_held: int = 0

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares


@dataclass
class PortfolioTrade:
    code: str
    name: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    exit_reason: str
    pnl: float
    return_pct: float
    hold_days: int


@dataclass
class PortfolioResult:
    start_cash: float
    end_value: float
    trades: list[PortfolioTrade] = field(default_factory=list)
    equity: pd.Series | None = None
    skipped_no_slot: int = 0      # 자리가 없어 못 산 신호 수
    skipped_no_cash: int = 0      # 현금이 모자라 못 산 신호 수

    @property
    def total_return_pct(self) -> float:
        return (self.end_value - self.start_cash) / self.start_cash * 100.0


def _apply_slippage(price: float, side: str, pct: float) -> float:
    return price * (1 + pct / 100.0) if side == "buy" else price * (1 - pct / 100.0)


def _costs(buy_value: float, sell_value: float, bt: BacktestConfig) -> float:
    commission = (
        bt.commission_per_trade * 2
        + (buy_value + sell_value) * bt.commission_pct / 100.0
    )
    return commission + sell_value * bt.sell_tax_pct / 100.0


def run(
    signals: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    bt: BacktestConfig,
    *,
    start_cash: float = 10_000_000.0,
    max_positions: int = 3,
    names: dict[str, str] | None = None,
) -> PortfolioResult:
    """날짜 순서대로 하루씩 진행하며 매매를 시뮬레이션합니다.

    signals  신호 목록. 인덱스가 신호일(날짜), 컬럼에 ticker 와 score.
             같은 날 여러 종목이 있으면 score 높은 것부터 삽니다.
    frames   종목코드 → 일봉 DataFrame
    """
    names = names or {}
    if signals.empty:
        return PortfolioResult(start_cash, start_cash)

    # 전체 거래일을 하나로 모읍니다. 종목마다 상장·거래정지가 달라
    # 날짜가 다르므로 합집합을 씁니다.
    calendar = sorted(set().union(*(f.index for f in frames.values())))
    calendar = pd.DatetimeIndex(calendar)

    # 신호일 → 그날 신호 목록 (점수 높은 순)
    by_day: dict[pd.Timestamp, list[tuple[str, float]]] = {}
    for day, group in signals.groupby(level=0):
        ordered = group.sort_values("score", ascending=False)
        by_day[day] = list(zip(ordered["ticker"], ordered["score"]))

    cash = start_cash
    holdings: dict[str, Position] = {}
    trades: list[PortfolioTrade] = []
    equity_dates: list[pd.Timestamp] = []
    equity_values: list[float] = []
    skipped_slot = skipped_cash = 0

    trailing = bt.trailing_stop_pct / 100.0 if bt.trailing_stop_pct > 0 else 0.0
    take_profit = bt.take_profit_pct / 100.0 if bt.take_profit_pct > 0 else 0.0

    for i, today in enumerate(calendar):
        # ── 1. 청산 ──
        for code in list(holdings):
            pos = holdings[code]
            bar = frames[code].loc[today] if today in frames[code].index else None
            if bar is None:
                continue                      # 거래정지 등. 그대로 보유

            pos.bars_held += 1
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            pos.peak_price = max(pos.peak_price, high)

            stop = pos.stop_price
            if trailing:
                stop = max(stop, pos.peak_price * (1 - trailing))

            exit_price = exit_reason = None
            if low <= stop:                   # 손절 우선(보수적)
                exit_price, exit_reason = stop, "stop"
            elif take_profit and high >= pos.entry_price * (1 + take_profit):
                exit_price, exit_reason = pos.entry_price * (1 + take_profit), "target"
            elif pos.bars_held >= bt.max_hold_days:
                exit_price, exit_reason = close, "timeout"

            if exit_price is None:
                continue

            fill = _apply_slippage(float(exit_price), "sell", bt.slippage_pct)
            sell_value = fill * pos.shares
            pnl = sell_value - pos.cost - _costs(pos.cost, sell_value, bt)
            cash += sell_value - _costs(pos.cost, sell_value, bt)

            trades.append(
                PortfolioTrade(
                    code=code, name=pos.name,
                    entry_date=pos.entry_date, exit_date=today,
                    entry_price=round(pos.entry_price, 1), exit_price=round(fill, 1),
                    shares=pos.shares, exit_reason=exit_reason,
                    pnl=round(pnl, 0),
                    return_pct=round(pnl / pos.cost * 100.0, 3),
                    hold_days=pos.bars_held,
                )
            )
            del holdings[code]

        # ── 2. 진입 (전날 신호를 오늘 시가에) ──
        if i > 0:
            for code, score in by_day.get(calendar[i - 1], []):
                if len(holdings) >= max_positions:
                    skipped_slot += 1
                    continue
                if code in holdings:
                    continue
                frame = frames.get(code)
                if frame is None or today not in frame.index:
                    continue

                price = _apply_slippage(float(frame.loc[today, "open"]), "buy",
                                        bt.slippage_pct)
                if price <= 0:
                    continue

                # 남은 자리 수로 현금을 나눠 한 종목에 몰리지 않게 합니다.
                slots_left = max_positions - len(holdings)
                budget = min(cash / slots_left, cash)
                shares = int(budget // price)
                if shares < 1:
                    skipped_cash += 1
                    continue

                cost = price * shares
                cash -= cost
                holdings[code] = Position(
                    code=code, name=names.get(code, ""),
                    entry_date=today, entry_price=price, shares=shares,
                    stop_price=price * (1 - bt.stop_loss_pct / 100.0),
                    peak_price=price,
                )

        # ── 3. 그날의 평가액 ──
        held_value = 0.0
        for code, pos in holdings.items():
            frame = frames[code]
            if today in frame.index:
                held_value += float(frame.loc[today, "close"]) * pos.shares
            else:
                held_value += pos.entry_price * pos.shares
        equity_dates.append(today)
        equity_values.append(cash + held_value)

    # 남은 보유는 마지막 종가로 청산한 것으로 봅니다.
    final = equity_values[-1] if equity_values else start_cash

    return PortfolioResult(
        start_cash=start_cash,
        end_value=final,
        trades=trades,
        equity=pd.Series(equity_values, index=pd.DatetimeIndex(equity_dates)),
        skipped_no_slot=skipped_slot,
        skipped_no_cash=skipped_cash,
    )


def summarize(result: PortfolioResult) -> dict:
    """1,000만원이 얼마가 됐나 — 실제로 알고 싶은 숫자들."""
    trades = result.trades
    equity = result.equity

    if equity is None or equity.empty:
        years = 0.0
        mdd = 0.0
    else:
        days = (equity.index[-1] - equity.index[0]).days
        years = days / 365.25 if days else 0.0
        peak = equity.cummax()
        mdd = float(((equity - peak) / peak).min() * 100.0)

    total_return = result.total_return_pct
    if years > 0 and result.start_cash > 0 and result.end_value > 0:
        cagr = ((result.end_value / result.start_cash) ** (1 / years) - 1) * 100.0
    else:
        cagr = 0.0

    pnl = np.array([t.pnl for t in trades], dtype=float) if trades else np.array([])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gross_loss = -losses.sum() if losses.size else 0.0

    return {
        "start_cash": result.start_cash,
        "end_value": round(result.end_value, 0),
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(mdd, 2),
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "avg_win_pct": round(float(np.mean([t.return_pct for t in trades if t.pnl > 0])), 2)
        if wins.size else 0.0,
        "avg_loss_pct": round(float(np.mean([t.return_pct for t in trades if t.pnl <= 0])), 2)
        if losses.size else 0.0,
        "profit_factor": round(float(wins.sum() / gross_loss), 3)
        if gross_loss > 0 else (float("inf") if wins.size else 0.0),
        "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 1)
        if trades else 0.0,
        "skipped_no_slot": result.skipped_no_slot,
        "skipped_no_cash": result.skipped_no_cash,
        "years": round(years, 2),
    }
