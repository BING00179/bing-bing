"""조용하다 깨어나는 종목 찾기 — 우리기술이 움직이기 직전의 모습.

저평가 찾기와는 완전히 다른 도구입니다. 여기서는 재무를 보지 않습니다.
회사가 좋은지 나쁜지도 묻지 않습니다. 오직 **가격과 거래량의 모양**만
봅니다.

우리기술 차트에서 실제로 보였던 것.

    12월까지 3,000원대에서 몇 달 조용히 횡보
      ↓
    거래량이 갑자기 몇 배로 늘면서
      ↓
    그 횡보 구간을 위로 벗어남
      ↓
    3개월에 걸쳐 9배

여기서 찾는 것은 마지막 결과가 아니라 **두 번째·세 번째 단계**입니다.
이미 3배 오른 뒤에 들어가면 늦습니다.

보는 것 네 가지.

    조용했나      최근 60일 가격 범위가 좁은가 (변동성 수축)
    깨어났나      최근 5일 거래대금이 그 전 60일 평균의 몇 배인가
    벗어났나      현재가가 그 횡보 구간 위인가
    아직 이른가   벗어난 지 얼마 안 됐는가 (이미 급등했으면 제외)

⚠️ 검증된 것이 아닙니다. 이건 '탐지기' 이지 '전략' 이 아닙니다.

  전에 만든 추세추종 스캐너는 5,078건을 돌려보니 PF 0.779 였습니다.
  같은 실수를 반복하지 않으려고, 이 조건도 diagnose-kr 로 우위가
  있는지 먼저 재 볼 수 있게 만들었습니다. 재보기 전에는 후보 목록일
  뿐이고 매수 신호가 아닙니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Setup:
    """무엇을 '조용하다 깨어남' 으로 볼지."""
    base_days: int = 60           # 조용했는지 보는 기간
    surge_days: int = 5           # 거래량이 터진 걸 보는 기간
    max_base_range_pct: float = 45.0   # 이 안에서만 움직였으면 '조용했다'
    min_volume_mult: float = 3.0       # 평소 거래대금의 몇 배 이상
    max_runup_pct: float = 40.0        # 이미 이만큼 올랐으면 늦음
    min_turnover: float = 500_000_000  # 하루 거래대금 하한 (5억)
    breakout_lookback: int = 60        # 이 기간 고가를 넘었는가


def base_range_pct(daily: pd.DataFrame, window: int, offset: int = 0) -> pd.Series:
    """직전 window일 동안 가격이 얼마나 좁게 움직였나 (%).

    offset 을 주면 그만큼 앞의 구간을 봅니다. 거래량이 터진 최근 며칠은
    빼고 '그 전에 조용했는지' 를 봐야 하기 때문입니다.
    """
    high = daily["high"].shift(offset).rolling(window, min_periods=window).max()
    low = daily["low"].shift(offset).rolling(window, min_periods=window).min()
    return (high / low - 1.0) * 100.0


def volume_multiple(daily: pd.DataFrame, surge_days: int, base_days: int) -> pd.Series:
    """최근 며칠 거래대금이 그 전 평균의 몇 배인가."""
    turnover = daily["close"] * daily["volume"]
    recent = turnover.rolling(surge_days, min_periods=surge_days).mean()
    # 최근 구간을 빼고 그 앞을 평균냅니다. 안 그러면 스스로를 나눕니다.
    base = turnover.shift(surge_days).rolling(base_days, min_periods=base_days).mean()
    return (recent / base.where(base > 0)).replace([np.inf, -np.inf], np.nan)


def runup_pct(daily: pd.DataFrame, window: int) -> pd.Series:
    """직전 window일 최저 종가 대비 지금 몇 % 올라와 있나."""
    low = daily["close"].rolling(window, min_periods=window).min()
    return (daily["close"] / low.where(low > 0) - 1.0) * 100.0


def broke_out(daily: pd.DataFrame, lookback: int, offset: int = 1) -> pd.Series:
    """오늘 종가가 직전 lookback일 고가를 넘었나.

    offset=1 이면 오늘을 뺀 어제까지의 고가와 견줍니다. 오늘 고가를
    포함하면 언제나 참이 되어 아무 뜻이 없습니다.
    """
    prior_high = daily["high"].shift(offset).rolling(
        lookback, min_periods=lookback
    ).max()
    return daily["close"] > prior_high


def broke_out_recently(daily: pd.DataFrame, lookback: int, within: int) -> pd.Series:
    """최근 within일 안에 박스를 벗어난 적이 있나.

    돌파는 하루짜리 사건이고 거래량은 며칠에 걸쳐 터집니다. 둘을 같은
    날에만 요구하면, 돌파한 첫날에는 아직 거래량 평균이 안 오르고
    거래량이 오를 때쯤엔 이미 신고가가 아니어서 영영 안 걸립니다.
    실제 차트 모양과 맞지 않는 조건이었습니다.
    """
    return broke_out(daily, lookback).rolling(within, min_periods=1).max().astype(bool)


def signals(daily: pd.DataFrame, cfg: Setup) -> pd.DataFrame:
    """조건별 참·거짓과 최종 신호를 날짜별로.

    ⚠️ 모든 값은 그날 종가까지만으로 계산됩니다. 미래를 보지 않습니다.
    """
    turnover = daily["close"] * daily["volume"]
    frame = pd.DataFrame(index=daily.index)

    frame["박스폭%"] = base_range_pct(daily, cfg.base_days, offset=cfg.surge_days)
    frame["거래량배수"] = volume_multiple(daily, cfg.surge_days, cfg.base_days)
    frame["상승률%"] = runup_pct(daily, cfg.base_days)
    frame["거래대금"] = turnover

    frame["1_조용했나"] = frame["박스폭%"] <= cfg.max_base_range_pct
    frame["2_깨어났나"] = frame["거래량배수"] >= cfg.min_volume_mult
    frame["3_벗어났나"] = broke_out_recently(
        daily, cfg.breakout_lookback, cfg.surge_days
    )
    frame["4_아직이른가"] = frame["상승률%"] <= cfg.max_runup_pct
    frame["5_사고팔수있나"] = turnover >= cfg.min_turnover

    조건 = ["1_조용했나", "2_깨어났나", "3_벗어났나", "4_아직이른가", "5_사고팔수있나"]
    frame["signal"] = frame[조건].fillna(False).all(axis=1)
    return frame


def score(row: pd.Series) -> float:
    """신호끼리 줄 세우기 위한 점수.

    거래량이 많이 터질수록, 박스가 좁았을수록, 아직 덜 올랐을수록 높게.
    ⚠️ 이 점수가 수익을 예측한다는 근거는 아직 없습니다. 전에 만든
    점수 체계는 상위 종목이 오히려 더 나빴습니다(PF 0.779 → 0.626).
    """
    배수 = float(row.get("거래량배수", np.nan))
    폭 = float(row.get("박스폭%", np.nan))
    상승 = float(row.get("상승률%", np.nan))
    if any(pd.isna(v) for v in (배수, 폭, 상승)):
        return 0.0
    return (min(배수, 20.0) * 5.0            # 거래량 폭발 (최대 100)
            + max(0.0, 50.0 - 폭)            # 박스가 좁을수록 (최대 50)
            + max(0.0, 40.0 - 상승))         # 덜 올랐을수록 (최대 40)


@dataclass
class Hit:
    code: str
    name: str
    date: pd.Timestamp
    close: float
    volume_mult: float
    base_range_pct: float
    runup_pct: float
    turnover: float
    score: float


def scan_today(frames: dict[str, pd.DataFrame], cfg: Setup,
               names: dict[str, str] | None = None,
               on_date: pd.Timestamp | None = None) -> list[Hit]:
    """오늘(또는 지정한 날) 신호가 난 종목들."""
    names = names or {}
    hits: list[Hit] = []
    for code, daily in frames.items():
        if len(daily) < cfg.base_days + cfg.surge_days + 5:
            continue
        table = signals(daily, cfg)
        날 = on_date if on_date is not None else table.index[-1]
        if 날 not in table.index or not bool(table.at[날, "signal"]):
            continue
        row = table.loc[날]
        hits.append(Hit(
            code=code, name=names.get(code, code), date=날,
            close=float(daily.at[날, "close"]),
            volume_mult=float(row["거래량배수"]),
            base_range_pct=float(row["박스폭%"]),
            runup_pct=float(row["상승률%"]),
            turnover=float(row["거래대금"]),
            score=score(row),
        ))
    return sorted(hits, key=lambda h: h.score, reverse=True)


def signal_dates(daily: pd.DataFrame, cfg: Setup) -> pd.DatetimeIndex:
    """과거 전체에서 신호가 났던 날들. 검증용."""
    table = signals(daily, cfg)
    return pd.DatetimeIndex(table.index[table["signal"].to_numpy()])


def report(hits: list[Hit], cfg: Setup, top: int = 20) -> str:
    lines = ["=" * 86,
             "[깨어나는 종목] 조용하던 종목에 거래량이 터지며 박스를 벗어난 것",
             "=" * 86, ""]

    lines.append("[사실] 건 조건")
    lines.append(f"   조용했나   최근 {cfg.base_days}일 가격 범위 ≤ {cfg.max_base_range_pct}%"
                 f" (최근 {cfg.surge_days}일은 빼고 잼)")
    lines.append(f"   깨어났나   최근 {cfg.surge_days}일 거래대금 ≥ 그 전 평균의 "
                 f"{cfg.min_volume_mult}배")
    lines.append(f"   벗어났나   종가가 직전 {cfg.breakout_lookback}일 고가 돌파")
    lines.append(f"   아직이른가 {cfg.base_days}일 최저 대비 상승률 ≤ {cfg.max_runup_pct}%")
    lines.append(f"   사고팔수있나 하루 거래대금 ≥ {cfg.min_turnover / 1e8:,.1f}억")
    lines.append("")

    if not hits:
        lines.append("[사실] 오늘 조건에 맞는 종목이 없습니다.")
        lines.append("")
        lines.append("   드물게 나오는 것이 정상입니다. 조용하다 깨어나는 순간은")
        lines.append("   자주 오지 않습니다. 억지로 조건을 풀어 매일 몇 건씩 나오게")
        lines.append("   만들면, 그건 다른 것을 찾는 도구가 됩니다.")
    else:
        lines.append(f"[사실] {len(hits)}종목")
        lines.append("")
        lines.append("   순위  종목명            코드      종가"
                     "    거래량배수  박스폭  상승률   거래대금")
        lines.append("   " + "-" * 80)
        for i, h in enumerate(hits[:top], 1):
            lines.append(
                f"   {i:>3}  {h.name[:14]:<14}  {h.code}  {h.close:>9,.0f}"
                f"   {h.volume_mult:>7.1f}배  {h.base_range_pct:>5.1f}%"
                f"  {h.runup_pct:>5.1f}%  {h.turnover / 1e8:>7.1f}억"
            )

    lines.append("")
    lines.append("[해석] 이 목록은 검증된 것이 아닙니다.")
    lines.append("   · 전에 만든 추세추종 스캐너는 5,078건을 돌려보니 PF 0.779,")
    lines.append("     즉 돈을 잃는 쪽이었습니다. 같은 실수를 반복하지 않으려면")
    lines.append("     이 조건도 먼저 재 봐야 합니다:")
    lines.append("       python -m src.cli diagnose-kr --setup breakout ...")
    lines.append("   · 재보기 전까지 이것은 '확인해 볼 거리' 이지 매수 신호가 아닙니다.")
    lines.append("   · 거래량이 터졌다는 것은 누군가 사고 있다는 뜻일 뿐,")
    lines.append("     그 사람이 옳다는 뜻은 아닙니다.")
    lines.append("=" * 86)
    return "\n".join(lines)
