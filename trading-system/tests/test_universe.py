"""종목 목록 청소 검사.

여기서 제일 중요한 것은 **멀쩡한 기업을 기업이 아니라고 하지 않는가**
입니다. 잘못 걸러내면 후보에서 통째로 빠지고, 우리는 그걸 모릅니다.
"""

from __future__ import annotations

import pandas as pd

from src import universe as uni


def _frame(rows):
    return pd.DataFrame(rows, columns=["code", "name"])


# ────────────── 기업이 아닌 것을 찾아내는가 ──────────────

def test_ETN은_종목코드가_영문으로_시작한다():
    assert uni.why_not_company("Q700018", "하나 인버스 2X 코스닥150 선물 ETN")


def test_이름에_ETN이_있으면_걸린다():
    assert uni.why_not_company("500001", "키움 코스피 200 ETN") == "ETN"


def test_ETF_운용사_브랜드로_알아본다():
    """ETF 는 이름에 'ETF' 가 안 들어가는 경우가 많습니다."""
    assert uni.why_not_company("069500", "KODEX 200") == "ETF"
    assert uni.why_not_company("102110", "TIGER 200") == "ETF"


def test_스팩과_리츠도_기업이_아니다():
    assert uni.why_not_company("123456", "엔에이치스팩29호") == "스팩"
    assert uni.why_not_company("330590", "롯데리츠") == "리츠"


def test_우선주는_같은_회사가_두_번_세어진다():
    assert uni.why_not_company("005935", "삼성전자우") == "우선주"


# ────────────── 멀쩡한 기업을 걸러내지 않는가 ──────────────

def test_보통주는_통과한다():
    for code, name in (("005930", "삼성전자"), ("032820", "우리기술"),
                       ("105560", "KB금융"), ("000660", "SK하이닉스")):
        assert uni.why_not_company(code, name) == "", f"{name} 이 잘못 걸렸습니다"


def test_이름_가운데_리츠는_리츠가_아니다():
    """2026-09-14 실제로 틀린 경우입니다.

    블리츠웨이엔터테인먼트(369370) 를 리츠로 판정했습니다. 리츠가 아니라
    '블리츠웨이' 입니다. 리츠는 이름 끝에 붙습니다.
    """
    assert uni.why_not_company("369370", "블리츠웨이엔터테인먼트") == ""
    assert uni.why_not_company("123450", "블리츠컴퍼니") == ""


def test_이름_끝의_리츠는_리츠로_본다():
    assert uni.why_not_company("330590", "롯데리츠") == "리츠"
    assert uni.why_not_company("293940", "신한알파리츠") == "리츠"


def test_이름이_없으면_판정하지_않는다():
    """없는 것은 없다고 씁니다. 이름을 모르면 기업이 아니라고 하면 안 됩니다."""
    assert uni.why_not_company("005930", "") == ""


# ────────────── 세고 보고하기 ──────────────

def _mixed():
    return _frame([
        ("005930", "삼성전자"), ("032820", "우리기술"), ("105560", "KB금융"),
        ("069500", "KODEX 200"), ("102110", "TIGER 200"),
        ("Q700018", "하나 인버스 2X ETN"),
        ("123456", "엔에이치스팩29호"), ("330590", "롯데리츠"),
        ("005935", "삼성전자우"),
    ])


def test_몇_개가_걸렸는지_센다():
    결과 = uni.check(_mixed())
    assert 결과.total == 9
    assert len(결과.flagged) == 6      # ETF 2 + ETN 1 + 스팩 1 + 리츠 1 + 우선주 1
    assert 결과.kept == 3


def test_걸러낸_목록에는_기업만_남는다():
    남은것 = uni.clean_codes(_mixed())
    assert 남은것 == ["005930", "032820", "105560"]


def test_보고서가_지우지_않았다고_분명히_쓴다():
    """장부 정신과 같습니다. 표시만 하고 사람이 정합니다."""
    글 = uni.report(uni.check(_mixed()))
    assert "아무것도 지우지 않았습니다" in 글


def test_보고서가_짐작이라고_밝힌다():
    """이름으로 거른 것입니다. 공식 구분인 척하면 안 됩니다."""
    글 = uni.report(uni.check(_mixed()))
    assert "짐작" in 글 and "공식 구분이" in 글
    assert "관리종목·투자경고를 알 수 없습니다" in 글


def test_이름_못_찾은_종목을_숨기지_않는다():
    글 = uni.report(uni.check(_mixed()), missing_names=7)
    assert "이름을 못 찾은 종목이 7개" in 글
    assert "판정하지 못했습니다" in 글


def test_빈_목록이면_판정하지_않는다():
    결과 = uni.check(pd.DataFrame())
    assert 결과.total == 0
    assert "볼 목록이 없습니다" in uni.report(결과)


# ────────── 우리가 쓴 파일을 우리가 못 읽으면 안 됩니다 ──────────

def test_우리가_만든_목록을_그대로_다시_읽을_수_있다(tmp_path):
    """2026-09-14 실제로 걸린 문제입니다.

    --write-clean 으로 만든 목록을 slice-kr 에 넣었더니
    "형식이 맞지 않아 건너뛴 줄 1개: ﻿" 가 나왔습니다. 메모장에서
    안 깨지라고 맨 앞에 붙인 BOM 이 첫 줄에 달라붙은 것이었습니다.
    """
    from src.cli import _write_text
    from src.data_kr import read_universe_kr

    경로 = _write_text(tmp_path / "목록.txt",
                     "# 기업만 남긴 목록\n005930  삼성전자\n032820  우리기술\n")
    assert 경로.read_bytes().startswith(b"\xef\xbb\xbf")   # BOM 은 그대로 둡니다
    assert read_universe_kr(경로) == ["005930", "032820"]  # 그래도 읽힙니다


def test_BOM_없는_파일도_읽는다(tmp_path):
    from src.data_kr import read_universe_kr
    경로 = tmp_path / "목록.txt"
    경로.write_text("005930  삼성전자\n", encoding="utf-8")
    assert read_universe_kr(경로) == ["005930"]
