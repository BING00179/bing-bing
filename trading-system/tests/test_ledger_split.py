"""ledger-split — avoid-kr 에서 버틴 조건 3개를 **앞으로의 장부**로 다시 본다.

2026-09-15 사장님 결정: 조건을 장부 규칙에 넣지 않는다(LEDGER_VERSION 그대로).
대신 장부에 이미 있는 volume_mult·turnover·gap_pct 로 갈라 보는 시험을
숫자를 보기 전에 적어 둔다. 여기의 문턱·합격선이 그 '미리 적어 둔 것' 이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import cli
from src import ledger_split as ls
from src import livetest as lt
from src.avoid import ABOVE


def test_pre_registered_rules_are_the_three_from_avoid_kr():
    rules = ls.pre_registered_rules()
    assert [(r.column, r.op, r.threshold) for r in rules] == [
        ("volume_mult", ABOVE, 12.0),
        ("turnover", ABOVE, 1.44e10),
        ("gap_pct", ABOVE, 1.2),
    ]


def test_pass_bar_is_corrected_for_three_rules():
    assert ls.BAR > 2.0                      # 하나만 볼 때(2.0)보다 높아야 합니다
    assert ls.MIN_EXCLUDED == 30             # 7번의 표본 기준과 같아야 합니다


def _table(n_excluded: int, n_kept: int, excluded_excess: float,
           kept_excess: float, seed: int = 0) -> pd.DataFrame:
    """제외될 쪽 n_excluded 줄(volume_mult 20), 남을 쪽 n_kept 줄(volume_mult 5)."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_excluded):
        rows.append({"volume_mult": 20.0, "turnover": 1e9, "gap_pct": 0.0,
                     "stock_pct": excluded_excess + rng.normal(0, 1.0), "index_pct": 0.0})
    for i in range(n_kept):
        rows.append({"volume_mult": 5.0, "turnover": 1e9, "gap_pct": 0.0,
                     "stock_pct": kept_excess + rng.normal(0, 1.0), "index_pct": 0.0})
    return pd.DataFrame(rows)


def test_not_enough_excluded_samples_means_unknown():
    rule = ls.pre_registered_rules()[0]
    result = ls.evaluate(_table(10, 60, -5.0, +2.0), rule)
    verdict = ls.judge(result)
    assert verdict.status == ls.UNKNOWN
    assert "10" in verdict.reason and "30" in verdict.reason


def test_clearly_bad_excluded_side_supports_the_rule():
    rule = ls.pre_registered_rules()[0]
    result = ls.evaluate(_table(40, 60, -5.0, +2.0), rule)
    verdict = ls.judge(result)
    assert verdict.status == ls.SUPPORTED, verdict


def test_excluded_side_not_bad_enough_fails():
    rule = ls.pre_registered_rules()[0]
    result = ls.evaluate(_table(40, 60, -0.2, +0.2), rule)   # t 가 통과선에 못 미침
    assert ls.judge(result).status == ls.FAILED


def test_throwing_away_most_signals_fails_even_if_bad():
    rule = ls.pre_registered_rules()[0]
    result = ls.evaluate(_table(80, 20, -5.0, +2.0), rule)   # 남는 비율 20%
    assert ls.judge(result).status == ls.FAILED


def test_rule_columns_are_attached_from_the_ledger():
    """채점 결과(Scored)에는 volume_mult·turnover 가 없어 장부에서 붙여야 합니다."""
    scored = pd.DataFrame([
        {"signal_date": "2026-09-01", "code": "000001", "stock_pct": 3.0,
         "index_pct": 1.0, "gap_pct": 0.5},
        {"signal_date": "2026-09-01", "code": "000002", "stock_pct": -3.0,
         "index_pct": 1.0, "gap_pct": 2.0},
    ])
    ledger = pd.DataFrame([
        {"signal_date": "2026-09-01", "code": "000001", "volume_mult": 15.0,
         "turnover": 2e10, "status": lt.STATUS_OK, "kind": lt.KIND_RECORD},
        {"signal_date": "2026-09-01", "code": "000002", "volume_mult": 4.0,
         "turnover": 8e8, "status": lt.STATUS_OK, "kind": lt.KIND_RECORD},
    ])
    table = ls.attach(scored, ledger)
    assert list(table["volume_mult"]) == [15.0, 4.0]
    assert list(table["turnover"]) == [2e10, 8e8]
    assert list(table["gap_pct"]) == [0.5, 2.0]            # 채점 쪽 값을 그대로


def test_report_states_the_bar_before_numbers():
    rule = ls.pre_registered_rules()[0]
    result = ls.evaluate(_table(10, 60, -5.0, +2.0), rule)
    out = ls.report([(rule, result, ls.judge(result))], horizon=20)
    assert "미리 적어 둔" in out
    assert f"{ls.BAR:.2f}" in out
    assert "아직 모릅니다" in out


def test_cli_with_empty_ledger(monkeypatch, capsys):
    monkeypatch.setattr(lt, "load", lambda path: pd.DataFrame())
    assert cli.main(["ledger-split"]) == 0
    assert "비어 있습니다" in capsys.readouterr().out


def test_cli_runs_end_to_end_on_a_small_ledger(monkeypatch, capsys, tmp_path):
    """장부 3건 → 시세로 채점 → 세 조건으로 갈라 보고 '아직 모릅니다' 가 나와야 합니다."""
    dates = pd.bdate_range("2026-08-03", periods=40)
    daily = pd.DataFrame({"open": 1000.0, "high": 1010.0, "low": 990.0,
                          "close": np.linspace(1000, 1100, 40), "volume": 1e5},
                         index=dates)
    index = pd.DataFrame({"close": np.linspace(800, 810, 40)}, index=dates)
    entry = str(dates[3].date())
    ledger = pd.DataFrame([
        lt._base_row("2026-08-05", c, f"종목{c}", 1000.0, "breakout", "시험") for c in ("000001", "000002", "000003")
    ])
    ledger["entry_date"] = entry
    ledger["entry_open"] = 1000.0
    ledger["bought"] = "예"
    ledger["gap_pct"] = [0.5, 2.0, 0.1]
    ledger["volume_mult"] = [3.0, 15.0, 4.0]
    ledger["turnover"] = [1e9, 2e10, 5e8]

    monkeypatch.setattr(lt, "load", lambda path: ledger)
    monkeypatch.setattr(cli, "_frames_for",
                        lambda codes, years, min_rows, cache_dir, refresh=False, pause=None:
                        {c: daily for c in codes})
    monkeypatch.setattr(cli, "fetch_index", lambda code, years=3.0: index)
    monkeypatch.setattr(cli, "_output_dir", lambda cfg: tmp_path)

    assert cli.main(["ledger-split", "--horizon", "20",
                     "--today", str(dates[-1].date())]) == 0
    out = capsys.readouterr().out
    assert "채점 3건" in out
    assert out.count("아직 모릅니다") == 3
    assert "LEDGER_VERSION" in out            # 규칙을 바꾸지 않았다는 말이 있어야
