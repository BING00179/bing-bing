"""실시간 검증 장부 — 지우지도 고치지도 않는 기록.

지금까지의 검증은 전부 과거 자료를 다시 본 것이었습니다. 결과가 나쁘면
조건을 고치고 또 돌렸습니다. 그러면 어느 순간 좋은 숫자가 나오는데,
그건 '통하는 규칙' 을 찾은 게 아니라 '그 자료에 맞는 답' 을 외운 것에
가깝습니다.

여기 적히는 것만이 앞으로의 자료라, 제가 손댈 수 없는 유일한 증거입니다.

## 장부의 규칙 일곱 가지

  1. 선정 당시 정보를 그대로 적습니다. 그때의 가격, 조건값, 근거까지.
  2. 결과가 나빠도 지우거나 고치지 않습니다. 줄어드는 저장은 거부합니다.
  3. 잘못 적은 것은 덮어쓰지 않고 **정정 기록을 새로 붙입니다.**
     원래 줄은 '정정됨' 으로 표시만 하고 그대로 남깁니다.
  4. 근거와 출처를 같이 적습니다 — 공시 접수번호, 기사 주소 같은 것.
  5. 진입 뒤의 최고가·최저가·목표 도달 여부를 계속 덧쌓습니다.
  6. 채점에 쓴 계산 기준(보유일수·비교지수·목표·무효선)을 같이 남깁니다.
  7. 프로그램 기준이 바뀌면 판(version)을 올려 앞뒤를 구분합니다.

## 왜 이렇게까지 하나

성적이 나쁜 기록을 슬쩍 빼면 남는 것은 잘된 것뿐이고, 그건 증거가
아니라 자랑입니다. 조건을 바꿔 놓고 예전 기록을 그대로 쓰면, 바뀐
규칙이 예전 성적을 물려받습니다. 둘 다 사람이 자기도 모르게 하는
일이라, 코드로 막아 두는 편이 낫습니다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_PATH = Path("data/livetest.csv")

# 프로그램 기준이 바뀌면 이 값을 올립니다. 그러면 앞뒤 기록이 구분되고,
# 채점할 때 섞이지 않습니다.
LEDGER_VERSION = "1"

COLUMNS = (
    # ── 이 줄이 언제 왜 생겼나 ──
    "row_id",           # 줄마다 붙는 번호. 정정 기록이 이걸 가리킵니다
    "recorded_at",      # 이 줄을 적은 시각
    "kind",             # 기록 / 정정
    "corrects",         # 정정이면 어느 row_id 를 고치는지
    "status",           # 유효 / 정정됨
    "version",          # 프로그램 기준 판
    # ── 선정 당시 정보 ──
    "signal_date",      # 신호가 난 날 (D일 종가 기준)
    "code",
    "name",
    "signal_close",     # D일 종가
    "setup",            # breakout / value
    "rule",             # 그때 쓴 조건값
    "basis",            # 왜 골랐나 — 사람이 읽는 한 줄
    "source",           # 출처 — 공시 접수번호·기사 주소 등
    "volume_mult",
    "base_range_pct",
    "runup_pct",
    "turnover",
    "score",
    # ── 다음날 아침에 채우는 것 ──
    "entry_date",
    "entry_open",
    "gap_pct",
    "bought",
    # ── 그 뒤로 계속 덧쌓는 것 ──
    "last_checked",     # 마지막으로 갱신한 날
    "high_since",       # 진입 후 최고가
    "high_date",
    "low_since",        # 진입 후 최저가
    "low_date",
    "target_pct",       # 목표 기준 (미리 정해 둡니다)
    "target_hit_date",  # 목표에 닿은 날. 안 닿았으면 빈칸
    "invalid_pct",      # 무효 기준
    "invalid_hit_date", # 무효선에 닿은 날
)

MAX_GAP_PCT = 5.0        # 이 값을 바꾸면 판을 올려야 합니다
TARGET_PCT = 15.0        # 목표: 진입가 대비 +15%
INVALID_PCT = -12.0      # 무효: 진입가 대비 -12%

KIND_RECORD, KIND_FIX = "기록", "정정"
STATUS_OK, STATUS_FIXED = "유효", "정정됨"


def make_row_id(signal_date: str, code: str, kind: str = KIND_RECORD,
                salt: str = "") -> str:
    """줄마다 붙는 번호. 같은 내용이면 같은 번호가 나오게 만듭니다."""
    씨앗 = f"{signal_date}|{code}|{kind}|{salt}"
    return hashlib.sha1(씨앗.encode("utf-8")).hexdigest()[:10]


def rule_text(setup) -> str:
    """그때 쓴 조건값을 한 줄로. 나중에 바뀌면 티가 나야 합니다."""
    return (f"base{setup.base_days}/surge{setup.surge_days}"
            f"/range{setup.max_base_range_pct:g}"
            f"/vol{setup.min_volume_mult:g}"
            f"/runup{setup.max_runup_pct:g}"
            f"/turnover{setup.min_turnover / 1e8:g}억"
            f"/maxgap{MAX_GAP_PCT:g}"
            f"/target{TARGET_PCT:g}/invalid{INVALID_PCT:g}"
            f"@v{LEDGER_VERSION}")


def load(path: str | Path = DEFAULT_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    frame = pd.read_csv(path, dtype={"code": str}, keep_default_na=False)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    for column in ("signal_close", "volume_mult", "base_range_pct",
                   "runup_pct", "turnover", "score", "entry_open", "gap_pct",
                   "high_since", "low_since", "target_pct", "invalid_pct"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[list(COLUMNS)]


# 기록을 지우려면 반드시 이 순서를 거칩니다.
#   ① 백업 파일을 만들어 사장님께 전달        (ledger-export)
#   ② 사장님이 받아서 보관했는지 확인
#   ③ 승인을 받은 뒤에야 정리
# 코드 안에는 ③ 없이 지우는 길을 두지 않습니다. 명령줄에도 없습니다.
BIG_LEDGER_MB = 20.0        # 이보다 커지면 백업을 권합니다


def size_note(path: str | Path = DEFAULT_PATH) -> str:
    """장부가 얼마나 컸는지, 정리해야 할 때인지."""
    path = Path(path)
    if not path.exists():
        return "장부가 아직 없습니다."
    메가 = path.stat().st_size / (1024 * 1024)
    줄수 = len(load(path))
    말 = f"장부 {줄수:,}줄 · {메가:.2f} MB"
    if 메가 < BIG_LEDGER_MB:
        남은해 = (BIG_LEDGER_MB - 메가) / max(메가, 1e-9) if 메가 > 0 else 999
        말 += " — 아직 넉넉합니다. 지울 이유가 없습니다."
    else:
        말 += (f"\n⚠️ {BIG_LEDGER_MB:g} MB 를 넘었습니다. 정리하려면 이 순서를 지키십시오.\n"
              "   ① python -m src.cli ledger-export   ← 백업 파일을 만듭니다\n"
              "   ② 그 zip 파일을 받아서 다른 곳에 보관하십시오\n"
              "   ③ 보관을 확인하고 승인하신 뒤에 정리합니다\n"
              "   승인 없이 지우는 길은 코드에 두지 않았습니다.")
    return 말


class LedgerShrank(RuntimeError):
    """기록이 줄어드는 저장을 막습니다."""


def save(frame: pd.DataFrame, path: str | Path = DEFAULT_PATH,
         allow_shrink: bool = False) -> Path:
    """덧붙이기만 하는 장부입니다. 줄어드는 저장은 거부합니다.

    이 파일의 값어치는 '지우지 않았다' 는 데 있습니다. 나중에 성적이
    나쁜 기록을 슬쩍 빼면 남는 것은 잘된 것뿐이고, 그건 증거가 아니라
    자랑입니다. 실수로든 일부러든 줄어들면 여기서 멈춥니다.

    기록 하나하나가 자산입니다. 되돌릴 수 없으니 막는 쪽이 낫습니다.
    """
    path = Path(path)
    if path.exists() and not allow_shrink:
        기존 = load(path)
        if len(frame) < len(기존):
            raise LedgerShrank(
                f"기록이 {len(기존):,}건에서 {len(frame):,}건으로 줄어듭니다. "
                "이 장부는 덧붙이기만 합니다.\n"
                "정말 줄여야 한다면 allow_shrink=True 를 주십시오. "
                "다만 그 순간부터 이 자료는 증거가 되지 못합니다."
            )
        사라진것 = (set(zip(기존["signal_date"].astype(str),
                        기존["code"].astype(str)))
                 - set(zip(frame["signal_date"].astype(str),
                           frame["code"].astype(str))))
        if 사라진것:
            보기 = ", ".join(f"{d} {c}" for d, c in sorted(사라진것)[:5])
            raise LedgerShrank(
                f"기존 기록 {len(사라진것)}건이 사라집니다 (예: {보기}). "
                "이 장부는 덧붙이기만 합니다."
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(COLUMNS)].to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _base_row(signal_date: str, code: str, name: str, close: float,
              setup: str, rule: str, basis: str = "", source: str = "") -> dict:
    """새 줄 하나. 아직 모르는 칸은 비워 둡니다 — 0 으로 채우지 않습니다."""
    return {
        "row_id": make_row_id(signal_date, code),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kind": KIND_RECORD, "corrects": "", "status": STATUS_OK,
        "version": LEDGER_VERSION,
        "signal_date": signal_date, "code": code, "name": name,
        "signal_close": close, "setup": setup, "rule": rule,
        "basis": basis, "source": source,
        "volume_mult": np.nan, "base_range_pct": np.nan, "runup_pct": np.nan,
        "turnover": np.nan, "score": np.nan,
        "entry_date": "", "entry_open": np.nan, "gap_pct": np.nan, "bought": "",
        "last_checked": "", "high_since": np.nan, "high_date": "",
        "low_since": np.nan, "low_date": "",
        "target_pct": TARGET_PCT, "target_hit_date": "",
        "invalid_pct": INVALID_PCT, "invalid_hit_date": "",
    }


def _append(frame: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return frame
    붙일것 = pd.DataFrame(rows).reindex(columns=list(COLUMNS))
    if frame.empty:
        return 붙일것
    return pd.concat([frame, 붙일것], ignore_index=True)


def add_signals(frame: pd.DataFrame, hits: list, setup,
                setup_name: str = "breakout",
                basis: str = "", source: str = "") -> tuple[pd.DataFrame, int]:
    """오늘 신호를 덧붙입니다. 이미 있는 (날짜, 종목) 은 건너뜁니다."""
    있는것 = set(zip(frame["signal_date"].astype(str), frame["code"].astype(str)))
    rule = rule_text(setup)

    새것 = []
    for h in hits:
        날 = str(pd.Timestamp(h.date).date())
        if (날, h.code) in 있는것:
            continue
        row = _base_row(날, h.code, h.name, h.close, setup_name, rule,
                        basis=basis or f"거래량 {h.volume_mult:.1f}배 · "
                                       f"박스폭 {h.base_range_pct:.0f}% · "
                                       f"상승률 {h.runup_pct:.0f}%",
                        source=source or "가격·거래량 (FinanceDataReader)")
        row.update({
            "volume_mult": round(h.volume_mult, 2),
            "base_range_pct": round(h.base_range_pct, 2),
            "runup_pct": round(h.runup_pct, 2),
            "turnover": h.turnover, "score": round(h.score, 1),
        })
        새것.append(row)

    return _append(frame, 새것), len(새것)


def add_correction(frame: pd.DataFrame, row_id: str, reason: str,
                   **changes) -> tuple[pd.DataFrame, str]:
    """잘못 적은 것을 고칩니다 — 덮어쓰지 않고 정정 기록을 새로 붙입니다.

    원래 줄은 '정정됨' 으로 표시만 하고 그대로 남깁니다. 무엇을 어떻게
    잘못 적었는지도 기록의 일부입니다.
    """
    맞는줄 = frame.index[frame["row_id"].astype(str) == str(row_id)]
    if len(맞는줄) == 0:
        raise KeyError(f"그런 줄이 없습니다: {row_id}")
    if not str(reason).strip():
        raise ValueError("무엇을 왜 고치는지 적어야 합니다.")

    자리 = 맞는줄[-1]
    원본 = frame.loc[자리].to_dict()

    새줄 = dict(원본)
    새줄.update(changes)
    새줄.update({
        "row_id": make_row_id(str(원본["signal_date"]), str(원본["code"]),
                              KIND_FIX, salt=datetime.now().isoformat()),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kind": KIND_FIX, "corrects": str(원본["row_id"]),
        "status": STATUS_OK, "version": LEDGER_VERSION,
        "basis": f"[정정] {reason} / 원래: {원본.get('basis', '')}",
    })

    frame = frame.copy()
    frame.at[자리, "status"] = STATUS_FIXED
    frame = _append(frame, [새줄])
    return frame, str(새줄["row_id"])


def active(frame: pd.DataFrame) -> pd.DataFrame:
    """지금 유효한 줄만. 정정된 원본은 빼고 봅니다 (지우지는 않습니다)."""
    if frame.empty or "status" not in frame:
        return frame
    return frame[frame["status"].astype(str) != STATUS_FIXED]


def add_value_picks(frame: pd.DataFrame, ranked: pd.DataFrame,
                    rule: str, on_date: pd.Timestamp | None = None,
                    top: int = 20) -> tuple[pd.DataFrame, int]:
    """저평가 후보를 그날짜로 적어 둡니다.

    저평가 스크리너는 돌릴 때마다 결과 파일을 덮어씁니다. 그러면
    지난달에 무엇을 골랐는지 알 수 없고, '그때 고른 게 어떻게 됐나'
    를 물을 수가 없습니다. 그래서 뽑을 때마다 여기에 남깁니다.
    """
    날 = str((on_date or pd.Timestamp.today()).date())
    있는것 = set(zip(frame["signal_date"].astype(str), frame["code"].astype(str)))

    새것 = []
    for _, row in ranked.head(top).iterrows():
        code = str(row["code"])
        if (날, code) in 있는것:
            continue
        pbr = row.get("PBR", float("nan"))
        per = row.get("PER", float("nan"))
        경고 = str(row.get("일회성경고", "") or "")
        근거 = f"PBR {pbr:.2f} · PER {per:.1f}" if pd.notna(pbr) else "저평가 조건 통과"
        if 경고:
            근거 += f" ⚠️ {경고}"

        새줄 = _base_row(날, code, str(row.get("name", code)),
                       float(row.get("close", float("nan"))),
                       "value", rule, basis=근거,
                       source="DART 사업보고서 주요계정 + 시가총액(FinanceDataReader)")
        새줄["turnover"] = float(row.get("turnover", float("nan")))
        새줄["score"] = round(float(row.get("저평가점수", 0.0)), 1)
        새것.append(새줄)

    return _append(frame, 새것), len(새것)


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
        # 갭 규칙은 '깨어나는 종목' 에만 겁니다. 저평가 후보는 몇 달을
        # 보고 사는 것이라 다음날 아침 갭으로 거를 이유가 없습니다.
        if str(row.get("setup", "")) == "breakout":
            frame.at[i, "bought"] = "예" if 갭 <= MAX_GAP_PCT else "아니오"
        else:
            frame.at[i, "bought"] = "예"
        채운수 += 1
    return frame, 채운수


def update_tracking(frame: pd.DataFrame, frames: dict[str, pd.DataFrame],
                    today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, int]:
    """진입 뒤의 최고가·최저가와 목표·무효선 도달 여부를 덧쌓습니다.

    최종 수익률만 남기면 '가는 길' 이 사라집니다. 한참 빠졌다 돌아온
    것과 곧장 오른 것은 같은 +5% 라도 우리 규칙에 걸리는 게 다릅니다.
    한 번 적힌 도달일은 다시 지우지 않습니다.
    """
    if frame.empty:
        return frame, 0
    today = today or pd.Timestamp.today().normalize()
    frame = frame.copy()
    갱신 = 0

    for i, row in frame.iterrows():
        진입일문자 = str(row.get("entry_date", ""))
        if not 진입일문자:
            continue
        daily = frames.get(str(row["code"]))
        if daily is None or daily.empty:
            continue
        진입일 = pd.Timestamp(진입일문자)
        if 진입일 not in daily.index:
            continue

        창 = daily.loc[(daily.index >= 진입일) & (daily.index <= today)]
        if 창.empty:
            continue
        시가 = float(row["entry_open"]) if pd.notna(row["entry_open"]) else np.nan
        if not np.isfinite(시가) or 시가 <= 0:
            continue

        고가 = float(창["high"].max())
        저가 = float(창["low"].min())
        frame.at[i, "high_since"] = round(고가, 2)
        frame.at[i, "high_date"] = str(창["high"].idxmax().date())
        frame.at[i, "low_since"] = round(저가, 2)
        frame.at[i, "low_date"] = str(창["low"].idxmin().date())
        frame.at[i, "last_checked"] = str(today.date())

        목표 = float(row["target_pct"]) if pd.notna(row["target_pct"]) else TARGET_PCT
        무효 = float(row["invalid_pct"]) if pd.notna(row["invalid_pct"]) else INVALID_PCT

        # 한 번 닿은 날은 덮어쓰지 않습니다 — 처음 닿은 날이 사실입니다.
        if not str(row.get("target_hit_date", "")):
            닿음 = 창.index[창["high"] >= 시가 * (1 + 목표 / 100.0)]
            if len(닿음):
                frame.at[i, "target_hit_date"] = str(닿음[0].date())
        if not str(row.get("invalid_hit_date", "")):
            닿음 = 창.index[창["low"] <= 시가 * (1 + 무효 / 100.0)]
            if len(닿음):
                frame.at[i, "invalid_hit_date"] = str(닿음[0].date())
        갱신 += 1

    return frame, 갱신


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
    setup: str = ""
    version: str = ""
    target_hit: bool = False
    invalid_hit: bool = False
    basis: str = ""


def score_rows(frame: pd.DataFrame, frames: dict[str, pd.DataFrame],
               index: pd.DataFrame, horizon: int = 20,
               only_bought: bool = True,
               today: pd.Timestamp | None = None,
               version: str | None = None) -> list[Scored]:
    """기간이 찬 기록을 채점합니다. 진입일 시가에서 N거래일 뒤 종가까지.

    정정된 원본 줄은 빼고 봅니다(지우지는 않습니다). 판(version)을 주면
    그 판의 기록만 봅니다 — 조건이 바뀐 앞뒤를 섞으면, 바뀐 규칙이
    예전 성적을 물려받습니다.
    """
    if frame.empty:
        return []
    today = today or pd.Timestamp.today().normalize()
    frame = active(frame)
    if version is not None and "version" in frame:
        frame = frame[frame["version"].astype(str) == str(version)]

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
            setup=str(row.get("setup", "")),
            version=str(row.get("version", "")),
            target_hit=bool(str(row.get("target_hit_date", ""))),
            invalid_hit=bool(str(row.get("invalid_hit_date", ""))),
            basis=str(row.get("basis", "")),
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


def versions_seen(frame: pd.DataFrame) -> list[str]:
    """기록에 남은 판. 두 개 이상이면 섞어 보면 안 됩니다."""
    if frame.empty or "version" not in frame:
        return []
    return sorted({str(v) for v in frame["version"] if str(v).strip()})


def corrections(frame: pd.DataFrame) -> pd.DataFrame:
    """정정 기록만. 무엇을 언제 왜 고쳤는지 남아 있어야 합니다."""
    if frame.empty or "kind" not in frame:
        return pd.DataFrame()
    return frame[frame["kind"].astype(str) == KIND_FIX]


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

    판들 = versions_seen(frame)
    if len(판들) > 1:
        lines.append("")
        lines.append(f"[사실] ⚠️ 판이 {len(판들)}개 섞여 있습니다: {', '.join(판들)}")
        lines.append("   프로그램 기준이 바뀌었다는 뜻입니다. 판별로 나눠서 봐야")
        lines.append("   합니다. 섞어 보면 바뀐 규칙이 예전 성적을 물려받습니다.")

    고친것 = corrections(frame)
    if not 고친것.empty:
        lines.append("")
        lines.append(f"[사실] 정정 기록 {len(고친것)}건 (원본은 지우지 않고 남아 있습니다)")
        for _, row in 고친것.head(5).iterrows():
            lines.append(f"   {row['recorded_at']}  {row['name']}({row['code']})"
                         f"  → {str(row['basis'])[:50]}")

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
