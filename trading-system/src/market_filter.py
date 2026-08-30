"""시장 필터 — "지금 시장이 살 만한가?"

종목 스캐너 위에 얹는 층입니다. 시장이 무너질 때는 아무리 좋은
종목도 같이 빠지므로, 그런 날은 매수 신호를 아예 내보내지 않습니다.

    1층: 시장 필터  ← 이 파일
         코스피가 200일선 위인가, 얼마나 떨어졌나, 변동성은?
              ↓ 통과할 때만
    2층: 종목 스캐너
         시가갭 + 정배열 + 신고가 갱신

보는 지표 네 가지. 전부 지수 일봉만으로 계산되므로 외부 API 키가
필요 없고, 조회 실패로 시스템이 멈추는 일이 없습니다.

  200일 이동평균선   장기 추세. 아래면 하락 국면
  고점 대비 낙폭     52주 고점에서 얼마나 내려와 있나
  실현 변동성        최근 20일 흔들림. VKOSPI 대용
  RSI                과매도·과열

원문 카드뉴스의 '공포지수'와 'VIX'는 넣지 않았습니다.
  * 공포지수(CNN Fear & Greed)는 미국 시장 전용이라 국내 대응물이 없습니다.
  * VIX 도 미국 지표입니다. 국내는 VKOSPI 가 대응되지만 무료로 안정적인
    조회 경로가 마땅치 않아, 직접 계산되는 실현 변동성으로 대체했습니다.
없는 데이터를 있는 척하는 것보다 계산되는 값만 쓰는 편이 낫습니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .config import MarketFilterConfig
from .indicators import drawdown_from_high, realized_volatility, rsi, sma

NORMAL, CAUTION, DANGER = "정상", "주의", "위험"


@dataclass
class MarketState:
    index_name: str
    close: float
    sma_slow: float
    above_sma_slow: bool
    rsi: float
    drawdown_pct: float
    volatility_pct: float
    verdict: str                 # 정상 / 주의 / 위험
    reasons: list[str]           # 주의·위험 판정의 근거
    tradable: bool               # 매수 신호를 내보내도 되는가

    def as_report(self) -> str:
        mark = {NORMAL: "🟢", CAUTION: "🟡", DANGER: "🔴"}[self.verdict]
        lines = [
            f"{mark} 시장 상태: {self.verdict}",
            f"   {self.index_name} {self.close:,.2f}"
            f" (200일선 {self.sma_slow:,.2f} {'위' if self.above_sma_slow else '아래'})",
            f"   고점대비 -{self.drawdown_pct:.1f}%"
            f" · 변동성 {self.volatility_pct:.1f}%"
            f" · RSI {self.rsi:.0f}",
        ]
        if self.reasons:
            lines.append("   사유: " + ", ".join(self.reasons))
        if not self.tradable:
            lines.append("   → 매수 신호를 내보내지 않습니다.")
        return "\n".join(lines)


def evaluate(
    index_daily: pd.DataFrame,
    cfg: MarketFilterConfig,
    index_name: str = "코스피",
) -> MarketState:
    """지수 일봉으로 시장 상태를 판정합니다."""
    if "close" not in index_daily.columns:
        raise ValueError("지수 데이터에 close 컬럼이 없습니다.")

    close = index_daily["close"]
    needed = max(cfg.sma_slow, cfg.volatility_window, cfg.rsi_window) + 1
    if len(close) < needed:
        raise ValueError(
            f"시장 판정에 일봉 {needed}개가 필요한데 {len(close)}개뿐입니다."
        )

    last_close = float(close.iloc[-1])
    sma_slow = float(sma(close, cfg.sma_slow).iloc[-1])
    rsi_value = float(rsi(close, cfg.rsi_window).iloc[-1])
    drawdown = float(drawdown_from_high(close, cfg.drawdown_window).iloc[-1])
    volatility = float(realized_volatility(close, cfg.volatility_window).iloc[-1])

    above = last_close > sma_slow

    danger: list[str] = []
    caution: list[str] = []

    if not above:
        danger.append(f"지수가 {cfg.sma_slow}일선 아래")
    if drawdown >= cfg.drawdown_danger_pct:
        danger.append(f"고점대비 -{drawdown:.1f}%")
    elif drawdown >= cfg.drawdown_caution_pct:
        caution.append(f"고점대비 -{drawdown:.1f}%")
    if volatility >= cfg.volatility_danger_pct:
        danger.append(f"변동성 {volatility:.1f}%")
    elif volatility >= cfg.volatility_caution_pct:
        caution.append(f"변동성 {volatility:.1f}%")
    if rsi_value <= cfg.rsi_oversold:
        caution.append(f"RSI {rsi_value:.0f} 과매도")
    elif rsi_value >= cfg.rsi_overbought:
        caution.append(f"RSI {rsi_value:.0f} 과열")

    if danger:
        verdict = DANGER
    elif caution:
        verdict = CAUTION
    else:
        verdict = NORMAL

    tradable = verdict == NORMAL or (verdict == CAUTION and not cfg.block_on_caution)

    return MarketState(
        index_name=index_name,
        close=round(last_close, 2),
        sma_slow=round(sma_slow, 2),
        above_sma_slow=above,
        rsi=round(rsi_value, 1),
        drawdown_pct=round(drawdown, 2),
        volatility_pct=round(volatility, 2),
        verdict=verdict,
        reasons=danger + caution,
        tradable=tradable,
    )


def to_row(state: MarketState) -> dict:
    row = asdict(state)
    row["reasons"] = " | ".join(state.reasons)
    return row
