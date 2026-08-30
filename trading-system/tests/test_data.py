from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.data import (
    DataUnavailable,
    load_csv,
    premarket_stats,
    read_universe,
    session_stats,
)
from tests.helpers import make_daily, rising

NY = ZoneInfo("America/New_York")


def _intraday(rows):
    """(시각문자열, 고가, 종가, 거래량) 목록으로 분봉 프레임을 만듭니다."""
    index = pd.DatetimeIndex(
        [datetime.fromisoformat(t).replace(tzinfo=NY) for t, *_ in rows]
    )
    return pd.DataFrame(
        {
            "open": [c for _, _, c, _ in rows],
            "high": [h for _, h, _, _ in rows],
            "low": [c * 0.999 for _, _, c, _ in rows],
            "close": [c for _, _, c, _ in rows],
            "volume": [v for *_, v in rows],
        },
        index=index,
    )


def test_premarket_stats_sums_only_pre_open_bars():
    frame = _intraday(
        [
            ("2024-05-01T07:00", 10.5, 10.4, 20_000),
            ("2024-05-01T08:00", 11.0, 10.9, 40_000),
            ("2024-05-01T09:35", 12.0, 11.9, 500_000),   # 정규장 → 제외
        ]
    )
    high, volume = premarket_stats(frame)
    assert high == pytest.approx(11.0)
    assert volume == 60_000


def test_premarket_stats_returns_none_without_premarket_trades():
    frame = _intraday([("2024-05-01T10:00", 12.0, 11.9, 100)])
    assert premarket_stats(frame) == (None, 0)


def test_premarket_stats_on_empty_frame():
    assert premarket_stats(pd.DataFrame()) == (None, 0)


def test_session_stats_uses_regular_hours_high():
    frame = _intraday(
        [
            ("2024-05-01T08:00", 99.0, 98.0, 1_000),     # 프리마켓 고가는 무시
            ("2024-05-01T09:35", 12.0, 11.5, 1_000),
            ("2024-05-01T11:00", 13.0, 12.8, 1_000),
        ]
    )
    high, last = session_stats(frame)
    assert high == pytest.approx(13.0)
    assert last == pytest.approx(12.8)


def test_session_stats_before_the_open_falls_back_to_last_price():
    frame = _intraday([("2024-05-01T08:00", 10.0, 9.8, 1_000)])
    high, last = session_stats(frame)
    assert high is None
    assert last == pytest.approx(9.8)


def test_load_csv_normalizes_column_names(tmp_path):
    path = tmp_path / "TEST.csv"
    make_daily(rising(5)).rename(
        columns={"open": "Open", "high": "High", "low": "Low",
                 "close": "Close", "volume": "Volume"}
    ).to_csv(path)
    frame = load_csv(path)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 5


def test_load_csv_missing_file(tmp_path):
    with pytest.raises(DataUnavailable, match="CSV"):
        load_csv(tmp_path / "nope.csv")


def test_read_universe_strips_comments_and_blanks(tmp_path):
    path = tmp_path / "u.txt"
    path.write_text("# 주석\n\naapl\n  msft  # 뒤 주석\n\n", encoding="utf-8")
    assert read_universe(path) == ["AAPL", "MSFT"]


def test_read_universe_missing_file(tmp_path):
    with pytest.raises(DataUnavailable):
        read_universe(tmp_path / "nope.txt")
