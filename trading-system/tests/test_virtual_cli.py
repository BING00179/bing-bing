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
    목록, 유지, 사라짐, 기록일 = cli.virtual_candidates(cand, ledger)
    assert [c for c, _, _ in 목록] == ["000003", "000001"]      # 점수 오름차순, 비후보 제외
    assert 유지 == {"000001", "000003"}
    assert dict(사라짐) == {} and 기록일 is None                 # '기업만 좋음' 은 함정?·제외 가 아님


def test_후보_파일이_없으면_집합은_None(tmp_path):
    결과 = cli.virtual_candidates(tmp_path / "없음.csv", pd.DataFrame(columns=list(lt.COLUMNS)))
    assert 결과 == ([], None, None, None)


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
    # 보유 종목이 '제외' 여도 그 달 '후보' 가 0건이면 판정 자체를 믿지 않습니다 — 한꺼번에 팔지 않음
    _write_cand(cand, [("000001", "제외", 1.0), ("000002", "비쌈", 2.0)])
    capsys.readouterr()
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[log["date"] == "2026-10-05"]
    assert len(오늘[오늘["action"] == "주문"]) == 0
    assert 오늘["detail"].str.contains("판정 없음").any()
    assert "'후보' 판정이 한 줄도 없습니다" in capsys.readouterr().out


@pytest.mark.parametrize("판정", ["함정?", "제외"])
def test_이번_달_함정_제외_판정인_보유_종목은_근거_사라짐으로_매도_주문이_난다(world, 판정):
    """위 시험의 대조군 — 배선을 끊으면 이쪽이 깨집니다."""
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000001", 판정, 1.0), ("000002", "후보", 2.0)])
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    주문 = log[(log["date"] == "2026-10-05") & (log["action"] == "주문") & (log["code"] == "000001")]
    assert len(주문) == 1 and f"근거 사라짐 — 이번 달 판정 {판정}" in 주문.iloc[0]["detail"]
    assert json.loads(주문.iloc[0]["order_json"])["tranche"] == "근거"


def test_이번_달_판정에_없는_보유_종목은_팔지_않고_거름망_탈락으로_남긴다(world):
    """PBR·PER 거름망에서 떨어져 판정 자체가 없는 것은 '근거 사라짐' 이 아닙니다 (I3, 2026-10-10)."""
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000002", "후보", 2.0)])
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[(log["date"] == "2026-10-05") & (log["code"] == "000001")]
    assert len(오늘[오늘["action"] == "주문"]) == 0
    assert 오늘["detail"].str.contains("거름망 탈락").any()


@pytest.mark.parametrize("판정", ["비쌈", "판단보류"])
def test_비쌈_판단보류는_근거가_유지된_것이다(world, 판정):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000001", 판정, 1.0), ("000002", "후보", 2.0)])
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    오늘 = log[(log["date"] == "2026-10-05") & (log["code"] == "000001")]
    assert len(오늘[오늘["action"] == "주문"]) == 0
    assert not 오늘["detail"].str.contains("거름망|근거 사라짐").any()


def test_판단보류_종목은_근거가_사라진_것이_아니고_새로_사지도_않는다(world):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _write_cand(cand, [("000001", "판단보류", 1.0), ("000002", "후보", 2.0)])
    목록, 유지, 사라짐, _ = cli.virtual_candidates(cand, pd.DataFrame(columns=list(lt.COLUMNS)))
    assert [c for c, _, _ in 목록] == ["000002"] and 유지 == {"000001", "000002"} and dict(사라짐) == {}
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
    assert "근거 사라짐 = 월말 판정 함정?·제외" in page and "다음 판정까지" in page   # 2026-10-10 가정도 규칙 표에


def test_첫날_오늘_손익은_0이_아니라_모름으로_남는다(world):
    tmp_path, cand = world
    _run(tmp_path, cand, "2026-10-01")
    d = vs.Store.default(tmp_path).load_daily()
    assert str(d.iloc[0]["day_pnl"]) == "" and str(d.iloc[0]["day_pnl_pct"]) == ""
    _run(tmp_path, cand, "2026-10-02")
    assert str(vs.Store.default(tmp_path).load_daily().iloc[-1]["day_pnl"]) != ""     # 둘째 날부터는 숫자


def test_web_오늘_종가_없는_보유_종목은_무엇으로_평가했는지_화면에_적는다(world, monkeypatch):
    tmp_path, cand = world
    web = tmp_path / "stocks"
    for d in ("2026-10-01", "2026-10-02", "2026-10-05"):
        _run(tmp_path, cand, d)
    full = {"000001": make_daily([1000, 1000, 1000, 1060, 1100, 1120], start="2026-10-01"),
            "000002": make_daily([300_000] * 6, start="2026-10-01")}
    full["000001"] = full["000001"].drop(full["000001"].index[3])            # 10-06 봉이 없다
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=2.0, pause=0.0: full[code])
    assert _run(tmp_path, cand, "2026-10-06", extra=("--web", "--web-dir", str(web))) == 0
    data = json.loads((web / "virtual.json").read_text(encoding="utf-8"))
    assert data["positions"][0]["close_note"] == "2026-10-05 종가"
    assert data["summary"]["valued_on"] == "2026-10-06"
    page = (web / "index.html").read_text(encoding="utf-8")
    assert "오늘 종가 없음 — 2026-10-05 종가 로 평가" in page


# ---- 최종 검토 반영 (2026-10-10) ----------------------------------------------

def _cand_rows(path, rows, recorded_on=None):
    """rows = [(code, basis, score)]"""
    df = pd.DataFrame({"month": ["2026-10"] * len(rows), "code": [r[0] for r in rows],
                       "name": [r[0] for r in rows], "close": [1000.0] * len(rows),
                       "score": [r[2] for r in rows], "기업점수": [70] * len(rows), "가격점수": [70] * len(rows),
                       "basis": [r[1] for r in rows]})
    if recorded_on is not None:
        df["recorded_on"] = recorded_on
    df.to_csv(path, index=False, encoding="utf-8-sig")


@pytest.fixture
def many(tmp_path, monkeypatch):
    """종목 아홉 개, 전부 1,000원 평평. 시세는 frames 를 바꿔 끼울 수 있게 돌려줍니다."""
    frames = {f"00000{i}": make_daily([1000] * 6, start="2026-10-01") for i in range(1, 10)}
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=2.0, pause=0.0: frames[code])
    monkeypatch.setattr(cli, "fetch_index",
                        lambda code="KS11", years=3.0: make_daily([800] * 6, start="2026-10-01"))
    monkeypatch.setattr(cli, "_notify", lambda text, enabled: None)
    pd.DataFrame(columns=list(lt.COLUMNS)).to_csv(tmp_path / "lt.csv", index=False, encoding="utf-8-sig")
    return tmp_path, tmp_path / "cand.csv", frames


def _orders_on(log, day):
    주문 = log[(log["date"] == day) & (log["action"] == "주문")]
    return [json.loads(j) for j in 주문["order_json"]]


# C1 ② — 같은 날 재실행은 새 주문을 내지 않습니다
def test_같은_날_후보가_바뀌어_다시_돌아도_새_주문을_내지_않는다(many, capsys):
    tmp_path, cand, _ = many
    _cand_rows(cand, [(f"00000{i}", "후보", float(i)) for i in range(1, 7)])
    _run(tmp_path, cand, "2026-10-01")
    _cand_rows(cand, [(f"00000{i}", "후보", float(i)) for i in range(4, 10)])   # 월말 후보가 같은 날 바뀜
    capsys.readouterr()
    _run(tmp_path, cand, "2026-10-01")
    assert "오늘 판단은 이미 끝났습니다" in capsys.readouterr().out
    s = vs.Store.default(tmp_path)
    assert {o["code"] for o in _orders_on(s.load_log(), "2026-10-01")} == {f"00000{i}" for i in range(1, 7)}
    _run(tmp_path, cand, "2026-10-02")
    t = s.load_trades()
    assert len(t) == 6 and sorted(t["code"]) == [f"00000{i}" for i in range(1, 7)]
    assert int(s.load_daily().iloc[-1]["n_positions"]) == 6


def test_같은_날_재실행도_평가와_화면은_갱신한다(many):
    """판단만 건너뜁니다. 스냅샷·화면 갱신은 그대로."""
    tmp_path, cand, _ = many
    _cand_rows(cand, [("000001", "후보", 1.0)])
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    s = vs.Store.default(tmp_path)
    before = (len(s.load_trades()), len(s.load_log()))
    web = tmp_path / "stocks"
    assert _run(tmp_path, cand, "2026-10-02", extra=("--web", "--web-dir", str(web))) == 0
    assert (len(s.load_trades()), len(s.load_log())) == before
    assert json.loads((web / "virtual.json").read_text(encoding="utf-8"))["as_of"] == "2026-10-02"


# I1 — 실행을 하루 이상 놓치면 묵은 주문은 만료
def test_실행을_놓친_묵은_주문은_체결하지_않고_만료로_남긴다(many):
    tmp_path, cand, _ = many
    _cand_rows(cand, [("000001", "후보", 1.0)])
    _run(tmp_path, cand, "2026-10-01")          # 10-02 용 주문
    _run(tmp_path, cand, "2026-10-05")          # 10-02 실행은 없었음
    s = vs.Store.default(tmp_path)
    assert s.load_trades().empty
    log = s.load_log()
    만료 = log[(log["date"] == "2026-10-05") & (log["action"] == "보류") & (log["gate"] == "체결")]
    assert len(만료) == 1 and 만료.iloc[0]["code"] == "000001"
    assert "만료" in 만료.iloc[0]["detail"] and "2026-10-01" in 만료.iloc[0]["detail"]
    # 판단은 오늘 종가로 다시 합니다 → 다음 거래일에는 체결
    _run(tmp_path, cand, "2026-10-06")
    t = s.load_trades()
    assert list(t["date"]) == ["2026-10-06"]
    log = s.load_log()
    assert int(log["detail"].str.contains("만료").sum()) == 1          # 만료 기록은 한 번만


def test_다음_거래일이면_체결한다_주말을_건너도(many):
    """금요일 주문 → 월요일 체결은 '다음 거래일' 입니다 (만료가 아님)."""
    tmp_path, cand, _ = many
    _cand_rows(cand, [("000001", "후보", 1.0)])
    _run(tmp_path, cand, "2026-10-02")          # 금요일
    _run(tmp_path, cand, "2026-10-05")          # 월요일
    assert list(vs.Store.default(tmp_path).load_trades()["date"]) == ["2026-10-05"]


# I4 — 다 판 종목은 다음 월말 판정 전까지 다시 사지 않음
@pytest.mark.parametrize("recorded_on", ["2026-10-01", None])
def test_무효선으로_판_종목은_같은_판정으로_다시_사지_않는다(many, recorded_on):
    tmp_path, cand, frames = many
    frames["000001"] = make_daily([1000, 1000, 780, 780, 780, 780], start="2026-10-01")
    _cand_rows(cand, [("000001", "후보", 1.0)], recorded_on=recorded_on)
    for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"):
        _run(tmp_path, cand, d)
    s = vs.Store.default(tmp_path)
    t = s.load_trades()
    assert list(zip(t["date"], t["tranche"])) == [("2026-10-02", "1차"), ("2026-10-06", "무효")]
    log = s.load_log()
    막힘 = log[(log["date"] == "2026-10-06") & (log["code"] == "000001") & (log["action"] == "건너뜀")]
    assert 막힘["detail"].str.contains("이번 달 이미 정리한 종목").any()
    assert not [o for o in _orders_on(log, "2026-10-06") if o["side"] == "매수"]


def test_새_월말_판정이_나오면_다시_살_수_있다(many):
    tmp_path, cand, frames = many
    frames["000001"] = make_daily([1000, 1000, 780, 780, 780, 780], start="2026-10-01")
    _cand_rows(cand, [("000001", "후보", 1.0)], recorded_on="2026-10-01")
    for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"):
        _run(tmp_path, cand, d)
    _cand_rows(cand, [("000001", "후보", 1.0)], recorded_on="2026-10-07")     # 새 판정 (팔고 난 뒤)
    _run(tmp_path, cand, "2026-10-07")
    assert [o["tranche"] for o in _orders_on(vs.Store.default(tmp_path).load_log(), "2026-10-07")] == ["1차"]


# I5 — CLI 배선
def test_일일_손실_한도가_걸린_날은_매수_주문_0건_매도는_그대로(many):
    """배선 확인: cli 가 halted 를 decide_buys 에 넘기지 않으면 000003 의 1차 주문이 나가 깨집니다."""
    tmp_path, cand, frames = many
    frames["000001"] = make_daily([1000, 1000, 300, 300, 300, 300], start="2026-10-01")
    _cand_rows(cand, [("000001", "후보", 1.0)])
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _cand_rows(cand, [("000001", "후보", 1.0), ("000003", "후보", 3.0)])
    _run(tmp_path, cand, "2026-10-05")       # 224주 × 700원 하락 ≈ 어제 평가액의 -3.1%
    s = vs.Store.default(tmp_path)
    d = s.load_daily()
    오늘 = d[d["date"] == "2026-10-05"].iloc[0]
    assert float(오늘["day_pnl_pct"]) <= -3.0 and str(오늘["halted"]) == "True"
    주문 = _orders_on(s.load_log(), "2026-10-05")
    assert [o["side"] for o in 주문] == ["매도"] and 주문[0]["code"] == "000001"
    log = s.load_log()
    assert ((log["date"] == "2026-10-05") & (log["code"] == "000003") & (log["gate"] == "리스크")).any()


@pytest.mark.parametrize("closes, 판정, 매도단계", [
    ([1000, 1000, 1110, 1110, 1110, 1110], "후보", "매도1"),   # 평단 +10.8% (매도1) · 1차가 +11% (2차 조건)
    ([1000, 1000, 1060, 1060, 1060, 1060], "함정?", "근거"),   # 근거 사라짐 · 1차가 +6% (2차 조건)
])
def test_매도_주문이_나간_날_같은_종목_2차_매수는_없다(many, closes, 판정, 매도단계):
    """배선 확인: cli 가 selling 을 넘기지 않으면 2차 주문이 같이 나가 깨집니다.
    (무효선 날에는 2차 조건(1차가 +5%)이 설 수 없어 이 두 경우로 봅니다.)"""
    tmp_path, cand, frames = many
    frames["000001"] = make_daily(closes, start="2026-10-01")
    _cand_rows(cand, [("000001", "후보", 1.0)])
    _run(tmp_path, cand, "2026-10-01"); _run(tmp_path, cand, "2026-10-02")
    _cand_rows(cand, [("000001", 판정, 1.0), ("000002", "후보", 2.0)])
    _run(tmp_path, cand, "2026-10-05")
    log = vs.Store.default(tmp_path).load_log()
    주문 = [o for o in _orders_on(log, "2026-10-05") if o["code"] == "000001"]
    assert [(o["side"], o["tranche"]) for o in 주문] == [("매도", 매도단계)]
    assert ((log["date"] == "2026-10-05") & (log["code"] == "000001")
            & log["detail"].str.contains("오늘 매도 주문이 있는 종목")).any()


def test_첫_실행이_판단_중에_죽으면_같은_날_재실행이_주문을_낸다(many, monkeypatch):
    """스냅샷을 판단보다 먼저 쓰면, 판단 중에 죽은 날은 재실행이 '이미 끝났다' 고 보고
    그날 주문이 영영 없습니다 (재검토 2026-10-10). 스냅샷은 판단·로그 뒤에 씁니다."""
    tmp_path, cand, _ = many
    _cand_rows(cand, [("000001", "후보", 1.0)])
    진짜 = cli.va_module.decide_buys

    def 터짐(*a, **k):
        raise RuntimeError("판단 중 사고")
    monkeypatch.setattr(cli.va_module, "decide_buys", 터짐)
    with pytest.raises(RuntimeError):
        _run(tmp_path, cand, "2026-10-01")
    monkeypatch.setattr(cli.va_module, "decide_buys", 진짜)
    assert _run(tmp_path, cand, "2026-10-01") == 0
    s = vs.Store.default(tmp_path)
    assert [o["code"] for o in _orders_on(s.load_log(), "2026-10-01")] == ["000001"]
    assert list(s.load_daily()["date"]) == ["2026-10-01"]
