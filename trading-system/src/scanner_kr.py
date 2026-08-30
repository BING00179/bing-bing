"""국내장 스캐너 A · B.

미국장 버전과 뼈대는 같고, 국내장 구조에 맞춰 두 곳을 바꿨습니다.

1) 갭의 기준
   미국은 프리마켓 체결가로 갭을 잽니다. 국내장은 08:30~09:00 이
   동시호가라 실제 체결이 09:00 에 한 번에 일어나므로, 그때 정해진
   '시가'를 전일 종가와 비교합니다.

2) 유동성 기준
   미국은 거래량(주)으로 걸렀지만, 국내에서는 주가 편차가 커서
   거래량보다 '거래대금(원)'이 실질적인 기준입니다. 1만원짜리
   10만주와 100만원짜리 1천주는 성격이 전혀 다릅니다.

추가로 국내장에만 있는 상한가를 표시합니다. 상한가(+30%)에 붙은
종목은 사실상 매수 체결이 안 되므로 신호로 받아도 소용이 없습니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from .config import ScannerAKrConfig, ScannerBConfig
from .data import DataUnavailable
from .data_kr import fetch_daily, normalize_code, split_today
from .indicators import sma, trend_aligned
from .markets import KR


@dataclass
class GapHitKr:
    code: str
    name: str
    price: float
    open_price: float
    gap_pct: float           # 전일 종가 대비 시가 상승률
    change_pct: float        # 전일 종가 대비 현재가 상승률
    turnover: float          # 오늘 거래대금 (원)
    prev_close: float
    at_limit_up: bool        # 상한가 도달 여부

    def as_line(self) -> str:
        billions = self.turnover / 1e8
        flag = "  🔒상한가" if self.at_limit_up else ""
        label = f"{self.code} {self.name}".strip()
        return (
            f"{label:<16} {self.price:>9,.0f}원  "
            f"시가갭 {self.gap_pct:>+6.2f}%  현재 {self.change_pct:>+6.2f}%  "
            f"대금 {billions:>7,.0f}억{flag}"
        )


@dataclass
class SignalKr:
    code: str
    name: str
    price: float
    prev_high: float
    prev_close: float
    sma_slow: float
    open_price: float
    today_high: float
    failed: list[str]

    @property
    def passed(self) -> bool:
        return not self.failed


def _limit_price(prev_close: float) -> float:
    """상한가. 국내장 가격제한폭은 ±30% 입니다."""
    return prev_close * (1.0 + (KR.price_limit_pct or 30.0) / 100.0)


def scan_a_code(
    code: str,
    cfg: ScannerAKrConfig,
    names: dict[str, str] | None = None,
    today: date | None = None,
) -> GapHitKr | None:
    """한 종목이 스캐너 A 조건을 만족하는지. 아니면 None."""
    code = normalize_code(code)
    daily = fetch_daily(code, years=0.5)
    history, current = split_today(daily, today)

    if current is None:
        return None                       # 오늘 봉이 없음 (휴장·거래정지 등)
    if history.empty:
        raise DataUnavailable(f"{code}: 전일 종가를 구할 일봉이 없습니다.")

    prev_close = float(history["close"].iloc[-1])
    if prev_close <= 0:
        return None

    open_price = float(current["open"])
    price = float(current["close"])       # 장중에는 '현재가'
    turnover = float(current["close"] * current["volume"])

    gap = (open_price - prev_close) / prev_close * 100.0
    change = (price - prev_close) / prev_close * 100.0

    if gap < cfg.min_gap_pct:
        return None
    if price < cfg.min_price:
        return None
    if turnover < cfg.min_turnover:
        return None

    # 상한가는 호가에 매물이 없어 사실상 체결이 안 됩니다. 걸러내되
    # 버리지 않고 표시만 하도록 설정으로 고를 수 있게 합니다.
    at_limit = price >= _limit_price(prev_close) * 0.999
    if at_limit and cfg.exclude_limit_up:
        return None

    return GapHitKr(
        code=code,
        name=(names or {}).get(code, ""),
        price=round(price, 1),
        open_price=round(open_price, 1),
        gap_pct=round(gap, 2),
        change_pct=round(change, 2),
        turnover=round(turnover, 0),
        prev_close=round(prev_close, 1),
        at_limit_up=at_limit,
    )


def scan_a(
    codes: list[str],
    cfg: ScannerAKrConfig,
    names: dict[str, str] | None = None,
    today: date | None = None,
) -> tuple[list[GapHitKr], list[str]]:
    """(조건 통과 종목, 조회 실패 종목)."""
    hits: list[GapHitKr] = []
    errors: list[str] = []
    for code in codes:
        try:
            hit = scan_a_code(code, cfg, names, today)
        except DataUnavailable as exc:
            errors.append(f"{code}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패로 전체를 멈추지 않음
            errors.append(f"{code}: 예기치 못한 오류 - {exc}")
            continue
        if hit:
            hits.append(hit)
    hits.sort(key=lambda h: h.gap_pct, reverse=True)
    return hits[: cfg.max_results], errors


def evaluate_kr(
    code: str,
    history: pd.DataFrame,
    price: float,
    today_high: float,
    open_price: float,
    cfg: ScannerBConfig,
    name: str = "",
) -> SignalKr:
    """Trend Join Long 5조건 판정 (국내장판).

    조건 3 만 다릅니다. 미국판의 '프리마켓 고가 돌파' 자리에
    '오늘 시가 위 유지' 가 들어갑니다. 국내장에는 프리마켓 연속
    거래가 없고, 동시호가로 정해진 시가가 장 시작 시점의 기준가이기
    때문입니다.
    """
    if len(history) < cfg.sma_slow:
        raise DataUnavailable(
            f"{code}: {cfg.sma_slow}일 이동평균에 일봉 {cfg.sma_slow}개가 "
            f"필요한데 {len(history)}개뿐입니다."
        )

    tol = 1.0 - cfg.breakout_tolerance_pct / 100.0
    near_high = 1.0 - cfg.close_near_high_pct / 100.0

    prev_high = float(history["high"].iloc[-1])
    prev_close = float(history["close"].iloc[-1])
    sma_slow = float(sma(history["close"], cfg.sma_slow).iloc[-1])
    aligned = bool(
        trend_aligned(history["close"], cfg.sma_fast, cfg.sma_mid, cfg.sma_slow).iloc[-1]
    )

    checks = {
        "1_전날고가돌파": price >= prev_high * tol,
        "2_전날종가>200MA": prev_close > sma_slow,
        "3_시가위유지": price >= open_price * tol,
        "4_오늘고가돌파": price >= today_high * near_high,
        "5_상승추세정렬": aligned,
    }

    return SignalKr(
        code=code,
        name=name,
        price=price,
        prev_high=prev_high,
        prev_close=prev_close,
        sma_slow=sma_slow,
        open_price=open_price,
        today_high=today_high,
        failed=[k for k, ok in checks.items() if not ok],
    )


def scan_b_code(
    code: str,
    cfg: ScannerBConfig,
    names: dict[str, str] | None = None,
    today: date | None = None,
) -> SignalKr:
    code = normalize_code(code)
    daily = fetch_daily(code, years=2.0)
    history, current = split_today(daily, today)
    if current is None:
        raise DataUnavailable(f"{code}: 오늘 거래가 없습니다.")
    if history.empty:
        raise DataUnavailable(f"{code}: 전일까지의 일봉이 없습니다.")

    return evaluate_kr(
        code=code,
        history=history,
        price=float(current["close"]),
        today_high=float(current["high"]),
        open_price=float(current["open"]),
        cfg=cfg,
        name=(names or {}).get(code, ""),
    )


def scan_b(
    codes: list[str],
    cfg: ScannerBConfig,
    names: dict[str, str] | None = None,
    today: date | None = None,
) -> tuple[list[SignalKr], list[str]]:
    passed: list[SignalKr] = []
    errors: list[str] = []
    for code in codes:
        try:
            result = scan_b_code(code, cfg, names, today)
        except DataUnavailable as exc:
            errors.append(f"{code}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code}: 예기치 못한 오류 - {exc}")
            continue
        if result.passed:
            passed.append(result)
    return passed, errors


def to_frame_a(hits: list[GapHitKr]) -> pd.DataFrame:
    if not hits:
        return pd.DataFrame(columns=[f.name for f in GapHitKr.__dataclass_fields__.values()])
    return pd.DataFrame([asdict(h) for h in hits])


def format_report_a(
    hits: list[GapHitKr], when: str, errors: list[str] | None = None, scanned: int = 0
) -> str:
    errors = errors or []
    header = f"[국내 시가갭 스캐너] {when}"

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


def format_report_b(
    results: list[SignalKr], when: str, errors: list[str] | None = None, scanned: int = 0
) -> str:
    errors = errors or []
    header = f"[국내 전략 스캐너 · Trend Join Long] {when}"

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
        label = f"{r.code} {r.name}".strip()
        lines.append(
            f"{label:<16} {r.price:>9,.0f}원  "
            f"전일고가 {r.prev_high:,.0f} / 200MA {r.sma_slow:,.0f}"
        )
    if errors:
        lines += ["", f"(조회 실패 {len(errors)}종목)"]
    lines += ["", "※ 신호일 뿐 매매 권유가 아닙니다. 최종 판단은 본인 기준으로."]
    return "\n".join(lines)
