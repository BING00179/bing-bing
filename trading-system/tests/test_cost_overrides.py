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
    assert "0.528" in 화면                     # 0.15*2 + 0.014*2 + 0.20


def test_슬리피지를_올리면_왕복_비용도_같이_오른다(capsys):
    cfg = Config()
    cli._apply_cost_overrides(cfg, _args(slippage=0.3))
    화면 = capsys.readouterr().out
    assert "0.828" in 화면                     # 0.3*2 + 0.014*2 + 0.20


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


# ────────────────── 시세 서버를 쉬지 않고 때리지 않는가 ──────────────────
# KRX 에서 실제로 하루 IP 차단을 당한 적이 있고, 그때 FinanceDataReader
# 까지 같이 죽었습니다. 회사처럼 여러 사람이 같은 IP 를 쓰는 곳이면
# 남까지 막힙니다.

def test_수백_종목을_훑을_때는_종목마다_쉰다(monkeypatch, tmp_path):
    import pandas as pd
    from src import cli as cli_module

    쉰시간 = []
    monkeypatch.setattr(cli_module.data_kr_module.time, "sleep", 쉰시간.append)

    days = pd.bdate_range("2024-01-01", periods=300)
    표본 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0,
                        "close": 1.0, "volume": 1}, index=days)

    def 가짜받기(code, years=2.0, pause=0.0):
        if pause:
            cli_module.data_kr_module.time.sleep(pause)
        return 표본

    monkeypatch.setattr(cli_module, "fetch_daily_kr", 가짜받기)
    codes = [f"{i:06d}" for i in range(60)]
    cli_module._frames_for(codes, 2.0, 100, None)

    assert len(쉰시간) == 60                       # 종목마다 한 번씩
    assert all(t > 0 for t in 쉰시간)


def test_몇_종목_안_되면_굳이_쉬지_않는다(monkeypatch):
    import pandas as pd
    from src import cli as cli_module

    쉰시간 = []
    monkeypatch.setattr(cli_module.data_kr_module.time, "sleep", 쉰시간.append)

    days = pd.bdate_range("2024-01-01", periods=300)
    표본 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0,
                        "close": 1.0, "volume": 1}, index=days)

    def 가짜받기(code, years=2.0, pause=0.0):
        if pause:
            cli_module.data_kr_module.time.sleep(pause)
        return 표본

    monkeypatch.setattr(cli_module, "fetch_daily_kr", 가짜받기)
    cli_module._frames_for(["000001", "000002"], 2.0, 100, None)
    assert 쉰시간 == []


def test_조회에_실패해도_쉰다(monkeypatch):
    """연달아 때리면 더 나빠집니다. 실패했을 때야말로 쉬어야 합니다."""
    from src import data_kr

    쉰시간 = []
    monkeypatch.setattr(data_kr.time, "sleep", 쉰시간.append)

    class 가짜fdr:
        @staticmethod
        def DataReader(*a, **k):
            raise RuntimeError("접속 거부")

    monkeypatch.setattr(data_kr, "_fdr", lambda: 가짜fdr)
    try:
        data_kr.fetch_daily("005930", pause=0.2)
    except data_kr.DataUnavailable:
        pass
    assert 쉰시간 == [0.2]
