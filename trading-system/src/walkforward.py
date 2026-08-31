"""워크포워드 검증 — 과거에 맞춘 답인지 가려냅니다.

같은 데이터를 보고 조건을 고치면 성적은 반드시 좋아집니다. 답을
보고 시험지를 푸는 것과 같기 때문입니다. 그렇게 만든 전략은
실전에서 무너집니다. 이것을 과최적화라고 합니다.

가리는 방법은 하나뿐입니다. 데이터를 시간 순으로 자르고,
앞쪽만 보고 정한 뒤, 뒤쪽에서는 손대지 않고 시험하는 것입니다.

    2021 ─────── 2023 │ 2024 ─── 2025
    [ 여기서 값을 고른다 ] │ [ 여기서 시험만 한다 ]
          학습 구간        │      검증 구간
                          │
                    이 선을 넘어가면 안 됩니다

검증 구간 성적이 학습 구간과 비슷하면 쓸 만한 것이고, 크게
떨어지면 과거에만 맞춘 답이었다는 뜻입니다.

⚠️ 검증 구간을 보고 다시 값을 고르면 그 순간 검증 구간도
   학습 구간이 됩니다. 한 번만 쓸 수 있는 카드입니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .backtest import Trade, run, summarize
from .config import BacktestConfig, ScannerBConfig


@dataclass
class Split:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp

    def clip(self, daily: pd.DataFrame) -> pd.DataFrame:
        return daily[(daily.index >= self.start) & (daily.index <= self.end)]


@dataclass
class WalkForwardResult:
    setting: str
    train: dict
    test: dict
    train_trades: int = 0
    test_trades: int = 0

    @property
    def decay(self) -> float:
        """학습 대비 검증에서 PF 가 얼마나 떨어졌나 (%)."""
        a = self.train.get("profit_factor", 0.0)
        b = self.test.get("profit_factor", 0.0)
        if not a or a == float("inf"):
            return 0.0
        return (b - a) / a * 100.0

    @property
    def survives(self) -> bool:
        """검증 구간에서도 살아남았는가.

        표본이 너무 적으면 판단할 수 없으므로 매매 30건을 하한으로 둡니다.
        """
        return (
            self.test_trades >= 30
            and self.test.get("profit_factor", 0.0) >= 1.0
            and self.decay > -50.0
        )


def make_splits(
    daily_index: pd.DatetimeIndex, train_ratio: float = 0.6
) -> tuple[Split, Split]:
    """시간 순으로 앞뒤를 자릅니다. 섞지 않습니다."""
    if len(daily_index) < 100:
        raise ValueError("구간을 나누기에 데이터가 너무 짧습니다.")
    ordered = daily_index.sort_values()
    cut = ordered[int(len(ordered) * train_ratio)]
    return (
        Split("학습", ordered[0], cut),
        Split("검증", cut + pd.Timedelta(days=1), ordered[-1]),
    )


def evaluate_setting(
    name: str,
    frames: dict[str, pd.DataFrame],
    bt: BacktestConfig,
    sb: ScannerBConfig,
    splits: tuple[Split, Split],
    market_ok: pd.Series | None = None,
) -> WalkForwardResult:
    """설정 하나를 학습·검증 구간에서 각각 돌립니다."""
    train_split, test_split = splits
    train_trades: list[Trade] = []
    test_trades: list[Trade] = []

    for code, daily in frames.items():
        for split, bucket in ((train_split, train_trades), (test_split, test_trades)):
            part = split.clip(daily)
            if len(part) < sb.sma_slow + 5:
                continue
            bucket.extend(run(code, part, bt, sb, market_ok))

    return WalkForwardResult(
        setting=name,
        train=summarize(train_trades),
        test=summarize(test_trades),
        train_trades=len(train_trades),
        test_trades=len(test_trades),
    )


def report(results: list[WalkForwardResult], splits: tuple[Split, Split]) -> str:
    train_split, test_split = splits
    lines = [
        "=" * 84,
        "[워크포워드 검증] 앞 구간에서 고르고, 뒤 구간에서는 손대지 않고 시험",
        "=" * 84,
        f"  학습 구간  {train_split.start:%Y-%m-%d} ~ {train_split.end:%Y-%m-%d}",
        f"  검증 구간  {test_split.start:%Y-%m-%d} ~ {test_split.end:%Y-%m-%d}",
        "-" * 84,
        f"  {'설정':<24}{'학습 PF':>10}{'검증 PF':>10}{'변화':>9}"
        f"{'학습 매매':>10}{'검증 매매':>10}",
        "-" * 84,
    ]
    for r in sorted(results, key=lambda x: x.test.get("profit_factor", 0), reverse=True):
        mark = "✅" if r.survives else "  "
        lines.append(
            f"{mark}{r.setting:<24}{r.train['profit_factor']:>10.3f}"
            f"{r.test['profit_factor']:>10.3f}{r.decay:>+8.1f}%"
            f"{r.train_trades:>10,}{r.test_trades:>10,}"
        )
    lines += [
        "-" * 84,
        "  ✅ = 검증 구간에서도 PF 1.0 이상이고, 학습 대비 절반 넘게 떨어지지 않음",
        "       (매매 30건 이상일 때만 판정)",
        "",
        "  ※ 검증 구간 성적이 학습 구간과 비슷해야 쓸 만합니다. 크게 떨어지면",
        "     과거에만 맞춘 답이었다는 뜻입니다.",
        "  ※ 이 결과를 보고 값을 다시 고르면, 그 순간 검증 구간도 학습 구간이",
        "     됩니다. 한 번만 쓸 수 있는 카드입니다.",
        "=" * 84,
    ]
    return "\n".join(lines)
