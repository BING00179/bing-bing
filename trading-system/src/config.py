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


@dataclass
class BacktestConfig:
    """백테스트 실행 조건.

    원문 가이드에는 '매도 규칙'이 없습니다. 검증을 하려면 청산 규칙이
    반드시 있어야 하므로 손절/익절/최대보유일을 여기서 정의합니다.
    """

    stop_loss_pct: float = 3.0        # 진입가 대비 손절 폭 (%)
    take_profit_pct: float = 6.0      # 진입가 대비 익절 폭 (%)
    max_hold_days: int = 5            # 최대 보유 거래일
    commission_per_trade: float = 1.0  # 편도 수수료 ($)
    slippage_pct: float = 0.1         # 편도 슬리피지 (%)
    capital_per_trade: float = 10_000.0  # 1회 매매 투입 금액 ($)


@dataclass
class Config:
    scanner_a: ScannerAConfig = field(default_factory=ScannerAConfig)
    scanner_b: ScannerBConfig = field(default_factory=ScannerBConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    universe_file: str = "data/universe.txt"
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
            backtest=BacktestConfig(**raw.get("backtest", {})),
            universe_file=raw.get("universe_file", "data/universe.txt"),
            output_dir=raw.get("output_dir", "output"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
