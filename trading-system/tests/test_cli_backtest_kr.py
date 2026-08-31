"""backtest-kr 의 --market-filter 가 실제로 동작하는가.

옵션이 만들어져 있는데 아무 일도 하지 않던 적이 있습니다. 파일
이름만 바뀌고 계산은 그대로였는데, 1~2시간 돌린 뒤에야 알았습니다.
'옵션이 존재하는가' 가 아니라 '결과가 실제로 달라지는가' 를 봅니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import cli


@pytest.fixture
def fake_market(monkeypatch, tmp_path):
    """지수와 종목 시세를 가짜로 바꿔 네트워크 없이 돌립니다."""
    days = 600
    dates = pd.bdate_range("2023-01-02", periods=days)

    # 앞 400일 상승 → 뒤 200일 폭락. 뒤쪽은 시장 필터가 막아야 합니다.
    index_close = np.concatenate([np.linspace(2000, 3200, 400),
                                  np.linspace(3200, 1900, 200)])
    index = pd.DataFrame({"close": index_close}, index=dates)

    rng = np.random.default_rng(11)
    close = 50_000 * np.exp(np.cumsum(rng.normal(0.001, 0.02, days)))
    opens = np.concatenate([[close[0]], close[:-1]])
    daily = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(close * 1.005, opens),
            "low": np.minimum(close * 0.99, opens),
            "close": close,
            "volume": np.full(days, 500_000.0),
        },
        index=dates,
    )

    universe = tmp_path / "u.txt"
    universe.write_text("005930 삼성전자\n", encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_index", lambda code: index)
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=3.0: daily)
    monkeypatch.setattr(cli, "_output_dir", lambda cfg: tmp_path)
    return universe


def _run(universe, *, market_filter: bool) -> pd.DataFrame:
    argv = ["backtest-kr", "--universe", str(universe)]
    if market_filter:
        argv.append("--market-filter")
    assert cli.main(argv) == 0

    suffix = "_filtered" if market_filter else ""
    return pd.read_csv(universe.parent / f"kr_backtest_trades{suffix}.csv")


def test_filter_changes_the_result(fake_market, capsys):
    """켰을 때와 껐을 때 매매 건수가 달라야 합니다."""
    off = _run(fake_market, market_filter=False)
    on = _run(fake_market, market_filter=True)

    assert len(off) > 0, "필터 없이는 매매가 있어야 합니다"
    assert len(on) < len(off), (
        f"필터를 켰는데 매매가 줄지 않았습니다 (끔 {len(off)}건, 켬 {len(on)}건). "
        "옵션이 계산에 반영되지 않은 것입니다."
    )


def test_filter_state_is_announced_at_start(fake_market, capsys):
    """1~2시간 돌린 뒤가 아니라 시작할 때 알 수 있어야 합니다."""
    _run(fake_market, market_filter=True)
    assert "시장 필터 켬" in capsys.readouterr().out

    _run(fake_market, market_filter=False)
    out = capsys.readouterr().out
    assert "시장 필터 꺼짐" in out
    assert "--market-filter" in out, "켜는 방법을 알려줘야 합니다"


def test_summary_records_the_filter_state(fake_market, capsys):
    _run(fake_market, market_filter=True)
    assert "시장 필터: 켬" in capsys.readouterr().out


def test_saved_file_name_matches_the_announced_path(fake_market, capsys):
    """안내한 경로와 실제 저장 경로가 같아야 합니다."""
    _run(fake_market, market_filter=True)
    out = capsys.readouterr().out
    assert "kr_backtest_trades_filtered.csv" in out


def test_no_trades_are_taken_during_the_blocked_period(fake_market):
    """막힌 구간에는 진입이 없어야 합니다."""
    on = _run(fake_market, market_filter=True)
    if on.empty:
        pytest.skip("이 합성 데이터에서는 신호가 없습니다")
    # 폭락 구간(뒤 200일)의 마지막 날짜대에는 진입이 없어야 합니다.
    entries = pd.to_datetime(on["entry_date"])
    assert entries.max() < pd.Timestamp("2025-06-01"), (
        "폭락 구간에서 진입이 발생했습니다"
    )


@pytest.fixture
def many_stocks(monkeypatch, tmp_path):
    """여러 종목이 같은 날 신호를 내는 상황. 점수 순위를 확인합니다."""
    days = 500
    dates = pd.bdate_range("2023-01-02", periods=days)
    index = pd.DataFrame({"close": np.linspace(2000, 3400, days)}, index=dates)

    rng = np.random.default_rng(3)
    frames = {}
    for i in range(12):
        close = (10_000 + i * 5_000) * np.exp(np.cumsum(rng.normal(0.0012, 0.018, days)))
        opens = np.concatenate([[close[0]], close[:-1]])
        frames[f"{i:06d}"] = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(close * 1.004, opens),
                "low": np.minimum(close * 0.99, opens),
                "close": close,
                "volume": np.full(days, 100_000.0 * (i + 1)),
            },
            index=dates,
        )

    universe = tmp_path / "many.txt"
    universe.write_text("\n".join(frames), encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_index", lambda code: index)
    monkeypatch.setattr(cli, "fetch_daily_kr", lambda code, years=3.0: frames[code])
    monkeypatch.setattr(cli, "_output_dir", lambda cfg: tmp_path)
    return universe


def _run_top(universe, top_n: int) -> pd.DataFrame:
    argv = ["backtest-kr", "--universe", str(universe)]
    suffix = ""
    if top_n:
        argv += ["--top-n", str(top_n)]
        suffix = f"_top{top_n}"
    assert cli.main(argv) == 0
    return pd.read_csv(universe.parent / f"kr_backtest_trades{suffix}.csv")


def test_top_n_reduces_trades(many_stocks):
    """하루 상위 N종목만 사면 매매가 줄어야 합니다."""
    everything = _run_top(many_stocks, 0)
    top2 = _run_top(many_stocks, 2)

    assert len(everything) > 0, "제한 없이는 매매가 있어야 합니다"
    assert len(top2) < len(everything), (
        f"상위 2종목 제한인데 매매가 줄지 않았습니다 "
        f"(전체 {len(everything)}건, 상위2 {len(top2)}건)"
    )


def test_top_n_never_exceeds_the_limit_on_any_day(many_stocks):
    """같은 날 진입이 N종목을 넘으면 안 됩니다."""
    top2 = _run_top(many_stocks, 2)
    if top2.empty:
        pytest.skip("이 데이터에서는 매매가 없습니다")
    per_day = top2.groupby("entry_date")["ticker"].nunique()
    assert per_day.max() <= 2, f"하루 최대 {per_day.max()}종목이 진입했습니다"


def test_top_n_state_is_announced(many_stocks, capsys):
    _run_top(many_stocks, 3)
    out = capsys.readouterr().out
    assert "점수 상위 켬" in out
    assert "점수 상위 3종목만" in out
    assert "점수 상위: 하루 3종목" in out


def test_min_score_can_drop_everything(many_stocks, capsys):
    """도달 불가능한 점수를 걸면 매매가 없어야 합니다."""
    assert cli.main([
        "backtest-kr", "--universe", str(many_stocks),
        "--top-n", "3", "--min-score", "999",
    ]) == 0
    frame = pd.read_csv(many_stocks.parent / "kr_backtest_trades_top3.csv")
    assert frame.empty
