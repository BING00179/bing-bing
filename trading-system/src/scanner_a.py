"""스캐너 A — 프리마켓 갭 스캐너.

목적: 장 시작 전에 크게 움직이는 종목을 자동으로 찾아냅니다.

조건(기본값, config.json 에서 변경 가능):
  * 전일 종가 대비 5% 이상 상승
  * 주가 $3 이상
  * 프리마켓 누적 거래량 50,000주 이상

출력: 티커 / 현재가 / 갭 비율(%) / 상승 이유(뉴스 한 줄)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from .config import ScannerAConfig
from .data import DataUnavailable, fetch_daily, fetch_intraday, premarket_stats
from .news import headline


@dataclass
class GapHit:
    ticker: str
    price: float
    gap_pct: float
    premarket_volume: int
    prev_close: float
    reason: str

    def as_line(self) -> str:
        reason = self.reason or "(뉴스 없음)"
        return (
            f"{self.ticker:<6} ${self.price:>8.2f}  "
            f"{self.gap_pct:>+6.2f}%  vol {self.premarket_volume:>9,}  {reason}"
        )


def scan_ticker(ticker: str, cfg: ScannerAConfig, with_news: bool = True) -> GapHit | None:
    """한 종목이 조건을 만족하는지 확인합니다. 아니면 None."""
    daily = fetch_daily(ticker, period="1mo")
    if len(daily) < 2:
        raise DataUnavailable(f"{ticker}: 전일 종가를 구할 일봉이 부족합니다.")

    intraday = fetch_intraday(ticker, days=2)
    pre_high, pre_volume = premarket_stats(intraday)
    if pre_high is None:
        return None                       # 프리마켓 거래 자체가 없음

    price = float(intraday["close"].iloc[-1])
    prev_close = float(daily["close"].iloc[-1])
    # 마지막 일봉이 오늘 것이면 그 전날 종가를 써야 합니다.
    if daily.index[-1].date() == intraday.index[-1].date():
        prev_close = float(daily["close"].iloc[-2])

    gap = (price - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0

    if gap < cfg.min_gap_pct:
        return None
    if price < cfg.min_price:
        return None
    if pre_volume < cfg.min_premarket_volume:
        return None

    return GapHit(
        ticker=ticker,
        price=round(price, 2),
        gap_pct=round(gap, 2),
        premarket_volume=pre_volume,
        prev_close=round(prev_close, 2),
        reason=headline(ticker) if with_news else "",
    )


def scan(
    tickers: list[str], cfg: ScannerAConfig, with_news: bool = True
) -> tuple[list[GapHit], list[str]]:
    """티커 목록 전체를 훑습니다.

    (조건 통과 종목, 조회 실패 종목) 을 함께 돌려줍니다. 실패를 따로
    돌려주는 이유는 '전부 조회 실패'와 '조회는 됐지만 통과 0건'이
    완전히 다른 상황이기 때문입니다.
    """
    hits: list[GapHit] = []
    errors: list[str] = []
    for ticker in tickers:
        try:
            hit = scan_ticker(ticker, cfg, with_news=with_news)
        except DataUnavailable as exc:
            errors.append(f"{ticker}: {exc}")
            print(f"  ! {ticker}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패로 전체를 멈추지 않음
            errors.append(f"{ticker}: 예기치 못한 오류 - {exc}")
            print(f"  ! {ticker}: 예기치 못한 오류 - {exc}")
            continue
        if hit:
            hits.append(hit)
    hits.sort(key=lambda h: h.gap_pct, reverse=True)
    return hits[: cfg.max_results], errors


def to_frame(hits: list[GapHit]) -> pd.DataFrame:
    if not hits:
        return pd.DataFrame(
            columns=["ticker", "price", "gap_pct", "premarket_volume", "prev_close", "reason"]
        )
    return pd.DataFrame([asdict(h) for h in hits])


def format_report(
    hits: list[GapHit], when: str, errors: list[str] | None = None, scanned: int = 0
) -> str:
    errors = errors or []
    header = f"[프리마켓 갭 스캐너] {when}"

    if errors and scanned and len(errors) >= scanned:
        return (
            f"{header}\n⚠️ {scanned}종목 전부 조회에 실패했습니다. 스캔 결과가 아닙니다.\n"
            f"첫 오류: {errors[0]}"
        )

    if not hits:
        line = f"{header}\n조건에 맞는 종목이 없습니다."
        return line + (f"\n(조회 실패 {len(errors)}종목)" if errors else "")

    lines = [header, f"조건 통과 {len(hits)}종목", ""]
    lines += [h.as_line() for h in hits]
    if errors:
        lines += ["", f"(조회 실패 {len(errors)}종목)"]
    return "\n".join(lines)
