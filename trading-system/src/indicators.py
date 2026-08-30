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


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """RSI (상대강도지수), 0~100.

    최근 window 일 동안 오른 폭과 내린 폭의 비율입니다.
    통상 30 아래를 과매도, 70 위를 과열로 봅니다.

    와일더(Wilder)의 원식대로 지수이동평균을 씁니다. 단순평균으로
    계산하는 변형도 흔한데, 값이 미묘하게 달라서 어느 쪽인지
    밝혀두는 편이 낫습니다.
    """
    if window < 1:
        raise ValueError(f"window 는 1 이상이어야 합니다: {window}")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # 하락이 하나도 없으면 avg_loss 가 0 이라 나눗셈이 무한대가 됩니다 → RSI 100
    return out.where(avg_loss != 0, 100.0).where(avg_gain != 0, out.fillna(0.0))


def realized_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """실현 변동성 (연율화, %).

    VIX·VKOSPI 같은 지수는 옵션 가격에서 뽑는 '앞으로의 예상 변동성'
    입니다. 여기서는 실제로 지나간 가격만으로 계산할 수 있는
    '지금까지의 변동성'을 씁니다. 정확히 같은 값은 아니지만 같은
    방향으로 움직이고, 외부 데이터 없이 항상 계산됩니다.

    일간 수익률의 표준편차에 연간 거래일수(252) 제곱근을 곱합니다.
    """
    if window < 2:
        raise ValueError(f"window 는 2 이상이어야 합니다: {window}")
    returns = close.pct_change()
    return returns.rolling(window, min_periods=window).std() * (252 ** 0.5) * 100.0


def drawdown_from_high(close: pd.Series, window: int = 252) -> pd.Series:
    """최근 window 일 고점 대비 낙폭 (%, 양수).

    MDD(최대낙폭)와 이름이 비슷하지만 다릅니다. MDD 는 과거 구간에서
    가장 컸던 낙폭이고, 이 함수는 '지금 고점에서 얼마나 내려와 있나'
    입니다. 시장 상태 판정에는 이쪽이 맞습니다.
    """
    peak = close.rolling(window, min_periods=1).max()
    return (peak - close) / peak * 100.0


def gap_pct(today_open: float, prev_close: float) -> float:
    """갭 비율(%) = (오늘 시가 - 전일 종가) / 전일 종가 * 100."""
    if prev_close <= 0:
        raise ValueError(f"전일 종가가 0 이하입니다: {prev_close}")
    return (today_open - prev_close) / prev_close * 100.0
