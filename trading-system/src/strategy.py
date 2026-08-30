"""Trend Join Long 전략의 조건 판정.

원문에서 제시한 5가지 조건:
  1. 전날 일봉 고가보다 위에 있을 것
  2. 전날 종가가 200일 이동평균선보다 위일 것
  3. 오늘 프리마켓 고가보다 위에 있을 것
  4. 오늘 일봉 고가보다 위에 있을 것
  5. 위 4가지 흐름이 상승 추세와 일치할 것

조건 3(프리마켓 고가)은 일봉 데이터에 존재하지 않습니다. 그래서
  - 실시간 스캔(scanner_b): 분봉 프리마켓 데이터로 실제 판정
  - 과거 백테스트(backtest): 판정 불가 → 명시적으로 제외
로 나눠서 다룹니다. 이 차이는 백테스트 결과에 그대로 남으므로
리포트에 항상 함께 표시합니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import ScannerBConfig
from .indicators import sma, trend_aligned

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class ConditionResult:
    """한 종목·한 시점의 조건 판정 결과."""

    ticker: str
    c1_above_prev_high: bool
    c2_prev_close_above_sma_slow: bool
    c3_above_premarket_high: bool | None  # None = 판정 불가(데이터 없음)
    c4_above_today_high: bool
    c5_trend_aligned: bool
    price: float
    prev_high: float
    prev_close: float
    sma_slow: float
    premarket_high: float | None
    today_high: float

    @property
    def passed(self) -> bool:
        """5개 조건 모두 통과했는지.

        c3 가 None(판정 불가)이면 통과로 치지 않습니다.
        """
        return all(
            [
                self.c1_above_prev_high,
                self.c2_prev_close_above_sma_slow,
                self.c3_above_premarket_high is True,
                self.c4_above_today_high,
                self.c5_trend_aligned,
            ]
        )

    @property
    def failed_conditions(self) -> list[str]:
        checks = {
            "1_전날고가돌파": self.c1_above_prev_high,
            "2_전날종가>200MA": self.c2_prev_close_above_sma_slow,
            "3_프리마켓고가돌파": self.c3_above_premarket_high,
            "4_오늘고가돌파": self.c4_above_today_high,
            "5_상승추세정렬": self.c5_trend_aligned,
        }
        return [name for name, ok in checks.items() if ok is not True]


def _validate(daily: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in daily.columns]
    if missing:
        raise ValueError(f"일봉 데이터에 다음 컬럼이 없습니다: {missing}")


def evaluate(
    ticker: str,
    daily: pd.DataFrame,
    price: float,
    today_high: float,
    premarket_high: float | None,
    cfg: ScannerBConfig,
) -> ConditionResult:
    """실시간 시점의 5조건 판정.

    daily 는 '어제까지'의 확정 일봉이어야 합니다(오늘 봉 제외).
    price 는 현재가, today_high 는 오늘 장중 지금까지의 고가입니다.
    """
    _validate(daily)
    if len(daily) < cfg.sma_slow:
        raise ValueError(
            f"{ticker}: {cfg.sma_slow}일 이동평균 계산에 일봉 {cfg.sma_slow}개가 "
            f"필요한데 {len(daily)}개뿐입니다."
        )

    tol = 1.0 - cfg.breakout_tolerance_pct / 100.0
    near_high = 1.0 - cfg.close_near_high_pct / 100.0
    prev = daily.iloc[-1]
    prev_high = float(prev["high"])
    prev_close = float(prev["close"])
    sma_slow_value = float(sma(daily["close"], cfg.sma_slow).iloc[-1])
    aligned = bool(
        trend_aligned(daily["close"], cfg.sma_fast, cfg.sma_mid, cfg.sma_slow).iloc[-1]
    )

    if premarket_high is None:
        c3: bool | None = None if cfg.require_premarket_high else True
    else:
        c3 = price >= premarket_high * tol

    return ConditionResult(
        ticker=ticker,
        c1_above_prev_high=price >= prev_high * tol,
        c2_prev_close_above_sma_slow=prev_close > sma_slow_value,
        c3_above_premarket_high=c3,
        # '오늘 일봉 고가보다 위' = 지금 값이 오늘 장중 신고가를 만들고 있다는 뜻.
        # 오늘 고가는 현재가가 계속 갱신하는 값이라 완전 일치를 요구하면 신호가
        # 나오지 않습니다. close_near_high_pct 만큼의 여유를 둡니다.
        c4_above_today_high=price >= today_high * near_high,
        c5_trend_aligned=aligned,
        price=price,
        prev_high=prev_high,
        prev_close=prev_close,
        sma_slow=sma_slow_value,
        premarket_high=premarket_high,
        today_high=today_high,
    )


def signals_from_daily(daily: pd.DataFrame, cfg: ScannerBConfig) -> pd.DataFrame:
    """일봉만으로 과거 신호를 계산합니다(백테스트용).

    반환 DataFrame 의 컬럼:
      c1, c2, c4, c5, signal  (c3 는 일봉에 프리마켓 정보가 없어 제외)

    미래 정보를 쓰지 않도록, 각 날짜의 판정에는 그 날의 종가까지만
    사용하고 진입은 다음 날 시가에서 이뤄집니다(backtest.py 참고).
    """
    _validate(daily)
    close = daily["close"]
    high = daily["high"]
    tol = 1.0 - cfg.breakout_tolerance_pct / 100.0

    ma_slow = sma(close, cfg.sma_slow)

    near_high = 1.0 - cfg.close_near_high_pct / 100.0

    c1 = close >= high.shift(1) * tol
    c2 = close.shift(1) > ma_slow.shift(1)
    # 일봉에는 '장중 신고가 갱신' 정보가 없습니다. 종가가 그날 고가에
    # 바짝 붙어 마감했다는 것으로 조건 4를 근사합니다(허용 폭은 설정값).
    c4 = close >= high * near_high
    c5 = trend_aligned(close, cfg.sma_fast, cfg.sma_mid, cfg.sma_slow)

    out = pd.DataFrame(
        {
            "c1": c1.fillna(False).astype(bool),
            "c2": c2.fillna(False).astype(bool),
            "c4": c4.fillna(False).astype(bool),
            "c5": c5,
        },
        index=daily.index,
    )
    out["signal"] = out["c1"] & out["c2"] & out["c4"] & out["c5"]
    return out
