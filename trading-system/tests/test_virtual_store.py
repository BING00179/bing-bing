"""가상 계좌 기록 — 지우지 않는다(§12). 같은 날 두 번 돌아도 같다."""
from __future__ import annotations

import pandas as pd
import pytest

from src import virtual_account as va
from src import virtual_store as vs


def _fill(order_id="o1", date="2026-10-05", side="매수", tranche="1차", shares=9):
    return va.Fill(order_id, date, "000001", "가", side, tranche, shares, 23_000.0, 2.8, 0.0, 310.5, 207_313.3, "")


def test_체결은_order_id_로_중복을_막는다(tmp_path):
    s = vs.Store.default(tmp_path)
    assert s.append_fills([_fill()]) == 1
    assert s.append_fills([_fill()]) == 0
    t = s.load_trades()
    assert len(t) == 1 and (t["version"] == va.VIRTUAL_VERSION).all()


def test_줄어드는_저장은_거부한다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.append_fills([_fill(), _fill(order_id="o2", date="2026-10-06", tranche="2차")])
    적은것 = s.load_trades().head(1)
    with pytest.raises(vs.StoreShrank):
        vs._save(적은것, s.trades_path, vs.TRADES_COLUMNS, key="row_id")


def test_주문은_로그에_남고_체결_전까지_미체결이다(tmp_path):
    s = vs.Store.default(tmp_path)
    order = va.Order("o9", "2026-10-05", "000001", "가", "매수", "1차", 0, 225_000.0, "후보")
    s.append_decisions([va.Decision("2026-10-05", "000001", "가", "주문", "조건", "후보")],
                       {("000001", "매수", "1차"): order})
    pending = s.pending_orders("2026-10-06")
    assert [o.order_id for o in pending] == ["o9"]
    assert pending[0].amount == 225_000.0
    assert s.pending_orders("2026-10-05") == [], "주문 낸 날에는 아직 체결하지 않습니다"
    s.append_fills([_fill(order_id="o9")])
    assert s.pending_orders("2026-10-06") == []


def test_하루_스냅샷은_같은_날이면_덮어쓰고_다른_날은_지우지_못한다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.upsert_daily({"date": "2026-10-05", "cash": 1.0, "positions_value": 0.0, "equity": 1.0,
                    "day_pnl": 0.0, "day_pnl_pct": 0.0, "halted": False, "n_positions": 0, "kosdaq_close": 800.0})
    s.upsert_daily({"date": "2026-10-05", "cash": 2.0, "positions_value": 0.0, "equity": 2.0,
                    "day_pnl": 0.0, "day_pnl_pct": 0.0, "halted": False, "n_positions": 0, "kosdaq_close": 800.0})
    d = s.load_daily()
    assert len(d) == 1 and float(d.iloc[0]["cash"]) == 2.0
    s.upsert_daily({"date": "2026-10-06", "cash": 3.0, "positions_value": 0.0, "equity": 3.0,
                    "day_pnl": 1.0, "day_pnl_pct": 50.0, "halted": False, "n_positions": 0, "kosdaq_close": 801.0})
    assert s.last_daily_before("2026-10-06")["equity"] == 2.0
    assert s.last_daily_before("2026-10-05") is None
