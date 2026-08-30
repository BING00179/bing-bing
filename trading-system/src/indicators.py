"""이동평균선 등 지표 계산.

'이동평균선'은 최근 N일 종가의 평균을 선으로 이은 것으로,
주가의 전반적인 방향을 보여줍니다.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """단순 이동평균(Simple Moving Average).

    앞쪽 window-1 개 구간은 데이터가 모자라므로 NaN 이 됩니다.
    """
    if window < 1:
        raise ValueError(f"window 는 1 이상이어야 합니다: {window}")
    return series.rolling(window=window, min_periods=window).mean()


def trend_aligned(
    close: pd.Series,
    fast: int,
    mid: int,
    slow: int,
) -> pd.Series:
    """상승 추세 정렬 여부.

    원문의 조건 5 '위 흐름이 상승 추세와 일치할 것'은 문장만으로는
    계산할 수 없어, 흔히 쓰는 정배열 정의로 구체화했습니다:

        종가 > 단기선 > 중기선 > 장기선

    정의를 바꾸고 싶으면 config.json 의 scanner_b 값을 조정하세요.
    """
    ma_fast = sma(close, fast)
    ma_mid = sma(close, mid)
    ma_slow = sma(close, slow)
    aligned = (close > ma_fast) & (ma_fast > ma_mid) & (ma_mid > ma_slow)
    # 이동평균이 아직 안 만들어진 구간은 판정 불가 → False
    return aligned.fillna(False).astype(bool)


def gap_pct(today_open: float, prev_close: float) -> float:
    """갭 비율(%) = (오늘 시가 - 전일 종가) / 전일 종가 * 100."""
    if prev_close <= 0:
        raise ValueError(f"전일 종가가 0 이하입니다: {prev_close}")
    return (today_open - prev_close) / prev_close * 100.0
