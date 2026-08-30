"""내일 관찰 후보 — 돌파 직전 종목을 찾는가."""

import numpy as np

from src.watchlist import WatchConfig, evaluate, format_report, rank
from tests.helpers import make_daily

CFG = WatchConfig(sma_slow=60, sma_mid=30, sma_fast=10, min_turnover=0.0, min_price=0.0)


def uptrend(n=120, start=10_000.0, step=40.0, seed=2):
    rng = np.random.default_rng(seed)
    return start + np.arange(n, dtype=float) * step + rng.normal(0, abs(step), n)


def frame(closes, *, highs=None, lows=None, opens=None, volume=1e6):
    df = make_daily(closes, highs=highs, lows=lows, opens=opens)
    df["volume"] = volume
    return df


def test_stock_just_below_recent_high_is_a_candidate():
    closes = list(uptrend())
    closes[-1] = max(closes[-21:-1]) * 0.99      # 최근 고가 1% 아래
    df = frame(closes)
    c = evaluate("005930", df, CFG, "테스트")
    assert c is not None
    assert 0 <= c.to_breakout_pct <= CFG.near_breakout_pct
    assert c.reasons


def test_stock_far_from_the_high_is_rejected():
    closes = list(uptrend())
    closes[-1] = max(closes[-21:-1]) * 0.80      # 20% 아래
    assert evaluate("005930", frame(closes), CFG) is None


def test_downtrend_is_rejected():
    closes = list(uptrend(start=30_000.0, step=-150.0))
    assert evaluate("005930", frame(closes), CFG) is None


def test_weak_close_is_rejected():
    """고가에서 크게 밀려 마감한 종목은 뺍니다."""
    closes = list(uptrend())
    closes[-1] = max(closes[-21:-1]) * 0.99
    highs = list(closes)
    highs[-1] = closes[-1] * 1.08                # 장중 8% 위까지 갔다가 밀림
    assert evaluate("005930", frame(closes, highs=highs), CFG) is None


def test_low_turnover_is_rejected():
    closes = list(uptrend())
    closes[-1] = max(closes[-21:-1]) * 0.99
    cfg = WatchConfig(sma_slow=60, sma_mid=30, sma_fast=10,
                      min_turnover=1e12, min_price=0.0)
    assert evaluate("005930", frame(closes), cfg) is None


def test_penny_stock_is_rejected():
    closes = list(uptrend(start=100.0, step=0.4))
    closes[-1] = max(closes[-21:-1]) * 0.99
    cfg = WatchConfig(sma_slow=60, sma_mid=30, sma_fast=10,
                      min_turnover=0.0, min_price=1_000.0)
    assert evaluate("005930", frame(closes), cfg) is None


def test_recent_high_excludes_today_itself():
    """오늘 스스로 만든 고가와 비교하면 항상 '돌파 임박' 이 됩니다."""
    closes = list(uptrend())
    closes[-1] = max(closes[:-1]) * 1.20         # 오늘 크게 돌파
    c = evaluate("005930", frame(closes), CFG)
    assert c is not None
    assert c.to_breakout_pct == 0.0              # 이미 넘어섰음
    assert c.recent_high < c.close               # 어제까지의 고가와 비교


def test_not_enough_history_returns_none():
    assert evaluate("005930", frame(list(uptrend(n=30))), CFG) is None


def test_rank_puts_the_closest_to_breakout_first():
    closes = list(uptrend())
    made = []
    for pct, code in ((0.995, "AAA"), (0.985, "BBB"), (0.999, "CCC")):
        c = list(closes)
        c[-1] = max(c[-21:-1]) * pct
        cand = evaluate(code, frame(c), CFG)
        if cand is not None:      # 종가를 낮추면 정배열이 깨질 수 있습니다
            made.append(cand)

    assert len(made) >= 2, "정렬을 확인할 후보가 모자랍니다"
    ordered = rank(made, CFG)
    gaps = [c.to_breakout_pct for c in ordered]
    assert gaps == sorted(gaps), f"돌파 임박 순이 아닙니다: {gaps}"


def test_report_says_it_is_not_a_buy_signal():
    closes = list(uptrend())
    closes[-1] = max(closes[-21:-1]) * 0.99
    c = evaluate("005930", frame(closes), CFG, "테스트")
    text = format_report([c], "2026-08-31 15:30 KST")
    assert "관찰 후보일 뿐 매수 신호가 아닙니다" in text
    assert "돌파 임박 순" in text


def test_empty_report_mentions_how_many_were_checked():
    text = format_report([], "2026-08-31 15:30 KST", scanned=1823)
    assert "1823종목 확인" in text
