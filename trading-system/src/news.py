"""'왜 올랐는지' 뉴스 한 줄.

원문 가이드는 Benzinga 를 언급하지만, Benzinga 뉴스 API 는 유료이고
키가 필요합니다. 키가 없어도 시스템이 돌아가도록:

  * 기본값: yfinance 가 제공하는 무료 뉴스 헤드라인을 씁니다.
  * 키가 있으면: BENZINGA_API_KEY 환경변수를 설정하면 그쪽을 씁니다.
  * 둘 다 안 되면: 빈 문자열을 돌려주고 스캔은 그대로 진행합니다.

뉴스 조회 실패가 스캐너 전체를 멈추게 하지 않습니다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BENZINGA_URL = "https://api.benzinga.com/api/v2/news"


def _from_benzinga(ticker: str, api_key: str, timeout: int = 10) -> str:
    query = urllib.parse.urlencode(
        {"token": api_key, "tickers": ticker, "pageSize": 1, "displayOutput": "abstract"}
    )
    request = urllib.request.Request(
        f"{BENZINGA_URL}?{query}", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        items = json.loads(response.read().decode())
    if isinstance(items, list) and items:
        return str(items[0].get("title", "")).strip()
    return ""


def _from_yfinance(ticker: str) -> str:
    try:
        import yfinance  # noqa: PLC0415
    except ImportError:
        return ""
    items = getattr(yfinance.Ticker(ticker), "news", None) or []
    for item in items:
        # yfinance 버전에 따라 평평한 dict 이거나 {"content": {...}} 형태입니다.
        title = item.get("title") or item.get("content", {}).get("title", "")
        if title:
            return str(title).strip()
    return ""


def headline(ticker: str) -> str:
    """티커의 최신 헤드라인 한 줄. 못 구하면 빈 문자열."""
    api_key = os.environ.get("BENZINGA_API_KEY", "").strip()
    if api_key:
        try:
            title = _from_benzinga(ticker, api_key)
            if title:
                return title
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            pass
    try:
        return _from_yfinance(ticker)
    except Exception:  # noqa: BLE001 - 뉴스는 부가정보이므로 어떤 실패든 무시
        return ""
