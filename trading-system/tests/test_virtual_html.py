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
    assert data["positions"][0]["close_missing"] is True
    html = virtual_html.render_tab(data)
    assert "시세 없음" in html and "일일 손실 한도 발동" in html
    assert "NaN" not in html and "nan" not in html


def test_화면에_들어가는_글자는_이스케이프된다(tmp_path):
    s = vs.Store.default(tmp_path)
    s.append_decisions([va.Decision("2026-10-02", "000009", "<b>x</b>", "보류", "조건", "<script>alert(1)</script>")], {})
    data = virtual_html.write_json(tmp_path / "v.json", s, R, {}, {}, "2026-10-02")
    html = virtual_html.render_tab(data)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
