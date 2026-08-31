"""요인 검정용 데이터 수집.

pykrx 는 '특정 날짜의 전 종목' 을 한 번에 줍니다. 종목마다 따로
받으면 1,800번 호출해야 할 것이 날짜당 한 번으로 끝납니다.
월 단위로 3년이면 36번이면 됩니다.

    get_market_cap_by_ticker(date, market)          시가총액·거래대금
    get_market_fundamental_by_ticker(date, market)  PER·PBR·EPS·BPS·배당

여기서 만드는 요인들. 전부 그 시점까지의 정보만 씁니다.

    밸류      PER, PBR 이 낮을수록 유리한가
    소형주    시가총액이 작을수록 유리한가
    모멘텀    최근 N개월 오른 종목이 더 오르는가
    저변동성  덜 흔들리는 종목이 오히려 나은가
    배당      배당수익률이 높을수록 유리한가
    유동성    거래대금이 클수록 유리한가
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data import DataUnavailable


def _pykrx():
    try:
        from pykrx import stock  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise DataUnavailable(
            "pykrx 가 설치돼 있지 않습니다. `pip install pykrx` 로 설치해 주세요."
        ) from exc
    return stock


def month_ends(years: float, today: date | None = None) -> list[str]:
    """리밸런싱 날짜 목록 (월말 영업일 근사). 'YYYYMMDD' 문자열."""
    today = today or date.today()
    start = today - timedelta(days=int(365.25 * years))
    days = pd.date_range(start=start, end=today, freq="ME")
    return [d.strftime("%Y%m%d") for d in days]


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.index = out.index.astype(str).str.zfill(6)
    return out


def snapshot(day: str, market: str = "KOSDAQ") -> pd.DataFrame:
    """하루치 전 종목 단면. 실패하면 빈 DataFrame."""
    stock = _pykrx()
    try:
        cap = _normalize(stock.get_market_cap_by_ticker(day, market=market))
        fund = _normalize(stock.get_market_fundamental_by_ticker(day, market=market))
    except Exception:  # noqa: BLE001 - 휴장일 등 다양한 실패
        return pd.DataFrame()
    if cap.empty:
        return pd.DataFrame()

    merged = cap.join(fund, how="left") if not fund.empty else cap
    return merged


def collect(
    days: list[str], market: str = "KOSDAQ", verbose: bool = True
) -> dict[str, pd.DataFrame]:
    """날짜별 단면을 모읍니다. 휴장일은 건너뜁니다."""
    out: dict[str, pd.DataFrame] = {}
    for day in days:
        frame = snapshot(day, market)
        if frame.empty:
            if verbose:
                print(f"  ! {day}: 데이터 없음 (휴장일 등)")
            continue
        out[day] = frame
        if verbose:
            print(f"  {day}  {len(frame):,}종목")
    return out


def _pick(frame: pd.DataFrame, *names: str) -> pd.Series | None:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return None


def build_matrices(
    snapshots: dict[str, pd.DataFrame],
    momentum_months: int = 6,
    volatility_months: int = 6,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """단면 모음에서 (가격표, 요인표들) 을 만듭니다.

    가격표  행=리밸런싱일, 열=종목코드, 값=종가
    요인표  같은 모양, 값=요인값
    """
    if len(snapshots) < 2:
        raise DataUnavailable("리밸런싱일이 2개 이상 필요합니다.")

    dates = pd.DatetimeIndex([pd.Timestamp(d) for d in sorted(snapshots)])
    keys = sorted(snapshots)

    def matrix(getter) -> pd.DataFrame:
        rows = {}
        for key, day in zip(keys, dates):
            series = getter(snapshots[key])
            if series is not None:
                rows[day] = series
        return pd.DataFrame(rows).T.sort_index() if rows else pd.DataFrame()

    prices = matrix(lambda f: _pick(f, "종가"))
    if prices.empty:
        raise DataUnavailable("종가 컬럼을 찾지 못했습니다.")

    market_cap = matrix(lambda f: _pick(f, "시가총액"))
    turnover = matrix(lambda f: _pick(f, "거래대금"))
    per = matrix(lambda f: _pick(f, "PER"))
    pbr = matrix(lambda f: _pick(f, "PBR"))
    div = matrix(lambda f: _pick(f, "DIV"))

    # PER·PBR 이 0 이하인 것은 적자·자본잠식이라 비교 대상이 아닙니다.
    per = per.where(per > 0) if not per.empty else per
    pbr = pbr.where(pbr > 0) if not pbr.empty else pbr

    # 모멘텀: 과거 N개월 수익률. shift 로 그 시점까지만 씁니다.
    momentum = prices.pct_change(momentum_months) * 100.0

    # 저변동성: 월간 수익률의 최근 N개월 표준편차
    monthly = prices.pct_change()
    volatility = monthly.rolling(volatility_months, min_periods=volatility_months).std() * 100.0

    factors = {
        "저PER(밸류)": per,
        "저PBR(밸류)": pbr,
        "소형주": market_cap,
        f"모멘텀{momentum_months}개월": momentum,
        f"저변동성{volatility_months}개월": volatility,
        "배당수익률": div,
        "거래대금": turnover,
    }
    return prices, {k: v for k, v in factors.items() if not v.empty}


# 요인마다 '어느 쪽이 유리하다고 가정하는가'.
# 알려진 통념일 뿐이며, 검정 결과가 반대로 나올 수도 있습니다.
DIRECTION = {
    "저PER(밸류)": False,          # 낮을수록 유리하다는 가정
    "저PBR(밸류)": False,
    "소형주": False,               # 시가총액이 작을수록
    "배당수익률": True,
    "거래대금": True,
}


def direction_for(name: str) -> bool:
    if name in DIRECTION:
        return DIRECTION[name]
    if name.startswith("모멘텀"):
        return True                # 많이 오른 쪽이 유리하다는 가정
    if name.startswith("저변동성"):
        return False               # 덜 흔들리는 쪽이 유리하다는 가정
    return True


def replace_inf(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.replace([np.inf, -np.inf], np.nan)
