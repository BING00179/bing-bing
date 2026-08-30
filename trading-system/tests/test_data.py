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


# ── 국내 종목코드 ──


def test_korean_code_may_contain_letters():
    """우선주·신주인수권 등은 코드에 알파벳이 들어갑니다.

    숫자만 허용하면 코스닥 전 종목을 훑다가 이런 종목을 만나는
    순간 전체가 멈춥니다. 실제로 '0009K0' 에서 멈췄습니다.
    """
    from src.data_kr import normalize_code

    assert normalize_code("0009K0") == "0009K0"
    assert normalize_code("00088K") == "00088K"
    assert normalize_code("005930") == "005930"


def test_short_numeric_code_gets_leading_zeros():
    """엑셀에서 옮기면 앞의 0 이 잘립니다."""
    from src.data_kr import normalize_code

    assert normalize_code("5930") == "005930"


def test_clearly_invalid_code_is_rejected():
    from src.data_kr import normalize_code

    for bad in ("삼성전자", "12345678", ""):
        with pytest.raises(DataUnavailable):
            normalize_code(bad)


def test_universe_file_skips_bad_lines_instead_of_failing(tmp_path, capsys):
    """한 줄이 이상하다고 1800종목 전체를 포기하지 않습니다."""
    from src.data_kr import read_universe_kr

    path = tmp_path / "u.txt"
    path.write_text(
        "005930 삼성전자\n0009K0 우선주\n삼성전자\n# 주석\n000660 SK하이닉스\n",
        encoding="utf-8",
    )
    codes = read_universe_kr(path)
    assert codes == ["005930", "0009K0", "000660"]
    assert "건너뛴 줄 1개" in capsys.readouterr().out


def test_universe_file_with_no_valid_codes_raises(tmp_path):
    from src.data_kr import read_universe_kr

    path = tmp_path / "u.txt"
    path.write_text("# 주석만\n삼성전자\n", encoding="utf-8")
    with pytest.raises(DataUnavailable, match="읽을 수 있는 종목코드가 없습니다"):
        read_universe_kr(path)
