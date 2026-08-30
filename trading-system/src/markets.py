"""시장별 특성 정의.

미국장과 국내장은 거래 구조가 달라서, 같은 전략이라도 조건을
그대로 옮길 수 없습니다. 그 차이를 여기 한곳에 모읍니다.

가장 큰 차이는 '장 시작 전 거래'입니다.

  미국  04:00~09:30 프리마켓에서 실제 체결이 일어납니다.
        그래서 "장 열기 전에 급등 종목을 미리 찾는다"가 성립합니다.

  한국  08:30~09:00 은 동시호가라 예상체결가만 뜨고 실제 체결은
        09:00 에 한꺼번에 일어납니다. 미국식 프리마켓 거래량 같은
        값이 아예 존재하지 않습니다.

그래서 국내장에서는 '프리마켓 고가' 대신 '오늘 시가'를 기준선으로
씁니다. 동시호가로 정해진 시가가 장 시작 시점의 합의 가격이므로,
그 위에 머무는지를 보는 것이 프리마켓 고가 돌파와 가장 가까운 의미입니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketProfile:
    code: str                    # "US" / "KR"
    label: str
    timezone: str
    open_time: str               # 정규장 시작 (현지시각)
    close_time: str              # 정규장 종료
    currency: str
    money_unit: str              # 리포트에 쓸 금액 단위 표기
    has_premarket: bool          # 장 시작 전 연속 거래가 있는가
    price_limit_pct: float | None  # 하루 가격제한폭 (%). 없으면 None
    gap_reference: str           # "premarket" | "open" — 조건 3 의 기준선

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


US = MarketProfile(
    code="US",
    label="미국장",
    timezone="America/New_York",
    open_time="09:30",
    close_time="16:00",
    currency="$",
    money_unit="달러",
    has_premarket=True,
    price_limit_pct=None,        # 미국은 가격제한폭이 없습니다
    gap_reference="premarket",
)

KR = MarketProfile(
    code="KR",
    label="국내장",
    timezone="Asia/Seoul",
    open_time="09:00",
    close_time="15:30",
    currency="₩",
    money_unit="원",
    has_premarket=False,         # 동시호가는 연속 거래가 아닙니다
    price_limit_pct=30.0,        # 상하한가 ±30%
    gap_reference="open",
)

PROFILES = {"US": US, "KR": KR}


def get(code: str) -> MarketProfile:
    key = (code or "US").strip().upper()
    if key not in PROFILES:
        raise ValueError(
            f"모르는 시장 코드입니다: {code!r}. 가능한 값: {', '.join(PROFILES)}"
        )
    return PROFILES[key]
