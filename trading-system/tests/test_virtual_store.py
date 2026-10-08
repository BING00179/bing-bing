"""가상 계좌 기록 — 지우지 않는다(§12). 같은 날 두 번 돌아도 같다."""
from __future__ import annotations

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


def test_한_번의_호출_안_중복_체결은_한_번만_쓴다(tmp_path):
    s = vs.Store.default(tmp_path)
    f = _fill()
    assert s.append_fills([f, f]) == 1
    assert len(s.load_trades()) == 1


def test_같은_주문을_reason_이_달라도_한_줄만_남긴다(tmp_path):
    s = vs.Store.default(tmp_path)
    d5 = va.Decision("2026-10-05", "000001", "가", "주문", "조건", "후보 점수 5")
    d6 = va.Decision("2026-10-05", "000001", "가", "주문", "조건", "후보 점수 6")
    o5 = va.Order("o9", "2026-10-05", "000001", "가", "매수", "1차", 0, 225_000.0, "후보 점수 5")
    o6 = va.Order("o9", "2026-10-05", "000001", "가", "매수", "1차", 0, 225_000.0, "후보 점수 6")
    assert s.append_decisions([d5], {("000001", "매수", "1차"): o5}) == 1
    assert s.append_decisions([d6], {("000001", "매수", "1차"): o6}) == 0
    log = s.load_log()
    assert (log["action"] == "주문").sum() == 1
    assert [o.order_id for o in s.pending_orders("2026-10-06")] == ["o9"]


def test_한_호출_안_같은_결정이_두_번이어도_한_줄(tmp_path):
    s = vs.Store.default(tmp_path)
    d = va.Decision("2026-10-05", "000001", "가", "건너뜀", "조건", "점수 미달")
    assert s.append_decisions([d, d], {}) == 1


def test_pending_orders_는_같은_order_id_를_마지막_줄로_한_번만_돌려준다(tmp_path):
    s = vs.Store.default(tmp_path)
    # 방어: 예전 판이 남긴 중복 줄(같은 order_id, reason 만 다름)을 손으로 만든다
    o5 = va.Order("o9", "2026-10-05", "000001", "가", "매수", "1차", 0, 225_000.0, "후보 점수 5")
    o6 = va.Order("o9", "2026-10-05", "000001", "가", "매수", "1차", 0, 225_000.0, "후보 점수 6")
    s.append_decisions([va.Decision("2026-10-05", "000001", "가", "주문", "조건", "후보 점수 5")],
                       {("000001", "매수", "1차"): o5})
    log = s.load_log()
    복제 = log.copy()
    복제["row_id"] = "dup0000001"
    복제["detail"] = "후보 점수 6"
    복제["order_json"] = vs.json.dumps(vs.asdict(o6), ensure_ascii=False)
    vs._save(vs.pd.concat([log, 복제], ignore_index=True), s.log_path, vs.LOG_COLUMNS, key="row_id")
    pending = s.pending_orders("2026-10-06")
    assert [o.order_id for o in pending] == ["o9"]
    assert pending[0].reason == "후보 점수 6"


def test_하루_스냅샷도_날짜가_줄어들면_거부한다(tmp_path):
    s = vs.Store.default(tmp_path)
    for i, day in enumerate(("2026-10-05", "2026-10-06")):
        s.upsert_daily({"date": day, "cash": 1.0 + i, "positions_value": 0.0, "equity": 1.0 + i,
                        "day_pnl": 0.0, "day_pnl_pct": 0.0, "halted": False, "n_positions": 0,
                        "kosdaq_close": 800.0})
    손으로_지운 = s.load_daily().iloc[1:]
    with pytest.raises(vs.StoreShrank):
        vs._save(손으로_지운, s.daily_path, vs.DAILY_COLUMNS, key="date")
    assert len(s.load_daily()) == 2


def test_매도_주문의_shares_는_로그를_거쳐_그대로_산다(tmp_path):
    s = vs.Store.default(tmp_path)
    sell = va.Order("s1", "2026-10-05", "000001", "가", "매도", "1차", 7, 0.0, "목표 +10%")
    d = va.Decision("2026-10-05", "000001", "가", "주문", "조건", "목표 +10%")
    assert s.append_decisions([d], {("000001", "매도", "1차"): sell}) == 1
    assert s.append_decisions([d], {("000001", "매도", "1차"): sell}) == 0
    (got,) = s.pending_orders("2026-10-06")
    assert got == sell and got.shares == 7


def test_일부만_체결되면_나머지만_미체결이다(tmp_path):
    s = vs.Store.default(tmp_path)
    a = va.Order("a", "2026-10-05", "000001", "가", "매수", "1차", 0, 100_000.0, "ra")
    b = va.Order("b", "2026-10-05", "000002", "나", "매수", "1차", 0, 100_000.0, "rb")
    s.append_decisions([va.Decision("2026-10-05", "000001", "가", "주문", "조건", "ra"),
                        va.Decision("2026-10-05", "000002", "나", "주문", "조건", "rb")],
                       {("000001", "매수", "1차"): a, ("000002", "매수", "1차"): b})
    s.append_fills([_fill(order_id="a")])
    assert [o.order_id for o in s.pending_orders("2026-10-06")] == ["b"]


def test_가장_최근_주문일_묶음만_미체결_대상이다(tmp_path):
    s = vs.Store.default(tmp_path)
    old = va.Order("old", "2026-10-02", "000001", "가", "매수", "1차", 0, 100_000.0, "ro")
    new = va.Order("new", "2026-10-05", "000002", "나", "매수", "1차", 0, 100_000.0, "rn")
    s.append_decisions([va.Decision("2026-10-02", "000001", "가", "주문", "조건", "ro")],
                       {("000001", "매수", "1차"): old})
    s.append_decisions([va.Decision("2026-10-05", "000002", "나", "주문", "조건", "rn")],
                       {("000002", "매수", "1차"): new})
    assert [o.order_id for o in s.pending_orders("2026-10-06")] == ["new"]
