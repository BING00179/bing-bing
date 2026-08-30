"""스캐너 B — 전략 스캐너 (Trend Join Long).

목적: 스캐너 A 가 찾은 종목 중 '지금 진입해도 되는 조건'에 맞는 것만
다시 걸러냅니다. 오전 10시(ET) 이후에 실행합니다.

5가지 조건의 정의는 strategy.py 주석을 보세요.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import ScannerBConfig
from .data import (
    NY,
    DataUnavailable,
    fetch_daily,
    fetch_intraday,
    premarket_stats,
    session_stats,
)
from .strategy import ConditionResult, evaluate


def _drop_today(daily: pd.DataFrame, today) -> pd.DataFrame:
    """오늘 봉을 빼고 '어제까지 확정된' 일봉만 남깁니다."""
    return daily[daily.index.date < today]


def scan_ticker(ticker: str, cfg: ScannerBConfig) -> ConditionResult:
    """한 종목의 5조건 판정 결과를 돌려줍니다(통과 여부와 무관)."""
    intraday = fetch_intraday(ticker, days=2)
    today = intraday.index[-1].date()

    daily = fetch_daily(ticker, period="2y")
    history = _drop_today(daily, today)
    if history.empty:
        raise DataUnavailable(f"{ticker}: 전일까지의 일봉이 없습니다.")

    premarket_high, _ = premarket_stats(intraday)
    today_high, last_price = session_stats(intraday)
    if last_price is None:
        raise DataUnavailable(f"{ticker}: 현재가를 구하지 못했습니다.")
    if today_high is None:
        today_high = last_price       # 아직 정규장 시작 전

    return evaluate(
        ticker=ticker,
        daily=history,
        price=last_price,
        today_high=today_high,
        premarket_high=premarket_high,
        cfg=cfg,
    )


def is_after_earliest_hour(cfg: ScannerBConfig, now: datetime | None = None) -> bool:
    """지금이 실행 허용 시각(기본 ET 오전 10시) 이후인지."""
    now = now or datetime.now(NY)
    return now.hour >= cfg.earliest_hour_et


def scan(
    tickers: list[str], cfg: ScannerBConfig
) -> tuple[list[ConditionResult], list[str]]:
    """(조건 통과 종목, 조회 실패 종목) 을 돌려줍니다."""
    passed: list[ConditionResult] = []
    errors: list[str] = []
    for ticker in tickers:
        try:
            result = scan_ticker(ticker, cfg)
        except DataUnavailable as exc:
            errors.append(f"{ticker}: {exc}")
            print(f"  ! {ticker}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패로 전체를 멈추지 않음
            errors.append(f"{ticker}: 예기치 못한 오류 - {exc}")
            print(f"  ! {ticker}: 예기치 못한 오류 - {exc}")
            continue
        if result.passed:
            passed.append(result)
        else:
            print(f"  - {ticker}: 미충족 {', '.join(result.failed_conditions)}")
    return passed, errors


def format_report(
    results: list[ConditionResult],
    when: str,
    errors: list[str] | None = None,
    scanned: int = 0,
) -> str:
    errors = errors or []
    header = f"[전략 스캐너 · Trend Join Long] {when}"

    if errors and scanned and len(errors) >= scanned:
        return (
            f"{header}\n⚠️ {scanned}종목 전부 조회에 실패했습니다. 스캔 결과가 아닙니다.\n"
            f"첫 오류: {errors[0]}"
        )

    if not results:
        line = f"{header}\n매수 신호 종목이 없습니다."
        return line + (f"\n(조회 실패 {len(errors)}종목)" if errors else "")

    lines = [header, f"매수 신호 {len(results)}종목", ""]
    for r in results:
        lines.append(
            f"{r.ticker:<6} ${r.price:>8.2f}  "
            f"전일고가 ${r.prev_high:.2f} / 200MA ${r.sma_slow:.2f}"
        )
    if errors:
        lines.append("")
        lines.append(f"(조회 실패 {len(errors)}종목)")
    lines.append("")
    lines.append("※ 신호일 뿐 매매 권유가 아닙니다. 최종 판단은 본인 기준으로.")
    return "\n".join(lines)
