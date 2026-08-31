"""비용 가정을 바꿔 돌릴 수 있는지 검사.

--market-filter 가 실제로는 아무것도 안 하는 채로 커맨드라인에만 붙어
있던 적이 있습니다. 그때 1~2시간짜리 백테스트를 두 번 헛돌렸습니다.
그래서 여기서는 '옵션이 있나' 가 아니라 '옵션이 계산까지 도달하나' 를
검사합니다. 값이 전달되지 않으면 이 파일이 깨져야 합니다.
"""

from __future__ import annotations

import argparse

import pytest

from src import cli
from src.config import Config


def _args(**kwargs) -> argparse.Namespace:
    base = {"slippage": None, "commission": None, "sell_tax": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_아무것도_안_주면_원래_값_그대로다(capsys):
    cfg = Config()
    before = cfg.backtest_kr
    cli._apply_cost_overrides(cfg, _args())
    assert cfg.backtest_kr.slippage_pct == before.slippage_pct
    assert cfg.backtest_kr.commission_pct == before.commission_pct
    assert cfg.backtest_kr.sell_tax_pct == before.sell_tax_pct


def test_슬리피지가_설정에_실제로_반영된다():
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args(slippage=0.3))
    assert cfg.backtest_kr.slippage_pct == 0.3      # 화면에만 찍히고 끝나면 실패


def test_수수료와_거래세도_반영된다():
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args(commission=0.05, sell_tax=0.25))
    assert cfg.backtest_kr.commission_pct == 0.05
    assert cfg.backtest_kr.sell_tax_pct == 0.25


def test_바꾸지_않은_항목은_건드리지_않는다():
    cfg = Config()
    원래_손절 = cfg.backtest_kr.stop_loss_pct
    원래_투입금 = cfg.backtest_kr.capital_per_trade
    cli._apply_cost_overrides(cfg, _args(slippage=0.5))
    assert cfg.backtest_kr.stop_loss_pct == 원래_손절
    assert cfg.backtest_kr.capital_per_trade == 원래_투입금


def test_바꾼_값을_화면에_반드시_찍는다(capsys):
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args(slippage=0.3))
    화면 = capsys.readouterr().out
    assert "0.15" in 화면 and "0.3" in 화면    # 무엇에서 무엇으로 바뀌었는지


def test_왕복_총비용을_항상_알려준다(capsys):
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args())
    화면 = capsys.readouterr().out
    assert "왕복 총비용" in 화면
    assert "0.510" in 화면                     # 0.15*2 + 0.015*2 + 0.18


def test_슬리피지를_올리면_왕복_비용도_같이_오른다(capsys):
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args(slippage=0.3))
    화면 = capsys.readouterr().out
    assert "0.810" in 화면                     # 0.3*2 + 0.015*2 + 0.18


def test_바꾼_비용이_실제_손익_계산까지_내려간다():
    """설정만 바뀌고 백테스트가 옛 값을 쓰면 의미가 없습니다."""
    import numpy as np
    import pandas as pd

    from src import backtest as bt_module
    from src.config import ScannerBConfig

    days = pd.bdate_range("2020-01-01", periods=320)
    rng = np.random.default_rng(0)
    close = pd.Series(100 + np.cumsum(rng.normal(0.25, 1.0, len(days))), index=days)
    # 종가가 그날 고가 바로 아래여야 '신고가 갱신' 조건이 걸립니다.
    # 고가를 3% 위에 두면 조건 4 가 영원히 안 맞아, 신호 0건짜리
    # 무의미한 표본이 됩니다 (예전에 실제로 이걸로 헛돌았습니다).
    daily = pd.DataFrame({
        "open": close * 0.995,
        "high": close * 1.001,
        "low": close * 0.985,
        "close": close,
        "volume": 1_000_000,
    })

    sb = ScannerBConfig()
    싼비용 = Config()
    cli._apply_cost_overrides(싼비용, _args(slippage=0.0, commission=0.0, sell_tax=0.0))
    비싼비용 = Config()
    cli._apply_cost_overrides(비싼비용, _args(slippage=2.0, commission=1.0, sell_tax=1.0))

    싼결과 = bt_module.run("T", daily, 싼비용.backtest_kr, sb)
    비싼결과 = bt_module.run("T", daily, 비싼비용.backtest_kr, sb)

    if not 싼결과:
        pytest.fail("표본에서 신호가 하나도 안 났습니다 — 이 검사는 아무것도 확인하지 못합니다")

    assert sum(t.pnl for t in 비싼결과) < sum(t.pnl for t in 싼결과)
