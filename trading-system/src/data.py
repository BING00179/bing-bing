"""시세 데이터 읽기.

두 가지 경로를 지원합니다.
  1) CSV 파일  — 인터넷 없이도 백테스트를 돌릴 수 있습니다.
  2) yfinance  — Yahoo Finance 에서 일봉/분봉을 내려받습니다.
     (`pip install yfinance` 가 필요하며, 설치돼 있지 않으면
      친절한 안내 메시지와 함께 예외를 냅니다.)

모든 함수는 컬럼명이 소문자 open/high/low/close/volume 이고
인덱스가 DatetimeIndex 인 DataFrame 을 돌려줍니다.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
COLUMNS = ["open", "high", "low", "close", "volume"]


class DataUnavailable(RuntimeError):
    """시세를 가져오지 못했을 때."""


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명을 소문자로 맞추고 필요한 컬럼만 남깁니다."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(-1, axis=1)
    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataUnavailable(f"시세 데이터에 컬럼이 없습니다: {missing}")
    out = df.loc[:, COLUMNS].copy()
    out.index = pd.to_datetime(out.index)
    return out.dropna(subset=["open", "high", "low", "close"]).sort_index()


def load_csv(path: str | Path) -> pd.DataFrame:
    """일봉 CSV 를 읽습니다. 첫 컬럼이 날짜여야 합니다."""
    path = Path(path)
    if not path.exists():
        raise DataUnavailable(f"CSV 파일이 없습니다: {path}")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return _normalize(df)


def _yfinance():
    try:
        import yfinance  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 다름
        raise DataUnavailable(
            "yfinance 가 설치돼 있지 않습니다. 스캐너를 쓰려면 `pip install yfinance` "
            "로 설치하세요. 백테스트만 할 거면 --csv-dir 로 CSV 폴더를 지정하면 됩니다."
        ) from exc
    return yfinance


def fetch_daily(ticker: str, period: str = "2y") -> pd.DataFrame:
    """일봉을 내려받습니다(기본 2년)."""
    yf = _yfinance()
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        raise DataUnavailable(f"{ticker}: 일봉 데이터를 받지 못했습니다.")
    return _normalize(df)


def fetch_intraday(ticker: str, days: int = 2) -> pd.DataFrame:
    """프리마켓을 포함한 1분봉을 내려받습니다.

    Yahoo 는 1분봉을 최근 며칠치만 제공합니다. prepost=True 여야
    장 시작 전(프리마켓) 거래가 포함됩니다.
    """
    yf = _yfinance()
    df = yf.Ticker(ticker).history(
        period=f"{days}d", interval="1m", prepost=True, auto_adjust=False
    )
    if df is None or df.empty:
        raise DataUnavailable(f"{ticker}: 분봉 데이터를 받지 못했습니다.")
    out = _normalize(df)
    if out.index.tz is None:
        out.index = out.index.tz_localize(NY)
    else:
        out.index = out.index.tz_convert(NY)
    return out


def premarket_stats(
    intraday: pd.DataFrame, session_date: datetime | None = None
) -> tuple[float | None, int]:
    """해당 날짜의 (프리마켓 고가, 프리마켓 누적 거래량)을 반환합니다.

    프리마켓 = 그날 09:30 ET 이전 구간.
    거래가 하나도 없으면 (None, 0) 을 반환합니다.
    """
    if intraday.empty:
        return None, 0
    day = (session_date or intraday.index[-1]).date()
    same_day = intraday[intraday.index.date == day]
    pre = same_day[same_day.index.time < MARKET_OPEN]
    if pre.empty:
        return None, 0
    return float(pre["high"].max()), int(pre["volume"].sum())


def session_stats(
    intraday: pd.DataFrame, session_date: datetime | None = None
) -> tuple[float | None, float | None]:
    """해당 날짜의 (정규장 시작 이후 고가, 마지막 체결가)를 반환합니다."""
    if intraday.empty:
        return None, None
    day = (session_date or intraday.index[-1]).date()
    same_day = intraday[intraday.index.date == day]
    regular = same_day[same_day.index.time >= MARKET_OPEN]
    if regular.empty:
        return None, float(same_day["close"].iloc[-1])
    return float(regular["high"].max()), float(regular["close"].iloc[-1])


def read_universe(path: str | Path) -> list[str]:
    """스캔 대상 티커 목록을 읽습니다. # 로 시작하는 줄은 주석."""
    path = Path(path)
    if not path.exists():
        raise DataUnavailable(f"티커 목록 파일이 없습니다: {path}")
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().upper()
        if line:
            tickers.append(line)
    return tickers
