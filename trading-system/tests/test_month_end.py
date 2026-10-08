"""월말 단계의 날짜 판정 — 말일이 주말이면 못 돌던 것을 고칩니다.

2026-10-31 은 토요일입니다. "내일이 1일" 로만 보면 이 달은 아예 안 돕니다.
(요일은 달력으로 확인: 2026-10-31 토, 2026-11-30 월, 2027-01-31 일.)
"""
from __future__ import annotations

from datetime import date

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


import pandas as pd


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
    monkeypatch.setattr(cli, "_value_screen_pipeline", lambda args, fin: (후보, "조건X"))

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
    assert len(again) == 6
