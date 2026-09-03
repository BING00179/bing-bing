"""시세 저장고 — 한 번 받은 것은 다시 받지 않습니다.

지금까지는 검증할 때마다 1,700종목의 시세를 새로 받았습니다.
종목당 1~2초라 한 번에 한두 시간이 걸립니다. 그런데 그 시간의
대부분은 계산이 아니라 기다림입니다.

    설정 하나 검증  =  시세 받기 100분  +  계산 2분

같은 시세로 설정만 바꿔 스무 번 돌리려면 33시간이 걸립니다.
받아둔 것을 파일로 남기면 두 번째부터는 몇 초입니다.

    첫 실행    시세 받기 100분  +  계산 2분
    두 번째    파일 읽기 5초    +  계산 2분

저장 형식은 parquet 를 쓰되, 그 라이브러리가 없으면 pickle 로
넘어갑니다. 둘 다 CSV 와 달리 자료형이 보존됩니다(날짜가 문자열로
바뀌는 일이 없습니다). 추가 설치 없이도 동작하게 하기 위해서입니다.

pickle 은 파일 안의 내용을 그대로 되살리는 형식이라, 남이 준 파일을
읽으면 위험할 수 있습니다. 여기서는 이 프로그램이 직접 만들어
자기 폴더에 둔 파일만 읽습니다.

⚠️ 저장된 시세는 받은 날짜에 멈춰 있습니다. 오늘 시세가 필요한
   실시간 스캔에는 쓰지 않습니다. 과거를 검증하는 용도입니다.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

CACHE_VERSION = 2
META_FILE = "_meta.json"


def _parquet_available() -> bool:
    """parquet 를 쓸 수 있는지. 불러오지 않고 설치 여부만 봅니다."""
    return any(
        importlib.util.find_spec(name) is not None
        for name in ("pyarrow", "fastparquet")
    )


USE_PARQUET = _parquet_available()
SUFFIX = ".parquet" if USE_PARQUET else ".pkl"


@dataclass
class CacheInfo:
    """저장고에 실제로 들어 있는 것. 마지막 실행이 아니라 **전체**를 말합니다.

    저장고는 여러 번에 걸쳐 채워집니다. 14종목을 5년치로 받은 실행이
    1,821종목 3년치 저장고의 이름표를 "5년치, 오늘 받음" 으로 덮어쓰면,
    화면은 그럴듯해지고 판단은 망가집니다. 그래서 섞였으면 섞였다고
    적습니다.
    """
    directory: Path
    codes: int
    years_min: float
    years_max: float
    first_on: str        # 제일 오래전에 받은 날
    last_on: str         # 제일 최근에 받은 날

    @property
    def mixed(self) -> bool:
        return self.years_min != self.years_max or self.first_on != self.last_on

    def as_line(self) -> str:
        # 오래됐는지는 **제일 오래된 것** 기준으로 봅니다.
        age = (date.today() - date.fromisoformat(self.first_on)).days
        stale = "  ⚠️ 오래됨" if age > 7 else ""

        if self.years_min == self.years_max:
            기간 = f"{self.years_min:g}년치"
        else:
            기간 = f"{self.years_min:g}~{self.years_max:g}년치 (섞임)"

        if self.first_on == self.last_on:
            언제 = f"{self.first_on} 기준 ({age}일 전)"
        else:
            언제 = f"{self.first_on}~{self.last_on} 에 나눠 받음 (섞임)"

        return f"저장된 시세 {self.codes:,}종목 · {기간} · {언제}{stale}"


class PriceCache:
    """종목별 일봉을 파일로 보관합니다."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    # ── 읽기 ──

    def path_for(self, code: str) -> Path:
        return self.directory / f"{code}{SUFFIX}"

    def has(self, code: str) -> bool:
        return self.path_for(code).exists()

    def get(self, code: str) -> pd.DataFrame | None:
        path = self.path_for(code)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path) if USE_PARQUET else pd.read_pickle(path)
        except Exception:  # noqa: BLE001 - 깨진 파일은 없는 것으로 봅니다
            return None

    def load_all(self, codes: list[str] | None = None) -> dict[str, pd.DataFrame]:
        """저장된 시세를 한꺼번에 읽습니다."""
        if codes is None:
            codes = [p.stem for p in self.directory.glob(f"*{SUFFIX}")]
        out: dict[str, pd.DataFrame] = {}
        for code in codes:
            frame = self.get(code)
            if frame is not None and not frame.empty:
                out[code] = frame
        return out

    # ── 쓰기 ──

    def put(self, code: str, frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(code)
        if USE_PARQUET:
            frame.to_parquet(path)
        else:
            frame.to_pickle(path)

    def save_meta(self, codes: int, years: float) -> None:
        """이름표를 갱신합니다 — **덮어쓰지 않고 합칩니다.**

        14종목을 5년치로 받은 실행이 1,821종목 3년치 저장고의 이름표를
        통째로 바꿔 버리면 안 됩니다. 기간은 넓은 쪽으로, 받은 날은
        처음과 마지막을 둘 다 남깁니다.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        오늘 = date.today().isoformat()
        이전 = self.info()

        years_min = min(이전.years_min, years) if 이전 else years
        years_max = max(이전.years_max, years) if 이전 else years
        first_on = min(이전.first_on, 오늘) if 이전 else 오늘

        (self.directory / META_FILE).write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "codes": codes,
                    "years_min": years_min,
                    "years_max": years_max,
                    "first_on": first_on,
                    "last_on": 오늘,
                    # 옛 형식으로 읽는 곳을 위해 남겨 둡니다. 넓게 보는 쪽
                    # (제일 짧은 기간, 제일 오래된 날) 을 적습니다.
                    "years": years_min,
                    "fetched_on": first_on,
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    # ── 상태 ──

    def info(self) -> CacheInfo | None:
        path = self.directory / META_FILE
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        # 옛 형식(years / fetched_on 하나씩)도 읽을 수 있게 합니다.
        옛기간 = float(raw.get("years", 0.0))
        옛날짜 = str(raw.get("fetched_on", date.today().isoformat()))
        return CacheInfo(
            directory=self.directory,
            codes=int(raw.get("codes", 0)),
            years_min=float(raw.get("years_min", 옛기간)),
            years_max=float(raw.get("years_max", 옛기간)),
            first_on=str(raw.get("first_on", 옛날짜)),
            last_on=str(raw.get("last_on", 옛날짜)),
        )

    def stored_codes(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob(f"*{SUFFIX}"))

    def clear(self) -> int:
        """저장된 것을 전부 지웁니다. 지운 개수를 돌려줍니다."""
        removed = 0
        for path in self.directory.glob(f"*{SUFFIX}"):
            path.unlink()
            removed += 1
        meta = self.directory / META_FILE
        if meta.exists():
            meta.unlink()
        return removed
