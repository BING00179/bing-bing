"""판단 기록장 — 돈을 넣지 않고 판단력을 재는 곳.

여기 있는 어떤 도구도 아직 "사도 된다" 고 말할 만큼 검증되지 않았습니다.
그런데 사람의 판단은 어떨까요. 그것도 모릅니다. 재본 적이 없으니까요.

    "이 종목 오를 것 같다"  →  적어만 둔다  →  석 달 뒤 채점

돈은 한 푼도 움직이지 않습니다. 대신 답이 나옵니다.
그리고 이 답은 코드로는 절대 만들 수 없습니다 — 시간이 흘러야 합니다.
그래서 오늘 시작하는 것과 다음 달에 시작하는 것이 다릅니다.

채점 기준은 하나뿐입니다.

    그 종목의 수익률  −  같은 기간 코스닥 지수 수익률

이걸 '초과수익' 이라고 합니다. 코스닥이 20% 오른 기간에 종목이
15% 올랐다면, 오르긴 했지만 **진 것** 입니다. 지수를 사는 편이
나았으니까요. 오른 것과 잘 고른 것은 다릅니다.

기록에는 반드시 '왜' 를 적습니다. 나중에 맞았을 때 무엇이 통했는지,
틀렸을 때 무엇을 잘못 봤는지 알려면 그때의 생각이 남아 있어야 합니다.
사람은 결과를 알고 나면 자기가 원래 그렇게 생각했다고 기억합니다.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_PATH = Path("data/journal.csv")

COLUMNS = ("recorded_at", "code", "name", "price", "conviction", "horizon_days",
           "why", "note")

CONVICTIONS = ("상", "중", "하")


@dataclass
class Entry:
    recorded_at: str          # YYYY-MM-DD
    code: str
    name: str
    price: float              # 기록 시점 종가
    conviction: str           # 상 / 중 / 하
    horizon_days: int         # 며칠 뒤에 채점할지
    why: str                  # 왜 오를 거라 보는가 — 반드시 적습니다
    note: str = ""


def load(path: str | Path = DEFAULT_PATH) -> pd.DataFrame:
    """기록을 읽습니다. 없으면 빈 표."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    frame = pd.read_csv(path, dtype={"code": str}, keep_default_na=False)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["horizon_days"] = pd.to_numeric(
        frame["horizon_days"], errors="coerce"
    ).fillna(90).astype(int)
    return frame[list(COLUMNS)]


def append(entry: Entry, path: str | Path = DEFAULT_PATH) -> Path:
    """한 건 덧붙입니다. 기존 기록은 절대 건드리지 않습니다."""
    if not entry.why.strip():
        raise ValueError(
            "'왜' 를 비워 둘 수 없습니다. 이유가 없으면 나중에 채점해도 "
            "무엇이 통했는지 알 수 없습니다."
        )
    if entry.conviction not in CONVICTIONS:
        raise ValueError(f"확신도는 {' / '.join(CONVICTIONS)} 중 하나여야 합니다.")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    새파일 = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        if 새파일:
            writer.writeheader()
        writer.writerow(asdict(entry))
    return path


def due(frame: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """채점할 때가 된 기록만."""
    if frame.empty:
        return frame
    today = today or pd.Timestamp.today().normalize()
    recorded = pd.to_datetime(frame["recorded_at"], errors="coerce")
    elapsed = (today - recorded).dt.days
    return frame[elapsed >= frame["horizon_days"]].copy()


@dataclass
class Scored:
    code: str
    name: str
    recorded_at: str
    conviction: str
    days: int
    entry_price: float
    end_price: float
    stock_pct: float
    index_pct: float
    excess: float
    why: str


def score_one(row: pd.Series, daily: pd.DataFrame, index: pd.DataFrame,
              today: pd.Timestamp | None = None) -> Scored | None:
    """기록 한 건을 채점합니다.

    기록일 종가에서 시작해, 기간이 지난 시점(또는 오늘)까지의 수익률을
    같은 기간 지수 수익률과 견줍니다.
    """
    start = pd.Timestamp(row["recorded_at"])
    horizon = int(row["horizon_days"])
    today = today or pd.Timestamp.today().normalize()
    end = min(start + pd.Timedelta(days=horizon), today)

    def _span(frame: pd.DataFrame) -> tuple[float, float] | None:
        window = frame.loc[frame.index <= end]
        window = window.loc[window.index >= start]
        if len(window) < 2:
            return None
        return float(window["close"].iloc[0]), float(window["close"].iloc[-1])

    stock = _span(daily)
    if stock is None:
        return None
    market = _span(index)

    시작가, 끝가 = stock
    if 시작가 <= 0:
        return None
    종목수익 = (끝가 / 시작가 - 1.0) * 100.0
    지수수익 = float("nan")
    if market is not None and market[0] > 0:
        지수수익 = (market[1] / market[0] - 1.0) * 100.0

    return Scored(
        code=str(row["code"]),
        name=str(row["name"]),
        recorded_at=str(row["recorded_at"]),
        conviction=str(row["conviction"]),
        days=int((end - start).days),
        entry_price=시작가,
        end_price=끝가,
        stock_pct=종목수익,
        index_pct=지수수익,
        excess=종목수익 - 지수수익,
        why=str(row["why"]),
    )


@dataclass
class Verdict:
    count: int
    mean_excess: float
    median_excess: float
    win_rate: float               # 지수를 이긴 비율
    t_stat: float
    by_conviction: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def enough(self) -> bool:
        """판정할 만큼 쌓였나. 적으면 운과 구분되지 않습니다."""
        return self.count >= 30

    @property
    def significant(self) -> bool:
        return self.enough and abs(self.t_stat) >= 2.0


def summarize(scored: list[Scored]) -> Verdict:
    if not scored:
        return Verdict(0, float("nan"), float("nan"), float("nan"), float("nan"))

    frame = pd.DataFrame([asdict(s) for s in scored])
    excess = frame["excess"].dropna()
    if excess.empty:
        return Verdict(len(frame), float("nan"), float("nan"),
                       float("nan"), float("nan"))

    std = float(excess.std(ddof=1)) if len(excess) > 1 else 0.0
    t = float(excess.mean() / (std / np.sqrt(len(excess)))) if std > 0 else 0.0

    by = pd.DataFrame()
    if "conviction" in frame:
        grouped = frame.dropna(subset=["excess"]).groupby("conviction")
        if len(grouped):
            by = pd.DataFrame({
                "건수": grouped.size(),
                "평균초과%": grouped["excess"].mean(),
                "이긴비율%": grouped["excess"].apply(lambda s: (s > 0).mean() * 100.0),
            })

    return Verdict(
        count=len(excess),
        mean_excess=float(excess.mean()),
        median_excess=float(excess.median()),
        win_rate=float((excess > 0).mean() * 100.0),
        t_stat=t,
        by_conviction=by,
    )


def report(scored: list[Scored], verdict: Verdict, pending: int = 0) -> str:
    lines = ["=" * 78,
             "[판단 기록장 채점] 내 판단이 코스닥 지수를 이겼는가",
             "=" * 78, ""]

    if not scored:
        lines.append("[사실] 채점할 기록이 아직 없습니다.")
        if pending:
            lines.append(f"   기다리는 중인 기록 {pending}건. 기간이 차면 채점됩니다.")
        lines.append("")
        lines.append("   기록하기:")
        lines.append('     python -m src.cli journal-add --code 032820 \\')
        lines.append('        --name 우리기술 --why "왜 오를 거라 보는지" --conviction 중')
        lines.append("=" * 78)
        return "\n".join(lines)

    lines.append(f"[사실] 채점한 기록 {len(scored)}건" +
                 (f" · 기다리는 중 {pending}건" if pending else ""))
    lines.append("")
    lines.append("   기록일       종목                수익률    지수     초과   확신")
    lines.append("   " + "-" * 68)
    for s in sorted(scored, key=lambda x: x.excess, reverse=True):
        지수 = "—" if np.isnan(s.index_pct) else f"{s.index_pct:>6.1f}%"
        초과 = "—" if np.isnan(s.excess) else f"{s.excess:>+7.1f}%"
        이름 = (s.name or s.code)[:12]
        lines.append(
            f"   {s.recorded_at}  {이름:<12}({s.code})"
            f" {s.stock_pct:>7.1f}% {지수} {초과}   {s.conviction}"
        )
    lines.append("")

    lines.append("[사실] 합계")
    lines.append(f"   평균 초과수익  {verdict.mean_excess:+.2f}%")
    lines.append(f"   중앙값         {verdict.median_excess:+.2f}%")
    lines.append(f"   지수를 이긴 비율  {verdict.win_rate:.1f}%")
    lines.append(f"   t값            {verdict.t_stat:.2f}   (표본 {verdict.count}건)")
    lines.append("")

    if not verdict.by_conviction.empty:
        lines.append("[사실] 확신도별")
        lines.append("   " + verdict.by_conviction.to_string().replace("\n", "\n   "))
        lines.append("")

    lines.append("[해석] 아래 기준으로만 읽으십시오.")
    if not verdict.enough:
        lines.append(f"   · 아직 {verdict.count}건입니다. 30건은 넘어야 운과 구분이 시작됩니다.")
        lines.append("     지금 숫자가 좋아도 그건 아무 뜻이 없습니다.")
    elif verdict.significant and verdict.mean_excess > 0:
        lines.append("   · 지수를 이기고 있고, 우연으로 보기 어렵습니다(|t| ≥ 2).")
        lines.append("     시스템은 종목을 고르는 쪽이 아니라 이 판단을 돕는 쪽으로")
        lines.append("     만드는 것이 맞습니다.")
    elif verdict.significant and verdict.mean_excess < 0:
        lines.append("   · 지수에 지고 있고, 우연으로 보기 어렵습니다.")
        lines.append("     이건 돈을 넣기 전에 알아서 다행인 사실입니다.")
    else:
        lines.append("   · 표본은 찼지만 우연과 구분되지 않습니다(|t| < 2).")
        lines.append("     더 쌓아야 합니다. 지금은 있다고도 없다고도 말할 수 없습니다.")
    lines.append("")
    lines.append("   ⚠️ 확신도 '상' 만 골라 보고 판단하지 마십시오. 나중에 고른 부분집합은")
    lines.append("      언제나 좋아 보입니다. 전체를 먼저 보고, 확신도별은 참고만 하십시오.")
    lines.append("=" * 78)
    return "\n".join(lines)
