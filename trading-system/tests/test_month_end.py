"""월말 단계의 날짜 판정 — 말일이 주말이면 못 돌던 것을 고칩니다.

2026-10-31 은 토요일입니다. "내일이 1일" 로만 보면 이 달은 아예 안 돕니다.
(요일은 달력으로 확인: 2026-10-31 토, 2026-11-30 월, 2027-01-31 일.)
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from src import cli


def test_말일이_평일이면_그날이_마지막_평일이다():
    assert cli.is_last_weekday_of_month(date(2026, 11, 30)) is True   # 월요일
    assert cli.is_last_weekday_of_month(date(2026, 11, 27)) is False


def test_말일이_토요일이면_그_전_금요일이_마지막_평일이다():
    assert cli.is_last_weekday_of_month(date(2026, 10, 30)) is True   # 금요일
    assert cli.is_last_weekday_of_month(date(2026, 10, 29)) is False
    assert cli.is_last_weekday_of_month(date(2026, 10, 31)) is False  # 토요일


def test_말일이_일요일이면_그_전_금요일이_마지막_평일이다():
    assert cli.is_last_weekday_of_month(date(2027, 1, 29)) is True    # 금요일 (1/30 토, 1/31 일)
    assert cli.is_last_weekday_of_month(date(2027, 1, 31)) is False   # 일요일


def test_명령은_종료코드로_답한다(capsys):
    assert cli.main(["month-end-check", "--date", "2026-10-30"]) == 0
    assert cli.main(["month-end-check", "--date", "2026-10-29"]) == 1
    out = capsys.readouterr().out
    assert "마지막 평일" in out


def test_value_record_는_후보_전체를_달별_파일에_남긴다(tmp_path, monkeypatch):
    """상위 10개만 장부에 적으면, 보유 종목이 11등이 됐을 때 '근거 사라짐' 으로
    오판합니다. 그래서 판정 '후보' 전체를 따로 남깁니다."""
    fin = tmp_path / "fin.csv"
    fin.write_text("code,rcept_dt\n", encoding="utf-8-sig")   # 내용은 안 씀 — 아래서 가짜로 바꿈

    후보 = pd.DataFrame({
        "code": ["000001", "000002", "000003"], "name": ["가", "나", "다"],
        "close": [1000.0, 2000.0, 3000.0], "PBR": [0.5, 0.6, 0.7], "PER": [5.0, 6.0, 7.0],
        "turnover": [1e9, 1e9, 1e9], "저평가점수": [1.0, 2.0, 3.0],
        "기업점수": [70, 70, 70], "가격점수": [70, 70, 70], "판정": ["후보"] * 3,
        "일회성경고": ["", "", ""],
    })
    monkeypatch.setattr(cli, "_value_screen_pipeline", lambda args, fin: (후보, "조건X", 후보))

    out = tmp_path / "cand.csv"
    rc = cli.main(["value-record", "--fin", str(fin), "--file", str(tmp_path / "lt.csv"),
                   "--top", "2", "--candidates-out", str(out)])
    assert rc == 0
    saved = pd.read_csv(out, dtype={"code": str})
    assert len(saved) == 3, "상위 2개만이 아니라 후보 3개 전부"
    assert set(saved.columns) >= {"month", "code", "name", "close", "score"}

    # 같은 달에 다시 돌리면 덮어쓰고(중복 없음), 다른 달 줄은 남는다
    saved["month"] = "2000-01"
    saved.to_csv(out, index=False, encoding="utf-8-sig")
    cli.main(["value-record", "--fin", str(fin), "--file", str(tmp_path / "lt.csv"),
              "--top", "2", "--candidates-out", str(out)])
    again = pd.read_csv(out, dtype={"code": str})
    assert (again["month"] == "2000-01").sum() == 3
    assert (again["month"] != "2000-01").sum() == 3
    assert len(again) == 6


# ---- 최종 검토 반영 (2026-10-10) — 후보 파일에는 좁히기 전 판정 전체 ----------------

def _판정표():
    return pd.DataFrame({
        "code": ["000001", "000002", "000003", "000004", "000005"], "name": list("가나다라마"),
        "close": [1000.0] * 5, "PBR": [0.5] * 5, "PER": [5.0] * 5, "turnover": [1e9] * 5,
        "저평가점수": [1.0, 2.0, 3.0, 4.0, 5.0], "기업점수": [70] * 5, "가격점수": [70] * 5,
        "판정": ["후보", "후보", "비쌈", "함정?", "제외"], "일회성경고": [""] * 5,
    })


def test_파이프라인은_장부용은_후보만_후보_파일용은_전체를_돌려준다(monkeypatch):
    """'근거 사라짐(함정?·제외)' 을 보려면 좁히기 전 판정이 있어야 합니다."""
    표 = _판정표()
    monkeypatch.setattr(cli.val_module, "listing_with_cap", lambda market: 표)
    monkeypatch.setattr(cli.val_module, "valuation", lambda listing, fin: 표)
    monkeypatch.setattr(cli.val_module, "screen", lambda v, rule: v.assign(통과=True))
    monkeypatch.setattr(cli.val_module, "rank", lambda x: x)
    monkeypatch.setattr(cli.qa_module, "evaluate", lambda x: 표)
    args = cli.build_parser().parse_args(["value-record"])
    통과, _, 전체 = cli._value_screen_pipeline(args, pd.DataFrame())
    assert list(통과["판정"]) == ["후보", "후보"]
    assert list(전체["판정"]) == ["후보", "후보", "비쌈", "함정?", "제외"]


def test_value_record_는_장부에는_후보만_후보_파일에는_판정_전체와_기록일을_남긴다(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src import livetest as lt
    표 = _판정표()
    monkeypatch.setattr(cli, "_value_screen_pipeline", lambda args, fin: (표[표["판정"] == "후보"], "조건X", 표))
    monkeypatch.setattr(cli, "now_kst", lambda: datetime(2026, 10, 30, 16, 5, tzinfo=ZoneInfo("Asia/Seoul")))
    fin = tmp_path / "fin.csv"
    fin.write_text("code,rcept_dt\n", encoding="utf-8-sig")
    out = tmp_path / "cand.csv"
    assert cli.main(["value-record", "--fin", str(fin), "--file", str(tmp_path / "lt.csv"),
                     "--top", "10", "--candidates-out", str(out)]) == 0
    saved = pd.read_csv(out, dtype={"code": str}, keep_default_na=False)
    assert list(saved["basis"]) == ["후보", "후보", "비쌈", "함정?", "제외"]
    assert set(saved["recorded_on"]) == {"2026-10-30"} and set(saved["month"]) == {"2026-10"}
    장부 = lt.load(tmp_path / "lt.csv")
    assert sorted(장부["code"].astype(str)) == ["000001", "000002"]     # 장부는 지금처럼 '후보' 만
    # 가상 계좌가 읽으면
    목록, 유지, 사라짐, 기록일 = cli.virtual_candidates(out, 장부)
    assert [c for c, _, _ in 목록] == ["000001", "000002"]
    assert 유지 == {"000001", "000002", "000003"}
    assert 사라짐 == {"000004": "함정?", "000005": "제외"} and 기록일 == "2026-10-30"
