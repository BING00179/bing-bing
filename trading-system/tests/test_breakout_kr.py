"""깨어나는 종목 탐지기 검사.

여기서 가장 위험한 것은 미래를 보는 것입니다. 오늘 고가를 오늘의
돌파 판정에 쓰거나, 거래량이 터진 날을 '조용했던 기간' 에 포함하면
어떤 종목이든 신호가 나고, 백테스트는 환상적으로 나옵니다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import breakout_kr as bo


def _bars(closes, volumes=None, start="2024-01-01", spread=0.01):
    closes = [float(c) for c in closes]
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx)
    return pd.DataFrame({
        "open": close,
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": (list(volumes) if volumes is not None
                   else [10_000] * len(closes)),
    })


def _quiet_then_wake(base_days=60, surge_days=5, quiet_price=1000.0,
                     jump=1.15, quiet_vol=10_000, surge_vol=100_000):
    """오래 조용하다가 거래량이 터지며 위로 벗어나는 자료."""
    n = base_days + 40
    closes = list(np.random.default_rng(0).normal(quiet_price, 5.0, n))
    vols = [quiet_vol] * n
    # 실제 돌파는 며칠에 걸쳐 계단처럼 올라갑니다. 마지막 며칠을 같은
    # 값으로 두면 첫날만 신고가라 조건이 영영 안 맞습니다.
    for k, i in enumerate(range(n - surge_days, n), 1):
        closes[i] = quiet_price * (1 + (jump - 1) * k / surge_days)
        vols[i] = surge_vol
    return _bars(closes, vols)


# ────────────────────── 각 조건 ──────────────────────

def test_박스폭은_최근_구간을_빼고_잰다():
    """거래량이 터진 날들을 '조용했던 기간' 에 넣으면 안 됩니다."""
    daily = _quiet_then_wake()
    포함 = bo.base_range_pct(daily, 60, offset=0).iloc[-1]
    제외 = bo.base_range_pct(daily, 60, offset=5).iloc[-1]
    assert 제외 < 포함                    # 급등 구간을 빼면 더 좁게 나옴


def test_거래량_배수는_자기_자신을_나누지_않는다():
    daily = _quiet_then_wake(quiet_vol=10_000, surge_vol=100_000)
    배수 = bo.volume_multiple(daily, 5, 60).iloc[-1]
    assert 배수 > 5.0                     # 조용할 때의 10배쯤 되어야 함


def test_평소와_같으면_배수가_1_근처다():
    daily = _bars([1000.0] * 100, [10_000] * 100)
    assert abs(bo.volume_multiple(daily, 5, 60).iloc[-1] - 1.0) < 0.05


def test_돌파는_오늘_고가를_쓰지_않는다():
    """오늘 고가를 포함하면 언제나 참이 되어 아무 뜻이 없습니다."""
    daily = _bars([100.0] * 70 + [200.0])
    assert bool(bo.broke_out(daily, 60, offset=1).iloc[-1])
    # 오늘까지 포함해서 재면(offset=0) 오늘 고가가 최고라 절대 못 넘습니다
    assert not bool(bo.broke_out(daily, 60, offset=0).iloc[-1])


def test_상승률은_구간_최저_종가_대비다():
    daily = _bars([100.0] * 60 + [150.0])
    assert abs(bo.runup_pct(daily, 60).iloc[-1] - 50.0) < 1.0


def test_자료가_모자라면_숫자를_지어내지_않는다():
    daily = _bars([100.0] * 10)
    assert pd.isna(bo.base_range_pct(daily, 60).iloc[-1])
    assert pd.isna(bo.volume_multiple(daily, 5, 60).iloc[-1])


# ────────────────────── 신호 ──────────────────────

def test_조용하다_깨어나면_신호가_난다():
    daily = _quiet_then_wake()
    daily["volume"] = daily["volume"] * 100          # 거래대금 하한 넘기기
    table = bo.signals(daily, bo.Setup())
    assert bool(table["signal"].iloc[-1])


def test_계속_시끄러웠으면_신호가_안_난다():
    """박스가 넓으면 '조용했다' 가 아닙니다."""
    rng = np.random.default_rng(1)
    closes = 1000 * np.cumprod(1 + rng.normal(0, 0.06, 110))
    daily = _bars(closes, [1_000_000] * 110)
    table = bo.signals(daily, bo.Setup())
    assert not table["1_조용했나"].iloc[-1]


def test_거래량이_안_터지면_신호가_안_난다():
    daily = _quiet_then_wake(surge_vol=10_000)       # 평소와 같은 거래량
    daily["volume"] = daily["volume"] * 100
    table = bo.signals(daily, bo.Setup())
    assert not table["2_깨어났나"].iloc[-1]
    assert not table["signal"].iloc[-1]


def test_이미_많이_올랐으면_늦었다고_본다():
    daily = _quiet_then_wake(jump=2.5)               # 이미 150% 상승
    daily["volume"] = daily["volume"] * 100
    table = bo.signals(daily, bo.Setup())
    assert not table["4_아직이른가"].iloc[-1]
    assert not table["signal"].iloc[-1]


def test_거래가_적으면_신호가_안_난다():
    daily = _quiet_then_wake()                       # 거래대금 몇 백만원
    table = bo.signals(daily, bo.Setup())
    assert not table["5_사고팔수있나"].iloc[-1]


def test_조건_다섯_개가_모두_맞아야_신호다():
    daily = _quiet_then_wake()
    daily["volume"] = daily["volume"] * 100
    table = bo.signals(daily, bo.Setup())
    조건 = ["1_조용했나", "2_깨어났나", "3_벗어났나", "4_아직이른가", "5_사고팔수있나"]
    난날 = table.index[table["signal"]]
    for 날 in 난날:
        assert all(bool(table.at[날, c]) for c in 조건)


# ────────────────────── 훑기 ──────────────────────

def test_오늘_신호가_난_종목만_돌려준다():
    좋은것 = _quiet_then_wake()
    좋은것["volume"] = 좋은것["volume"] * 100
    조용한것 = _bars([1000.0] * 110, [1_000_000] * 110)
    hits = bo.scan_today({"A": 좋은것, "B": 조용한것}, bo.Setup(),
                         names={"A": "깨어난주", "B": "잠든주"})
    assert [h.code for h in hits] == ["A"]
    assert hits[0].name == "깨어난주"


def test_자료가_짧은_종목은_건너뛴다():
    assert bo.scan_today({"A": _bars([100.0] * 20)}, bo.Setup()) == []


def test_점수가_높은_것이_위로_온다():
    낮음 = pd.Series({"거래량배수": 3.0, "박스폭%": 44.0, "상승률%": 39.0})
    높음 = pd.Series({"거래량배수": 15.0, "박스폭%": 10.0, "상승률%": 5.0})
    assert bo.score(높음) > bo.score(낮음)


def test_값이_없으면_점수는_0이다():
    assert bo.score(pd.Series({"거래량배수": np.nan})) == 0.0


# ────────────────────── 보고서 ──────────────────────

def test_보고서는_검증되지_않았음을_반드시_말한다():
    text = bo.report([], bo.Setup())
    assert "검증된 것이 아닙니다" in text
    assert "0.779" in text                 # 전에 실패한 숫자를 잊지 않기
    assert "매수 신호가 아닙니다" in text


def test_없으면_없는_것이_정상이라고_말한다():
    text = bo.report([], bo.Setup())
    assert "드물게 나오는 것이 정상" in text
    assert "억지로 조건을 풀어" in text


def test_보고서는_건_조건을_먼저_적는다():
    text = bo.report([], bo.Setup(min_volume_mult=5.0))
    assert "5.0배" in text


def test_사실과_해석을_가른다():
    text = bo.report([], bo.Setup())
    assert "[사실]" in text and "[해석]" in text


def test_돌파_첫날에만_요구하면_영영_안_걸린다():
    """돌파는 하루짜리 사건, 거래량은 며칠에 걸쳐 터집니다.

    같은 날에만 둘 다 요구하면 첫날에는 거래량 평균이 아직 안 오르고,
    거래량이 오를 때쯤엔 이미 신고가가 아닙니다. 실제로 이 조건 때문에
    신호가 한 건도 안 났습니다.
    """
    # 하루 확 뛰고 그 값에서 옆으로 가는 모양. 신고가는 첫날 하루뿐입니다.
    closes = [1000.0] * 70 + [1200.0] * 4
    daily = _bars(closes, [1_000_000] * len(closes))

    하루짜리 = bo.broke_out(daily, 60)
    며칠안에 = bo.broke_out_recently(daily, 60, 5)

    assert 하루짜리.sum() == 1                 # 돌파는 첫날 하루뿐
    assert not bool(하루짜리.iloc[-1])          # 거래량이 오를 때쯤엔 이미 거짓
    assert bool(며칠안에.iloc[-1])              # '최근 며칠 안에' 로 보면 살아 있음
    assert 며칠안에.sum() > 하루짜리.sum()


def test_한_번도_박스를_안_벗어났으면_거짓이다():
    daily = _bars([100.0] * 110, [1_000_000] * 110)
    assert not bool(bo.broke_out_recently(daily, 60, 5).iloc[-1])
