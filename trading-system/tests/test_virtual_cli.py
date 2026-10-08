"""virtual-update 한 바퀴 — 가짜 시세로 네트워크 없이. 같은 날 두 번 돌리면 두 번째는 변화 0."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src import cli
from src import livetest as lt
from src import virtual_store as vs
from tests.helpers import make_daily


@pytest.fixture
def world(tmp_path, monkeypatch):
    # 후보 파일: 이번 달(2026-10) 후보 둘
    cand = tmp_path / "cand.csv"
    pd.DataFrame({"month": ["2026-10", "2026-10"], "code": ["000001", "000002"], "name": ["가", "나"],
                  "close": [1000.0, 300_000.0], "score": [1.0, 2.0], "기업점수": [70, 70],
                  "가격점수": [70, 70], "basis": ["후보", "후보"]}).to_csv(cand, index=False, encoding="utf-8-sig")
    # 시세: 2026-10-01 ~ 10-08 (평일 6일: 1,2,5,6,7,8)
    frames = {
        "000001": make_daily([1000, 1000, 1000, 1060, 1100, 1120], start="2026-10-01"),
        "000002": make_daily([300_000] * 6, start="2026-10-01"),    # 1차 22.5만으로 1주도 못 삼
    }
    index = make_daily([800, 801, 802, 803, 804, 805], start="2026-10-01")
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=2.0, pause=0.0: frames[code])
    monkeypatch.setattr(cli, "fetch_index", lambda code="KS11", years=3.0: index)
    monkeypatch.setattr(cli, "_notify", lambda text, enabled: None)
    # 빈 장부 = 머리글만 있는 파일 (lt_module.load 는 0바이트 파일을 읽지 못합니다)
    pd.DataFrame(columns=list(lt.COLUMNS)).to_csv(tmp_path / "lt.csv", index=False, encoding="utf-8-sig")
    return tmp_path, cand


def _run(tmp_path, cand, day, extra=()):
    return cli.main(["virtual-update", "--as-of", day, "--data-dir", str(tmp_path), "--candidates", str(cand),
                     "--file", str(tmp_path / "lt.csv"), "--no-telegram", *extra])


def test_첫날은_주문만_내고_둘째날_시가에_체결한다(world):
    tmp_path, cand = world
    assert _run(tmp_path, cand, "2026-10-01") == 0
    s = vs.Store.default(tmp_path)
    assert s.load_trades().empty
    log = s.load_log()
    assert set(log[log["action"] == "주문"]["code"]) == {"000001"}
    assert _run(tmp_path, cand, "2026-10-02") == 0
    t = s.load_trades()
    assert list(t["code"]) == ["000001"] and t.iloc[0]["price"] == 1000.0   # 10-02 시가 = 10-01 종가
    assert t.iloc[0]["shares"] == 224                                      # 225000/(1000*1.0015)=224.6
    log = s.load_log()
    못삼 = log[(log["action"] == "살 수 없음") & (log["code"] == "000002")]
    assert len(못삼) >= 1 and "1주" in 못삼.iloc[0]["detail"]
    assert "000002" not in set(log[log["action"] == "주문"]["code"]), "못 살 종목에는 주문을 내지 않습니다"


def test_같은_날_두_번_돌리면_두_번째는_아무것도_더하지_않는다(world):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    s = vs.Store.default(tmp_path)
    before = (len(s.load_trades()), len(s.load_log()), len(s.load_daily()))
    _run(tmp_path, cand, "2026-10-02")
    assert (len(s.load_trades()), len(s.load_log()), len(s.load_daily())) == before


def test_1차가_5퍼센트_위_마감한_다음날_2차가_체결된다(world):
    tmp_path, cand = world
    for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"):
        _run(tmp_path, cand, d)
    t = vs.Store.default(tmp_path).load_trades()
    assert list(t["tranche"]) == ["1차", "2차"]          # 10-06 종가 1060 ≥ 1000×1.05 → 10-07 시가 체결
    assert t.iloc[1]["date"] == "2026-10-07" and t.iloc[1]["price"] == 1060.0


def test_하루_스냅샷에_평가액과_코스닥이_남는다(world):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    d = vs.Store.default(tmp_path).load_daily()
    assert list(d["date"]) == ["2026-10-01", "2026-10-02"]
    r = d.iloc[-1]
    assert float(r["kosdaq_close"]) == 801.0
    assert float(r["equity"]) == pytest.approx(float(r["cash"]) + 224 * 1000.0)


def test_오늘_봉이_없으면_아무것도_하지_않는다(world, capsys):
    tmp_path, cand = world
    assert _run(tmp_path, cand, "2026-10-03") == 0          # 토요일
    assert vs.Store.default(tmp_path).load_log().empty
    assert "오늘 봉" in capsys.readouterr().out


def test_마감_전이면_스스로_끝난다(world, monkeypatch, capsys):
    tmp_path, cand = world
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(cli, "now_kst", lambda: datetime(2026, 10, 2, 15, 30, tzinfo=ZoneInfo("Asia/Seoul")))
    rc = cli.main(["virtual-update", "--data-dir", str(tmp_path), "--candidates", str(cand),
                   "--file", str(tmp_path / "lt.csv"), "--no-telegram"])
    assert rc == 0 and "16:00" in capsys.readouterr().out
    assert vs.Store.default(tmp_path).load_log().empty


def test_후보_파일에서_후보가_아닌_줄은_후보로_삼지_않는다(tmp_path):
    cand = tmp_path / "cand.csv"
    pd.DataFrame({"month": ["2026-10"] * 3, "code": ["000001", "000002", "000003"], "name": ["가", "나", "다"],
                  "close": [1000.0] * 3, "score": [3.0, 1.0, 2.0], "기업점수": [70] * 3, "가격점수": [70] * 3,
                  "basis": ["후보", "기업만 좋음", "후보"]}).to_csv(cand, index=False, encoding="utf-8-sig")
    ledger = pd.DataFrame(columns=list(lt.COLUMNS))
    목록, 집합 = cli.virtual_candidates(cand, ledger)
    assert [c for c, _, _ in 목록] == ["000003", "000001"]      # 점수 오름차순, 비후보 제외
    assert 집합 == {"000001", "000003"}


def test_후보_파일이_없으면_집합은_None(tmp_path):
    목록, 집합 = cli.virtual_candidates(tmp_path / "없음.csv", pd.DataFrame(columns=list(lt.COLUMNS)))
    assert 목록 == [] and 집합 is None
