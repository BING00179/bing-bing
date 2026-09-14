"""_frames_for 가 시세 실패를 조용히 삼키지 않는가.

2026-09-01 에 fetch 호출에 pause= 가 붙었는데 시험의 가짜 fetch 가 그 인자를
안 받아 TypeError 가 났습니다. _frames_for 는 모든 예외를 `continue` 로
넘겨서 화면에는 "시세 확보 0종목" 만 찍혔고, CI 는 2주 동안 이유 없이
빨간 채였습니다. 실패했으면 몇 종목이 왜 실패했는지 보여야 합니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import cli
from src.data import DataUnavailable


def _fake_daily(days: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=days)
    close = np.linspace(10_000, 12_000, days)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": np.full(days, 1_000.0)},
        index=dates,
    )


def test_programming_error_is_reported_not_swallowed(monkeypatch, capsys):
    """TypeError 같은 코드 오류는 종목 수와 첫 오류 내용이 화면에 남아야 합니다."""
    def broken(code, years=3.0, pause=0.0):
        raise TypeError("got an unexpected keyword argument 'pause'")

    monkeypatch.setattr(cli, "fetch_daily_kr", broken)
    frames = cli._frames_for(["000001", "000002", "000003"], years=3.0,
                             min_rows=10, cache_dir=None)
    out = capsys.readouterr().out

    assert frames == {}
    assert "실패 3종목" in out, out
    assert "TypeError" in out and "pause" in out, (
        "무엇이 잘못됐는지 첫 오류를 보여줘야 합니다\n" + out)


def test_data_unavailable_is_counted_too(monkeypatch, capsys):
    """조회 실패(DataUnavailable)도 몇 종목인지 세어 보여줍니다."""
    good = _fake_daily()

    def flaky(code, years=3.0, pause=0.0):
        if code == "000002":
            raise DataUnavailable("000002: 조회 실패")
        return good

    monkeypatch.setattr(cli, "fetch_daily_kr", flaky)
    frames = cli._frames_for(["000001", "000002", "000003"], years=3.0,
                             min_rows=10, cache_dir=None)
    out = capsys.readouterr().out

    assert set(frames) == {"000001", "000003"}
    assert "실패 1종목" in out, out
    assert "조회 실패" in out, out


def test_nothing_printed_about_failures_when_all_succeed(monkeypatch, capsys):
    good = _fake_daily()
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=3.0, pause=0.0: good)
    cli._frames_for(["000001", "000002"], years=3.0, min_rows=10, cache_dir=None)
    assert "실패" not in capsys.readouterr().out
