"""실시간 검증 — 오늘부터 쌓는, 손댈 수 없는 자료.

지금까지의 검증은 전부 과거 자료를 다시 본 것이었습니다. 결과가 나쁘면
조건을 고치고 또 돌렸습니다. 그러면 어느 순간 좋은 숫자가 나오는데,
그건 '통하는 규칙' 을 찾은 게 아니라 '그 자료에 맞는 답' 을 외운 것에
가깝습니다.

갭 규칙을 넣었더니 20일 t 값이 1.97 에서 2.72 로 올라갔습니다. 기준을
넘겼지만 그건 같은 자료를 다시 본 결과입니다. 진짜 확인은 하나뿐입니다.

    오늘부터 신호를 적어 두고, 몇 달 뒤에 실제로 어땠는지 본다.

여기에 적힌 것은 제가 고칠 수 없습니다. 미래는 아직 오지 않았으니까요.

## 지키는 것

  1. **규칙을 얼려 둡니다.** 기록마다 그때 쓴 조건값을 같이 저장합니다.
     나중에 조건을 바꾸면 기록에 남아, 서로 다른 규칙의 결과를 섞어
     보는 일을 막습니다. 조건을 바꾸면 시계는 그날부터 다시 갑니다.
  2. **신호일과 진입일을 나눠 적습니다.** 신호는 D일 종가, 진입은
     D+1일 시가입니다. 갭은 D+1 아침에야 알 수 있으므로 그때 채웁니다.
  3. **채점은 코스닥 지수 대비로 합니다.** 종목이 올랐는지가 아니라
     지수보다 나았는지를 봅니다.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_PATH = Path("data/livetest.csv")

COLUMNS = (
    "signal_date",      # 신호가 난 날 (D일 종가 기준)
    "code",
    "name",
    "signal_close",     # D일 종가
    "setup",            # 어떤 조건으로 잡았나
    "rule",             # 그때 쓴 조건값 — 규칙을 얼려 두는 자리
    "volume_mult",
    "base_range_pct",
    "runup_pct",
    "turnover",
    "score",
    # 아래는 다음날 아침에 채워집니다
    "entry_date",       # D+1
    "entry_open",       # D+1 시가
    "gap_pct",          # (D+1 시가 / D 종가 - 1) × 100
    "bought",           # 갭 규칙을 통과했나 (샀을 것인가)
)

MAX_GAP_PCT = 5.0       # 이 값을 바꾸면 그날부터 시계가 다시 갑니다


def rule_text(setup) -> str:
    """그때 쓴 조건값을 한 줄로. 나중에 바뀌면 티가 나야 합니다."""
    return (f"base{setup.base_days}/surge{setup.surge_days}"
            f"/range{setup.max_base_range_pct:g}"
            f"/vol{setup.min_volume_mult:g}"
            f"/runup{setup.max_runup_pct:g}"
            f"/turnover{setup.min_turnover / 1e8:g}억"
            f"/maxgap{MAX_GAP_PCT:g}")


def load(path: str | Path = DEFAULT_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    frame = pd.read_csv(path, dtype={"code": str}, keep_default_na=False)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    for column in ("signal_close", "volume_mult", "base_range_pct",
                   "runup_pct", "turnover", "score", "entry_open", "gap_pct"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[list(COLUMNS)]


def save(frame: pd.DataFrame, path: str | Path = DEFAULT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(COLUMNS)].to_csv(path, index=False, encoding="utf-8-sig")
    return path


def add_signals(frame: pd.DataFrame, hits: list, setup,
                setup_name: str = "breakout") -> tuple[pd.DataFrame, int]:
    """오늘 신호를 덧붙입니다. 이미 있는 (날짜, 종목) 은 건너뜁니다."""
    있는것 = set(zip(frame["signal_date"].astype(str), frame["code"].astype(str)))
    rule = rule_text(setup)

    새것 = []
    for h in hits:
        날 = str(pd.Timestamp(h.date).date())
        if (날, h.code) in 있는것:
            continue
        새것.append({
            "signal_date": 날, "code": h.code, "name": h.name,
            "signal_close": h.close, "setup": setup_name, "rule": rule,
            "volume_mult": round(h.volume_mult, 2),
            "base_range_pct": round(h.base_range_pct, 2),
            "runup_pct": round(h.runup_pct, 2),
            "turnover": h.turnover, "score": round(h.score, 1),
            "entry_date": "", "entry_open": np.nan,
            "gap_pct": np.nan, "bought": "",
        })

    if not 새것:
        return frame, 0
    붙일것 = pd.DataFrame(새것)
    if frame.empty:                      # 빈 표와 붙이면 열 종류가 흐트러집니다
        return 붙일것.reindex(columns=list(COLUMNS)), len(새것)
    return pd.concat([frame, 붙일것], ignore_index=True), len(새것)


def fill_entries(frame: pd.DataFrame,
                 frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    """아직 안 채운 기록에 다음날 시가와 갭을 채웁니다.

    갭은 D+1 아침에야 알 수 있는 값입니다. 신호를 적을 때 미리 채우면
    미래를 보는 것이 됩니다. 그래서 다음 실행 때 채웁니다.
    """
    if frame.empty:
        return frame, 0

    채운수 = 0
    for i, row in frame.iterrows():
        if str(row.get("entry_date", "")):
            continue
        daily = frames.get(str(row["code"]))
        if daily is None or daily.empty:
            continue

        신호일 = pd.Timestamp(row["signal_date"])
        뒤 = daily.index[daily.index > 신호일]
        if len(뒤) == 0:
            continue                       # 아직 다음 거래일이 안 왔습니다

        진입일 = 뒤[0]
        시가 = float(daily.at[진입일, "open"])
        종가 = float(row["signal_close"])
        갭 = (시가 / 종가 - 1.0) * 100.0 if 종가 > 0 else float("nan")

        frame.at[i, "entry_date"] = str(진입일.date())
        frame.at[i, "entry_open"] = 시가
        frame.at[i, "gap_pct"] = round(갭, 3)
        frame.at[i, "bought"] = "예" if 갭 <= MAX_GAP_PCT else "아니오"
        채운수 += 1
    return frame, 채운수


# ─────────────────────────── 채점 ───────────────────────────

@dataclass
class Scored:
    code: str
    name: str
    signal_date: str
    entry_date: str
    days: int
    entry_open: float
    end_close: float
    stock_pct: float
    index_pct: float
    excess: float
    gap_pct: float


def score_rows(frame: pd.DataFrame, frames: dict[str, pd.DataFrame],
               index: pd.DataFrame, horizon: int = 20,
               only_bought: bool = True,
               today: pd.Timestamp | None = None) -> list[Scored]:
    """기간이 찬 기록을 채점합니다. 진입일 시가에서 N거래일 뒤 종가까지."""
    if frame.empty:
        return []
    today = today or pd.Timestamp.today().normalize()

    결과: list[Scored] = []
    for _, row in frame.iterrows():
        if not str(row.get("entry_date", "")):
            continue
        if only_bought and str(row.get("bought", "")) != "예":
            continue

        daily = frames.get(str(row["code"]))
        if daily is None or daily.empty:
            continue
        진입일 = pd.Timestamp(row["entry_date"])
        if 진입일 not in daily.index:
            continue

        자리 = daily.index.get_loc(진입일)
        끝자리 = 자리 + horizon - 1
        if 끝자리 >= len(daily):
            continue                       # 아직 기간이 안 찼습니다
        끝날 = daily.index[끝자리]
        if 끝날 > today:
            continue

        시가 = float(row["entry_open"])
        if not np.isfinite(시가) or 시가 <= 0:
            continue
        끝종가 = float(daily["close"].iloc[끝자리])
        종목수익 = (끝종가 / 시가 - 1.0) * 100.0

        지수수익 = float("nan")
        창 = index.loc[(index.index >= 진입일) & (index.index <= 끝날)]
        if len(창) >= 2 and float(창["close"].iloc[0]) > 0:
            지수수익 = (float(창["close"].iloc[-1]) / float(창["close"].iloc[0])
                     - 1.0) * 100.0

        결과.append(Scored(
            code=str(row["code"]), name=str(row["name"]),
            signal_date=str(row["signal_date"]), entry_date=str(row["entry_date"]),
            days=horizon, entry_open=시가, end_close=끝종가,
            stock_pct=종목수익, index_pct=지수수익,
            excess=종목수익 - 지수수익,
            gap_pct=float(row["gap_pct"]) if pd.notna(row["gap_pct"]) else float("nan"),
        ))
    return 결과


@dataclass
class Verdict:
    count: int
    mean_excess: float
    median_excess: float
    win_rate: float
    t_stat: float
    horizon: int

    @property
    def enough(self) -> bool:
        return self.count >= 30

    @property
    def passes(self) -> bool:
        """숫자를 보기 전에 정한 기준. 표본 30건 이상, 초과수익 +, |t| ≥ 2."""
        return self.enough and self.mean_excess > 0 and self.t_stat >= 2.0


def summarize(scored: list[Scored], horizon: int = 20) -> Verdict:
    if not scored:
        return Verdict(0, float("nan"), float("nan"), float("nan"),
                       float("nan"), horizon)
    excess = pd.Series([s.excess for s in scored]).dropna()
    if excess.empty:
        return Verdict(len(scored), float("nan"), float("nan"),
                       float("nan"), float("nan"), horizon)
    std = float(excess.std(ddof=1)) if len(excess) > 1 else 0.0
    t = float(excess.mean() / (std / np.sqrt(len(excess)))) if std > 0 else 0.0
    return Verdict(
        count=len(excess), mean_excess=float(excess.mean()),
        median_excess=float(excess.median()),
        win_rate=float((excess > 0).mean() * 100.0), t_stat=t, horizon=horizon,
    )


def rules_seen(frame: pd.DataFrame) -> list[str]:
    """기록에 남은 조건값들. 두 개 이상이면 섞어 보면 안 됩니다."""
    if frame.empty or "rule" not in frame:
        return []
    return sorted({str(r) for r in frame["rule"] if str(r).strip()})


def report(frame: pd.DataFrame, scored: list[Scored], verdict: Verdict) -> str:
    lines = ["=" * 80,
             "[실시간 검증] 오늘부터 쌓는, 손댈 수 없는 자료",
             "=" * 80, ""]

    기다리는중 = 0
    if not frame.empty:
        기다리는중 = len(frame) - len(scored)
    lines.append(f"[사실] 기록 {len(frame):,}건 · 채점 {len(scored):,}건 "
                 f"· 기다리는 중 {기다리는중:,}건")

    if not frame.empty:
        첫날 = frame["signal_date"].min()
        끝날 = frame["signal_date"].max()
        산것 = int((frame["bought"] == "예").sum())
        거른것 = int((frame["bought"] == "아니오").sum())
        lines.append(f"   기간 {첫날} ~ {끝날}")
        lines.append(f"   갭 규칙 통과 {산것:,}건 · 갭이 커서 거른 것 {거른것:,}건")

    조건들 = rules_seen(frame)
    if len(조건들) > 1:
        lines.append("")
        lines.append("[사실] ⚠️ 서로 다른 조건이 섞여 있습니다. 나눠서 봐야 합니다.")
        for r in 조건들:
            수 = int((frame["rule"] == r).sum())
            lines.append(f"   {r}  ({수}건)")
    elif 조건들:
        lines.append(f"   조건 {조건들[0]}")
    lines.append("")

    if not scored:
        lines.append("[사실] 아직 채점할 것이 없습니다.")
        lines.append("")
        lines.append(f"   신호가 난 뒤 {verdict.horizon}거래일이 지나야 채점됩니다.")
        lines.append("   30건이 쌓여야 판정을 시작합니다. 몇 달 걸립니다.")
        lines.append("=" * 80)
        return "\n".join(lines)

    lines.append(f"[사실] {verdict.horizon}거래일 보유 성적 (코스닥 지수 대비)")
    lines.append("")
    lines.append("   신호일        종목               갭      수익률    지수     초과")
    lines.append("   " + "-" * 70)
    for s in sorted(scored, key=lambda x: x.signal_date, reverse=True)[:25]:
        지수 = "—" if np.isnan(s.index_pct) else f"{s.index_pct:>6.1f}%"
        초과 = "—" if np.isnan(s.excess) else f"{s.excess:>+7.1f}%"
        lines.append(
            f"   {s.signal_date}  {s.name[:14]:<14}({s.code})"
            f" {s.gap_pct:>5.1f}% {s.stock_pct:>7.1f}% {지수} {초과}"
        )
    if len(scored) > 25:
        lines.append(f"   ... 외 {len(scored) - 25}건")
    lines.append("")

    lines.append("[사실] 합계")
    lines.append(f"   평균 초과수익  {verdict.mean_excess:+.2f}%")
    lines.append(f"   중앙값         {verdict.median_excess:+.2f}%")
    lines.append(f"   지수를 이긴 비율  {verdict.win_rate:.1f}%")
    lines.append(f"   t값            {verdict.t_stat:.2f}   (표본 {verdict.count}건)")
    lines.append("")

    lines.append("[해석] 숫자를 보기 전에 정한 기준으로만 읽으십시오.")
    if not verdict.enough:
        lines.append(f"   · 아직 {verdict.count}건입니다. 30건은 넘어야 시작합니다.")
        lines.append("     지금 숫자가 좋아도 아무 뜻이 없습니다.")
    elif verdict.passes:
        lines.append("   · 표본 30건 이상, 초과수익 +, t ≥ 2 — 세 가지를 다 넘겼습니다.")
        lines.append("     과거 자료가 아니라 앞으로의 자료에서 나온 결과입니다.")
        lines.append("     다만 거래비용(왕복 0.51%)을 빼고도 남는지 따로 보셔야 합니다.")
    elif verdict.mean_excess <= 0:
        lines.append("   · 초과수익이 0 이하입니다. 이 조건은 무작위보다 나을 게 없습니다.")
        lines.append("     과거 자료에서 좋아 보였던 것은 그 자료에 맞춘 답이었습니다.")
    else:
        lines.append("   · 초과수익은 +인데 t < 2 입니다. 있는지 없는지 알 수 없습니다.")
        lines.append("     더 쌓아야 합니다.")
    lines.append("")
    lines.append("   ⚠️ 조건을 바꾸면 그날부터 시계가 다시 갑니다. 지금까지 쌓은 것은")
    lines.append("      바뀐 조건의 증거가 되지 못합니다.")
    lines.append("=" * 80)
    return "\n".join(lines)
