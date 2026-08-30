"""이상 징후 점검 — "평소와 다른 점" 표시.

⚠️ 먼저 분명히 해둡니다. 이것은 **작전·시세조종을 판정하는 기능이
   아닙니다.** 그건 금융당국이 계좌 추적까지 해야 알 수 있는 일이고,
   공개 데이터로는 증명할 수 없습니다.

   여기서 하는 일은 "이 종목의 오늘이 평소와 얼마나 다른가"를
   숫자로 보여주는 것뿐입니다. 판단은 사람이 합니다.

점검 항목

  거래량 급증      오늘 거래량이 최근 20일 평균의 몇 배인가
                   추세 초입이면 3~5배가 흔하고, 20배가 넘으면
                   평범한 매수세로 보기 어렵습니다.

  거래대금 회전율   하루 거래대금 / 시가총액
                   소형주에 시총의 30% 넘는 돈이 하루에 돌면
                   유통 물량이 소수 손에서 돌고 있을 수 있습니다.

  단기 급등 누적    최근 5일 누적 상승률
                   이미 크게 오른 뒤 올라타면 고점 매수가 됩니다.

  200일선 이격도    장기선에서 얼마나 떨어져 있나
                   너무 멀면 되돌림 위험이 큽니다.

  수급 주체        외국인·기관이 사는가, 개인만 사는가
                   개인만 순매수인 상승은 힘이 약한 경우가 많습니다.

각 항목은 정상 / 주의 / 경고 로 표시하고, 왜 그렇게 봤는지 기준값을
같이 남깁니다. 경고가 떴다고 사면 안 된다는 뜻은 아니고, 반대로
전부 정상이라고 안전하다는 뜻도 아닙니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OK, WATCH, ALERT = "정상", "주의", "경고"


@dataclass
class Flag:
    label: str
    level: str          # 정상 / 주의 / 경고
    value: str          # 측정값
    basis: str          # 어떤 기준으로 그렇게 봤는가


@dataclass
class AnomalyReport:
    flags: list[Flag] = field(default_factory=list)
    supply: str = ""    # 수급 요약 (조회 못 하면 빈 문자열)

    @property
    def level(self) -> str:
        levels = [f.level for f in self.flags]
        if ALERT in levels:
            return ALERT
        if WATCH in levels:
            return WATCH
        return OK

    @property
    def alerts(self) -> list[Flag]:
        return [f for f in self.flags if f.level != OK]


@dataclass
class AnomalyConfig:
    volume_watch_x: float = 8.0        # 평균 거래량 대비 몇 배부터 주의
    volume_alert_x: float = 20.0       # 몇 배부터 경고
    turnover_watch_pct: float = 15.0   # 시총 대비 거래대금 %
    turnover_alert_pct: float = 30.0
    run_up_watch_pct: float = 20.0     # 최근 5일 누적 상승률
    run_up_alert_pct: float = 40.0
    extension_watch_pct: float = 50.0  # 200일선 이격도
    extension_alert_pct: float = 100.0
    run_up_days: int = 5


def _level(value: float, watch: float, alert: float) -> str:
    if value >= alert:
        return ALERT
    if value >= watch:
        return WATCH
    return OK


def check(
    *,
    closes: list[float],
    volumes: list[float],
    today_volume: float,
    turnover: float,
    market_cap: float,
    price: float,
    sma_slow: float,
    cfg: AnomalyConfig | None = None,
) -> AnomalyReport:
    """공개 데이터로 계산되는 항목만 점검합니다."""
    cfg = cfg or AnomalyConfig()
    flags: list[Flag] = []

    # 1) 거래량 급증
    past = [v for v in volumes[-20:] if v and v > 0]
    if past and today_volume > 0:
        avg = sum(past) / len(past)
        ratio = today_volume / avg if avg > 0 else 0.0
        flags.append(
            Flag(
                label="거래량 급증",
                level=_level(ratio, cfg.volume_watch_x, cfg.volume_alert_x),
                value=f"평소의 {ratio:,.1f}배",
                basis=f"최근 {len(past)}일 평균 {avg:,.0f}주 대비 "
                      f"(주의 {cfg.volume_watch_x:.0f}배 / 경고 {cfg.volume_alert_x:.0f}배)",
            )
        )

    # 2) 거래대금 회전율
    if market_cap > 0 and turnover > 0:
        pct = turnover / market_cap * 100.0
        flags.append(
            Flag(
                label="거래대금 회전율",
                level=_level(pct, cfg.turnover_watch_pct, cfg.turnover_alert_pct),
                value=f"시총의 {pct:,.1f}%",
                basis=f"거래대금 {turnover / 1e8:,.0f}억 / 시총 {market_cap / 1e8:,.0f}억 "
                      f"(주의 {cfg.turnover_watch_pct:.0f}% / 경고 {cfg.turnover_alert_pct:.0f}%)",
            )
        )

    # 3) 단기 급등 누적
    window = cfg.run_up_days
    if len(closes) > window:
        base = closes[-(window + 1)]
        if base > 0:
            run_up = (price - base) / base * 100.0
            flags.append(
                Flag(
                    label=f"최근 {window}일 누적 상승",
                    level=_level(run_up, cfg.run_up_watch_pct, cfg.run_up_alert_pct),
                    value=f"{run_up:+,.1f}%",
                    basis=f"{window}일 전 {base:,.0f}원 → 현재 {price:,.0f}원 "
                          f"(주의 +{cfg.run_up_watch_pct:.0f}% / 경고 +{cfg.run_up_alert_pct:.0f}%)",
                )
            )

    # 4) 200일선 이격도
    if sma_slow > 0 and price > 0:
        extension = (price - sma_slow) / sma_slow * 100.0
        flags.append(
            Flag(
                label="200일선 이격도",
                level=_level(extension, cfg.extension_watch_pct, cfg.extension_alert_pct),
                value=f"+{extension:,.1f}%",
                basis=f"200일선 {sma_slow:,.0f}원 대비 "
                      f"(주의 +{cfg.extension_watch_pct:.0f}% / 경고 +{cfg.extension_alert_pct:.0f}%)",
            )
        )

    return AnomalyReport(flags=flags)


def fetch_supply(code: str, days: int = 5) -> tuple[str, Flag | None]:
    """최근 수급 — 외국인·기관이 사는가, 개인만 사는가.

    한국거래소가 투자자별 순매수를 공개합니다. 조회에 실패하면
    빈 값을 돌려주고 점검을 건너뜁니다(부가 정보이므로).
    """
    try:
        from datetime import date, timedelta  # noqa: PLC0415

        from pykrx import stock  # noqa: PLC0415
    except ImportError:
        return "", None

    end = date.today()
    start = end - timedelta(days=days * 3)      # 휴장일을 감안해 넉넉히
    try:
        frame = stock.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code
        )
    except Exception:  # noqa: BLE001 - 수급은 부가 정보
        return "", None
    if frame is None or frame.empty:
        return "", None

    recent = frame.tail(days)
    totals = {}
    for column in ("외국인합계", "기관합계", "개인"):
        if column in recent.columns:
            totals[column] = float(recent[column].sum())
    if not totals:
        return "", None

    def label(value: float) -> str:
        return f"{value / 1e8:+,.0f}억"

    parts = [f"{k.replace('합계', '')} {label(v)}" for k, v in totals.items()]
    summary = f"최근 {len(recent)}거래일 순매수 — " + " · ".join(parts)

    foreign = totals.get("외국인합계", 0.0)
    institution = totals.get("기관합계", 0.0)
    retail = totals.get("개인", 0.0)

    flag = None
    if retail > 0 and foreign < 0 and institution < 0:
        flag = Flag(
            label="수급 주체",
            level=WATCH,
            value="개인만 순매수",
            basis="외국인과 기관은 순매도 중입니다. 상승의 힘이 약할 수 있습니다.",
        )
    elif foreign > 0 and institution > 0:
        flag = Flag(
            label="수급 주체",
            level=OK,
            value="외국인·기관 동반 순매수",
            basis="주요 수급 주체가 함께 매수하고 있습니다.",
        )
    return summary, flag
