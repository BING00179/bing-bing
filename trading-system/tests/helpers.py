"""테스트용 합성 데이터 생성기. 네트워크를 쓰지 않습니다."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_daily(closes, *, highs=None, lows=None, opens=None, start="2024-01-02"):
    """종가 배열로 일봉 DataFrame 을 만듭니다.

    기본값에서는 고가 = 종가(그날 고가에 붙어 마감), 저가 = 종가 * 0.99,
    시가 = 직전 종가로 두어 조건 판정이 예측 가능하게 합니다.
    """
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    highs = np.asarray(highs, dtype=float) if highs is not None else closes.copy()
    lows = np.asarray(lows, dtype=float) if lows is not None else closes * 0.99
    if opens is None:
        opens = np.concatenate([[closes[0]], closes[:-1]])
    opens = np.asarray(opens, dtype=float)

    index = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(n, 1_000_000, dtype=float),
        },
        index=index,
    )


def rising(n: int, start: float = 100.0, step: float = 1.0):
    """매일 step 씩 오르는 종가 배열."""
    return start + np.arange(n, dtype=float) * step
