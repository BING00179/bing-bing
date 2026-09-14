"""종목 목록 청소 — 우리가 찾는 것은 '기업' 입니다.

시세를 받아둔 1,822종목 안에 기업이 아닌 것이 섞여 있을 수 있습니다.
ETF·ETN·리츠·스팩은 회사가 아니라 상품이거나 껍데기입니다. 재무제표도
없고, "매출이 늘고 있나" 를 물을 수 없습니다.

이게 왜 문제가 되냐면 — 우리가 지금까지 잰 숫자에 그것들이 섞여
있었다면, 그 숫자가 흔들립니다. 특히 `slice-kr` 에서 나온 "거래대금이
작은 쪽이 좋다" 는 결과가 그렇습니다. 거래가 거의 없는 ETN 이 그
칸에 잔뜩 들어 있었다면 이야기가 달라집니다.

⚠️ **여기 판정은 종목 이름으로 하는 짐작입니다.** 공식 자료가 아닙니다.
   한국투자증권이 매일 올리는 종목 마스터 파일에는 `stkgrp_code`
   (주권/ETF/ETN/리츠 구분), `isAcquisition`(스팩), `isManagement`
   (관리종목), `market_warning_code`(투자주의·경고·위험) 가 공식으로
   들어 있습니다. 그쪽으로 바꾸는 것이 맞습니다. 지금은 그 전에
   **얼마나 섞여 있는지부터** 보는 단계입니다.

   이름으로 거르면 두 가지를 놓칩니다.
     · 이름에 티가 안 나는 것 (관리종목·투자경고는 이름에 안 적힙니다)
     · 이름만 비슷한 멀쩡한 기업 (그래서 지우지 않고 표시만 합니다)

**지우지 않습니다.** 무엇이 왜 걸렸는지 보여주고, 걸러낸 목록을 새
파일로 따로 씁니다. 원래 파일은 그대로 둡니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# 이름 안에 이 말이 있으면 기업이 아닐 가능성이 큽니다.
NAME_MARKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ETN", ("ETN",)),
    ("ETF", ("ETF",)),
    ("스팩", ("스팩", "기업인수목적")),
    ("선박투자", ("선박투자",)),
    ("인프라펀드", ("맥쿼리인프라", "인프라투융자", "인프라펀드")),
)

# 리츠는 **이름 끝에** 붙습니다 (롯데리츠, 신한알파리츠, ESR켄달스퀘어리츠).
# 가운데에 들어간 것은 글자가 우연히 겹친 것입니다.
#
# 2026-09-14, 실제로 걸렸습니다 — 블리츠웨이엔터테인먼트(369370) 를
# 리츠로 판정했습니다. 리츠가 아니라 '블리츠웨이' 입니다. 부분 일치의
# 위험이 그대로 나온 경우라, 끝에 붙은 것만 보도록 고쳤습니다.
REIT_TAIL = ("리츠",)

# ETF 는 이름에 'ETF' 가 안 들어가고 상품 이름만 붙는 경우가 많습니다.
# 운용사 브랜드로 알아봅니다.
ETF_BRANDS = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "KOSEF", "SOL ",
    "ACE ", "PLUS ", "RISE ", "TIMEFOLIO", "히어로즈", "마이다스",
    "TREX", "FOCUS", "네비게이터", "WOORI ", "VITA ", "BNK ", "UNICORN",
)

# ETN 은 종목코드가 영문자로 시작합니다 (예: Q700018).
CODE_NOT_STOCK = re.compile(r"^[A-Za-z]")

# 우선주는 보통주와 같은 회사입니다. 재무가 겹쳐 두 번 세어집니다.
PREFERRED_TAIL = ("5", "7", "9")

REASON_PREFERRED = "우선주"
REASON_CODE = "주식코드아님"


@dataclass
class Check:
    """무엇이 왜 걸렸나. 세어 보고 판단은 사람이 합니다."""
    total: int = 0
    flagged: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def kept(self) -> int:
        return self.total - len(self.flagged)

    @property
    def flagged_pct(self) -> float:
        return len(self.flagged) / self.total * 100.0 if self.total else 0.0


def why_not_company(code: str, name: str) -> str:
    """기업이 아니라고 볼 이유. 없으면 빈 문자열.

    이름으로 하는 짐작입니다. 공식 구분 코드가 아닙니다.
    """
    code = str(code or "").strip()
    name = str(name or "").strip()

    if code and CODE_NOT_STOCK.match(code):
        return REASON_CODE

    위 = name.upper()
    for 이름, 표시들 in NAME_MARKS:
        if any(표시.upper() in 위 for 표시 in 표시들):
            return 이름
    if any(브랜드.upper() in 위 for 브랜드 in ETF_BRANDS):
        return "ETF"
    if any(name.endswith(꼬리) for 꼬리 in REIT_TAIL):
        return "리츠"

    # 우선주 — 6자리 숫자이고 끝자리가 5·7·9
    if len(code) == 6 and code.isdigit() and code[-1] in PREFERRED_TAIL:
        return REASON_PREFERRED
    return ""


def check(frame: pd.DataFrame) -> Check:
    """code·name 을 가진 표를 받아 걸리는 것을 골라냅니다."""
    if frame is None or frame.empty:
        return Check()
    일 = frame.copy()
    일["이유"] = [
        why_not_company(r.get("code", ""), r.get("name", ""))
        for _, r in 일.iterrows()
    ]
    걸림 = 일[일["이유"] != ""].copy()
    return Check(total=len(일), flagged=걸림)


def clean_codes(frame: pd.DataFrame) -> list[str]:
    """걸린 것을 뺀 종목코드 목록."""
    if frame is None or frame.empty:
        return []
    return [
        str(r.get("code", ""))
        for _, r in frame.iterrows()
        if not why_not_company(r.get("code", ""), r.get("name", ""))
    ]


def report(result: Check, missing_names: int = 0) -> str:
    """무엇이 얼마나 걸렸나. 지운 게 아니라 표시했다고 분명히 씁니다."""
    줄 = ["🧹 종목 목록에 기업이 아닌 것이 섞여 있나", ""]
    if not result.total:
        return "\n".join(줄 + ["   볼 목록이 없습니다."])

    줄 += [f"   전체 {result.total:,}종목 중 "
           f"**{len(result.flagged):,}개**가 걸렸습니다 "
           f"({result.flagged_pct:.1f}%). 남는 것 {result.kept:,}종목.", ""]

    if len(result.flagged):
        센것 = result.flagged["이유"].value_counts()
        줄 += ["   이유            개수   예시"]
        for 이유, 수 in 센것.items():
            보기 = result.flagged[result.flagged["이유"] == 이유]
            이름들 = ", ".join(
                f"{r['name']}({r['code']})" for _, r in 보기.head(3).iterrows()
            )
            줄.append(f"   {이유:<12s} {수:6,d}   {이름들[:52]}")
        줄 += [""]

    if missing_names:
        줄 += [f"   ⚠️ 이름을 못 찾은 종목이 {missing_names:,}개 있습니다. "
               "이건 판정하지 못했습니다.",
               "      상장폐지됐거나 목록에서 빠진 것일 수 있습니다.", ""]

    줄 += ["   ⚠️ 이 판정은 **종목 이름으로 하는 짐작**입니다. 공식 구분이",
           "      아닙니다. 한국투자증권 종목 마스터 파일에는 주권/ETF/ETN/",
           "      리츠 구분과 관리종목·투자경고가 공식으로 들어 있습니다.",
           "      이름으로는 관리종목·투자경고를 알 수 없습니다.", "",
           "   **아무것도 지우지 않았습니다.** 원래 목록은 그대로입니다."]
    return "\n".join(줄)
