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
    assert info.fetched_on == date.today().isoformat()
    assert "3.0년치" in info.as_line()


def test_old_cache_is_flagged(tmp_path):
    """오래된 시세를 모르고 쓰면 안 됩니다."""
    cache = PriceCache(tmp_path)
    cache.put("005930", frame())
    cache.save_meta(1, 3.0)

    old = (date.today() - timedelta(days=30)).isoformat()
    path = tmp_path / META_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["fetched_on"] = old
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
