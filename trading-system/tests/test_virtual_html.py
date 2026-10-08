"""화면이 거짓말을 하지 않나 — 막힌 결정이 보이고, 숫자 옆에 기준일이 있다."""
from __future__ import annotations

import json

from src import report_html, virtual_account as va, virtual_html, virtual_store as vs
from src.config import VirtualAccountConfig

R = va.Rules.from_config(VirtualAccountConfig())


def _store(tmp_path):
    s = vs.Store.default(tmp_path)
    s.append_fills([va.Fill("o1", "2026-10-02", "000001", "가", "매수", "1차", 224, 1000.0, 3.1, 0.0, 336.0, 224_339.1, "후보")])
    s.append_decisions([va.Decision("2026-10-02", "000002", "나", "살 수 없음", "체결", "1차 금액 225,000원으로 1주(300,000원)도 못 삽니다"),
                        va.Decision("2026-10-02", "000003", "다", "보류", "리스크", "일일 손실 한도(-3%) 발동 — 오늘은 매도만")], {})
    s.upsert_daily({"date": "2026-10-01", "cash": 5_000_000.0, "positions_value": 0.0, "equity": 5_000_000.0,
                    "day_pnl": 0.0, "day_pnl_pct": 0.0, "halted": False, "n_positions": 0, "kosdaq_close": 800.0})
    s.upsert_daily({"date": "2026-10-02", "cash": 4_775_660.9, "positions_value": 246_400.0, "equity": 5_022_060.9,
                    "day_pnl": 22_060.9, "day_pnl_pct": 0.441, "halted": False, "n_positions": 1, "kosdaq_close": 808.0})
    return s


def test_json_에_요약_곡선_보유_로그가_있다(tmp_path):
    data = virtual_html.write_json(tmp_path / "virtual.json", _store(tmp_path), R, {"000001": 1100.0}, {"000001": "가"}, "2026-10-02")
    assert json.loads((tmp_path / "virtual.json").read_text(encoding="utf-8"))["as_of"] == "2026-10-02"
    assert data["summary"]["equity"] == 5_022_060.9 and data["summary"]["max_positions"] == 6
    assert data["summary"]["kosdaq_return_pct"] == 1.0
    assert [c["date"] for c in data["curve"]] == ["2026-10-01", "2026-10-02"]
    p = data["positions"][0]
    assert p["code"] == "000001" and p["shares"] == 224 and p["return_pct"] > 0
    assert p["to_invalid_pct"] < 0 < p["to_target_pct"]
    assert data["log"][0]["date"] == "2026-10-02"
    assert data["version"] == va.VIRTUAL_VERSION and data["rules"]["invalid_pct"] == -20.0


def test_탭_에_막힌_결정과_기준일이_보인다(tmp_path):
    data = virtual_html.write_json(tmp_path / "v.json", _store(tmp_path), R, {"000001": 1100.0}, {}, "2026-10-02")
    html = virtual_html.render_tab(data)
    assert "살 수 없음" in html and "일일 손실 한도" in html
    assert "2026-10-02 종가 기준" in html
    assert "<svg" in html and "코스닥" in html
    assert "VIRTUAL_VERSION" in html or "판 v1" in html


def test_페이지는_탭_둘을_그리고_가상_탭이_없으면_예전과_같다(tmp_path):
    data = virtual_html.write_json(tmp_path / "v.json", _store(tmp_path), R, {}, {}, "2026-10-02")
    page = report_html.render([], virtual=data)
    assert 'data-panel="scan"' in page and 'data-panel="virtual"' in page
    assert "가상 계좌" in page
    plain = report_html.render([])
    assert 'data-panel="virtual"' not in plain


def test_rerender_는_virtual_json_을_읽는다(tmp_path):
    virtual_html.write_json(tmp_path / "virtual.json", _store(tmp_path), R, {}, {}, "2026-10-02")
    page = report_html.rerender(tmp_path)
    assert "가상 계좌" in page.read_text(encoding="utf-8")


def test_빈_기록이어도_json_과_탭이_그려진다(tmp_path):
    s = vs.Store.default(tmp_path)
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-02")
    assert data["summary"]["equity"] == R.capital and data["summary"]["day_pnl"] is None
    assert data["curve"] == [] and data["positions"] == []
    json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))          # NaN 이 섞이면 표준 JSON 이 아님
    html = virtual_html.render_tab(data)
    assert "보유 종목이 없습니다" in html and "아직 결정 기록이 없습니다" in html and "이틀 이상" in html


def test_없는_값은_0이_아니라_없음으로_보인다(tmp_path):
    s = _store(tmp_path)
    s.upsert_daily({"date": "2026-10-05", "cash": 4_775_660.9, "positions_value": 246_400.0, "equity": 5_022_060.9,
                    "day_pnl": 0.0, "day_pnl_pct": 0.0, "halted": True, "n_positions": 1, "kosdaq_close": float("nan")})
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-05")   # 시세도 없음
    assert data["summary"]["halted"] is True                       # CSV 에서 읽힌 값이 무엇이든 불리언
    assert data["curve"][-1]["kosdaq_close"] is None
    assert data["positions"][0]["close_note"] == "평단"
    html = virtual_html.render_tab(data)
    assert "오늘 종가 없음 — 평단 로 평가" in html and "일일 손실 한도 발동" in html
    assert "NaN" not in html and "nan" not in html


def test_화면에_들어가는_글자는_이스케이프된다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.append_decisions([va.Decision("2026-10-02", "000009", "<b>x</b>", "보류", "조건", "<script>alert(1)</script>")], {})
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-02")
    html = virtual_html.render_tab(data)
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_대체한_종가는_무엇으로_평가했는지_표에_적힌다(tmp_path):
    data = virtual_html.write_json(tmp_path / "v.json", _store(tmp_path), R, {"000001": 1000.0}, {}, "2026-10-02",
                                   substituted={"000001": "2026-10-01 종가"})
    assert data["positions"][0]["close_note"] == "2026-10-01 종가"
    assert "오늘 종가 없음 — 2026-10-01 종가 로 평가" in virtual_html.render_tab(data)
    정상 = virtual_html.write_json(tmp_path / "v2.json", _store(tmp_path), R, {"000001": 1100.0}, {}, "2026-10-02")
    assert 정상["positions"][0]["close_note"] is None and "오늘 종가 없음" not in virtual_html.render_tab(정상)


def test_코스닥_기간은_값이_있는_첫날과_마지막날이고_카드에_적힌다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.upsert_daily({"date": "2026-10-01", "cash": 5e6, "positions_value": 0.0, "equity": 5e6, "day_pnl": "", "day_pnl_pct": "",
                    "halted": False, "n_positions": 0, "kosdaq_close": float("nan")})
    s.upsert_daily({"date": "2026-10-02", "cash": 5e6, "positions_value": 0.0, "equity": 5e6, "day_pnl": 0.0, "day_pnl_pct": 0.0,
                    "halted": False, "n_positions": 0, "kosdaq_close": 800.0})
    s.upsert_daily({"date": "2026-10-05", "cash": 5e6, "positions_value": 0.0, "equity": 5e6, "day_pnl": 0.0, "day_pnl_pct": 0.0,
                    "halted": False, "n_positions": 0, "kosdaq_close": 808.0})
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-05")
    sm = data["summary"]
    assert sm["kosdaq_from"] == "2026-10-02" and sm["kosdaq_to"] == "2026-10-05" and sm["kosdaq_return_pct"] == 1.0
    assert sm["day_pnl"] == 0.0 and data["curve"][0]["equity"] == 5e6
    assert "코스닥 같은 기간 (10-02~10-05)" in virtual_html.render_tab(data)


def test_오늘_스냅샷이_없으면_평가한_날을_기준일로_적고_경고한다(tmp_path):
    data = virtual_html.write_json(tmp_path / "v.json", _store(tmp_path), R, {"000001": 1100.0}, {}, "2026-10-06")
    assert data["summary"]["valued_on"] == "2026-10-02"
    html = virtual_html.render_tab(data)
    assert "오늘(2026-10-06) 스냅샷 없음 — 2026-10-02 평가" in html
    assert "2026-10-02 종가 기준" in html
    같은날 = virtual_html.render_tab(virtual_html.write_json(tmp_path / "v2.json", _store(tmp_path), R, {}, {}, "2026-10-02"))
    assert "스냅샷 없음" not in 같은날


def test_목표를_넘었으면_음수_거리_대신_도달이라고_적는다(tmp_path):
    s = _store(tmp_path)
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {"000001": 1130.0}, {}, "2026-10-02")   # 평단≈1002 → +12.8% (10% 넘음)
    assert data["positions"][0]["to_target_pct"] < 0
    html = virtual_html.render_tab(data)
    assert "도달 — 내일 매도 주문" in html and "+-" not in html


def test_숫자_카드는_줄바꿈되지_않는다(tmp_path):
    data = virtual_html.write_json(tmp_path / "v.json", _store(tmp_path), R, {}, {}, "2026-10-02")
    assert 'class="v vnum"' in virtual_html.render_tab(data)
    assert ".vnum{white-space:nowrap}" in report_html.STYLE


def test_halted_가_대문자_문자열이어도_발동으로_읽는다(tmp_path):
    s = _store(tmp_path)
    frame = s.load_daily().astype({"halted": object})
    frame.loc[frame.index[-1], "halted"] = "TRUE"
    s.load_daily = lambda: frame
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-02")
    assert data["summary"]["halted"] is True and "일일 손실 한도 발동" in virtual_html.render_tab(data)


def test_보유와_체결_표의_이름도_이스케이프된다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.append_fills([va.Fill("o1", "2026-10-02", "000001", "<u>체결</u>", "매수", "1차", 10, 1000.0, 1.0, 0.0, 15.0, 10_016.0, "<i>r</i>")])
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {"000001": 1000.0}, {"000001": "<b>보유</b>"}, "2026-10-02")
    html = virtual_html.render_tab(data)
    assert "<b>보유</b>" not in html and "&lt;b&gt;보유&lt;/b&gt;" in html
    assert "<u>체결</u>" not in html and "&lt;u&gt;체결&lt;/u&gt;" in html
