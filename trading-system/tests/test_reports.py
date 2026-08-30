"""리포트 문구 — 실패와 '통과 0건' 을 헷갈리게 쓰면 안 됩니다."""

from src import scanner_a, scanner_b
from src.config import ScannerBConfig
from src.strategy import ConditionResult

WHEN = "2026-01-02 09:00 ET"


def _hit(ticker="ABCD", gap=7.5):
    return scanner_a.GapHit(
        ticker=ticker, price=10.75, gap_pct=gap, premarket_volume=120_000,
        prev_close=10.0, reason="실적 발표",
    )


def _result(ticker="ABCD"):
    return ConditionResult(
        ticker=ticker, c1_above_prev_high=True, c2_prev_close_above_sma_slow=True,
        c3_above_premarket_high=True, c4_above_today_high=True, c5_trend_aligned=True,
        price=11.0, prev_high=10.5, prev_close=10.2, sma_slow=9.0,
        premarket_high=10.8, today_high=11.0,
    )


def test_scanner_a_all_failures_is_not_reported_as_zero_hits():
    report = scanner_a.format_report([], WHEN, errors=["A: 오류", "B: 오류"], scanned=2)
    assert "전부 조회에 실패" in report
    assert "조건에 맞는 종목이 없습니다" not in report


def test_scanner_a_genuine_zero_hits():
    report = scanner_a.format_report([], WHEN, errors=[], scanned=5)
    assert "조건에 맞는 종목이 없습니다" in report
    assert "실패" not in report


def test_scanner_a_partial_failure_is_disclosed():
    report = scanner_a.format_report([_hit()], WHEN, errors=["B: 오류"], scanned=3)
    assert "ABCD" in report
    assert "조회 실패 1종목" in report


def test_scanner_b_all_failures_is_not_reported_as_no_signal():
    report = scanner_b.format_report([], WHEN, errors=["A: 오류"], scanned=1)
    assert "전부 조회에 실패" in report
    assert "매수 신호 종목이 없습니다" not in report


def test_scanner_b_genuine_no_signal():
    report = scanner_b.format_report([], WHEN, errors=[], scanned=4)
    assert "매수 신호 종목이 없습니다" in report


def test_scanner_b_report_carries_the_disclaimer():
    report = scanner_b.format_report([_result()], WHEN, errors=[], scanned=1)
    assert "매매 권유가 아닙니다" in report
    assert "ABCD" in report


def test_scanner_a_sorts_by_gap_and_caps_results():
    from src.config import ScannerAConfig
    cfg = ScannerAConfig(max_results=2)
    hits = [_hit("AAA", 6.0), _hit("BBB", 9.0), _hit("CCC", 7.0)]
    hits.sort(key=lambda h: h.gap_pct, reverse=True)
    assert [h.ticker for h in hits[: cfg.max_results]] == ["BBB", "CCC"]


def test_earliest_hour_guard():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cfg = ScannerBConfig(earliest_hour_et=10)
    ny = ZoneInfo("America/New_York")
    assert not scanner_b.is_after_earliest_hour(cfg, datetime(2026, 1, 2, 9, 0, tzinfo=ny))
    assert scanner_b.is_after_earliest_hour(cfg, datetime(2026, 1, 2, 10, 0, tzinfo=ny))


# ── 휴장일은 오류가 아닙니다 ──


def test_scanner_a_holiday_is_not_reported_as_failure():
    from src import scanner_kr

    text = scanner_kr.format_report_a([], WHEN, errors=[], scanned=14, closed=14)
    assert "휴장일" in text
    assert "실패" not in text
    assert "조건에 맞는 종목이 없습니다" not in text


def test_scanner_b_holiday_is_not_reported_as_failure():
    from src import scanner_kr

    text = scanner_kr.format_report_b([], WHEN, errors=[], scanned=14, closed=14)
    assert "휴장일" in text
    assert "매수 신호 종목이 없습니다" not in text


def test_partial_suspension_is_disclosed_but_not_called_a_holiday():
    from src import scanner_kr

    text = scanner_kr.format_report_b([], WHEN, errors=[], scanned=14, closed=3)
    assert "휴장일" not in text
    assert "오늘 거래 없음 3종목" in text


def test_errors_and_suspensions_are_counted_separately():
    from src import scanner_kr

    text = scanner_kr.format_report_a([], WHEN, errors=["A: 오류"], scanned=10, closed=4)
    assert "조회 실패 1종목" in text
    assert "오늘 거래 없음 4종목" in text
