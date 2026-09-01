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


SHAPE_MEANING = {
    "바로 상승": "고르자마자 올랐습니다",
    "횡보 후 상승": "한동안 제자리였다가 나중에 올랐습니다",
    "손실 후 반등": "먼저 빠졌다가 되돌아왔습니다",
    "고점 후 반락": "올랐다가 도로 내려왔습니다",
    "선정 직후 하락": "고르자마자 빠져서 못 돌아왔습니다",
    "그 밖": "뚜렷한 모양이 없었습니다",
}

SHAPE_LESSON = {
    "횡보 후 상승": "→ 손절을 좁게 잡으면 이런 건 오르기 전에 잘려나갑니다",
    "손실 후 반등": "→ 손절 3% 였다면 이건 전부 잘렸습니다",
    "고점 후 반락": "→ 올랐을 때 파는 규칙이 없어서 되돌려주고 있습니다",
    "선정 직후 하락": "→ 이미 오른 뒤에 들어가고 있다는 뜻일 수 있습니다",
}


@dataclass
class NextMonth:
    """다음 달에 무엇을 봐야 하나."""
    waiting: int = 0            # 아직 성적이 안 나온 것
    scored_so_far: int = 0      # 지금까지 성적이 나온 것 (누적)
    need_more: int = 0          # 판정까지 몇 개 더 필요한가
    target_hit: int = 0         # 목표에 닿은 것
    invalid_hit: int = 0        # 무효선에 닿은 것
    still_open: int = 0         # 목표도 무효도 아직인 것


def next_month(ledger: pd.DataFrame, scored_total: int,
               horizon: int = 20) -> NextMonth:
    """다음 달을 준비하려면 알아야 하는 것들."""
    안 = NextMonth(scored_so_far=scored_total,
                  need_more=max(0, MIN_FOR_TRUST - scored_total))
    if ledger.empty:
        return 안
    닿음 = ledger.get("target_hit_date", pd.Series(dtype=str)).astype(str)
    무효 = ledger.get("invalid_hit_date", pd.Series(dtype=str)).astype(str)
    진입 = ledger.get("entry_date", pd.Series(dtype=str)).astype(str)
    안.target_hit = int((닿음 != "").sum())
    안.invalid_hit = int((무효 != "").sum())
    안.still_open = int(((진입 != "") & (닿음 == "") & (무효 == "")).sum())
    return 안


def plain_verdict(mean_excess: float, count: int) -> str:
    """한 줄로 답합니다. 이번 기간 결과가 어땠나."""
    if count == 0:
        return "아직 성적이 나온 게 없습니다."
    if count < MIN_FOR_TRUST:
        return (f"아직 {count}건뿐이라 판단할 수 없습니다. "
                f"{MIN_FOR_TRUST}건은 넘어야 합니다.")
    if mean_excess > 0:
        return f"코스닥 평균보다 평균 {mean_excess:.1f}% 더 올랐습니다."
    return f"코스닥 평균보다 평균 {abs(mean_excess):.1f}% 덜 올랐습니다."


def report(scored: pd.DataFrame, period: str, horizon: int,
           recorded: int = 0, waiting: int = 0, basis: str = "",
           ahead: NextMonth | None = None,
           target_pct: float = 20.0, invalid_pct: float = -12.0) -> str:
    """월말 브리핑. 주식을 잘 모르는 사람이 읽어도 알 수 있게 씁니다.

    숫자만 늘어놓으면 아무 뜻이 없습니다. 무슨 뜻인지, 왜 중요한지를
    같이 적습니다.
    """
    lines = [f"📋 월말 브리핑 — {period}", ""]

    유효 = scored.dropna(subset=["excess"]) if not scored.empty else scored
    평균 = float(유효["excess"].mean()) if len(유효) else float("nan")

    # ── 먼저 한 줄로 답합니다 ──
    lines.append("■ 한 줄로 말하면")
    lines.append(f"   {plain_verdict(평균, len(유효))}")
    lines.append("")

    lines.append("■ 이번에 뭘 했나")
    lines.append(f"   골라 적어 둔 종목  {recorded}개")
    lines.append(f"   성적이 나온 것    {len(유효)}개")
    lines.append(f"   아직 기다리는 것   {waiting}개")
    lines.append("")
    lines.append(f"   ※ 고른 다음날 아침 시가에 샀다고 치고, {horizon}거래일"
                 f"(약 {horizon // 20}개월) 들고 있었다면 어땠을지를 봅니다.")
    lines.append("   ※ 실제로 산 것은 아닙니다. 돈은 한 푼도 안 들어갔습니다.")
    lines.append("")

    if 유효.empty:
        lines.append("아직 성적을 매길 수 있는 게 없습니다.")
        lines.append(f"고른 뒤 {horizon}거래일이 지나야 점수가 나옵니다.")
        lines.append("한 달쯤 기다리셔야 합니다.")
        if ahead is not None and ahead.waiting:
            lines.append("")
            lines.append("■ 다음 달에 볼 것")
            lines.append(f"   기다리는 {ahead.waiting}개의 점수가 나옵니다.")
            lines.append(f"   판정에는 {MIN_FOR_TRUST}개가 필요합니다.")
        if basis:
            lines.append("")
            lines.append(f"계산 기준: {basis}")
        return "\n".join(lines)

    # ── 성적 ──
    lines.append("■ 성적")
    lines.append("")
    lines.append("   '초과수익' 이란 — 그 종목이 오른 정도에서 코스닥 지수가")
    lines.append("   오른 정도를 뺀 값입니다. 코스닥이 10% 올랐는데 종목이")
    lines.append("   8% 올랐으면, 오르긴 했어도 초과수익은 -2% 입니다.")
    lines.append("   그냥 지수를 사는 게 나았다는 뜻이니까요.")
    lines.append("")

    있는설정 = [s for s in ("breakout", "value")
              if "setup" in scored and (scored["setup"] == s).any()]
    for setup in 있는설정 or ["breakout"]:
        요약 = summarize(scored, setup)
        if 요약 is None:
            continue
        이름 = SETUP_LABEL.get(setup, setup)
        lines.append(f"   〈{이름}〉 {요약.count}개")
        lines.append(f"     초과수익 평균 {_pct(요약.mean_excess)}"
                     f" (한가운데 값 {_pct(요약.median_excess)})")
        lines.append(f"     지수보다 잘한 것이 {요약.win_rate:.0f}%")
        if 요약.best:
            lines.append(f"     제일 잘된 것  {요약.best[0]} {요약.best[2]:+.1f}%")
        if 요약.worst:
            lines.append(f"     제일 못된 것  {요약.worst[0]} {요약.worst[2]:+.1f}%")
        lines.append("")

    # ── 어떻게 움직였나 ──
    모양표 = by_shape(scored)
    if not 모양표.empty:
        lines.append("■ 사고 나서 어떻게 움직였나")
        lines.append("")
        lines.append("   같은 +5% 라도 곧장 오른 것과 한참 빠졌다 돌아온 것은")
        lines.append("   전혀 다릅니다. 우리 매도 규칙에 걸리는 게 다르니까요.")
        lines.append("")
        for 모양, row in 모양표.iterrows():
            뜻 = SHAPE_MEANING.get(str(모양), "")
            lines.append(f"   · {모양} {int(row['건수'])}개 — {뜻}")
            lines.append(f"     초과수익 평균 {row['평균초과%']:+.1f}%")
            배움 = SHAPE_LESSON.get(str(모양))
            if 배움 and int(row["건수"]) >= MIN_FOR_HINT:
                lines.append(f"     {배움}")
        lines.append("")

    # ── 조건별 ──
    쪼갠것 = [(c, by_condition(scored, c)) for c in BUCKETS]
    쪼갠것 = [(c, v) for c, v in 쪼갠것 if len(v) >= 2]
    if 쪼갠것:
        lines.append("■ 어떤 종목이 잘 됐나")
        lines.append("")
        for column, 조각들 in 쪼갠것:
            설명 = {
                "거래량배수": "평소보다 거래량이 몇 배로 늘었을 때 골랐나",
                "박스폭%": "그 전에 얼마나 조용했나 (좁을수록 조용했던 것)",
                "상승률%": "고를 때 이미 얼마나 올라 있었나",
                "갭%": "다음날 아침 얼마나 비싸게 시작했나",
            }.get(column, "")
            lines.append(f"   〈{column}〉 {설명}")
            for s in 조각들:
                lines.append(f"     {s.label:<12} {s.count:>3}개"
                             f"  초과수익 {_pct(s.mean_excess):>8}"
                             f"  잘한 비율 {s.win_rate:>3.0f}%")
            lines.append("")

    # ── 다음 달 준비 ──
    if ahead is not None:
        lines.append("■ 다음 달에 볼 것")
        lines.append("")
        if ahead.waiting:
            lines.append(f"   · 아직 성적이 안 나온 것 {ahead.waiting}개 —"
                         f" 다음 달에 점수가 나옵니다")
        if ahead.still_open:
            lines.append(f"   · 목표({target_pct:g}%)도 무효선({invalid_pct:g}%)도"
                         f" 아직인 것 {ahead.still_open}개 — 계속 지켜봅니다")
        if ahead.target_hit:
            lines.append(f"   · 목표 {target_pct:g}% 에 닿았던 것 {ahead.target_hit}개")
        if ahead.invalid_hit:
            lines.append(f"   · 무효선 {invalid_pct:g}% 에 닿았던 것"
                         f" {ahead.invalid_hit}개 — 골라낸 기준이 틀렸던 경우")
        lines.append("")
        if ahead.need_more > 0:
            lines.append(f"   판정까지 {ahead.need_more}개 더 필요합니다."
                         f" (지금 {ahead.scored_so_far}개 / {MIN_FOR_TRUST}개)")
            달수 = max(1, round(ahead.need_more / max(1, len(유효)))) if len(유효) else 3
            lines.append(f"   지금 속도면 {달수}개월쯤 더 걸립니다.")
        else:
            lines.append(f"   판정에 필요한 {MIN_FOR_TRUST}개를 넘겼습니다"
                         f" (지금 {ahead.scored_so_far}개).")
            lines.append("   이제 비용을 뺀 실제 손익을 따져볼 때입니다.")
        lines.append("")
        lines.append("   다음 달에도 규칙은 그대로 둡니다. 지금 바꾸면 여기까지")
        lines.append("   쌓은 것이 증거가 되지 못하고 처음부터 다시 시작합니다.")
        lines.append("")

    # ── 어떻게 읽어야 하나 ──
    lines.append("■ 이 숫자를 어떻게 봐야 하나")
    lines.append("")
    if len(유효) < MIN_FOR_TRUST:
        lines.append(f"   1. 아직 {len(유효)}개뿐입니다. {MIN_FOR_TRUST}개는 넘어야")
        lines.append("      운인지 실력인지 구분이 시작됩니다. 지금 숫자가")
        lines.append("      좋게 나와도 그건 아무 뜻이 없습니다.")
    else:
        lines.append(f"   1. {len(유효)}개가 모였습니다. 이제 볼 만합니다.")
        lines.append("      다만 여기서 사고파는 비용(왕복 0.51%)을 빼야")
        lines.append("      실제로 남는 돈이 됩니다.")
    lines.append("")
    lines.append("   2. 위의 '어떤 종목이 잘 됐나' 표는 참고만 하십시오.")
    lines.append("      적은 수를 여러 조각으로 나누면 그중 하나는 반드시")
    lines.append("      좋아 보입니다. 우연히요.")
    lines.append("")
    lines.append("   3. 이 표를 보고 고르는 조건을 바꾸면, 지금까지 쌓은")
    lines.append("      기록은 증거가 되지 못합니다. 처음부터 다시 쌓아야")
    lines.append("      합니다. 바꾸실 거면 그걸 알고 바꾸셔야 합니다.")
    lines.append("")
    lines.append("   4. 다시 말씀드리지만 이건 수익 보고서가 아닙니다.")
    lines.append("      돈은 아직 한 푼도 안 들어갔습니다. '고르는 규칙이")
    lines.append("      맞나' 를 보는 성적표입니다.")

    if basis:
        lines.append("")
        lines.append(f"계산 기준: {basis}")
    return "\n".join(lines)
