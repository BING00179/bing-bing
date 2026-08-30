"""설정 로딩.

config.json 에서 값을 읽고, 없으면 기본값을 씁니다.
비밀값(텔레그램 토큰 등)은 절대 config.json 에 넣지 말고
환경변수로만 전달하세요.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class ScannerAConfig:
    """프리마켓 갭 스캐너(스캐너 A) 조건."""

    min_gap_pct: float = 5.0          # 전일 종가 대비 상승률 하한 (%)
    min_price: float = 3.0            # 주가 하한 ($)
    min_premarket_volume: int = 50_000  # 프리마켓 누적 거래량 하한 (주)
    max_results: int = 20
    run_start_et: str = "08:30"       # 이 시간대(ET) 밖에서는 실행하지 않음
    run_end_et: str = "14:00"


@dataclass
class ScannerAKrConfig:
    """국내장 시가갭 스캐너 조건.

    미국판과 두 가지가 다릅니다.
      * 갭 기준: 프리마켓 체결가가 아니라 동시호가로 정해진 '시가'
      * 유동성 기준: 거래량(주)이 아니라 거래대금(원)
        국내는 주가 편차가 커서 1만원짜리 10만주와 100만원짜리
        1천주가 전혀 다른 의미라, 거래대금이 실질적인 기준입니다.
    """

    min_gap_pct: float = 5.0          # 전일 종가 대비 시가 상승률 하한 (%)
    min_price: float = 1_000.0        # 주가 하한 (원) — 동전주 제외
    min_turnover: float = 1_000_000_000.0  # 거래대금 하한 (원, 기본 10억)
    exclude_limit_up: bool = True     # 상한가 종목 제외 (매수 체결이 안 됨)
    max_results: int = 20
    run_start_kst: str = "09:00"      # 이 시간대(KST) 밖에서는 실행하지 않음
    run_end_kst: str = "15:20"


@dataclass
class ScannerBKrConfig:
    """국내장 전략 스캐너 실행 시간대."""

    run_start_kst: str = "10:00"
    run_end_kst: str = "15:20"


@dataclass
class ScannerBConfig:
    """전략 스캐너(스캐너 B) — Trend Join Long 조건."""

    sma_slow: int = 200               # 조건 2 에 쓰이는 장기 이동평균
    sma_fast: int = 20                # 조건 5 추세 정렬용
    sma_mid: int = 50                 # 조건 5 추세 정렬용
    # 조건 1·3: 전일 고가 / 프리마켓 고가처럼 '고정된 기준선' 돌파 판정 여유 (%)
    breakout_tolerance_pct: float = 0.0
    # 조건 4: 현재가(또는 종가)가 '그날 고가'에서 몇 % 이내면 신고가 갱신으로 볼지.
    # 0 으로 두면 현재가가 그날 최고가와 정확히 같아야만 참이 되어 신호가 사실상
    # 나오지 않습니다. 오늘 고가는 현재가 자신이 계속 갱신하는 값이기 때문입니다.
    close_near_high_pct: float = 0.5
    earliest_hour_et: int = 10        # 이 시각(ET) 이후에만 신호 인정
    require_premarket_high: bool = True  # 조건 3 적용 여부
    run_start_et: str = "10:00"       # 이 시간대(ET) 밖에서는 실행하지 않음
    run_end_et: str = "15:05"


@dataclass
class RankingConfig:
    """신호 점수와 상위 몇 개만 알릴지.

    조건을 통과한 종목이 여럿이면 전부 사는 대신 점수 순으로
    상위 top_n 개만 알림으로 보냅니다. 자본이 흩어지지 않고
    거래 횟수도 줄어듭니다.

    ⚠️ 점수가 높다고 더 오른다는 근거는 없습니다. 같은 조건을
    통과한 것들 중 상대적으로 뚜렷한 쪽을 고르는 장치일 뿐입니다.
    """

    enabled: bool = True
    top_n: int = 3                    # 하루에 알릴 최대 종목 수
    min_score: float = 0.0            # 이 점수 미만은 아예 제외

    # 각 항목이 만점을 받는 기준
    gap_full_mark_pct: float = 15.0        # 갭 15% 면 만점
    turnover_full_mark: float = 100_000_000_000.0  # 거래대금 1000억이면 만점
    trend_full_mark_pct: float = 30.0      # 200일선 대비 +30% 면 만점
    trend_overheat_penalty: float = 2.0    # 그 위로는 1%p 당 2점 감점
    near_high_penalty: float = 20.0        # 고가에서 1% 멀어질 때마다 20점 감점

    # 가중치 (합이 1일 필요는 없습니다)
    weight_gap: float = 1.0
    weight_turnover: float = 1.0
    weight_trend: float = 1.5
    weight_near_high: float = 1.5


@dataclass
class MarketFilterConfig:
    """시장 필터 기준값.

    "지금 시장이 살 만한가"를 판정합니다. 기준을 빡빡하게 잡으면
    신호가 거의 안 나오고, 느슨하게 잡으면 필터가 무의미해집니다.
    아래 값은 흔히 쓰는 출발점일 뿐 최적화된 값이 아닙니다.
    """

    enabled: bool = True
    index_code: str = "KS11"          # 코스피 지수 (코스닥은 KQ11)
    index_name: str = "코스피"
    sma_slow: int = 200               # 지수 장기 추세선
    rsi_window: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 75.0
    drawdown_window: int = 252        # 고점 기준 구간 (약 1년)
    drawdown_caution_pct: float = 10.0
    drawdown_danger_pct: float = 20.0
    volatility_window: int = 20
    volatility_caution_pct: float = 25.0
    volatility_danger_pct: float = 35.0
    block_on_caution: bool = False    # '주의'에서도 신호를 막을지


@dataclass
class BacktestConfig:
    """백테스트 실행 조건.

    원문 가이드에는 '매도 규칙'이 없습니다. 검증을 하려면 청산 규칙이
    반드시 있어야 하므로 손절/익절/최대보유일을 여기서 정의합니다.
    """

    stop_loss_pct: float = 3.0        # 진입가 대비 손절 폭 (%)

    # ── 청산 방식 두 가지 ──
    # take_profit_pct: 정해진 이익률에 닿으면 판다 (고정 익절)
    # trailing_stop_pct: 최고가에서 이만큼 밀리면 판다 (추격 손절)
    #
    # 추세추종은 "이익은 끝까지 끌고 가고, 꺾이면 나온다"가 핵심이라
    # 고정 익절과 상성이 나쁩니다. +6% 에서 자동으로 팔면 20% 갈
    # 종목도 6% 에서 끊깁니다. 추격 손절을 켜면 오르는 동안은 계속
    # 따라 올라가고, 고점에서 정해진 폭만큼 밀릴 때 나옵니다.
    #
    # 0 으로 두면 그 방식은 사용하지 않습니다. 둘 다 켜도 되고,
    # 둘 다 0 이면 최대보유일까지 들고 갑니다.
    take_profit_pct: float = 0.0      # 고정 익절 (%). 0 = 사용 안 함
    trailing_stop_pct: float = 7.0    # 추격 손절 (%). 0 = 사용 안 함
    exit_on_ma_break: int = 0         # 종가가 N일선 아래로 마감하면 청산. 0 = 사용 안 함

    max_hold_days: int = 20           # 최대 보유 거래일

    # ── 거래비용 ──
    # 정액과 정률을 둘 다 지원합니다. 미국은 건당 정액 수수료가 흔하고,
    # 국내는 거래대금 대비 정률입니다. 증권거래세는 매도할 때만 붙습니다.
    commission_per_trade: float = 1.0  # 편도 정액 수수료 (통화 단위)
    commission_pct: float = 0.0       # 편도 정률 수수료 (거래대금 대비 %)
    sell_tax_pct: float = 0.0         # 매도세 (%, 매도할 때만)
    slippage_pct: float = 0.1         # 편도 슬리피지 (%)

    # ⚠️ 통화 단위 주의. 미국장은 달러, 국내장은 원입니다.
    # 국내장에서 이 값이 주가보다 작으면 살 수 있는 주식이 0주가 되어
    # 매매가 한 건도 성립하지 않습니다.
    capital_per_trade: float = 10_000.0  # 1회 매매 투입 금액


@dataclass
class BacktestKrConfig(BacktestConfig):
    """국내장 백테스트 설정.

    통화가 원이고 거래비용 구조가 달라서 기본값을 따로 둡니다.

    비용 기본값은 2026년 8월 기준의 흔한 수준을 넣은 것입니다.
    증권거래세율은 해마다 바뀌므로 반드시 현재 요율을 확인하고
    본인 증권사 수수료로 맞춰 주세요. 비용을 낮게 잡으면 백테스트가
    실제보다 좋게 나옵니다.
    """

    commission_per_trade: float = 0.0     # 국내는 정액이 아니라 정률
    commission_pct: float = 0.015         # 편도 수수료율 (%)
    sell_tax_pct: float = 0.18            # 증권거래세 (%, 매도 시)
    slippage_pct: float = 0.15            # 편도 슬리피지 (%)
    capital_per_trade: float = 10_000_000.0  # 1회 투입 1천만원


@dataclass
class Config:
    scanner_a: ScannerAConfig = field(default_factory=ScannerAConfig)
    scanner_b: ScannerBConfig = field(default_factory=ScannerBConfig)
    scanner_a_kr: ScannerAKrConfig = field(default_factory=ScannerAKrConfig)
    scanner_b_kr: ScannerBKrConfig = field(default_factory=ScannerBKrConfig)
    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    backtest_kr: BacktestKrConfig = field(default_factory=BacktestKrConfig)
    universe_file: str = "data/universe.txt"
    universe_file_kr: str = "data/universe_kr.txt"
    output_dir: str = "output"

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            scanner_a=ScannerAConfig(**raw.get("scanner_a", {})),
            scanner_b=ScannerBConfig(**raw.get("scanner_b", {})),
            scanner_a_kr=ScannerAKrConfig(**raw.get("scanner_a_kr", {})),
            scanner_b_kr=ScannerBKrConfig(**raw.get("scanner_b_kr", {})),
            market_filter=MarketFilterConfig(**raw.get("market_filter", {})),
            ranking=RankingConfig(**raw.get("ranking", {})),
            backtest=BacktestConfig(**raw.get("backtest", {})),
            backtest_kr=BacktestKrConfig(**raw.get("backtest_kr", {})),
            universe_file=raw.get("universe_file", "data/universe.txt"),
            universe_file_kr=raw.get("universe_file_kr", "data/universe_kr.txt"),
            output_dir=raw.get("output_dir", "output"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
