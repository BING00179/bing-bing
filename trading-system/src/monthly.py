"""월말 브리핑 — 지난 한 달, 고른 종목들이 실제로 어떻게 됐나.

매달 말일에 지난 기록을 돌아봅니다.

    이번 달에 고른 종목이 몇 개였고
    그중 몇 개가 코스닥 지수를 이겼고
    어떤 조건일 때 잘 됐고 못 됐나

이건 '수익 보고서' 가 아닙니다. 아직 돈을 넣지 않았으니까요.
**고르는 규칙이 맞는지 확인하는 성적표** 입니다.

## 여기 있는 함정 — 먼저 적어 둡니다

조건별로 쪼개서 보면 반드시 뭔가 눈에 띕니다. 30건을 거래량 배수로
셋으로 나누면 한 칸은 10건뿐이고, 그 10건이 우연히 좋을 확률은
꽤 높습니다. 그걸 보고 "거래량 5배 이상만 사면 되겠네" 하면, 그게
바로 지금까지 우리가 피해온 자기합리화입니다.

그래서 이 보고서는 쪼갠 표에 항상 건수를 같이 적고, 건수가 적으면
'참고만' 이라고 못 박습니다. **여기 맞춰 규칙을 바꾸면 그날부터
시계가 다시 갑니다.**
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# 조건별로 쪼갤 때 쓰는 구간. 미리 정해 둡니다 — 결과를 보고 나서
# 경계를 옮기면 원하는 그림을 만들 수 있습니다.
BUCKETS = {
    "거래량배수": ([-np.inf, 3, 5, 10, np.inf], ["3배 미만", "3~5배", "5~10배", "10배+"]),
    "박스폭%": ([-np.inf, 20, 30, 45, np.inf], ["20% 미만", "20~30%", "30~45%", "45%+"]),
    "상승률%": ([-np.inf, 10, 20, 40, np.inf], ["10% 미만", "10~20%", "20~40%", "40%+"]),
    "갭%": ([-np.inf, 0, 2, 5, np.inf], ["갭 없음/하락", "0~2%", "2~5%", "5%+"]),
}

MIN_FOR_HINT = 8        # 이보다 적으면 표에 내지 않습니다
MIN_FOR_TRUST = 30      # 이보다 적으면 무슨 값이 나와도 판정하지 않습니다


@dataclass
class Slice:
    label: str
    count: int
    mean_excess: float
    win_rate: float


def by_condition(scored: pd.DataFrame, column: str) -> list[Slice]:
    """조건 구간별 초과수익. 건수를 반드시 같이 냅니다."""
    if scored.empty or column not in scored or column not in BUCKETS:
        return []
    edges, labels = BUCKETS[column]
    part = scored[[column, "excess"]].dropna()
    if part.empty:
        return []
    bucket = pd.cut(part[column], bins=edges, labels=labels)
    out: list[Slice] = []
    for label, group in part.groupby(bucket, observed=False):
        if len(group) < MIN_FOR_HINT:
            continue
        out.append(Slice(
            label=str(label), count=len(group),
            mean_excess=float(group["excess"].mean()),
            win_rate=float((group["excess"] > 0).mean() * 100.0),
        ))
    return out


# ── 값이 어떻게 움직였나 ──
# 최종 수익률이 같아도 거기까지 가는 길은 전혀 다릅니다. 바로 오른 것과
# 한참 빠졌다 돌아온 것은 같은 +5% 라도 우리 규칙에 걸리는 게 다릅니다.
#   · 바로 오름       → 짧게 들고도 잡힘
#   · 횡보 후 상승    → 좁은 손절이면 중간에 잘림
#   · 손실 후 반등    → 3% 손절이었으면 못 버팀
#   · 고점 후 반락    → 익절 규칙이 필요하다는 뜻
# 그래서 '무엇을 고쳐야 하나' 에 바로 이어집니다.

EARLY_DAYS = 5              # '초반' 을 며칠로 볼지
FLAT_BAND_PCT = 3.0         # 이 안에서만 움직였으면 횡보로 봄
DIP_PCT = -5.0              # 이만큼 빠졌으면 손실 구간에 갔다고 봄
RUN_PCT = 10.0              # 이만큼 올랐으면 목표에 닿았다고 봄

SHAPES = ("바로 상승", "횡보 후 상승", "손실 후 반등", "고점 후 반락",
          "선정 직후 하락", "그 밖")


@dataclass
class Path:
    shape: str
    final_pct: float
    max_gain_pct: float
    max_loss_pct: float
    days_to_peak: int
    early_pct: float          # 초반 며칠 동안의 움직임(종가 기준)


def path_shape(daily: pd.DataFrame, entry_date, horizon: int = 20) -> Path | None:
    """진입 후 값이 어떤 모양으로 움직였나.

    ⚠️ 이건 지나간 일을 설명하는 것이지 예측이 아닙니다. 결과를 알고
    나서 붙이는 이름이므로, 이걸로 앞일을 맞힐 수 있다고 읽으면 안 됩니다.
    """
    entry_date = pd.Timestamp(entry_date)
    if entry_date not in daily.index:
        return None
    자리 = daily.index.get_loc(entry_date)
    창 = daily.iloc[자리:자리 + horizon]
    if len(창) < 2:
        return None

    시가 = float(창["open"].iloc[0])
    if not np.isfinite(시가) or 시가 <= 0:
        return None

    종가들 = 창["close"].to_numpy(dtype=float)
    고가들 = 창["high"].to_numpy(dtype=float)
    저가들 = 창["low"].to_numpy(dtype=float)

    최종 = (종가들[-1] / 시가 - 1.0) * 100.0
    최대이익 = (float(np.nanmax(고가들)) / 시가 - 1.0) * 100.0
    최대손실 = (float(np.nanmin(저가들)) / 시가 - 1.0) * 100.0
    고점까지 = int(np.nanargmax(고가들)) + 1
    초반 = (종가들[min(EARLY_DAYS, len(종가들)) - 1] / 시가 - 1.0) * 100.0
    초반저가 = (float(np.nanmin(저가들[:min(EARLY_DAYS, len(저가들))])) / 시가
              - 1.0) * 100.0

    # 순서가 곧 규칙입니다. 앞의 것부터 맞으면 그것으로 정합니다.
    if 최대이익 >= RUN_PCT and 최종 < 최대이익 / 2.0:
        모양 = "고점 후 반락"
    elif 최대손실 <= DIP_PCT and 최종 > 0:
        모양 = "손실 후 반등"
    elif 초반저가 <= DIP_PCT and 최종 <= 0:
        모양 = "선정 직후 하락"
    elif abs(초반) <= FLAT_BAND_PCT and 최종 > FLAT_BAND_PCT:
        모양 = "횡보 후 상승"
    elif 최종 > FLAT_BAND_PCT and 고점까지 <= EARLY_DAYS:
        모양 = "바로 상승"
    else:
        모양 = "그 밖"

    return Path(shape=모양, final_pct=최종, max_gain_pct=최대이익,
                max_loss_pct=최대손실, days_to_peak=고점까지, early_pct=초반)


def by_shape(scored: pd.DataFrame) -> pd.DataFrame:
    """모양별로 몇 건이었고 평균이 어땠나."""
    if scored.empty or "모양" not in scored:
        return pd.DataFrame()
    part = scored.dropna(subset=["excess"])
    if part.empty:
        return pd.DataFrame()
    grouped = part.groupby("모양", observed=False)
    표 = pd.DataFrame({
        "건수": grouped.size(),
        "평균초과%": grouped["excess"].mean().round(2),
        "평균최대손실%": (grouped["최대손실%"].mean().round(1)
                     if "최대손실%" in part else np.nan),
        "평균최대이익%": (grouped["최대이익%"].mean().round(1)
                     if "최대이익%" in part else np.nan),
    })
    순서 = [s for s in SHAPES if s in 표.index]
    return 표.reindex(순서).dropna(how="all")


@dataclass
class Summary:
    setup: str
    count: int
    mean_excess: float
    median_excess: float
    win_rate: float
    best: tuple[str, str, float] | None      # (종목명, 코드, 초과수익)
    worst: tuple[str, str, float] | None


def summarize(scored: pd.DataFrame, setup: str) -> Summary | None:
    part = scored[scored["setup"] == setup] if "setup" in scored else scored
    part = part.dropna(subset=["excess"])
    if part.empty:
        return None
    좋은것 = part.loc[part["excess"].idxmax()]
    나쁜것 = part.loc[part["excess"].idxmin()]
    return Summary(
        setup=setup, count=len(part),
        mean_excess=float(part["excess"].mean()),
        median_excess=float(part["excess"].median()),
        win_rate=float((part["excess"] > 0).mean() * 100.0),
        best=(str(좋은것["name"]), str(좋은것["code"]), float(좋은것["excess"])),
        worst=(str(나쁜것["name"]), str(나쁜것["code"]), float(나쁜것["excess"])),
    )


SETUP_LABEL = {"breakout": "깨어나는 종목", "value": "저평가 후보"}


def _pct(value: float) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:+.2f}%"


def report(scored: pd.DataFrame, period: str, horizon: int,
           recorded: int = 0, waiting: int = 0, basis: str = "") -> str:
    """텔레그램으로 보낼 만큼 짧게. 사실과 해석을 갈라 적습니다."""
    lines = [f"📋 월말 브리핑 — {period}", ""]

    lines.append(f"[사실] 이번 기간 기록 {recorded}건 · "
                 f"채점 {len(scored)}건 · 대기 {waiting}건")
    lines.append(f"       채점 기준: 진입일 시가 → {horizon}거래일 뒤 종가,")
    lines.append("       코스닥 지수 같은 기간 수익률을 뺀 값(초과수익)")
    if basis:
        # 나중에 '그때 어떻게 쟀지?' 를 물을 수 있어야 합니다.
        lines.append(f"       계산 기준: {basis}")
    lines.append("")

    if scored.empty:
        lines.append("아직 채점할 것이 없습니다.")
        lines.append(f"신호가 난 뒤 {horizon}거래일이 지나야 성적이 나옵니다.")
        return "\n".join(lines)

    있는설정 = [s for s in ("breakout", "value")
              if "setup" in scored and (scored["setup"] == s).any()]
    for setup in 있는설정 or ["breakout"]:
        요약 = summarize(scored, setup)
        if 요약 is None:
            continue
        이름 = SETUP_LABEL.get(setup, setup)
        lines.append(f"■ {이름} — {요약.count}건")
        lines.append(f"   평균 초과수익 {_pct(요약.mean_excess)}"
                     f" · 중앙값 {_pct(요약.median_excess)}")
        lines.append(f"   지수를 이긴 비율 {요약.win_rate:.0f}%")
        if 요약.best:
            lines.append(f"   가장 좋았던 것  {요약.best[0]}({요약.best[1]})"
                         f" {요약.best[2]:+.1f}%")
        if 요약.worst:
            lines.append(f"   가장 나빴던 것  {요약.worst[0]}({요약.worst[1]})"
                         f" {요약.worst[2]:+.1f}%")
        lines.append("")

    # 조건별 — 어떤 모양일 때 실제로 올랐나
    쪼갠것 = []
    for column in BUCKETS:
        조각들 = by_condition(scored, column)
        if len(조각들) >= 2:
            쪼갠것.append((column, 조각들))

    if 쪼갠것:
        lines.append("[사실] 어떤 조건일 때 어땠나")
        for column, 조각들 in 쪼갠것:
            lines.append(f"   〈{column}〉")
            for s in 조각들:
                lines.append(f"     {s.label:<12} {s.count:>3}건"
                             f"  평균 {_pct(s.mean_excess):>8}"
                             f"  이긴비율 {s.win_rate:>3.0f}%")
        lines.append("")

    모양표 = by_shape(scored)
    if not 모양표.empty:
        lines.append("[사실] 값이 어떻게 움직였나 — 같은 결과라도 길이 다릅니다")
        lines.append("   " + 모양표.to_string().replace("\n", "\n   "))
        lines.append("")
        lines.append("   손실 후 반등·횡보 후 상승이 많으면 → 손절이 좁아서 중간에")
        lines.append("     잘려나가고 있다는 뜻입니다.")
        lines.append("   고점 후 반락이 많으면 → 익절 규칙이 없어서 되돌려주고")
        lines.append("     있다는 뜻입니다.")
        lines.append("   선정 직후 하락이 많으면 → 진입 시점이 늦다는 뜻입니다.")
        lines.append("")

    lines.append("[해석] 이 표를 읽는 법")
    전체 = len(scored.dropna(subset=["excess"]))
    if 전체 < MIN_FOR_TRUST:
        lines.append(f"   · 아직 {전체}건입니다. {MIN_FOR_TRUST}건은 넘어야 판정을")
        lines.append("     시작합니다. 지금 숫자가 좋아도 아무 뜻이 없습니다.")
    lines.append("   · 조건별 표는 참고만 하십시오. 표본을 여러 조각으로")
    lines.append("     나누면 그중 하나는 우연히 좋아 보입니다.")
    lines.append("   · 이 표를 보고 조건을 바꾸면 그날부터 시계가 다시 갑니다.")
    lines.append("     지금까지 쌓은 것은 바뀐 조건의 증거가 되지 못합니다.")
    lines.append("   · 아직 돈은 한 푼도 들어가지 않았습니다. 이건 수익 보고서가")
    lines.append("     아니라 고르는 규칙의 성적표입니다.")
    return "\n".join(lines)
