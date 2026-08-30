"""알림을 언제 보낼지 결정합니다.

스캐너는 장중 30분마다 돕니다. 결과를 매번 보내면 하루 13번,
대부분 "신호 없음"인 메시지가 옵니다. 그러면 알림을 꺼버리게 되고,
정작 진짜 신호가 왔을 때 못 봅니다.

그래서 이렇게 정했습니다.

  · 새로운 종목이 신호에 뜨면 → 보냅니다
  · 이미 오늘 알린 종목만 다시 뜨면 → 보내지 않습니다
  · 시장 판정이 바뀌면 (정상→위험 등) → 한 번 보냅니다
  · 같은 판정이 계속되면 → 보내지 않습니다
  · 장 마감 요약 → 따로 한 번 보냅니다

'오늘 무엇을 이미 알렸는가' 는 파일에 남깁니다. 깃허브 서버는
실행할 때마다 새 컴퓨터라 기억이 없기 때문에, 저장소에 함께
올려 다음 실행이 이어받게 합니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILE = "notified.json"


@dataclass
class NotifyState:
    date: str = ""
    market_verdict: str = ""
    codes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, directory: Path, today: str) -> "NotifyState":
        path = directory / STATE_FILE
        if not path.exists():
            return cls(date=today)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls(date=today)
        if raw.get("date") != today:
            return cls(date=today)          # 날짜가 바뀌면 새로 시작
        return cls(
            date=raw.get("date", today),
            market_verdict=raw.get("market_verdict", ""),
            codes=list(raw.get("codes", [])),
        )

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / STATE_FILE).write_text(
            json.dumps(
                {"date": self.date, "market_verdict": self.market_verdict,
                 "codes": self.codes},
                ensure_ascii=False, indent=1,
            ),
            encoding="utf-8",
        )


@dataclass
class Decision:
    send: bool
    reason: str
    new_codes: list[str] = field(default_factory=list)
    market_changed: bool = False


def decide(
    state: NotifyState,
    signal_codes: list[str],
    market_verdict: str,
) -> Decision:
    """지금 알림을 보낼지 판단합니다. 상태는 바꾸지 않습니다."""
    new_codes = [c for c in signal_codes if c not in state.codes]
    market_changed = bool(market_verdict) and market_verdict != state.market_verdict

    if new_codes:
        return Decision(True, f"새 신호 {len(new_codes)}종목", new_codes, market_changed)
    if market_changed:
        return Decision(True, f"시장 판정 변경 → {market_verdict}", [], True)
    return Decision(False, "새로운 내용 없음", [], False)


def commit(state: NotifyState, signal_codes: list[str], market_verdict: str) -> None:
    """보냈다고 기록합니다."""
    for code in signal_codes:
        if code not in state.codes:
            state.codes.append(code)
    if market_verdict:
        state.market_verdict = market_verdict
