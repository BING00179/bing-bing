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


# ---- 검토 반영 (수정 라운드 1) -------------------------------------------------

def _frames():
    return {
        "000001": make_daily([1000, 1000, 1000, 1060, 1100, 1120], start="2026-10-01"),
        "000002": make_daily([300_000] * 6, start="2026-10-01"),
    }


def _set_frames(monkeypatch, frames):
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=2.0, pause=0.0: frames[code])


def _write_cand(path, rows):
    pd.DataFrame({"month": ["2026-10"] * len(rows), "code": [r[0] for r in rows], "name": [r[0] for r in rows],
                  "close": [1000.0] * len(rows), "score": [r[2] for r in rows], "기업점수": [70] * len(rows),
                  "가격점수": [70] * len(rows), "basis": [r[1] for r in rows]}
                 ).to_csv(path, index=False, encoding="utf-8-sig")


def _bytes(tmp_path):
    return {n: (tmp_path / n).read_bytes() for n in ("virtual_trades.csv", "virtual_log.csv", "virtual_daily.csv")}


def test_지난_날짜를_다시_돌려도_기록을_건드리지_않는다(world, capsys):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    before = _bytes(tmp_path)
    capsys.readouterr()
    assert _run(tmp_path, cand, "2026-10-01") == 0
    assert _bytes(tmp_path) == before
    assert "지난 날짜" in capsys.readouterr().out
    d = vs.Store.default(tmp_path).load_daily()
    assert float(d[d["date"] == "2026-10-01"].iloc[0]["cash"]) == 5_000_000.0


def test_오늘_봉이_없는_보유_종목은_직전_종가로_평가하고_그_사실을_남긴다(world, monkeypatch):
    tmp_path, cand = world
    for d in ("2026-10-01", "2026-10-02", "2026-10-05"):
        _run(tmp_path, cand, d)
    frames = _frames()
    frames["000001"] = frames["000001"].drop(pd.Timestamp("2026-10-06"))
    _set_frames(monkeypatch, frames)
    _run(tmp_path, cand, "2026-10-06")
    s = vs.Store.default(tmp_path)
    row = s.load_daily().iloc[-1]
    assert row["date"] == "2026-10-06" and float(row["positions_value"]) == 224 * 1000.0   # 10-05 종가, 평단 아님
    log = s.load_log()
    대체 = log[(log["date"] == "2026-10-06") & (log["action"] == "보류") & log["detail"].str.contains("평가")]
    assert len(대체) == 1 and "2026-10-05" in 대체.iloc[0]["detail"]
    assert len(log[(log["date"] == "2026-10-06") & (log["action"] == "주문")]) == 0   # 판단에는 오늘 종가만


def test_시각이_섞인_인덱스에서도_오늘_봉을_찾는다(world, monkeypatch):
    tmp_path, cand = world
    frames = _frames()
    for f in frames.values():
        f.index = f.index + pd.Timedelta(hours=15, minutes=30)
    _set_frames(monkeypatch, frames)
    monkeypatch.setattr(cli, "fetch_index", lambda code="KS11", years=3.0: frames["000001"])
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    s = vs.Store.default(tmp_path)
    assert list(s.load_trades()["code"]) == ["000001"]
    assert float(s.load_daily().iloc[-1]["kosdaq_close"]) == 1000.0


def test_그달_후보_판정이_0건이면_근거_사라짐을_판단하지_않는다(world, capsys):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000001", "비쌈", 1.0), ("000002", "제외", 2.0)])
    capsys.readouterr()
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[log["date"] == "2026-10-05"]
    assert len(오늘[오늘["action"] == "주문"]) == 0
    assert 오늘["detail"].str.contains("판정 없음").any()
    assert "'후보' 판정이 한 줄도 없습니다" in capsys.readouterr().out


def test_후보에서_빠진_보유_종목은_근거_사라짐으로_매도_주문이_난다(world):
    """위 시험의 대조군 — 배선을 끊으면 이쪽이 깨집니다."""
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000002", "후보", 2.0)])
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[log["date"] == "2026-10-05"]
    assert "000001" in set(오늘[오늘["action"] == "주문"]["code"])


def test_판단보류_종목은_근거가_사라진_것이_아니고_새로_사지도_않는다(world):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000001", "판단보류", 1.0), ("000002", "후보", 2.0)])
    목록, 집합 = cli.virtual_candidates(cand, pd.DataFrame(columns=list(lt.COLUMNS)))
    assert [c for c, _, _ in 목록] == ["000002"] and 집합 == {"000001", "000002"}
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[log["date"] == "2026-10-05"]
    assert "000001" not in set(오늘[오늘["action"] == "주문"]["code"])


def test_시세를_하나도_못_받으면_휴장과_가르고_알린다(world, monkeypatch, capsys):
    tmp_path, cand = world
    알림 = []
    monkeypatch.setattr(cli, "_notify", lambda text, enabled: 알림.append(text))

    def boom(code, years=2.0, pause=0.0):
        raise RuntimeError("연결 안 됨")
    monkeypatch.setattr(cli, "fetch_daily_kr", boom)
    assert _run(tmp_path, cand, "2026-10-01") == 0
    assert vs.Store.default(tmp_path).load_daily().empty
    assert len(알림) == 1 and "시세 실패 2종목" in 알림[0]


def test_종목이_없는_휴장일에는_스냅샷이_쌓이지_않는다(world, tmp_path_factory):
    tmp_path, _ = world
    없음 = tmp_path / "없는파일.csv"
    assert _run(tmp_path, 없음, "2026-10-03") == 0           # 토요일: 지수 봉도 없음
    assert vs.Store.default(tmp_path).load_daily().empty
    assert _run(tmp_path, 없음, "2026-10-02") == 0           # 평일: 종목은 없어도 현금 스냅샷은 남김
    assert list(vs.Store.default(tmp_path).load_daily()["date"]) == ["2026-10-02"]


def test_지수_조회가_실패해도_종목_봉으로_계속하고_한_줄_알린다(world, monkeypatch, capsys):
    tmp_path, cand = world

    def boom(code="KS11", years=3.0):
        raise RuntimeError("지수 서버 오류")
    monkeypatch.setattr(cli, "fetch_index", boom)
    assert _run(tmp_path, cand, "2026-10-01") == 0
    assert "코스닥 지수 실패" in capsys.readouterr().out
    assert len(vs.Store.default(tmp_path).load_daily()) == 1


def test_web_을_켜면_virtual_json_과_가상_계좌_탭이_생긴다(world):
    tmp_path, cand = world
    web = tmp_path / "stocks"
    for d in ("2026-10-01", "2026-10-02"):
        assert _run(tmp_path, cand, d, extra=("--web", "--web-dir", str(web))) == 0
    data = json.loads((web / "virtual.json").read_text(encoding="utf-8"))
    assert data["as_of"] == "2026-10-02" and data["positions"][0]["code"] == "000001"
    page = (web / "index.html").read_text(encoding="utf-8")
    assert 'data-panel="virtual"' in page and "가상 계좌" in page and "2026-10-02 종가 기준" in page
    assert "살 수 없음" in page                                  # 못 산 결정도 화면에 보임
