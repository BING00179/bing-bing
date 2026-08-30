"""국내 주식 시세 조회.

기본은 FinanceDataReader 를 씁니다. 한국거래소(KRX) 데이터를 그대로
가져오고, 코스피·코스닥 전 종목 목록도 한 번에 받을 수 있습니다.
설치돼 있지 않으면 안내 메시지와 함께 예외를 냅니다.

    pip install finance-datareader

종목 코드는 6자리 숫자입니다. 삼성전자는 005930, 카카오는 035720.
앞의 0 이 잘리면 조회가 실패하므로 문자열로 다룹니다(엑셀에서 옮겨올 때
가장 흔한 실수입니다).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from .data import COLUMNS, DataUnavailable

TICKER_PATTERN = re.compile(r"^\d{6}$")


class NoTodayBar(DataUnavailable):
    """오늘 거래가 없습니다 — 휴장일이거나 거래정지 종목.

    조회 실패와 구분해야 합니다. 휴장일에 전 종목이 이 상태가 되는데,
    이걸 오류로 세면 '전부 조회 실패' 로 보고돼 시스템이 고장난 것처럼
    보입니다.
    """


def normalize_code(value: str) -> str:
    """'5930' 이나 'A005930' 같은 입력을 '005930' 으로 맞춥니다."""
    raw = str(value).strip().upper()
    raw = raw.removeprefix("A")
    raw = raw.split(".")[0]              # '005930.KS' 형태도 허용
    if raw.isdigit():
        raw = raw.zfill(6)
    if not TICKER_PATTERN.match(raw):
        raise DataUnavailable(
            f"국내 종목코드는 숫자 6자리여야 합니다: {value!r} → {raw!r}"
        )
    return raw


def _fdr():
    try:
        import FinanceDataReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 다름
        raise DataUnavailable(
            "FinanceDataReader 가 설치돼 있지 않습니다. "
            "`pip install finance-datareader` 로 설치해 주세요."
        ) from exc
    return FinanceDataReader


def _normalize_frame(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise DataUnavailable(f"{code}: 시세 데이터를 받지 못했습니다.")
    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataUnavailable(f"{code}: 시세에 컬럼이 없습니다: {missing}")
    out = df.loc[:, COLUMNS].copy()
    out.index = pd.to_datetime(out.index)
    out = out.dropna(subset=["open", "high", "low", "close"]).sort_index()
    # 거래정지일은 거래량 0 으로 남는데, 이런 봉은 고가·저가가 종가와 같아
    # 돌파 판정을 왜곡합니다. 빼고 계산합니다.
    return out[out["volume"] > 0]


def fetch_daily(code: str, years: float = 2.0) -> pd.DataFrame:
    """일봉을 받아옵니다(기본 2년)."""
    fdr = _fdr()
    code = normalize_code(code)
    start = (date.today() - timedelta(days=int(365 * years) + 30)).isoformat()
    try:
        df = fdr.DataReader(code, start)
    except Exception as exc:  # noqa: BLE001 - 라이브러리가 다양한 예외를 냅니다
        raise DataUnavailable(f"{code}: 조회 실패 - {exc}") from exc
    return _normalize_frame(df, code)


def today_bar(daily: pd.DataFrame, today: date | None = None) -> pd.Series | None:
    """일봉에서 오늘 봉을 꺼냅니다. 없으면 None.

    장중에 조회하면 마지막 봉이 '오늘 여기까지'의 값입니다.
    시가는 확정(동시호가 결과), 고가·종가는 계속 갱신됩니다.
    """
    if daily.empty:
        return None
    today = today or date.today()
    last = daily.index[-1]
    return daily.iloc[-1] if last.date() == today else None


def split_today(daily: pd.DataFrame, today: date | None = None):
    """(어제까지 확정 일봉, 오늘 봉) 으로 나눕니다.

    전략 판정에는 '어제까지'만 써야 합니다. 오늘 봉을 이동평균에
    섞으면 아직 끝나지 않은 값으로 판정하게 됩니다.
    """
    today = today or date.today()
    history = daily[daily.index.date < today]
    current = today_bar(daily, today)
    return history, current


def fetch_index(code: str = "KS11", years: float = 3.0) -> pd.DataFrame:
    """지수 일봉을 받아옵니다.

    KS11 = 코스피, KQ11 = 코스닥, KS200 = 코스피200.
    시장 필터에서 200일선을 보려면 최소 1년치 이상이 필요해서
    기본 3년으로 넉넉히 받습니다.
    """
    fdr = _fdr()
    start = (date.today() - timedelta(days=int(365 * years) + 30)).isoformat()
    try:
        df = fdr.DataReader(code, start)
    except Exception as exc:  # noqa: BLE001
        raise DataUnavailable(f"{code}: 지수 조회 실패 - {exc}") from exc
    if df is None or df.empty:
        raise DataUnavailable(f"{code}: 지수 데이터가 비어 있습니다.")

    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    if "close" not in df.columns:
        raise DataUnavailable(f"{code}: 지수에 close 컬럼이 없습니다: {list(df.columns)}")
    # 지수는 거래량이 없는 경우가 있어 종가만 필수로 봅니다.
    keep = [c for c in COLUMNS if c in df.columns]
    out = df.loc[:, keep].copy()
    out.index = pd.to_datetime(out.index)
    return out.dropna(subset=["close"]).sort_index()


def list_market(market: str = "KOSPI") -> pd.DataFrame:
    """코스피/코스닥 전 종목 목록.

    반환 컬럼: code, name, market  (없는 값은 비워둡니다)
    """
    fdr = _fdr()
    key = market.strip().upper()
    if key not in {"KOSPI", "KOSDAQ", "KRX"}:
        raise DataUnavailable(f"모르는 시장입니다: {market!r} (KOSPI/KOSDAQ/KRX)")
    try:
        df = fdr.StockListing(key)
    except Exception as exc:  # noqa: BLE001
        raise DataUnavailable(f"{key} 종목 목록 조회 실패 - {exc}") from exc
    if df is None or df.empty:
        raise DataUnavailable(f"{key} 종목 목록이 비어 있습니다.")

    lower = {str(c).strip().lower(): c for c in df.columns}
    code_col = lower.get("code") or lower.get("symbol")
    name_col = lower.get("name")
    if code_col is None or name_col is None:
        raise DataUnavailable(
            f"{key} 목록에서 종목코드/종목명 컬럼을 찾지 못했습니다: {list(df.columns)}"
        )

    out = pd.DataFrame(
        {
            "code": df[code_col].astype(str).str.zfill(6),
            "name": df[name_col].astype(str),
        }
    )
    out["market"] = key
    return out.reset_index(drop=True)


def read_universe_kr(path) -> list[str]:
    """국내 종목코드 목록 파일을 읽습니다.

    '005930  삼성전자' 처럼 코드 뒤에 이름을 적어둬도 됩니다.
    앞쪽 코드만 읽고 나머지는 무시합니다. # 뒤는 주석입니다.
    """
    from pathlib import Path  # noqa: PLC0415

    path = Path(path)
    if not path.exists():
        raise DataUnavailable(f"종목 목록 파일이 없습니다: {path}")

    codes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        codes.append(normalize_code(line.split()[0]))
    return codes
