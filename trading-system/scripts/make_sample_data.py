"""동작 확인용 합성 일봉 CSV 만들기.

인터넷이나 yfinance 없이 백테스트가 도는지 확인할 때 씁니다.

    python3 scripts/make_sample_data.py
    python3 -m src.cli backtest --csv-dir data/daily

⚠️ 여기서 나오는 가격은 난수로 만든 가짜입니다. 이 데이터로 나온
   백테스트 숫자는 전략의 성능과 아무 관련이 없습니다. 배관이
   제대로 연결됐는지만 확인하는 용도입니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TICKERS = ["AAPL", "MSFT", "NVDA"]


def make(ticker: str, seed: int, days: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0006, 0.018, days)
    close = 100 * np.exp(np.cumsum(rets))
    op = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.003, days))
    high = close * (1 + np.abs(rng.normal(0, 0.008, days)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, days)))

    frame = pd.DataFrame(
        {
            "open": op,
            "high": np.maximum(high, np.maximum(op, close)),
            "low": np.minimum(low, np.minimum(op, close)),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, days),
        },
        index=pd.bdate_range("2023-01-02", periods=days),
    )
    frame.index.name = "Date"
    return frame


def main() -> int:
    out = ROOT / "data" / "daily"
    out.mkdir(parents=True, exist_ok=True)
    for i, ticker in enumerate(TICKERS):
        make(ticker, seed=42 + i).to_csv(out / f"{ticker}.csv")
    print(f"합성 CSV {len(TICKERS)}개 생성: {out}")
    print("⚠️ 가짜 데이터입니다. 성능 판단에 쓰지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
