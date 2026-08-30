"""미국 동부시간(ET) 기준 실행 시간대 판정.

한국에서 예약을 걸 때 생기는 문제를 여기서 해결합니다.

미국은 서머타임(3월~11월)이 있어서 ET 와 한국시간(KST)의 차이가
14시간과 16시간 사이를 오갑니다. 윈도우 작업 스케줄러나 cron 에
"밤 10시 30분"처럼 한국시간을 박아두면 1년에 두 번 한 시간씩
어긋납니다.

그래서 예약은 넉넉하게(예: 30분마다) 걸어두고, 실행할지 말지는
이 모듈이 ET 를 직접 보고 판단합니다. 서머타임이 바뀌어도
따로 손댈 것이 없습니다.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def now_et() -> datetime:
    """지금의 미국 동부시간."""
    return datetime.now(NY)


def parse_hhmm(value: str) -> time:
    """'08:30' 형식 문자열을 time 으로."""
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"시각은 'HH:MM' 형식이어야 합니다: {value!r}") from exc


def is_weekday(now: datetime) -> bool:
    """월~금이면 True. (공휴일 휴장은 판정하지 않습니다.)"""
    return now.weekday() < 5


def within_window(now: datetime, start: str, end: str) -> bool:
    """now(ET)가 start~end 구간 안인지. 양끝을 포함합니다."""
    current = now.timetz().replace(tzinfo=None)
    return parse_hhmm(start) <= current <= parse_hhmm(end)


def should_run(now: datetime, start: str, end: str) -> tuple[bool, str]:
    """지금 실행해도 되는지와 그 이유를 돌려줍니다."""
    if not is_weekday(now):
        return False, f"주말입니다 (ET {now:%Y-%m-%d %a})"
    if not within_window(now, start, end):
        return False, (
            f"실행 시간대 밖입니다 (지금 ET {now:%H:%M}, 대상 {start}~{end})"
        )
    return True, ""
