"""웹페이지 생성 — 근거가 빠짐없이 들어가는가."""

import json

from src.report_html import build_entry, load_history, render, update
from src.scanner_kr import Check, SignalKr


from src.ranking import Score

SCORE = Score(total=88.0, gap=70.0, turnover=90.0, trend=95.0, near_high=92.0)


def signal(code="123456", name="테스트", price=10_000.0):
    s = SignalKr(
        code=code, name=name, price=price, prev_high=price * 0.97,
        prev_close=price * 0.94, sma_slow=price * 0.7, open_price=price * 0.98,
        today_high=price, failed=[], gap_pct=6.5, turnover=2.4e10,
        closes=[price * (0.8 + i * 0.004) for i in range(50)],
        volumes=[100_000.0] * 20, sma_fast_v=price * 0.93, sma_mid_v=price * 0.85,
    )
    s.checks = [
        Check("① 전날 고가 돌파", True, f"현재가 {price:,.0f}원 vs 전날 고가", "설명1"),
        Check("② 전날 종가 > 200일선", True, "전날 종가 vs 200일선", "설명2"),
    ]
    return s


def test_entry_keeps_every_number_used_for_the_decision():
    s = signal()
    s.score = SCORE
    entry = build_entry("2026-08-31 10:30 KST", None, [s], top_n=1)
    row = entry["signals"][0]

    for key in ("prev_high", "prev_close", "sma_slow", "sma_fast", "sma_mid",
                "open", "today_high", "turnover", "gap_pct", "closes", "checks"):
        assert key in row, f"근거 항목 누락: {key}"
    assert row["recommended"] is True
    assert len(row["checks"]) == 2


def test_top_n_marks_only_the_recommended_ones():
    rows = [signal(code=f"00000{i}") for i in range(1, 5)]
    entry = build_entry("2026-08-31 10:30 KST", None, rows, top_n=2)
    marks = [r["recommended"] for r in entry["signals"]]
    assert marks == [True, True, False, False]


def test_page_shows_the_evidence_section():
    s = signal()
    s.score = SCORE
    entry = build_entry("2026-08-31 10:30 KST", None, [s], top_n=1)
    html = render([entry])

    assert "선정 근거 전체 보기" in html
    assert "① 전날 고가 돌파" in html
    assert "점수 계산" in html
    assert "사용한 값" in html
    assert "매매 권유가 아닙니다" in html


def test_page_draws_a_chart_when_there_is_price_history():
    s = signal()
    entry = build_entry("2026-08-31 10:30 KST", None, [s], top_n=1)
    html = render([entry])
    assert "<svg" in html and "polyline" in html


def test_empty_page_does_not_crash():
    html = render([])
    assert "아직 스캔 기록이 없습니다" in html
    assert "<svg" not in html


def test_no_signal_day_says_so():
    entry = build_entry("2026-08-31 10:30 KST", None, [], top_n=3)
    assert "조건을 통과한 종목이 없습니다" in render([entry])


def test_history_accumulates_by_day(tmp_path):
    s = signal()
    update(tmp_path, "2026-08-31 10:30 KST", None, [s], 1)
    update(tmp_path, "2026-09-01 10:30 KST", None, [s], 1)
    entries = load_history(tmp_path / "history.json")
    assert [e["date"] for e in entries] == ["2026-08-31", "2026-09-01"]


def test_same_day_rerun_overwrites_instead_of_duplicating(tmp_path):
    update(tmp_path, "2026-08-31 10:30 KST", None, [signal()], 1)
    update(tmp_path, "2026-08-31 14:00 KST", None, [signal(), signal("999999")], 1)
    entries = load_history(tmp_path / "history.json")
    assert len(entries) == 1
    assert entries[0]["count"] == 2
    assert entries[0]["when"].endswith("14:00 KST")


def test_broken_history_file_starts_over(tmp_path):
    (tmp_path / "history.json").write_text("{ 깨진 파일", encoding="utf-8")
    assert load_history(tmp_path / "history.json") == []


def test_update_writes_both_files(tmp_path):
    page = update(tmp_path, "2026-08-31 10:30 KST", None, [signal()], 1)
    assert page.exists() and page.name == "index.html"
    assert json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))


def test_html_escapes_company_names():
    s = signal(name="<script>alert(1)</script>")
    entry = build_entry("2026-08-31 10:30 KST", None, [s], top_n=1)
    html = render([entry])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
