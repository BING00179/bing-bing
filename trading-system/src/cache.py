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

CACHE_VERSION = 1
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
    directory: Path
    codes: int
    fetched_on: str
    years: float

    def as_line(self) -> str:
        age = (date.today() - date.fromisoformat(self.fetched_on)).days
        stale = "  ⚠️ 오래됨" if age > 7 else ""
        return (
            f"저장된 시세 {self.codes:,}종목 · {self.years}년치 · "
            f"{self.fetched_on} 기준 ({age}일 전){stale}"
        )


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
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / META_FILE).write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "codes": codes,
                    "years": years,
                    "fetched_on": date.today().isoformat(),
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
        return CacheInfo(
            directory=self.directory,
            codes=int(raw.get("codes", 0)),
            fetched_on=str(raw.get("fetched_on", date.today().isoformat())),
            years=float(raw.get("years", 0.0)),
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
