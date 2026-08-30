"""내일 관찰 후보 — 장 마감 후 다음날을 준비합니다.

장중 스캐너는 "지금 사도 되는가"를 봅니다. 갭이 이미 떴고 신고가를
갱신 중인 종목을 찾죠. 그런데 그건 이미 움직인 뒤입니다.

이 모듈은 반대 시점을 봅니다. 장이 끝난 뒤 오늘 마감 데이터로
"내일 터질 자리에 와 있는 종목"을 미리 추려둡니다. 내일 아침
09:00 에 갭이 뜨는지만 확인하면 되므로, 장 시작 직후의 짧은 시간에
허둥대지 않아도 됩니다.

장중 스캐너와 조건이 다릅니다.

  장중 스캐너            내일 관찰 후보
  ─────────────────      ─────────────────────────
  시가갭 5% 이상    →    (내일 갭은 아직 모름 · 조건에서 뺌)
  전날 고가 돌파    →    최근 고가 근처까지 올라옴 (돌파 임박)
  신고가 갱신 중    →    오늘 고가 근처에서 강하게 마감
  200일선 위        →    같음
  정배열            →    같음

즉 "이미 돌파한 종목"이 아니라 "돌파 직전에서 힘을 모은 종목"을
찾습니다. 내일 갭 상승하면 장중 스캐너가 바로 잡아냅니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .indicators import sma, trend_aligned


@dataclass
class WatchConfig:
    sma_slow: int = 200
    sma_mid: int = 50
    sma_fast: int = 20
    near_breakout_pct: float = 3.0     # 최근 고가에서 몇 % 이내면 '돌파 임박'
    breakout_window: int = 20          # 최근 고가를 볼 기간
    strong_close_pct: float = 1.5      # 종가가 당일 고가에서 몇 % 이내여야 강한 마감
    min_turnover: float = 1_000_000_000.0
    min_price: float = 1_000.0
    max_results: int = 10


@dataclass
class Candidate:
    code: str
    name: str
    close: float
    recent_high: float
    to_breakout_pct: float     # 돌파까지 몇 % 남았나
    sma_slow: float
    turnover: float
    day_change_pct: float      # 오늘 등락률
    reasons: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        label = f"{self.code} {self.name}".strip()
        return (
            f"{label:<16} {self.close:>9,.0f}원  "
            f"돌파까지 {self.to_breakout_pct:>4.1f}%  "
            f"오늘 {self.day_change_pct:>+5.1f}%  "
            f"대금 {self.turnover / 1e8:>6,.0f}억"
        )


def evaluate(
    code: str,
    daily: pd.DataFrame,
    cfg: WatchConfig,
    name: str = "",
) -> Candidate | None:
    """오늘 마감 기준으로 내일 볼 만한 종목인지 판단합니다."""
    if len(daily) < cfg.sma_slow + 1:
        return None

    close = daily["close"]
    today = daily.iloc[-1]
    price = float(today["close"])
    if price < cfg.min_price:
        return None

    turnover = float(today["close"] * today["volume"])
    if turnover < cfg.min_turnover:
        return None

    sma_slow = float(sma(close, cfg.sma_slow).iloc[-1])
    if price <= sma_slow:
        return None                                   # 장기 하락 추세 제외

    if not bool(trend_aligned(close, cfg.sma_fast, cfg.sma_mid, cfg.sma_slow).iloc[-1]):
        return None                                   # 정배열 아님

    # 오늘 봉을 뺀 최근 고가. 오늘 스스로 만든 고가와 비교하면
    # 항상 '돌파 임박' 이 되어 의미가 없습니다.
    window = daily["high"].iloc[-(cfg.breakout_window + 1):-1]
    if window.empty:
        return None
    recent_high = float(window.max())
    if recent_high <= 0:
        return None

    to_breakout = (recent_high - price) / recent_high * 100.0
    if to_breakout < 0:
        to_breakout = 0.0                             # 이미 넘어섰음
    if to_breakout > cfg.near_breakout_pct:
        return None                                   # 아직 멀었음

    day_high = float(today["high"])
    if day_high > 0 and price < day_high * (1 - cfg.strong_close_pct / 100.0):
        return None                                   # 고가에서 밀려서 마감

    day_open = float(today["open"])
    day_change = (price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100.0

    reasons = [
        f"{cfg.breakout_window}일 고가 {recent_high:,.0f}원까지 {to_breakout:.1f}% 남음",
        f"{cfg.sma_slow}일선 {sma_slow:,.0f}원 위",
        "이동평균 정배열",
    ]
    if price >= day_open:
        reasons.append("양봉 마감")
    if day_high > 0:
        reasons.append(f"당일 고가 대비 {(price - day_high) / day_high * 100:+.1f}%")

    return Candidate(
        code=code,
        name=name,
        close=round(price, 1),
        recent_high=round(recent_high, 1),
        to_breakout_pct=round(to_breakout, 2),
        sma_slow=round(sma_slow, 1),
        turnover=round(turnover, 0),
        day_change_pct=round(day_change, 2),
        reasons=reasons,
    )


def rank(candidates: list[Candidate], cfg: WatchConfig) -> list[Candidate]:
    """돌파에 가까운 순으로. 같으면 거래대금이 큰 쪽."""
    ordered = sorted(candidates, key=lambda c: (c.to_breakout_pct, -c.turnover))
    return ordered[: cfg.max_results]


def format_report(candidates: list[Candidate], when: str, scanned: int = 0) -> str:
    header = f"[내일 관찰 후보] {when}"
    if not candidates:
        return (f"{header}\n조건에 맞는 종목이 없습니다."
                + (f" ({scanned}종목 확인)" if scanned else ""))

    lines = [header, f"{len(candidates)}종목 — 돌파 임박 순", ""]
    lines += [c.as_line() for c in candidates]
    lines += [
        "",
        "내일 09:00 에 갭 상승하면 장중 스캐너가 매수 신호를 판단합니다.",
        "※ 관찰 후보일 뿐 매수 신호가 아닙니다.",
    ]
    return "\n".join(lines)
