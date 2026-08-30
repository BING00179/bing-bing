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

from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

from .config import ScannerAKrConfig, ScannerBConfig
from .data import DataUnavailable
from .data_kr import fetch_daily, normalize_code, split_today
from .anomaly import check as anomaly_check
from .anomaly import fetch_supply
from .config import RankingConfig
from .indicators import sma, trend_aligned
from .markets import KR
from .ranking import Score, score as compute_score


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
class Check:
    """조건 하나의 판정 근거.

    통과 여부만 남기면 나중에 "왜 이 종목이 뽑혔지?" 를 확인할 수
    없습니다. 실제로 비교한 숫자와 그 조건이 무엇을 뜻하는지를
    함께 남깁니다.
    """

    label: str      # ① 전날 고가 돌파
    passed: bool
    detail: str     # 현재가 152,000원 ≥ 전날 고가 148,500원
    why: str        # 어제 팔려던 물량을 소화하고 올라섰다는 뜻


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
    checks: list[Check] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)   # 최근 종가 (차트용)
    sma_fast_v: float = 0.0
    sma_mid_v: float = 0.0
    fundamentals: object | None = None                  # Fundamentals
    anomaly: object | None = None                       # AnomalyReport
    supply_summary: str = ""                            # 수급 요약
    volumes: list[float] = field(default_factory=list)
    today_volume: float = 0.0
    gap_pct: float = 0.0        # 전일 종가 대비 시가 상승률
    turnover: float = 0.0       # 오늘 거래대금 (원)
    score: Score | None = None  # 순위 점수 (매기지 않았으면 None)

    @property
    def passed(self) -> bool:
        return not self.failed

    def as_line(self, rank: int | None = None) -> str:
        label = f"{self.code} {self.name}".strip()
        head = f"{rank}. " if rank else "   "
        line = f"{head}{label:<16} {self.price:>9,.0f}원"
        if self.score is not None:
            line += f"  {self.score.as_line()}"
        return line


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
    gap_pct: float = 0.0,
    turnover: float = 0.0,
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

    ma_fast = float(sma(history["close"], cfg.sma_fast).iloc[-1])
    ma_mid = float(sma(history["close"], cfg.sma_mid).iloc[-1])

    details = [
        Check(
            label="① 전날 고가 돌파",
            passed=price >= prev_high * tol,
            detail=f"현재가 {price:,.0f}원 vs 전날 고가 {prev_high:,.0f}원",
            why="어제 팔려던 물량을 소화하고 그 위로 올라섰는가",
        ),
        Check(
            label=f"② 전날 종가 > {cfg.sma_slow}일선",
            passed=prev_close > sma_slow,
            detail=f"전날 종가 {prev_close:,.0f}원 vs {cfg.sma_slow}일선 {sma_slow:,.0f}원",
            why="장기 상승 추세 안에 있는 종목만 본다 (하락 종목의 반등은 제외)",
        ),
        Check(
            label="③ 시가 위 유지",
            passed=price >= open_price * tol,
            detail=f"현재가 {price:,.0f}원 vs 오늘 시가 {open_price:,.0f}원",
            why="동시호가로 정해진 시가 아래로 밀린 종목은 제외",
        ),
        Check(
            label="④ 오늘 고가 갱신 중",
            passed=price >= today_high * near_high,
            detail=(
                f"현재가 {price:,.0f}원 vs 오늘 고가 {today_high:,.0f}원 "
                f"(허용 {cfg.close_near_high_pct}%)"
            ),
            why="지금 이 순간에도 사는 사람이 있는가",
        ),
        Check(
            label="⑤ 상승 추세 정렬",
            passed=aligned,
            detail=(
                f"종가 {prev_close:,.0f} > {cfg.sma_fast}일 {ma_fast:,.0f} > "
                f"{cfg.sma_mid}일 {ma_mid:,.0f} > {cfg.sma_slow}일 {sma_slow:,.0f}"
            ),
            why="단기·중기·장기 이동평균이 모두 위를 향하는가 (정배열)",
        ),
    ]
    checks = {
        "1_전날고가돌파": details[0].passed,
        "2_전날종가>200MA": details[1].passed,
        "3_시가위유지": details[2].passed,
        "4_오늘고가돌파": details[3].passed,
        "5_상승추세정렬": details[4].passed,
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
        checks=details,
        closes=[float(v) for v in history["close"].tail(60)] + [price],
        volumes=[float(v) for v in history["volume"].tail(20)],
        sma_fast_v=ma_fast,
        sma_mid_v=ma_mid,
        gap_pct=gap_pct,
        turnover=turnover,
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

    prev_close = float(history["close"].iloc[-1])
    open_price = float(current["open"])
    gap = (open_price - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0

    signal = evaluate_kr(
        code=code,
        history=history,
        price=float(current["close"]),
        today_high=float(current["high"]),
        open_price=open_price,
        cfg=cfg,
        name=(names or {}).get(code, ""),
        gap_pct=gap,
        turnover=float(current["close"] * current["volume"]),
    )
    signal.today_volume = float(current["volume"])
    return signal


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

    if passed:
        try:
            from .fundamentals import fetch_bulk  # noqa: PLC0415

            info = fetch_bulk([r.code for r in passed])
            for r in passed:
                r.fundamentals = info.get(r.code)
                if r.fundamentals is not None and not r.name:
                    r.name = r.fundamentals.name
        except Exception as exc:  # noqa: BLE001 - 부가 정보라 실패해도 진행
            print(f"  ! 기업 정보 조회 실패 (스캔은 계속): {exc}")

    # 이상 징후 점검. 매수 여부를 가르지는 않고, 사람이 보고 판단할
    # 재료로만 붙입니다.
    for r in passed:
        cap = getattr(r.fundamentals, "market_cap", 0.0) or 0.0
        r.anomaly = anomaly_check(
            closes=r.closes,
            volumes=r.volumes,
            today_volume=r.today_volume,
            turnover=r.turnover,
            market_cap=cap,
            price=r.price,
            sma_slow=r.sma_slow,
        )
        summary, flag = fetch_supply(r.code)
        r.supply_summary = summary
        if flag is not None:
            r.anomaly.flags.append(flag)

    return passed, errors


def rank(results: list[SignalKr], cfg: RankingConfig) -> list[SignalKr]:
    """점수를 매겨 높은 순으로 정렬합니다. 목록에서 빼지는 않습니다."""
    if not cfg.enabled:
        return results
    for r in results:
        r.score = compute_score(
            gap_pct=r.gap_pct,
            turnover=r.turnover,
            price=r.price,
            sma_slow=r.sma_slow,
            today_high=r.today_high,
            cfg=cfg,
        )
    kept = [r for r in results if r.score is None or r.score.total >= cfg.min_score]
    kept.sort(key=lambda r: (r.score.total if r.score else 0.0), reverse=True)
    return kept


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
    results: list[SignalKr],
    when: str,
    errors: list[str] | None = None,
    scanned: int = 0,
    top_n: int = 3,
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

    ranked = results[0].score is not None if results else False
    if ranked and top_n > 0:
        top = results[:top_n]
        rest = results[top_n:]

        lines.append(f"⭐ 추천 상위 {len(top)}종목")
        lines += [r.as_line(i) for i, r in enumerate(top, 1)]

        if rest:
            lines += ["", f"── 나머지 조건 통과 {len(rest)}종목 ──"]
            lines += [r.as_line(i) for i, r in enumerate(rest, len(top) + 1)]
    else:
        for r in results:
            label = f"{r.code} {r.name}".strip()
            lines.append(
                f"{label:<16} {r.price:>9,.0f}원  "
                f"전일고가 {r.prev_high:,.0f} / 200MA {r.sma_slow:,.0f}"
            )

    if errors:
        lines += ["", f"(조회 실패 {len(errors)}종목)"]
    lines += [
        "",
        "※ 점수는 같은 조건을 통과한 것들 중 상대적으로 뚜렷한 쪽을",
        "   고르는 장치입니다. 점수가 높다고 더 오른다는 근거는 없습니다.",
        "※ 신호일 뿐 매매 권유가 아닙니다. 최종 판단은 본인 기준으로.",
    ]
    return "\n".join(lines)
