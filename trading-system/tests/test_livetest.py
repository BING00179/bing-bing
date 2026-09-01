"""실시간 검증 검사.

이 기록의 값어치는 '앞으로의 자료' 라는 데 있습니다. 그래서 두 가지를
집중해서 봅니다 — 미래를 미리 채우지 않는가, 조건이 바뀐 걸 숨기지
않는가.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import breakout_kr as bo
from src import livetest as lt


def _bars(closes, opens=None, start="2026-01-02"):
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series([float(c) for c in closes], index=idx)
    open_ = (pd.Series([float(o) for o in opens], index=idx)
             if opens is not None else close)
    return pd.DataFrame({"open": open_, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": 1_000})


def _hit(code="000001", name="가나", date="2026-01-02", close=1000.0):
    return bo.Hit(code=code, name=name, date=pd.Timestamp(date), close=close,
                  volume_mult=5.0, base_range_pct=20.0, runup_pct=10.0,
                  turnover=1e9, score=80.0)


# ────────────────────── 적기 ──────────────────────

def test_기록이_없으면_빈_표다(tmp_path):
    assert lt.load(tmp_path / "없음.csv").empty


def test_적고_다시_읽으면_그대로다(tmp_path):
    frame, 수 = lt.add_signals(lt.load(tmp_path / "j.csv"), [_hit()], bo.Setup())
    assert 수 == 1
    lt.save(frame, tmp_path / "j.csv")
    다시 = lt.load(tmp_path / "j.csv")
    assert len(다시) == 1
    assert 다시.iloc[0]["code"] == "000001"


def test_종목코드_앞자리_0이_사라지지_않는다(tmp_path):
    frame, _ = lt.add_signals(lt.load(tmp_path / "j.csv"),
                              [_hit(code="005930")], bo.Setup())
    lt.save(frame, tmp_path / "j.csv")
    assert lt.load(tmp_path / "j.csv").iloc[0]["code"] == "005930"


def test_같은_날_같은_종목을_두_번_적지_않는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    frame, 수 = lt.add_signals(frame, [_hit()], bo.Setup())
    assert 수 == 0 and len(frame) == 1


def test_적을_때는_갭을_비워_둔다():
    """갭은 다음날 아침에야 아는 값입니다. 미리 채우면 미래를 보는 것."""
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    assert str(frame.iloc[0]["entry_date"]) == ""
    assert pd.isna(frame.iloc[0]["gap_pct"])
    assert str(frame.iloc[0]["bought"]) == ""


def test_그때_쓴_조건값을_같이_적는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup(min_volume_mult=7.0))
    assert "vol7" in frame.iloc[0]["rule"]


# ────────────────────── 다음날 채우기 ──────────────────────

def test_다음_거래일_시가와_갭을_채운다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    daily = _bars([1000.0, 1100.0], opens=[1000.0, 1030.0])
    frame, 수 = lt.fill_entries(frame, {"000001": daily})
    assert 수 == 1
    assert frame.iloc[0]["entry_open"] == 1030.0
    assert abs(frame.iloc[0]["gap_pct"] - 3.0) < 1e-6
    assert frame.iloc[0]["bought"] == "예"          # 갭 3% ≤ 5%


def test_갭이_크면_사지_않은_것으로_적는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    daily = _bars([1000.0, 1200.0], opens=[1000.0, 1100.0])   # 갭 10%
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    assert frame.iloc[0]["bought"] == "아니오"


def test_다음_거래일이_아직_없으면_비워_둔다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    daily = _bars([1000.0])                     # 신호일 하루뿐
    frame, 수 = lt.fill_entries(frame, {"000001": daily})
    assert 수 == 0
    assert str(frame.iloc[0]["entry_date"]) == ""


def test_이미_채운_것은_다시_건드리지_않는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    daily = _bars([1000.0, 1100.0], opens=[1000.0, 1030.0])
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    frame, 수 = lt.fill_entries(frame, {"000001": daily})
    assert 수 == 0


# ────────────────────── 채점 ──────────────────────

def _채운기록(gap_open=1030.0):
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    daily = _bars([1000.0] + [1100.0] * 25,
                  opens=[1000.0, gap_open] + [1100.0] * 24)
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    return frame, daily


def test_기간이_안_찼으면_채점하지_않는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    daily = _bars([1000.0, 1100.0], opens=[1000.0, 1030.0])
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    index = _bars([100.0, 101.0])
    assert lt.score_rows(frame, {"000001": daily}, index, horizon=20) == []


def test_기간이_차면_지수_대비로_잰다():
    frame, daily = _채운기록()
    index = _bars([100.0] * 26)                 # 지수는 그대로
    결과 = lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                        today=pd.Timestamp("2026-12-31"))
    assert len(결과) == 1
    s = 결과[0]
    assert abs(s.stock_pct - (1100 / 1030 - 1) * 100) < 1e-6
    assert abs(s.index_pct) < 1e-9
    assert abs(s.excess - s.stock_pct) < 1e-6


def test_지수가_더_오르면_초과수익이_마이너스다():
    """지수는 보유 기간 '동안' 올라야 합니다.

    (앞선 실패: 진입일 전에만 올려 두니 보유 구간 안에서는 평평해서
     지수 수익이 0 이 나왔습니다. 구간 안에서 오르게 고칩니다.)
    """
    frame, daily = _채운기록()
    index = _bars(list(np.linspace(100.0, 200.0, 26)))   # 기간 내내 두 배로
    결과 = lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                        today=pd.Timestamp("2026-12-31"))
    assert 결과[0].index_pct > 50.0
    assert 결과[0].excess < 0


def test_갭_때문에_안_산_것은_기본으로_빼고_잰다():
    frame, daily = _채운기록(gap_open=1100.0)   # 갭 10% → 안 삼
    index = _bars([100.0] * 26)
    assert lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                         today=pd.Timestamp("2026-12-31")) == []
    포함 = lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                        only_bought=False, today=pd.Timestamp("2026-12-31"))
    assert len(포함) == 1


# ────────────────────── 판정 ──────────────────────

def _scored(excesses):
    return [lt.Scored(code="A", name="A", signal_date="2026-01-02",
                      entry_date="2026-01-05", days=20, entry_open=100,
                      end_close=100 + e, stock_pct=e, index_pct=0.0,
                      excess=e, gap_pct=1.0) for e in excesses]


def test_표본이_적으면_판정하지_않는다():
    v = lt.summarize(_scored([50.0] * 5))
    assert not v.enough and not v.passes


def test_세_가지를_다_넘겨야_통과다():
    rng = np.random.default_rng(0)
    좋음 = lt.summarize(_scored(list(rng.normal(8.0, 5.0, 60))))
    assert 좋음.passes
    나쁨 = lt.summarize(_scored(list(rng.normal(-8.0, 5.0, 60))))
    assert not 나쁨.passes


# ────────────────────── 보고서 ──────────────────────

def test_조건이_섞이면_경고한다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    frame, _ = lt.add_signals(frame, [_hit(code="000002", date="2026-01-05")],
                              bo.Setup(min_volume_mult=9.0))
    text = lt.report(frame, [], lt.summarize([]))
    assert "서로 다른 조건이 섞여" in text


def test_보고서는_조건을_바꾸면_시계가_다시_간다고_적는다():
    scored = _scored([1.0] * 40)
    text = lt.report(pd.DataFrame(columns=list(lt.COLUMNS)), scored,
                     lt.summarize(scored))
    assert "시계가 다시 갑니다" in text


def test_아직_없으면_몇_달_걸린다고_말한다():
    text = lt.report(pd.DataFrame(columns=list(lt.COLUMNS)), [],
                     lt.summarize([]))
    assert "30건이 쌓여야" in text


def test_통과해도_비용을_따로_보라고_말한다():
    rng = np.random.default_rng(1)
    scored = _scored(list(rng.normal(8.0, 5.0, 60)))
    text = lt.report(pd.DataFrame(columns=list(lt.COLUMNS)), scored,
                     lt.summarize(scored))
    assert "거래비용" in text


# ────────────────── 지우지 않는 장부 ──────────────────
# 이 파일의 값어치는 '지우지 않았다' 는 데 있습니다. 성적이 나쁜
# 기록을 슬쩍 빼면 남는 것은 잘된 것뿐이고, 그건 증거가 아닙니다.

def test_기록이_줄어드는_저장은_거부한다(tmp_path):
    import pytest
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(), _hit(code="000002")], bo.Setup())
    lt.save(frame, path)
    with pytest.raises(lt.LedgerShrank):
        lt.save(frame.iloc[:1], path)
    assert len(lt.load(path)) == 2          # 원본은 그대로


def test_건수가_같아도_바뀌치기는_거부한다(tmp_path):
    import pytest
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    lt.save(frame, path)
    다른것, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                             [_hit(code="000099")], bo.Setup())
    with pytest.raises(lt.LedgerShrank) as caught:
        lt.save(다른것, path)
    assert "사라집니다" in str(caught.value)


def test_덧붙이는_저장은_통과한다(tmp_path):
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    lt.save(frame, path)
    frame, _ = lt.add_signals(frame, [_hit(code="000002")], bo.Setup())
    lt.save(frame, path)
    assert len(lt.load(path)) == 2


def test_정말_필요하면_열어_줄_수는_있다(tmp_path):
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    lt.save(frame, path)
    lt.save(pd.DataFrame(columns=list(lt.COLUMNS)), path, allow_shrink=True)
    assert lt.load(path).empty


# ────────────────── 저평가 후보도 같은 장부에 ──────────────────

def test_저평가_후보를_적는다():
    ranked = pd.DataFrame({
        "code": ["000001", "000002"], "name": ["가", "나"],
        "close": [1000.0, 2000.0], "turnover": [1e9, 2e9],
        "저평가점수": [1.5, 2.5],
    })
    frame, 수 = lt.add_value_picks(pd.DataFrame(columns=list(lt.COLUMNS)),
                                  ranked, "pbr1/per15",
                                  on_date=pd.Timestamp("2026-08-31"))
    assert 수 == 2
    assert set(frame["setup"]) == {"value"}
    assert frame.iloc[0]["rule"] == "pbr1/per15"


def test_저평가_후보에는_갭_규칙을_걸지_않는다():
    """저평가는 몇 달을 보고 사는 것이라 다음날 아침 갭과 무관합니다."""
    ranked = pd.DataFrame({"code": ["000001"], "name": ["가"],
                           "close": [1000.0], "turnover": [1e9],
                           "저평가점수": [1.0]})
    frame, _ = lt.add_value_picks(pd.DataFrame(columns=list(lt.COLUMNS)),
                                  ranked, "규칙",
                                  on_date=pd.Timestamp("2026-01-02"))
    daily = _bars([1000.0, 1200.0], opens=[1000.0, 1150.0])   # 갭 15%
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    assert frame.iloc[0]["bought"] == "예"


def test_같은_날_같은_종목은_두_번_안_적는다():
    ranked = pd.DataFrame({"code": ["000001"], "name": ["가"],
                           "close": [1000.0], "turnover": [1e9],
                           "저평가점수": [1.0]})
    frame, _ = lt.add_value_picks(pd.DataFrame(columns=list(lt.COLUMNS)),
                                  ranked, "규칙",
                                  on_date=pd.Timestamp("2026-08-31"))
    frame, 수 = lt.add_value_picks(frame, ranked, "규칙",
                                  on_date=pd.Timestamp("2026-08-31"))
    assert 수 == 0


# ────────────── 감사 장부의 규칙 일곱 가지 ──────────────
# 돈이 움직일 통로입니다. 그냥 넘기면 나중에 더 크게 물어야 합니다.

def test_줄마다_번호와_적은_시각이_붙는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    row = frame.iloc[0]
    assert row["row_id"] and row["recorded_at"]
    assert row["kind"] == lt.KIND_RECORD
    assert row["status"] == lt.STATUS_OK
    assert row["version"] == lt.LEDGER_VERSION


def test_선정_근거와_출처를_같이_적는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    row = frame.iloc[0]
    assert "거래량" in row["basis"]
    assert row["source"].strip()


def test_정정은_덮어쓰지_않고_새_줄로_붙는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(name="틀린이름")], bo.Setup())
    원래id = frame.iloc[0]["row_id"]
    frame, 새id = lt.add_correction(frame, 원래id, "종목명 오기", name="맞는이름")

    assert len(frame) == 2                       # 원본이 그대로 남아 있음
    원본 = frame[frame["row_id"] == 원래id].iloc[0]
    assert 원본["status"] == lt.STATUS_FIXED
    assert 원본["name"] == "틀린이름"              # 원본은 손대지 않음

    정정 = frame[frame["row_id"] == 새id].iloc[0]
    assert 정정["kind"] == lt.KIND_FIX
    assert 정정["corrects"] == 원래id
    assert 정정["name"] == "맞는이름"
    assert "종목명 오기" in 정정["basis"]


def test_정정_사유를_안_적으면_거부한다():
    import pytest
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    with pytest.raises(ValueError):
        lt.add_correction(frame, frame.iloc[0]["row_id"], "  ", name="바꿈")


def test_없는_줄은_고칠_수_없다():
    import pytest
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    with pytest.raises(KeyError):
        lt.add_correction(frame, "없는번호", "사유", name="바꿈")


def test_채점은_정정된_원본을_빼고_본다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    frame, _ = lt.add_correction(frame, frame.iloc[0]["row_id"], "오기", name="새이름")
    daily = _bars([1000.0] + [1100.0] * 25, opens=[1000.0, 1030.0] + [1100.0] * 24)
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    결과 = lt.score_rows(frame, {"000001": daily}, _bars([100.0] * 26),
                        horizon=20, today=pd.Timestamp("2026-12-31"))
    assert len(결과) == 1                        # 두 줄이 아니라 한 줄만
    assert 결과[0].name == "새이름"


def test_판이_다르면_섞어_채점하지_않는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    frame.at[0, "version"] = "0"                 # 예전 판인 척
    daily = _bars([1000.0] + [1100.0] * 25, opens=[1000.0, 1030.0] + [1100.0] * 24)
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    index = _bars([100.0] * 26)
    assert lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                         today=pd.Timestamp("2026-12-31"), version="1") == []
    assert len(lt.score_rows(frame, {"000001": daily}, index, horizon=20,
                             today=pd.Timestamp("2026-12-31"), version="0")) == 1


def test_진입_뒤_최고가_최저가를_덧쌓는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    daily = _bars([1000.0, 900.0, 1300.0, 1100.0],
                  opens=[1000.0, 1000.0, 1200.0, 1100.0])
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    frame, 갱신 = lt.update_tracking(frame, {"000001": daily},
                                   today=pd.Timestamp("2026-12-31"))
    assert 갱신 == 1
    row = frame.iloc[0]
    assert row["high_since"] > 1300.0 * 0.99
    assert row["low_since"] < 900.0 * 1.01
    assert row["high_date"] and row["low_date"] and row["last_checked"]


def test_목표와_무효선_도달일을_적는다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    # 진입 시가 1000 → +15% 는 1150, -12% 는 880
    daily = _bars([1000.0, 850.0, 1200.0], opens=[1000.0, 1000.0, 1150.0])
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    frame, _ = lt.update_tracking(frame, {"000001": daily},
                                 today=pd.Timestamp("2026-12-31"))
    row = frame.iloc[0]
    assert str(row["target_hit_date"])           # 목표에 닿음
    assert str(row["invalid_hit_date"])          # 무효선에도 닿음


def test_한_번_닿은_날은_덮어쓰지_않는다():
    """처음 닿은 날이 사실입니다. 나중에 또 닿았다고 바꾸면 안 됩니다."""
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit(close=1000.0)], bo.Setup())
    daily = _bars([1000.0, 1200.0, 1000.0, 1300.0],
                  opens=[1000.0, 1000.0, 1000.0, 1000.0])
    frame, _ = lt.fill_entries(frame, {"000001": daily})
    frame, _ = lt.update_tracking(frame, {"000001": daily},
                                 today=pd.Timestamp("2026-12-31"))
    처음 = frame.iloc[0]["target_hit_date"]
    frame, _ = lt.update_tracking(frame, {"000001": daily},
                                 today=pd.Timestamp("2026-12-31"))
    assert frame.iloc[0]["target_hit_date"] == 처음


def test_보고서가_판이_섞인_것을_알려준다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    frame, _ = lt.add_signals(frame, [_hit(code="000002")], bo.Setup())
    frame.at[0, "version"] = "0"
    text = lt.report(frame, [], lt.summarize([]))
    assert "판이 2개 섞여" in text


def test_보고서가_정정_기록을_보여준다():
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    frame, _ = lt.add_correction(frame, frame.iloc[0]["row_id"], "오기", name="새것")
    text = lt.report(frame, [], lt.summarize([]))
    assert "정정 기록 1건" in text
    assert "지우지 않고 남아" in text


def test_장부가_작으면_지울_이유가_없다고_말한다(tmp_path):
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    lt.save(frame, path)
    말 = lt.size_note(path)
    assert "지울 이유가 없습니다" in 말


def test_커지면_백업_먼저_받으라는_순서를_알려준다(tmp_path, monkeypatch):
    path = tmp_path / "j.csv"
    frame, _ = lt.add_signals(pd.DataFrame(columns=list(lt.COLUMNS)),
                              [_hit()], bo.Setup())
    lt.save(frame, path)
    monkeypatch.setattr(lt, "BIG_LEDGER_MB", 0.0)   # 이미 큰 것처럼
    말 = lt.size_note(path)
    assert "ledger-export" in 말
    assert "승인" in 말
    assert "승인 없이 지우는 길은 코드에 두지 않았습니다" in 말
