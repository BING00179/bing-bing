import json

from src.config import Config, VirtualAccountConfig


def test_가상_계좌_설정은_사장님_값이_기본이다():
    v = VirtualAccountConfig()
    assert v.capital == 5_000_000 and v.max_positions == 6
    assert v.buy_tranches_pct == (30, 30, 40)
    assert v.sell_tranches == ((10.0, 30), (20.0, 40), (35.0, 30))
    assert v.invalid_pct == -20.0 and v.daily_loss_halt_pct == -3.0


def test_config_json_에서_읽는다(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"virtual_account": {"capital": 1000, "buy_tranches_pct": [50, 50, 0],
                                                 "sell_tranches": [[10, 100]]}}), encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.virtual_account.capital == 1000
    assert cfg.virtual_account.buy_tranches_pct == (50, 50, 0)   # list → tuple
    assert cfg.virtual_account.sell_tranches == ((10.0, 100),)


def test_저장소_config_json_에_절이_있다():
    cfg = Config.load()
    assert cfg.virtual_account.capital == 5_000_000
