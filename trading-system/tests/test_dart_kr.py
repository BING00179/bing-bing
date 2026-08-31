"""DART 모듈 검사.

네트워크를 쓰지 않습니다. HTTP 호출은 전부 가짜로 갈아끼웁니다.
확인하려는 것은 '인터넷이 되나' 가 아니라 '응답을 제대로 해석하나' 입니다.
"""

from __future__ import annotations

import io
import json
import zipfile

import pandas as pd
import pytest

from src import dart_kr


# ────────────────────────── 인증키 ──────────────────────────

def test_인증키가_없으면_무엇을_해야_하는지_알려준다(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(dart_kr.DartNotConfigured) as caught:
        dart_kr.api_key()
    말 = str(caught.value)
    assert "opendart.fss.or.kr" in 말          # 어디서 받는지
    assert "DART_API_KEY" in 말                # 어디에 넣는지


def test_환경변수의_인증키를_읽는다(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "  abc123  ")
    assert dart_kr.api_key() == "abc123"


def test_직접_넘긴_키가_환경변수보다_앞선다(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "환경변수키")
    assert dart_kr.api_key("직접키") == "직접키"


# ────────────────────────── 오류 해석 ──────────────────────────

def _응답(monkeypatch, payload: dict):
    """_get 이 부를 urlopen 을 가짜로 바꿉니다."""
    class 가짜응답:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", lambda *a, **k: 가짜응답())
    monkeypatch.setattr(dart_kr.time, "sleep", lambda *_: None)


def test_등록되지_않은_키는_사람_말로_알려준다(monkeypatch):
    _응답(monkeypatch, {"status": "010", "message": "등록되지 않은 키입니다."})
    with pytest.raises(dart_kr.DartError) as caught:
        dart_kr._get("list.json", "키")
    assert "등록되지 않은 인증키" in str(caught.value)
    assert caught.value.status == "010"


def test_요청_제한_초과도_구분한다(monkeypatch):
    _응답(monkeypatch, {"status": "020", "message": ""})
    with pytest.raises(dart_kr.DartError) as caught:
        dart_kr._get("list.json", "키")
    assert "20,000" in str(caught.value)


def test_JSON_이_아닌_응답도_터지지_않고_설명한다(monkeypatch):
    class 점검안내:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>system check</html>"

    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", lambda *a, **k: 점검안내())
    monkeypatch.setattr(dart_kr.time, "sleep", lambda *_: None)
    with pytest.raises(dart_kr.DartError) as caught:
        dart_kr._get("list.json", "키")
    assert "JSON" in str(caught.value)


def test_자료_없음은_오류가_아니라_빈_표다(monkeypatch):
    _응답(monkeypatch, {"status": "013", "message": "조회된 데이타가 없습니다."})
    frame = dart_kr.filings("키", "00126380", "20240101", "20241231")
    assert frame.empty                          # 예외가 아니라 빈 표


# ────────────────────────── 회사 목록 ──────────────────────────

def _corp_zip() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
            <stock_code>005930</stock_code></list>
      <list><corp_code>00164779</corp_code><corp_name>삼성전자우</corp_name>
            <stock_code>005935</stock_code></list>
      <list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>
            <stock_code> </stock_code></list>
    </result>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buffer.getvalue()


def _회사목록(monkeypatch, raw: bytes):
    class 가짜:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return raw
    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", lambda *a, **k: 가짜())


def test_회사_목록을_풀어서_저장하고_다시_읽는다(monkeypatch, tmp_path):
    _회사목록(monkeypatch, _corp_zip())
    frame = dart_kr.download_corp_index("키", tmp_path)
    assert len(frame) == 3
    assert (tmp_path / "corp_codes.csv").exists()

    # 두 번째부터는 네트워크를 건드리지 않아야 합니다.
    monkeypatch.setattr(dart_kr.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("저장해 뒀는데 또 받았습니다"))
    다시 = dart_kr.load_corp_index("키", tmp_path)
    assert len(다시) == 3


def test_종목코드_앞자리_0이_사라지지_않는다(monkeypatch, tmp_path):
    _회사목록(monkeypatch, _corp_zip())
    dart_kr.download_corp_index("키", tmp_path)
    다시 = dart_kr.load_corp_index("키", tmp_path)
    assert "005930" in set(다시["stock_code"])   # 5930 으로 줄어들면 실패


def test_zip_이_아니면_상태코드를_읽어_알려준다(monkeypatch, tmp_path):
    _회사목록(monkeypatch, b"<result><status>010</status></result>")
    with pytest.raises(dart_kr.DartError) as caught:
        dart_kr.download_corp_index("키", tmp_path)
    assert caught.value.status == "010"


def test_종목코드와_회사명_둘_다로_찾는다(monkeypatch, tmp_path):
    _회사목록(monkeypatch, _corp_zip())
    index = dart_kr.download_corp_index("키", tmp_path)
    assert dart_kr.find_corp_code(index, "005930") == "00126380"
    assert dart_kr.find_corp_code(index, "삼성전자") == "00126380"
    assert dart_kr.find_corp_code(index, "없는회사") is None


def test_글자가_섞인_종목코드도_터지지_않는다(tmp_path):
    index = pd.DataFrame([{"corp_code": "001", "corp_name": "우선주회사",
                           "stock_code": "0009K0"}])
    assert dart_kr.find_corp_code(index, "0009K0") == "001"


# ────────────────────────── 공시 플래그 ──────────────────────────

def _공시(*제목: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"rcept_dt": f"2026080{i}", "report_nm": t, "rcept_no": f"2026080{i}00001",
         "flr_nm": "회사"}
        for i, t in enumerate(제목, 1)
    ])


def test_감사의견_거절은_높음으로_잡는다():
    flagged = dart_kr.flag_events(_공시("감사보고서제출(감사의견거절)"))
    assert len(flagged) == 1
    assert flagged.iloc[0]["label"] == "감사의견 비적정"
    assert flagged.iloc[0]["severity"] == "높음"


def test_띄어쓰기가_달라도_잡는다():
    assert len(dart_kr.flag_events(_공시("유상 증자 결정"))) == 1
    assert len(dart_kr.flag_events(_공시("유상증자결정"))) == 1


def test_규칙에_없는_공시는_거르지_않는다():
    assert dart_kr.flag_events(_공시("기업설명회(IR)개최")).empty


def test_심각한_것이_위로_온다():
    flagged = dart_kr.flag_events(_공시("유상증자결정", "횡령·배임혐의발생"))
    assert flagged.iloc[0]["label"] == "횡령·배임"


def test_왜_봐야_하는지가_항상_붙는다():
    flagged = dart_kr.flag_events(_공시("최대주주변경"))
    assert flagged.iloc[0]["why"].strip()


def test_공시가_없으면_빈_표를_준다():
    assert dart_kr.flag_events(pd.DataFrame()).empty


# ────────────────────────── 재무 ──────────────────────────

def test_괄호친_숫자는_음수다():
    assert dart_kr._to_number("(1,234)") == -1234.0
    assert dart_kr._to_number("1,234") == 1234.0
    assert dart_kr._to_number("-") != dart_kr._to_number("-")     # nan


def test_한_번의_응답에서_세_개_연도를_뽑는다(monkeypatch):
    payload = {"status": "000", "list": [
        {"account_nm": "매출액", "fs_div": "CFS",
         "thstrm_amount": "3,000", "frmtrm_amount": "2,000",
         "bfefrmtrm_amount": "1,000"},
        {"account_nm": "영업이익", "fs_div": "CFS",
         "thstrm_amount": "300", "frmtrm_amount": "200",
         "bfefrmtrm_amount": "100"},
    ]}
    _응답(monkeypatch, payload)
    trend = dart_kr.financial_trend("키", "00126380", years=3, end_year=2025)
    assert list(trend.index) == [2023, 2024, 2025]
    assert trend.loc[2025, "매출액"] == 3000
    assert trend.loc[2023, "영업이익"] == 100


def test_연결재무제표를_개별보다_먼저_쓴다(monkeypatch):
    payload = {"status": "000", "list": [
        {"account_nm": "매출액", "fs_div": "OFS", "thstrm_amount": "111",
         "frmtrm_amount": "", "bfefrmtrm_amount": ""},
        {"account_nm": "매출액", "fs_div": "CFS", "thstrm_amount": "999",
         "frmtrm_amount": "", "bfefrmtrm_amount": ""},
    ]}
    _응답(monkeypatch, payload)
    trend = dart_kr.financial_trend("키", "00126380", years=1, end_year=2025)
    assert trend.loc[2025, "매출액"] == 999


def test_자본잠식을_사실로_적는다():
    trend = pd.DataFrame({"자본총계": [100.0, -50.0]}, index=[2024, 2025])
    notes = dart_kr.health_flags(trend)
    assert any("자본총계가 마이너스" in n for n in notes)
    assert any("2025" in n for n in notes)


def test_영업적자_연도를_센다():
    trend = pd.DataFrame({"영업이익": [-1.0, -2.0, -3.0]}, index=[2023, 2024, 2025])
    assert any("3개 연도" in n for n in dart_kr.health_flags(trend))


def test_흑자만_있으면_적자_얘기를_하지_않는다():
    trend = pd.DataFrame({"영업이익": [1.0, 2.0]}, index=[2024, 2025])
    assert not any("적자" in n for n in dart_kr.health_flags(trend))


def test_재무가_없으면_조용히_빈_목록이다():
    assert dart_kr.health_flags(pd.DataFrame()) == []


def test_비율은_계산되는_것만_만든다():
    trend = pd.DataFrame({"매출액": [100.0, 200.0], "영업이익": [10.0, 40.0]},
                         index=[2024, 2025])
    ratios = dart_kr.derived(trend)
    assert "영업이익률%" in ratios.columns
    assert "부채비율%" not in ratios.columns        # 자본총계가 없으므로
    assert ratios.loc[2025, "영업이익률%"] == 20.0


def test_자본이_0이어도_나눗셈에서_터지지_않는다():
    trend = pd.DataFrame({"부채총계": [100.0], "자본총계": [0.0]}, index=[2025])
    ratios = dart_kr.derived(trend)
    assert pd.isna(ratios.loc[2025, "부채비율%"])


# ────────────────────────── 보고서 ──────────────────────────

def _brief() -> dart_kr.CompanyBrief:
    return dart_kr.CompanyBrief(
        code="005930", name="삼성전자", corp_code="00126380",
        trend=pd.DataFrame({"매출액": [3e14], "영업이익": [-1e12]}, index=[2025]),
        events=dart_kr.flag_events(_공시("유상증자결정")),
        notes=["영업적자 연도: 2025"],
        filing_count=12, window_days=365,
    )


def test_보고서는_사실과_해석을_갈라_적는다():
    text = dart_kr.report(_brief())
    assert "[사실]" in text
    assert "[해석]" in text
    assert text.index("[사실]") < text.index("[해석]")


def test_보고서는_출처를_밝힌다():
    assert "opendart.fss.or.kr" in dart_kr.report(_brief())


def test_보고서는_매수_매도를_말하지_않는다():
    text = dart_kr.report(_brief())
    assert "매수 신호" not in text or "아닙니다" in text
    assert "사세요" not in text and "파세요" not in text


def test_보고서는_공시가_늦다는_것을_알려준다():
    assert "90일" in dart_kr.report(_brief())


def test_큰_금액은_조_억으로_줄여_쓴다():
    assert dart_kr._money(3e14) == "300.00조"
    assert dart_kr._money(-1e8) == "-1억"
    assert dart_kr._money(float("nan")) == "—"


# ────────────────────── 끊겼을 때 다시 걸기 ──────────────────────
# 1,800종목을 20분 넘게 부르는 동안 연결이 한 번쯤 끊기는 것은 정상입니다.
# 그때마다 전체가 죽으면 그 20분이 통째로 날아갑니다.

def test_한_번_끊겨도_다시_걸어_성공한다(monkeypatch):
    부른횟수 = {"n": 0}

    class 응답:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"status":"000","list":[]}'

    def 가짜열기(*a, **k):
        부른횟수["n"] += 1
        if 부른횟수["n"] == 1:
            raise dart_kr.urllib.error.URLError("SSL: UNEXPECTED_EOF_WHILE_READING")
        return 응답()

    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", 가짜열기)
    monkeypatch.setattr(dart_kr.time, "sleep", lambda *_: None)

    assert dart_kr._get("list.json", "키")["status"] == "000"
    assert 부른횟수["n"] == 2                      # 한 번 실패, 한 번 성공


def test_계속_끊기면_무엇이_문제인지_말하고_포기한다(monkeypatch):
    def 항상실패(*a, **k):
        raise dart_kr.urllib.error.URLError("연결 실패")

    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", 항상실패)
    monkeypatch.setattr(dart_kr.time, "sleep", lambda *_: None)

    with pytest.raises(dart_kr.DartUnreachable) as caught:
        dart_kr._get("list.json", "키")
    assert "3번 시도" in str(caught.value)


def test_시간초과도_다시_걸어본다(monkeypatch):
    부른횟수 = {"n": 0}

    class 응답:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"status":"000","list":[]}'

    def 가짜열기(*a, **k):
        부른횟수["n"] += 1
        if 부른횟수["n"] < 3:
            raise TimeoutError("시간 초과")
        return 응답()

    monkeypatch.setattr(dart_kr.urllib.request, "urlopen", 가짜열기)
    monkeypatch.setattr(dart_kr.time, "sleep", lambda *_: None)
    assert dart_kr._get("list.json", "키")["status"] == "000"
    assert 부른횟수["n"] == 3
