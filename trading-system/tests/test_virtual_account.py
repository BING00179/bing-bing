"""가상 계좌 규칙 — 숫자가 나오나가 아니라 거짓말을 하지 않나.

판단은 D일 종가, 체결은 D+1일 시가 (§8). 숫자는 전부 Rules 에서 온다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import virtual_account as va
from src.config import VirtualAccountConfig

R = va.Rules.from_config(VirtualAccountConfig())      # 사장님 기본값


def _trade(**kw) -> dict:
    base = dict(row_id="x", version="1", order_id="o", date="2026-10-02", code="000001",
                name="가", side="매수", tranche="1차", shares=10, price=1000.0,
                fee=1.37, tax=0.0, slippage=15.0, amount=10016.37, reason="")
    base.update(kw)
    return base


def test_되감기는_주수와_현금을_맞춘다():
    trades = pd.DataFrame([
        _trade(shares=10, amount=10016.37),
        _trade(order_id="o2", date="2026-10-05", tranche="2차", shares=20, price=1050.0, amount=21033.0),
        _trade(order_id="o3", date="2026-10-07", side="매도", tranche="매도1", shares=9, price=1200.0,
               fee=1.5, tax=21.6, slippage=16.2, amount=10760.7),
    ])
    positions, cash = va.replay(trades, R)
    p = positions["000001"]
    assert p.shares == 21 and p.tranche_done == 2 and p.sells_done == 1
    assert p.first_price == 1000.0
    assert cash == pytest.approx(R.capital - 10016.37 - 21033.0 + 10760.7)


def test_다_팔린_종목은_포지션에서_빠지고_현금은_남는다():
    trades = pd.DataFrame([_trade(shares=10, amount=10016.37),
                           _trade(order_id="o2", date="2026-10-03", side="매도", tranche="무효",
                                  shares=10, price=800.0, amount=7980.0)])
    positions, cash = va.replay(trades, R)
    assert "000001" not in positions
    assert cash == pytest.approx(R.capital - 10016.37 + 7980.0)


def test_비용을_끄면_체결_금액이_달라진다():
    """배선 확인 — 비용이 실제로 계산에 들어가는가."""
    order = va.Order(order_id="o", date="2026-10-02", code="000001", name="가", side="매수",
                     tranche="1차", shares=0, amount=R.tranche_amount(1), reason="")
    fills, _, _ = va.fill_orders([order], {"000001": 1000.0}, {}, R.capital, R, "2026-10-05")
    공짜 = va.Rules.from_config(VirtualAccountConfig(slippage_pct=0, fee_buy_pct=0))
    fills0, _, _ = va.fill_orders([order], {"000001": 1000.0}, {}, 공짜.capital, 공짜, "2026-10-05")
    assert fills[0].fee > 0 and fills[0].slippage > 0
    assert fills0[0].fee == 0 and fills0[0].slippage == 0
    # 주 수가 내림이라 총액이 아니라 '주당 실제 지불액' 으로 비교한다
    assert fills[0].amount / fills[0].shares > fills0[0].amount / fills0[0].shares
    assert fills[0].shares <= fills0[0].shares


def test_체결은_다음날_시가이고_주수는_내림이다():
    order = va.Order(order_id="o", date="2026-10-02", code="000001", name="가", side="매수",
                     tranche="1차", shares=0, amount=225_000.0, reason="")
    fills, decisions, cash = va.fill_orders([order], {"000001": 23_000.0}, {}, R.capital, R, "2026-10-05")
    f = fills[0]
    assert f.date == "2026-10-05" and f.price == 23_000.0
    assert f.shares == 9                         # 225000 / (23000*1.0015) = 9.77 → 9
    assert f.slippage == pytest.approx(9 * 23_000 * 0.0015)
    assert cash == pytest.approx(R.capital - f.amount)
    assert any(d.action == "체결" for d in decisions)


def _pos(code="000001", shares=30, avg=1000.0, tranche_done=1, sells_done=0, first=1000.0):
    return {code: va.Position(code=code, name="가", shares=shares, cost=avg * shares,
                              tranche_done=tranche_done, first_price=first, sells_done=sells_done)}


def test_평단_10퍼센트_위_마감이면_30퍼센트를_판다_한_번만():
    orders, _ = va.decide_sells(_pos(), {"000001": 1100.0}, R, "2026-10-05", None)
    assert [o.tranche for o in orders] == ["매도1"]
    assert orders[0].shares == 9                      # 30 × 30% = 9
    orders2, _ = va.decide_sells(_pos(sells_done=1), {"000001": 1100.0}, R, "2026-10-06", None)
    assert orders2 == []


def test_세_번째_매도는_나머지_전부():
    orders, _ = va.decide_sells(_pos(shares=9, sells_done=2), {"000001": 1350.0}, R, "2026-10-05", None)
    assert orders[0].tranche == "매도3" and orders[0].shares == 9


def test_무효선_마감이면_전량이고_사유가_남는다():
    orders, decisions = va.decide_sells(_pos(), {"000001": 800.0}, R, "2026-10-05", None)
    assert orders[0].tranche == "무효" and orders[0].shares == 30
    assert "무효선" in orders[0].reason


def test_근거가_사라지면_전량():
    orders, _ = va.decide_sells(_pos(), {"000001": 1000.0}, R, "2026-10-31", candidates_now={"000009"})
    assert orders[0].tranche == "근거"
    orders2, _ = va.decide_sells(_pos(), {"000001": 1000.0}, R, "2026-10-31", candidates_now={"000001"})
    assert orders2 == []


def test_종가가_없으면_매도_판단을_하지_않고_이유를_남긴다():
    orders, decisions = va.decide_sells(_pos(), {}, R, "2026-10-05", None)
    assert orders == [] and decisions[0].action == "보류"


CANDS = [(f"00000{i}", f"종목{i}", float(i)) for i in range(1, 10)]   # 점수 오름차순


def test_빈자리만큼_점수순으로_1차_주문을_낸다():
    orders, decisions = va.decide_buys({}, {}, CANDS, R, "2026-10-05", R.capital, halted=False)
    assert len(orders) == R.max_positions
    assert [o.code for o in orders] == [c for c, _, _ in CANDS[:6]]
    assert all(o.tranche == "1차" and o.amount == R.tranche_amount(1) for o in orders)
    막힘 = [d for d in decisions if d.action == "건너뜀" and d.gate == "포트폴리오"]
    assert len(막힘) == 3 and "6" in 막힘[0].detail


def test_이미_보유한_종목은_새로_사지_않는다():
    orders, _ = va.decide_buys(_pos("000001"), {"000001": 1000.0}, CANDS, R, "2026-10-05", R.capital, False)
    assert "000001" not in [o.code for o in orders if o.tranche == "1차"]


def test_일일_한도가_걸리면_매수_주문은_0건이고_이유가_남는다():
    orders, decisions = va.decide_buys({}, {}, CANDS, R, "2026-10-05", R.capital, halted=True)
    assert orders == []
    assert any(d.gate == "리스크" and d.action == "보류" for d in decisions)


def test_현금_예비금을_침범하는_주문은_내지_않는다():
    cash = R.cash_reserve + R.tranche_amount(1) * 1.5      # 1건만 가능
    orders, decisions = va.decide_buys({}, {}, CANDS, R, "2026-10-05", cash, False)
    assert len(orders) == 1
    assert any("예비" in d.detail for d in decisions if d.gate == "포트폴리오")


def test_1차가_5퍼센트_위_마감이면_2차_그_뒤_10퍼센트_아래면_3차():
    p1 = _pos(tranche_done=1, first=1000.0)
    o, _ = va.decide_buys(p1, {"000001": 1050.0}, [], R, "2026-10-05", R.capital, False)
    assert [x.tranche for x in o] == ["2차"] and o[0].amount == R.tranche_amount(2)
    o2, _ = va.decide_buys(p1, {"000001": 1049.0}, [], R, "2026-10-05", R.capital, False)
    assert o2 == []
    p2 = _pos(tranche_done=2, first=1000.0)
    o3, _ = va.decide_buys(p2, {"000001": 900.0}, [], R, "2026-10-06", R.capital, False)
    assert [x.tranche for x in o3] == ["3차"] and o3[0].amount == R.tranche_amount(3)
    o4, _ = va.decide_buys(_pos(tranche_done=1, first=1000.0), {"000001": 900.0}, [], R, "2026-10-06", R.capital, False)
    assert o4 == [], "2차 없이 3차는 없습니다"


def test_무효선_아래에서는_3차를_사지_않는다():
    o, d = va.decide_buys(_pos(tranche_done=2, first=1000.0), {"000001": 790.0}, [], R, "2026-10-06", R.capital, False)
    assert o == []


def test_배정_한도를_넘기는_추가_매수는_막힌다():
    p = _pos(tranche_done=1, shares=700, avg=1000.0, first=1000.0)     # 이미 70만 원어치
    o, d = va.decide_buys(p, {"000001": 1050.0}, [], R, "2026-10-05", R.capital, False)
    assert o == [] and any("배정" in x.detail for x in d)


def test_1주도_못_사는_후보는_주문_전에_살_수_없음으로_남는다():
    o, d = va.decide_buys({}, {"000001": 300_000.0}, CANDS[:1], R, "2026-10-05", R.capital, False)
    assert o == []
    assert d[0].action == "살 수 없음" and d[0].gate == "조건" and "1주" in d[0].detail


def test_주문_날짜는_판단한_날이다():
    o, _ = va.decide_buys({}, {}, CANDS[:1], R, "2026-10-05", R.capital, False)
    assert o[0].date == "2026-10-05"


def test_경계값은_정확히_걸린다():
    """800/1000 이 -19.999999999999996 으로 계산돼 무효선을 비껴가던 부동소수점 문제."""
    o, _ = va.decide_sells(_pos(), {"000001": 800.0}, R, "2026-10-05", None)
    assert [x.tranche for x in o] == ["무효"]
    o2, _ = va.decide_buys(_pos(tranche_done=1, first=1000.0), {"000001": 1050.0}, [], R, "2026-10-05", R.capital, False)
    assert [x.tranche for x in o2] == ["2차"]
    o3, _ = va.decide_buys(_pos(tranche_done=2, first=1000.0), {"000001": 900.0}, [], R, "2026-10-06", R.capital, False)
    assert [x.tranche for x in o3] == ["3차"]
    assert va.is_halted(5_000_000.0, 4_850_000.0, R) is True
