"""가상 계좌 규칙 — 순수 함수만. 시세도 파일도 여기서 안 만집니다.

사장님 원칙(CLAUDE.md §5)을 숫자로 옮긴 것입니다. 숫자는 Rules 에서만 옵니다.
판단은 D일 종가, 체결은 D+1일 시가 (§8). 돈은 0원입니다.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import pandas as pd

from src.config import VirtualAccountConfig

# 규칙 값을 바꾸면 올립니다. 그날부터 시계가 다시 갑니다 (§12).
VIRTUAL_VERSION = "1"

SIDE_BUY, SIDE_SELL = "매수", "매도"
BUY_TRANCHES = ("1차", "2차", "3차")
SELL_TRANCHES = ("매도1", "매도2", "매도3")
T_INVALID, T_BASIS = "무효", "근거"


@dataclass(frozen=True)
class Rules:
    capital: float
    max_positions: int
    position_cap_pct: float
    cash_reserve: float
    buy_tranches_pct: tuple
    tranche2_trigger_pct: float
    tranche3_trigger_pct: float
    sell_tranches: tuple
    invalid_pct: float
    daily_loss_halt_pct: float
    slippage_pct: float
    fee_buy_pct: float
    fee_sell_pct: float
    tax_pct: float

    @classmethod
    def from_config(cls, cfg: VirtualAccountConfig) -> "Rules":
        return cls(capital=cfg.capital, max_positions=cfg.max_positions,
                   position_cap_pct=cfg.position_cap_pct, cash_reserve=cfg.cash_reserve,
                   buy_tranches_pct=tuple(cfg.buy_tranches_pct),
                   tranche2_trigger_pct=cfg.tranche2_trigger_pct,
                   tranche3_trigger_pct=cfg.tranche3_trigger_pct,
                   sell_tranches=tuple(cfg.sell_tranches), invalid_pct=cfg.invalid_pct,
                   daily_loss_halt_pct=cfg.daily_loss_halt_pct, slippage_pct=cfg.slippage_pct,
                   fee_buy_pct=cfg.fee_buy_pct, fee_sell_pct=cfg.fee_sell_pct, tax_pct=cfg.tax_pct)

    def allotment(self) -> float:
        return self.capital * self.position_cap_pct / 100.0

    def tranche_amount(self, n: int) -> float:
        return self.allotment() * self.buy_tranches_pct[n - 1] / 100.0


@dataclass
class Position:
    code: str
    name: str
    shares: int = 0
    cost: float = 0.0
    tranche_done: int = 0
    first_price: float = 0.0
    sells_done: int = 0

    @property
    def avg_price(self) -> float:
        return self.cost / self.shares if self.shares else 0.0


@dataclass(frozen=True)
class Order:
    order_id: str
    date: str
    code: str
    name: str
    side: str
    tranche: str
    shares: int
    amount: float
    reason: str


@dataclass(frozen=True)
class Fill:
    order_id: str
    date: str
    code: str
    name: str
    side: str
    tranche: str
    shares: int
    price: float
    fee: float
    tax: float
    slippage: float
    amount: float
    reason: str


@dataclass(frozen=True)
class Decision:
    date: str
    code: str
    name: str
    action: str
    gate: str
    detail: str


def make_order_id(date: str, code: str, side: str, tranche: str) -> str:
    return hashlib.sha1(f"{date}|{code}|{side}|{tranche}".encode("utf-8")).hexdigest()[:10]


def replay(trades: pd.DataFrame, rules: Rules) -> tuple[dict[str, Position], float]:
    """체결 기록을 처음부터 되감아 지금 보유와 현금을 만듭니다.

    보유 현황을 따로 저장하지 않는 이유: 저장이 둘이면 언젠가 어긋납니다.
    """
    positions: dict[str, Position] = {}
    cash = float(rules.capital)
    if trades is None or trades.empty:
        return positions, cash
    # 같은 날은 매도가 먼저 (문자열 순서에 기대지 않고 키로 명시). stable 정렬이라 나머지는 기록 순서.
    order_key = (trades["side"] != SIDE_SELL).astype(int)
    rows = trades.assign(_side_order=order_key).sort_values(["date", "_side_order"], kind="stable").to_dict("records")
    for r in rows:
        code = str(r["code"]); shares = int(r["shares"]); amount = float(r["amount"])
        p = positions.setdefault(code, Position(code=code, name=str(r.get("name", ""))))
        if r["side"] == SIDE_BUY:
            if p.shares == 0 and p.tranche_done == 0:
                p.first_price = float(r["price"])
            p.shares += shares
            p.cost += amount
            if r["tranche"] in BUY_TRANCHES:
                p.tranche_done = max(p.tranche_done, BUY_TRANCHES.index(r["tranche"]) + 1)
            cash -= amount
        else:
            # 평단은 유지하고 원가를 비례해서 뺍니다.
            if p.shares:
                p.cost -= p.avg_price * shares
            p.shares -= shares
            if r["tranche"] in SELL_TRANCHES:
                p.sells_done = max(p.sells_done, SELL_TRANCHES.index(r["tranche"]) + 1)
            cash += amount
            if p.shares <= 0:
                del positions[code]
    return positions, cash


def value_of(positions: dict[str, Position], closes: dict[str, float]) -> float:
    return sum(p.shares * closes.get(code, p.avg_price) for code, p in positions.items())


def pct_change(price: float, base: float) -> float:
    """base 대비 price 의 변화율(%). 소수 여섯째 자리에서 반올림 — 800/1000 이
    -19.999999999999996 으로 계산돼 무효선 -20% 를 비껴가던 것을 막습니다."""
    if not base:
        return 0.0
    return round((price / base - 1.0) * 100.0, 6)


def is_halted(prev_equity: float | None, equity: float, rules: Rules) -> bool:
    """어제 평가액 대비 오늘 평가액이 한도(-3%)보다 더 빠졌는가."""
    if not prev_equity:
        return False
    return pct_change(equity, prev_equity) <= rules.daily_loss_halt_pct


def _buy_cost(shares: int, price: float, rules: Rules) -> tuple[float, float, float]:
    """(수수료, 슬리피지, 현금에서 나가는 총액)"""
    slippage = shares * price * rules.slippage_pct / 100.0
    gross = shares * price + slippage
    fee = gross * rules.fee_buy_pct / 100.0
    return fee, slippage, gross + fee


def _sell_proceeds(shares: int, price: float, rules: Rules) -> tuple[float, float, float, float]:
    """(수수료, 세금, 슬리피지, 현금으로 들어오는 순액)"""
    slippage = shares * price * rules.slippage_pct / 100.0
    gross = shares * price - slippage
    fee = gross * rules.fee_sell_pct / 100.0
    tax = gross * rules.tax_pct / 100.0
    return fee, tax, slippage, gross - fee - tax


def fill_orders(orders: list[Order], opens: dict[str, float], positions: dict[str, Position],
                cash: float, rules: Rules, date: str) -> tuple[list[Fill], list[Decision], float]:
    """어제 낸 주문을 오늘 시가로 체결합니다. 주 수는 내림. 못 사면 이유를 남깁니다."""
    fills: list[Fill] = []
    decisions: list[Decision] = []
    for o in orders:
        price = opens.get(o.code)
        if price is None or not price > 0:
            decisions.append(Decision(date, o.code, o.name, "보류", "체결", "오늘 시가가 없습니다 (휴장·상폐·조회 실패)"))
            continue
        if o.side == SIDE_BUY:
            # 종목 배정 상한을 체결 직전에 다시 검사 (이미 들고 있는 매입액을 뺀 남은 자리까지만)
            held = positions.get(o.code)
            room = rules.allotment() - (held.cost if held else 0.0)
            if room <= 0:
                decisions.append(Decision(date, o.code, o.name, "건너뜀", "체결",
                                          f"종목 배정 {rules.allotment():,.0f}원 초과 — 체결 직전 재검사"))
                continue
            amount_cap = min(o.amount, room)
            # 슬리피지와 수수료까지 얹은 값으로 나눠야 총액이 주문 금액을 넘지 않는다
            shares = math.floor(amount_cap / (price * (1 + rules.slippage_pct / 100.0)
                                              * (1 + rules.fee_buy_pct / 100.0)))
            if shares < 1:
                decisions.append(Decision(date, o.code, o.name, "살 수 없음", "체결",
                                          f"{o.tranche} 금액 {o.amount:,.0f}원으로 1주({price:,.0f}원)도 못 삽니다"))
                continue
            fee, slippage, total = _buy_cost(shares, price, rules)
            if total > cash:
                decisions.append(Decision(date, o.code, o.name, "보류", "체결",
                                          f"현금 {cash:,.0f}원 < 필요 {total:,.0f}원"))
                continue
            cash -= total
            fills.append(Fill(o.order_id, date, o.code, o.name, SIDE_BUY, o.tranche, shares, price,
                              round(fee, 2), 0.0, round(slippage, 2), round(total, 2), o.reason))
            decisions.append(Decision(date, o.code, o.name, "체결", "체결",
                                      f"{o.tranche} 매수 {shares}주 × {price:,.0f}원 (슬리피지 가정 {rules.slippage_pct}%)"))
        else:
            held = positions.get(o.code)
            shares = min(o.shares, held.shares if held else 0)
            if shares < 1:
                decisions.append(Decision(date, o.code, o.name, "보류", "체결", "팔 주식이 없습니다"))
                continue
            fee, tax, slippage, net = _sell_proceeds(shares, price, rules)
            cash += net
            fills.append(Fill(o.order_id, date, o.code, o.name, SIDE_SELL, o.tranche, shares, price,
                              round(fee, 2), round(tax, 2), round(slippage, 2), round(net, 2), o.reason))
            decisions.append(Decision(date, o.code, o.name, "체결", "체결",
                                      f"{o.tranche} 매도 {shares}주 × {price:,.0f}원"))
    return fills, decisions, cash


def decide_sells(positions: dict[str, Position], closes: dict[str, float], rules: Rules,
                 date: str, candidates_now: set[str] | None) -> tuple[list[Order], list[Decision]]:
    """오늘 종가로 내일 매도 주문. 평단 기준. 각 단계는 한 번만.

    하루에 매도 단계는 하나만 나간다 — 갭상승으로 두 기준을 한꺼번에 넘어도 다음 날 다음 단계.
    """
    orders: list[Order] = []
    decisions: list[Decision] = []
    for code, p in positions.items():
        close = closes.get(code)
        if close is None:
            decisions.append(Decision(date, code, p.name, "보류", "조건", "오늘 종가가 없어 판단하지 않습니다"))
            continue
        chg = pct_change(close, p.avg_price)

        def _order(tranche: str, shares: int, reason: str) -> None:
            orders.append(Order(make_order_id(date, code, SIDE_SELL, tranche), date, code, p.name,
                                SIDE_SELL, tranche, shares, 0.0, reason))
            decisions.append(Decision(date, code, p.name, "주문", "조건", reason))

        if chg <= rules.invalid_pct:
            _order(T_INVALID, p.shares, f"무효선 {rules.invalid_pct:g}% — 평단 {p.avg_price:,.0f} 대비 {chg:+.1f}% 마감")
            continue
        if candidates_now is not None and code not in candidates_now:
            _order(T_BASIS, p.shares, "근거 사라짐 — 이번 달 후보 판정에서 빠짐")
            continue
        if p.sells_done < len(rules.sell_tranches):
            pct, weight = rules.sell_tranches[p.sells_done]
            if chg >= pct:
                last = p.sells_done == len(rules.sell_tranches) - 1
                # 비중은 '처음 보유분' 기준 (30·40·30). 처음 수를 따로 저장하지 않으므로
                # 남은 주 × 이 단계 비중 / 남은 단계 비중의 합 으로 내림 (100주 -> 30·40·30). 마지막은 전부.
                rest_weight = sum(w for _, w in rules.sell_tranches[p.sells_done:])
                shares = p.shares if last else min(p.shares, max(1, p.shares * weight // rest_weight))
                _order(SELL_TRANCHES[p.sells_done], shares,
                       f"평단 대비 {chg:+.1f}% ≥ +{pct:g}% → {shares}주 매도(처음 보유의 {weight}%)")
    return orders, decisions


def decide_buys(positions: dict[str, Position], closes: dict[str, float],
                candidates: list[tuple[str, str, float]], rules: Rules, date: str,
                cash: float, halted: bool,
                selling: "set[str] | frozenset[str]" = frozenset()) -> tuple[list[Order], list[Decision]]:
    """오늘 종가로 내일 매수 주문. 관문 순서는 코드 그대로:
    리스크(일일 한도) → 조건(오늘 매도 주문 종목 제외·2차 3차 트리거·1주 살 수 있나)
    → 포트폴리오(종목 배정·현금 예비금·빈자리).

    selling: 오늘 매도 주문이 나간 종목 코드. 같은 종목을 같은 날 팔고 사지 않는다.

    막히면 막힌 이유를 남깁니다. 그것이 '왜 안 샀는지' 입니다.
    """
    orders: list[Order] = []
    decisions: list[Decision] = []
    usable = cash - rules.cash_reserve          # 예비금은 늘 남깁니다 (§5 ②)

    def _want(code: str, name: str, tranche: str, amount: float, reason: str, cost_so_far: float) -> None:
        nonlocal usable
        if code in selling:
            decisions.append(Decision(date, code, name, "건너뜀", "조건", "오늘 매도 주문이 있는 종목"))
            return
        if halted:
            decisions.append(Decision(date, code, name, "보류", "리스크",
                                      f"일일 손실 한도({rules.daily_loss_halt_pct:g}%) 발동 — 오늘은 매도만"))
            return
        if cost_so_far + amount > rules.allotment() + 1e-6:
            decisions.append(Decision(date, code, name, "건너뜀", "포트폴리오",
                                      f"종목 배정 {rules.allotment():,.0f}원 초과 (이미 {cost_so_far:,.0f}원)"))
            return
        if amount > usable:
            decisions.append(Decision(date, code, name, "건너뜀", "포트폴리오",
                                      f"현금 예비금 {rules.cash_reserve:,.0f}원을 남기면 {usable:,.0f}원뿐"))
            return
        usable -= amount
        orders.append(Order(make_order_id(date, code, SIDE_BUY, tranche), date, code, name,
                            SIDE_BUY, tranche, 0, amount, reason))
        decisions.append(Decision(date, code, name, "주문", "조건", reason))

    # ① 보유 종목의 2차·3차
    for code, p in positions.items():
        close = closes.get(code)
        if close is None or not p.first_price:
            continue
        chg = pct_change(close, p.first_price)
        if p.tranche_done == 1 and chg >= rules.tranche2_trigger_pct:
            _want(code, p.name, "2차", rules.tranche_amount(2),
                  f"1차 매수가 대비 {chg:+.1f}% ≥ +{rules.tranche2_trigger_pct:g}% (관찰 구간 상단)", p.cost)
        elif p.tranche_done == 2 and chg <= rules.tranche3_trigger_pct:
            avg_chg = pct_change(close, p.avg_price)
            if avg_chg <= rules.invalid_pct:
                decisions.append(Decision(date, code, p.name, "건너뜀", "조건",
                                          f"무효선 아래({avg_chg:+.1f}%)라 3차를 사지 않습니다"))
            else:
                _want(code, p.name, "3차", rules.tranche_amount(3),
                      f"1차 매수가 대비 {chg:+.1f}% ≤ {rules.tranche3_trigger_pct:g}% (관찰 구간 하단), 무효선 미도달", p.cost)

    # ② 새 종목 — 빈자리만큼 점수순
    slots = rules.max_positions - len(positions)
    for code, name, score in candidates:
        if code in positions:
            continue
        if slots <= 0:
            decisions.append(Decision(date, code, name, "건너뜀", "포트폴리오",
                                      f"보유 종목 수 상한 {rules.max_positions} — 빈자리 없음"))
            continue
        close = closes.get(code)
        if close is not None and close * (1 + rules.slippage_pct / 100.0) > rules.tranche_amount(1):
            decisions.append(Decision(date, code, name, "살 수 없음", "조건",
                                      f"1차 금액 {rules.tranche_amount(1):,.0f}원으로 1주({close:,.0f}원)도 못 삽니다"))
            continue
        before = len(orders)
        _want(code, name, "1차", rules.tranche_amount(1), f"이번 달 후보 (점수 {score:g}) — 1차 관찰 매수", 0.0)
        if len(orders) > before:
            slots -= 1
    return orders, decisions
