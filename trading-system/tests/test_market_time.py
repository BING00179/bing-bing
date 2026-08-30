"""실행 시간대 판정 — 서머타임이 바뀌어도 흔들리면 안 됩니다."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.market_time import (
    is_weekday,
    parse_hhmm,
    should_run,
    within_window,
)

NY = ZoneInfo("America/New_York")


def et(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def test_parse_hhmm():
    assert parse_hhmm("08:30").hour == 8
    assert parse_hhmm("08:30").minute == 30
    with pytest.raises(ValueError):
        parse_hhmm("8시 30분")


def test_within_window_includes_both_ends():
    assert within_window(et(2026, 6, 1, 8, 30), "08:30", "14:00")
    assert within_window(et(2026, 6, 1, 14, 0), "08:30", "14:00")
    assert within_window(et(2026, 6, 1, 11, 0), "08:30", "14:00")


def test_outside_window():
    assert not within_window(et(2026, 6, 1, 8, 29), "08:30", "14:00")
    assert not within_window(et(2026, 6, 1, 14, 1), "08:30", "14:00")


def test_weekend_is_skipped():
    saturday = et(2026, 6, 6, 11, 0)
    assert not is_weekday(saturday)
    ok, reason = should_run(saturday, "08:30", "14:00")
    assert not ok
    assert "주말" in reason


def test_weekday_inside_window_runs():
    ok, reason = should_run(et(2026, 6, 1, 9, 0), "08:30", "14:00")
    assert ok
    assert reason == ""


def test_reason_names_the_window():
    ok, reason = should_run(et(2026, 6, 1, 6, 0), "08:30", "14:00")
    assert not ok
    assert "08:30~14:00" in reason


def test_window_is_judged_in_et_not_local_time():
    """서머타임 유무와 관계없이 'ET 09:00' 은 항상 실행 시간대 안입니다.

    한국시간으로는 여름 밤 10시, 겨울 밤 11시로 달라지지만
    ET 기준 판정이므로 스케줄을 손댈 필요가 없습니다.
    """
    summer = et(2026, 7, 1, 9, 0)     # EDT (UTC-4)
    winter = et(2026, 12, 1, 9, 0)    # EST (UTC-5)
    assert summer.utcoffset() != winter.utcoffset()   # 실제로 오프셋이 다름
    assert should_run(summer, "08:30", "14:00")[0]
    assert should_run(winter, "08:30", "14:00")[0]
