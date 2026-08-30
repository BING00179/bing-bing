"""이상 징후 점검 — 평소와 다른 점을 잡아내는가."""

from src.anomaly import ALERT, OK, WATCH, AnomalyConfig, check

CFG = AnomalyConfig()
NORMAL = dict(
    closes=[100.0 + i * 0.3 for i in range(60)],
    volumes=[100_000.0] * 20,
    today_volume=180_000.0,
    turnover=2.0e10,
    market_cap=2.0e12,
    price=118.0,
    sma_slow=95.0,
)


def test_ordinary_stock_is_normal():
    report = check(**NORMAL, cfg=CFG)
    assert report.level == OK
    assert report.alerts == []


def test_volume_spike_is_flagged():
    report = check(**{**NORMAL, "today_volume": 100_000 * 25}, cfg=CFG)
    flag = next(f for f in report.flags if f.label == "거래량 급증")
    assert flag.level == ALERT
    assert "배" in flag.value
    assert "평균" in flag.basis


def test_moderate_volume_increase_is_only_a_watch():
    report = check(**{**NORMAL, "today_volume": 100_000 * 10}, cfg=CFG)
    flag = next(f for f in report.flags if f.label == "거래량 급증")
    assert flag.level == WATCH


def test_high_turnover_relative_to_market_cap_is_flagged():
    """시총 1100억에 하루 480억이 돌면 경고."""
    report = check(**{**NORMAL, "turnover": 4.8e10, "market_cap": 1.1e11}, cfg=CFG)
    flag = next(f for f in report.flags if f.label == "거래대금 회전율")
    assert flag.level == ALERT


def test_sharp_run_up_is_flagged():
    closes = [100.0] * 55 + [102.0, 108.0, 118.0, 132.0, 150.0]
    report = check(**{**NORMAL, "closes": closes, "price": 150.0}, cfg=CFG)
    flag = next(f for f in report.flags if "누적 상승" in f.label)
    assert flag.level == ALERT


def test_extension_from_long_ma_is_flagged():
    report = check(**{**NORMAL, "price": 300.0, "sma_slow": 95.0}, cfg=CFG)
    flag = next(f for f in report.flags if f.label == "200일선 이격도")
    assert flag.level == ALERT


def test_every_flag_explains_its_basis():
    report = check(**{**NORMAL, "today_volume": 3_000_000.0}, cfg=CFG)
    for flag in report.flags:
        assert flag.basis, f"{flag.label} 에 판정 근거가 없습니다"
        assert flag.value


def test_missing_market_cap_skips_that_check_without_crashing():
    report = check(**{**NORMAL, "market_cap": 0.0}, cfg=CFG)
    assert all(f.label != "거래대금 회전율" for f in report.flags)
    assert report.level in {OK, WATCH, ALERT}


def test_no_history_does_not_crash():
    report = check(closes=[], volumes=[], today_volume=0.0, turnover=0.0,
                   market_cap=0.0, price=0.0, sma_slow=0.0, cfg=CFG)
    assert report.level == OK


def test_alert_outranks_watch_in_the_overall_level():
    report = check(**{**NORMAL, "today_volume": 100_000 * 10, "price": 300.0}, cfg=CFG)
    assert report.level == ALERT
