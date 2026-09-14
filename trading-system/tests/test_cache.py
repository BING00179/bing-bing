"""시세 저장고 — 한 번 받은 것을 다시 받지 않는가."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from src.cache import META_FILE, PriceCache


def frame(rows=5):
    return pd.DataFrame(
        {
            "open": range(rows), "high": range(rows), "low": range(rows),
            "close": range(rows), "volume": range(rows),
        },
        index=pd.bdate_range("2024-01-01", periods=rows),
    ).astype(float)


def test_saved_data_comes_back_identical(tmp_path):
    cache = PriceCache(tmp_path)
    original = frame()
    cache.put("005930", original)
    pd.testing.assert_frame_equal(cache.get("005930"), original)


def test_date_index_survives_the_round_trip(tmp_path):
    """CSV 로 저장하면 날짜가 문자열이 됩니다. 그러면 안 됩니다."""
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    assert isinstance(cache.get("005930").index, pd.DatetimeIndex)


def test_missing_code_returns_none(tmp_path):
    assert PriceCache(tmp_path).get("999999") is None


def test_empty_frame_is_not_saved(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", pd.DataFrame())
    assert not cache.has("005930")


def test_corrupt_file_is_treated_as_missing(tmp_path):
    """깨진 파일 하나가 전체를 멈추면 안 됩니다."""
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.path_for("005930").write_bytes("쓰레기".encode("utf-8"))
    assert cache.get("005930") is None


def test_load_all_skips_broken_entries(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.put("000660", frame())
    cache.path_for("000660").write_bytes(b"x")

    loaded = cache.load_all()
    assert "005930" in loaded
    assert "000660" not in loaded


def test_meta_records_when_it_was_fetched(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(codes=1, years=3.0)

    info = cache.info()
    assert info.codes == 1
    assert info.first_on == date.today().isoformat()
    assert info.last_on == date.today().isoformat()
    assert "3년치" in info.as_line()


def test_old_cache_is_flagged(tmp_path):
    """오래된 시세를 모르고 쓰면 안 됩니다."""
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(1, 3.0)

    old = (date.today() - timedelta(days=30)).isoformat()
    path = tmp_path / META_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["first_on"] = raw["last_on"] = raw["fetched_on"] = old
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert "오래됨" in PriceCache(tmp_path).info().as_line()


def test_fresh_cache_is_not_flagged(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(1, 3.0)
    assert "오래됨" not in cache.info().as_line()


def test_no_meta_returns_none(tmp_path):
    assert PriceCache(tmp_path).info() is None


def test_clear_removes_everything(tmp_path):
    cache = PriceCache(tmp_path)
    for code in ("005930", "000660", "035720"):
        cache.put(code, frame())
    cache.save_meta(3, 3.0)

    assert cache.clear() == 3
    assert cache.stored_codes() == []
    assert cache.info() is None


def test_stored_codes_are_sorted(tmp_path):
    cache = PriceCache(tmp_path)
    for code in ("035720", "005930", "000660"):
        cache.put(code, frame())
    assert cache.stored_codes() == ["000660", "005930", "035720"]


def test_reading_is_much_faster_than_a_network_fetch(tmp_path):
    """저장분 읽기가 실제로 빨라야 의미가 있습니다."""
    import time

    cache = PriceCache(tmp_path)
    big = frame(rows=750)
    for i in range(50):
        cache.put(f"{i:06d}", big)

    start = time.perf_counter()
    loaded = cache.load_all()
    elapsed = time.perf_counter() - start

    assert len(loaded) == 50
    assert elapsed < 2.0, f"50종목 읽는 데 {elapsed:.1f}초 걸렸습니다"


# ────────── 이름표가 거짓말을 하지 않는가 ──────────
#
# 실제로 겪은 일입니다. 14종목을 5년치로 받은 실행이 1,821종목 3년치
# 저장고의 이름표를 "1,832종목 · 5.0년치 · 오늘 받음" 으로 덮어썼습니다.
# 화면만 그럴듯해지고 실제 자료는 3년치였습니다.

def test_작은_실행이_큰_저장고의_이름표를_덮어쓰지_않는다(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(codes=1821, years=3.0)      # 어제 크게 받아둔 것
    cache.save_meta(codes=1832, years=5.0)      # 오늘 14종목만 5년치로

    줄 = cache.info().as_line()
    assert "5년치" not in 줄 or "섞임" in 줄
    assert "3~5년치 (섞임)" in 줄


def test_기간이_섞이면_섞였다고_적는다(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(codes=10, years=2.0)
    cache.save_meta(codes=12, years=5.0)
    info = cache.info()
    assert info.mixed
    assert info.years_min == 2.0 and info.years_max == 5.0


def test_같은_조건으로_다시_받으면_섞였다고_하지_않는다(tmp_path):
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(codes=10, years=3.0)
    cache.save_meta(codes=12, years=3.0)
    info = cache.info()
    assert not info.mixed
    assert "섞임" not in info.as_line()


def test_오래됨은_제일_오래된_것을_기준으로_본다(tmp_path):
    """새로 받은 게 섞였다고 '싱싱하다' 고 하면 안 됩니다."""
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(codes=1000, years=3.0)

    옛날 = (date.today() - timedelta(days=30)).isoformat()
    path = tmp_path / META_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["first_on"] = 옛날                      # 대부분은 한 달 전에 받은 것
    path.write_text(json.dumps(raw), encoding="utf-8")

    cache.save_meta(codes=1010, years=3.0)      # 오늘 열 종목만 더 받음
    줄 = cache.info().as_line()
    assert "오래됨" in 줄
    assert "나눠 받음" in 줄


def test_옛_형식_이름표도_읽는다(tmp_path):
    """전에 만든 저장고를 못 읽어서 다시 받게 하면 안 됩니다."""
    (tmp_path / META_FILE).write_text(json.dumps(
        {"version": 1, "codes": 500, "years": 3.0, "fetched_on": "2026-08-01"},
    ), encoding="utf-8")
    info = PriceCache(tmp_path).info()
    assert info.codes == 500
    assert info.years_min == info.years_max == 3.0
    assert info.first_on == info.last_on == "2026-08-01"
    assert not info.mixed


# ────────── 이름표 말고 실제를 재는가 ──────────
#
# info() 는 저장할 때 적어둔 말입니다. 파일을 열어본 것이 아닙니다.
# 2026-09-14 실제로 사무실 이름표는 "3.0년치", 집 이름표는 "1.2년치"
# 였는데 어느 쪽이 맞는지 이름표로는 알 수 없었습니다.

def _frame_days(n, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        index=idx,
    )


def test_실제로_열어서_기간을_센다(tmp_path):
    cache = PriceCache(tmp_path)
    for i in range(10):
        cache.put(f"{i:06d}", _frame_days(500))
    from src import cache as cache_module
    잰것 = cache_module.measure(cache)
    assert 잰것 is not None
    assert 잰것.median_rows == 500
    assert 1.9 < 잰것.years < 2.2          # 500 거래일이면 대략 2년


def test_이름표와_실제가_어긋나면_말해_준다(tmp_path):
    """이름표만 믿으면 7개월치를 18개월치로 알고 판단하게 됩니다."""
    from src import cache as cache_module
    cache = PriceCache(tmp_path)
    for i in range(10):
        cache.put(f"{i:06d}", _frame_days(300))     # 약 1.2년치
    cache.save_meta(codes=10, years=3.0)            # 이름표만 3년

    말 = cache_module.disagreement(cache.info(), cache_module.measure(cache))
    assert "이름표는 3년치라는데" in 말
    assert "실제 쪽을 믿으십시오" in 말


def test_이름표와_실제가_맞으면_잔소리하지_않는다(tmp_path):
    from src import cache as cache_module
    cache = PriceCache(tmp_path)
    for i in range(10):
        cache.put(f"{i:06d}", _frame_days(735))     # 약 3년치
    cache.save_meta(codes=10, years=3.0)
    assert cache_module.disagreement(cache.info(), cache_module.measure(cache)) == ""


def test_저장된_게_없으면_재지_않는다(tmp_path):
    from src import cache as cache_module
    assert cache_module.measure(PriceCache(tmp_path)) is None
    assert cache_module.disagreement(None, None) == ""


def test_종목마다_길이가_다르면_짧은_것도_알려준다(tmp_path):
    from src import cache as cache_module
    cache = PriceCache(tmp_path)
    for i, n in enumerate((100, 300, 500, 700, 735)):
        cache.put(f"{i:06d}", _frame_days(n))
    잰것 = cache_module.measure(cache)
    assert 잰것.min_rows == 100 and 잰것.max_rows == 735
    assert "제일 짧은 것 100일" in 잰것.as_line()


# ────────── --years 가 말한 대로 자르는가 ──────────
#
# 저장된 시세는 --years 와 상관없이 있는 그대로 읽힙니다. 그래서
# "최근 3.0년" 이라고 찍어 놓고 실제로는 5년치로 계산했습니다
# (2026-09-14). 화면과 실제가 다르면 그 결과는 쓸모가 없습니다.

def test_요청한_기간으로_실제로_자른다():
    from src import cache as cache_module
    frames = {f"{i:06d}": _frame_days(1242, start="2021-08-02") for i in range(5)}
    잘린것, 처음, 끝 = cache_module.trim_to_years(frames, 3.0)
    남은일수 = len(next(iter(잘린것.values())))
    assert 700 < 남은일수 < 800          # 3년이면 거래일 약 735일
    assert 처음 > "2023-01-01"


def test_자르지_않으면_검사가_깨진다():
    """이 검사의 뜻 — 안 자르면 1,242일이 그대로 남습니다."""
    from src import cache as cache_module
    frames = {"000001": _frame_days(1242, start="2021-08-02")}
    assert len(frames["000001"]) == 1242
    잘린것, _, _ = cache_module.trim_to_years(frames, 3.0)
    assert len(잘린것["000001"]) < 1242


def test_기준은_오늘이_아니라_자료의_마지막_날이다():
    """저장된 시세가 오래됐다고 창이 밀리면, 같은 명령이 날마다 다른
    답을 냅니다."""
    from src import cache as cache_module
    frames = {"000001": _frame_days(1242, start="2021-08-02")}
    _, 처음1, 끝1 = cache_module.trim_to_years(frames, 3.0)
    _, 처음2, 끝2 = cache_module.trim_to_years(frames, 3.0)
    assert (처음1, 끝1) == (처음2, 끝2)
    assert 끝1 == str(frames["000001"].index.max().date())


def test_모든_종목을_같은_기간으로_자른다():
    """종목마다 다른 창으로 자르면 비교가 안 됩니다."""
    from src import cache as cache_module
    frames = {
        "000001": _frame_days(1242, start="2021-08-02"),
        "000002": _frame_days(1242, start="2021-08-02"),
    }
    잘린것, _, _ = cache_module.trim_to_years(frames, 3.0)
    assert len(잘린것["000001"]) == len(잘린것["000002"])


def test_기간을_안_주면_그대로_둔다():
    from src import cache as cache_module
    frames = {"000001": _frame_days(1242)}
    잘린것, 처음, 끝 = cache_module.trim_to_years(frames, 0)
    assert len(잘린것["000001"]) == 1242
    assert 처음 == "" and 끝 == ""


def test_자르고_나서_남는_게_없으면_원래대로_둡니다():
    """빈 표를 돌려주면 '자료가 없다' 로 오해합니다."""
    from src import cache as cache_module
    frames = {"000001": _frame_days(30, start="2020-01-02")}
    잘린것, _, _ = cache_module.trim_to_years(frames, 0.01)
    assert len(잘린것) == 1
