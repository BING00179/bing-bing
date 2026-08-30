"""신호 점수 — 좋은 것 몇 개만 고르기."""

import pytest

from src.config import RankingConfig
from src.ranking import score
from src.scanner_kr import SignalKr, format_report_b, rank

CFG = RankingConfig()


def sig(code, name, price, gap, turnover, sma, high):
    return SignalKr(
        code=code, name=name, price=price, prev_high=price * 0.98,
        prev_close=price * 0.95, sma_slow=sma, open_price=price * 0.99,
        today_high=high, failed=[], gap_pct=gap, turnover=turnover,
    )


STRONG = dict(gap_pct=12.0, turnover=8e10, price=52_000, sma_slow=40_000, today_high=52_000)
WEAK = dict(gap_pct=5.2, turnover=1.2e9, price=9_800, sma_slow=9_700, today_high=10_400)


def test_every_part_is_bounded_zero_to_hundred():
    s = score(**STRONG, cfg=CFG)
    for part in (s.total, s.gap, s.turnover, s.trend, s.near_high):
        assert 0.0 <= part <= 100.0


def test_strong_signal_scores_higher_than_weak():
    assert score(**STRONG, cfg=CFG).total > score(**WEAK, cfg=CFG).total


def test_bigger_gap_scores_higher():
    small = score(**{**STRONG, "gap_pct": 3.0}, cfg=CFG)
    big = score(**{**STRONG, "gap_pct": 14.0}, cfg=CFG)
    assert big.gap > small.gap


def test_gap_above_full_mark_is_capped_not_unbounded():
    """갭 50% 한 종목이 점수를 독식하면 안 됩니다."""
    at_mark = score(**{**STRONG, "gap_pct": CFG.gap_full_mark_pct}, cfg=CFG)
    way_over = score(**{**STRONG, "gap_pct": 50.0}, cfg=CFG)
    assert at_mark.gap == pytest.approx(100.0)
    assert way_over.gap == pytest.approx(100.0)


def test_turnover_uses_log_scale():
    """거래대금은 자릿수로 봅니다. 10억과 100억 차이가 100억과 1000억 차이와 비슷해야 합니다."""
    a = score(**{**STRONG, "turnover": 1e9}, cfg=CFG).turnover
    b = score(**{**STRONG, "turnover": 1e10}, cfg=CFG).turnover
    c = score(**{**STRONG, "turnover": 1e11}, cfg=CFG).turnover
    assert a < b < c
    assert (b - a) == pytest.approx(c - b, abs=1.0)


def test_overheated_trend_is_penalised():
    """200일선 위 적당히가 만점이고, 너무 멀면 감점입니다."""
    healthy = score(**{**STRONG, "price": 52_000, "sma_slow": 40_000}, cfg=CFG)
    overheated = score(**{**STRONG, "price": 120_000, "sma_slow": 40_000,
                          "today_high": 120_000}, cfg=CFG)
    assert healthy.trend > overheated.trend


def test_pullback_from_the_session_high_loses_points():
    at_high = score(**{**STRONG, "price": 52_000, "today_high": 52_000}, cfg=CFG)
    pulled = score(**{**STRONG, "price": 52_000, "today_high": 56_000}, cfg=CFG)
    assert at_high.near_high > pulled.near_high


def test_zero_turnover_does_not_crash():
    assert score(**{**STRONG, "turnover": 0.0}, cfg=CFG).turnover == 0.0


def test_rank_sorts_by_score_without_dropping_anyone():
    rows = [
        sig("000001", "약", 9_800, 5.2, 1.2e9, 9_700, 10_400),
        sig("000002", "강", 52_000, 12.0, 8e10, 40_000, 52_000),
        sig("000003", "중", 30_000, 7.0, 2e10, 26_000, 30_500),
    ]
    ranked = rank(rows, CFG)
    assert len(ranked) == 3                     # 아무도 빠지지 않습니다
    assert [r.code for r in ranked] == ["000002", "000003", "000001"]
    assert ranked[0].score.total > ranked[-1].score.total


def test_min_score_filters_out_the_weakest():
    rows = [
        sig("000001", "약", 9_800, 5.2, 1.2e9, 9_700, 10_400),
        sig("000002", "강", 52_000, 12.0, 8e10, 40_000, 52_000),
    ]
    ranked = rank(rows, RankingConfig(min_score=70.0))
    assert [r.code for r in ranked] == ["000002"]


def test_ranking_can_be_turned_off():
    rows = [sig("000001", "가", 9_800, 5.2, 1.2e9, 9_700, 10_400)]
    ranked = rank(rows, RankingConfig(enabled=False))
    assert ranked[0].score is None


def test_report_separates_recommended_from_the_rest():
    rows = [
        sig("000001", "일", 52_000, 12.0, 8e10, 40_000, 52_000),
        sig("000002", "이", 30_000, 9.0, 4e10, 25_000, 30_000),
        sig("000003", "삼", 20_000, 7.0, 2e10, 17_000, 20_100),
        sig("000004", "사", 9_800, 5.2, 1.2e9, 9_700, 10_400),
    ]
    text = format_report_b(rank(rows, CFG), "2026-08-31 10:30 KST", top_n=3)
    assert "⭐ 추천 상위 3종목" in text
    assert "나머지 조건 통과 1종목" in text
    for row in rows:                            # 전부 보여줘야 합니다
        assert row.code in text
    assert "점수가 높다고 더 오른다는 근거는 없습니다" in text


def test_report_without_ranking_still_lists_everyone():
    rows = [sig("000001", "가", 52_000, 12.0, 8e10, 40_000, 52_000)]
    text = format_report_b(rank(rows, RankingConfig(enabled=False)),
                           "2026-08-31 10:30 KST", top_n=0)
    assert "000001" in text
    assert "⭐" not in text
