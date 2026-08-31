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

import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data import DataUnavailable


def _pykrx():
    """pykrx 를 불러옵니다. 실패하면 DataUnavailable.

    pykrx 는 불러오는 순간 KRX 에 로그인을 시도합니다. 계정이 없거나
    KRX 가 응답 형식을 바꾸면 여기서 예외가 터지는데, 그게 프로그램
    전체를 죽이면 안 됩니다. 다른 데이터 출처로 넘어갈 수 있어야 합니다.
    """
    try:
        from pykrx import stock  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise DataUnavailable(
            "pykrx 가 설치돼 있지 않습니다. `pip install pykrx` 로 설치해 주세요."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 로그인 실패 등 무엇이든
        raise DataUnavailable(
            f"pykrx 를 쓸 수 없습니다 (KRX 로그인 실패 등): {exc}"
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
    days: list[str],
    market: str = "KOSDAQ",
    verbose: bool = True,
    pause: float = 1.5,
) -> dict[str, pd.DataFrame]:
    """날짜별 단면을 모읍니다. 휴장일은 건너뜁니다.

    ⚠️ 조회 사이에 반드시 쉽니다. 쉬지 않고 수십 번 연속 요청하면
       한국거래소가 '자동화 수단을 통한 비정상 대량 조회' 로 보고
       IP 를 하루 동안 차단합니다. 실제로 그렇게 막혔던 적이 있습니다.
       차단되면 FinanceDataReader 도 함께 막힙니다. 종목 목록을
       같은 서버에서 가져오기 때문입니다.
    """
    out: dict[str, pd.DataFrame] = {}
    for i, day in enumerate(days):
        if i:
            time.sleep(pause)
        frame = snapshot(day, market)
        if frame.empty:
            if verbose:
                print(f"  ! {day}: 데이터 없음 (휴장일 등)")
            continue
        out[day] = frame
        if verbose:
            print(f"  {day}  {len(frame):,}종목")
    return out


# ─────────────────────────────────────────────────────────────
# FinanceDataReader 경로 — 로그인이 필요 없습니다.
#
# pykrx 는 KRX 계정을 요구하고 로그인이 자주 깨집니다. FDR 은
# 백테스트에서 이미 코스닥 1700여 종목을 문제없이 받아온 도구라
# 이쪽을 기본으로 씁니다.
#
# 대신 PER·PBR·배당은 받을 수 없습니다. 가격과 거래량으로 계산되는
# 네 가지(소형주·모멘텀·저변동성·거래대금)만 검정합니다.
# ─────────────────────────────────────────────────────────────


def _fdr():
    try:
        import FinanceDataReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise DataUnavailable(
            "FinanceDataReader 가 없습니다. `pip install finance-datareader`"
        ) from exc
    return FinanceDataReader


def listing_with_size(market: str = "KOSDAQ", top: int = 0) -> pd.DataFrame:
    """종목 목록 + 시가총액. top 을 주면 시총 상위 N개만.

    전 종목을 다 받으면 시간이 오래 걸립니다. 거래가 거의 없는
    종목은 실제로 사고팔 수 없으므로, 시총 상위만 보는 것이
    현실적이기도 합니다.
    """
    fdr = _fdr()
    try:
        frame = fdr.StockListing(market.strip().upper())
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "krx" in text.lower():
            raise DataUnavailable(
                f"{market} 종목 목록을 받지 못했습니다.\n"
                "   한국거래소가 이 IP 의 접속을 제한했을 수 있습니다.\n"
                "   짧은 시간에 너무 많이 조회하면 하루 동안 막힙니다.\n"
                "   내일 다시 시도하거나, 다른 네트워크에서 실행해 보세요."
            ) from exc
        raise DataUnavailable(f"{market} 종목 목록 조회 실패: {exc}") from exc
    if frame is None or frame.empty:
        raise DataUnavailable(f"{market} 종목 목록이 비어 있습니다.")

    lower = {str(c).strip().lower(): c for c in frame.columns}
    code_col = lower.get("code") or lower.get("symbol")
    name_col = lower.get("name")
    cap_col = lower.get("marcap") or lower.get("marketcap")
    if code_col is None:
        raise DataUnavailable(f"종목코드 컬럼을 찾지 못했습니다: {list(frame.columns)}")

    out = pd.DataFrame({"code": frame[code_col].astype(str).str.zfill(6)})
    out["name"] = frame[name_col].astype(str) if name_col else ""
    out["marcap"] = (
        pd.to_numeric(frame[cap_col], errors="coerce") if cap_col else float("nan")
    )
    out = out.dropna(subset=["code"]).drop_duplicates("code")
    if top and "marcap" in out:
        out = out.nlargest(top, "marcap")
    return out.reset_index(drop=True)


def collect_fdr(
    codes: list[str],
    years: float = 5.0,
    verbose: bool = True,
    pause: float = 0.3,
) -> dict[str, pd.DataFrame]:
    """종목별 일봉을 받습니다. 종목당 1~2초 걸립니다.

    ⚠️ 여기도 조회 사이에 쉽니다. 수백 종목을 쉬지 않고 긁으면
       차단당합니다. 느려 보여도 이게 안전한 속도입니다.
    """
    fdr = _fdr()
    start = (date.today() - timedelta(days=int(365.25 * (years + 1)))).isoformat()

    frames: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(codes, 1):
        if i > 1:
            time.sleep(pause)
        try:
            frame = fdr.DataReader(code, start)
        except Exception:  # noqa: BLE001 - 상장폐지 등
            continue
        if frame is None or frame.empty:
            continue
        frame = frame.rename(columns={c: str(c).strip().lower() for c in frame.columns})
        if "close" not in frame.columns:
            continue
        frames[code] = frame
        if verbose and i % 100 == 0:
            print(f"  {i:,}/{len(codes):,}종목  (확보 {len(frames):,})")

    if verbose:
        print(f"  시세 확보 {len(frames):,}종목")
    return frames


def build_from_fdr(
    frames: dict[str, pd.DataFrame],
    momentum_months: int = 6,
    volatility_months: int = 6,
    listing: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """일봉 모음에서 월말 기준 (가격표, 요인표들) 을 만듭니다."""
    if len(frames) < 30:
        raise DataUnavailable(f"종목이 {len(frames)}개뿐이라 검정할 수 없습니다.")

    closes, turnovers = {}, {}
    for code, frame in frames.items():
        monthly = frame["close"].resample("ME").last()
        closes[code] = monthly
        if "volume" in frame.columns:
            value = frame["close"] * frame["volume"]
            turnovers[code] = value.resample("ME").mean()

    prices = pd.DataFrame(closes).sort_index().dropna(how="all")
    turnover = pd.DataFrame(turnovers).reindex(prices.index) if turnovers else pd.DataFrame()

    momentum = prices.pct_change(momentum_months) * 100.0
    monthly_ret = prices.pct_change()
    volatility = (
        monthly_ret.rolling(volatility_months, min_periods=volatility_months).std() * 100.0
    )
    factors = {
        f"모멘텀{momentum_months}개월": momentum,
        f"저변동성{volatility_months}개월": volatility,
    }

    # 과거 시가총액을 복원합니다.
    #
    #   상장주식수 = 현재 시가총액 ÷ 현재 주가
    #   과거 시가총액 = 그때 주가 × 상장주식수
    #
    # 주식수는 지금 값만 알 수 있어서, 유상증자나 액면분할이 있었던
    # 종목은 어긋납니다. 주가를 그대로 쓰는 것보다는 훨씬 낫습니다
    # (주가가 낮다고 작은 회사가 아니기 때문입니다).
    if listing is not None and not listing.empty and "marcap" in listing.columns:
        caps = listing.set_index("code")["marcap"].dropna()
        last_price = prices.ffill().iloc[-1]
        common = caps.index.intersection(last_price.index)
        shares = (caps.loc[common] / last_price.loc[common]).replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(shares) >= 30:
            factors["소형주(시가총액)"] = prices[shares.index] * shares

    if not turnover.empty:
        factors["거래대금"] = turnover
    return prices, factors


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
    "소형주(시가총액)": False,      # 시가총액이 작을수록 유리하다는 가정
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
