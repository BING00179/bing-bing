"""DART 공시 읽기 — 숫자가 말해주지 않는 것.

지금까지 만든 것은 전부 '가격'만 봤습니다. 어제 종가, 200일선, 거래대금.
가격은 결과일 뿐이고, 그 결과가 왜 나왔는지는 알려주지 않습니다.

이 모듈은 다른 쪽을 봅니다 — 회사가 금융감독원에 제출한 서류.
사업보고서, 감사보고서, 유상증자 결정, 최대주주 변경. 전부 공시 의무가
있어서 반드시 올라오고, 늦게 올라올지언정 거짓이면 처벌받습니다.

    가격 데이터 (기존)          공시 데이터 (여기)
    ─────────────────          ─────────────────
    오늘 6% 올랐다              왜 올랐는지는 모름
    거래대금 300억              누가 샀는지는 모름
                               지난주 유상증자 결정 공시가 떴다
                               3년째 영업적자다
                               감사의견이 '한정'이다

한계를 먼저 적습니다. 이걸 모르고 쓰면 안 됩니다.

  * 공시는 늦습니다. 사업보고서는 결산 후 90일, 분기보고서는 45일.
    "지금 이 종목이 어떤가" 에는 답하지 못하고
    "이 회사가 어떤 회사인가" 에만 답합니다.
  * 국내에는 어닝콜 전문이 거의 공개되지 않습니다. 미국의 10-K·컨퍼런스콜
    텍스트 분석을 그대로 따라할 수 없습니다.
  * 여기서 나오는 것은 전부 '사실'과 '경고 플래그'입니다.
    매수·매도 판단은 하지 않습니다. 그건 사람이 합니다.

무료 API 키가 필요합니다. https://opendart.fss.or.kr → 인증키 신청.
발급된 키는 환경변수 DART_API_KEY 에 넣습니다. 코드나 설정 파일에
적으면 안 됩니다 — 이 저장소는 공개되어 있습니다.
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

API_BASE = "https://opendart.fss.or.kr/api"
TIMEOUT = 30
PAUSE = 0.15                      # 호출 간 간격. 일일 20,000건 제한이 있습니다.
CACHE_DIR = Path("data/cache/dart")

# 사업보고서 / 반기 / 1분기 / 3분기
REPORT_CODES = {"사업": "11011", "반기": "11012", "1분기": "11013", "3분기": "11014"}

# DART 가 돌려주는 상태 코드. 무엇이 잘못됐는지 사람 말로 옮깁니다.
STATUS_TEXT = {
    "000": "정상",
    "010": "등록되지 않은 인증키입니다. 키를 다시 확인해 주세요.",
    "011": "사용할 수 없는 인증키입니다. 일시적으로 정지됐거나 만료됐습니다.",
    "012": "접근할 수 없는 IP 입니다.",
    "013": "조회된 자료가 없습니다.",
    "014": "파일이 존재하지 않습니다.",
    "020": "요청 제한을 초과했습니다. 하루 20,000건까지입니다.",
    "021": "조회 가능한 회사 개수를 초과했습니다.",
    "100": "요청 값이 잘못됐습니다.",
    "101": "부적절한 접근입니다.",
    "800": "DART 시스템 점검 중입니다.",
    "900": "정의되지 않은 오류입니다.",
    "901": "사용자 계정의 개인정보 보호 요청이 있습니다.",
}

# 자료 없음은 오류가 아닙니다 — 신생 기업이거나 해당 분기가 아직 없을 뿐.
NO_DATA = "013"


class DartNotConfigured(RuntimeError):
    """인증키가 환경변수에 없을 때."""


class DartError(RuntimeError):
    """DART 가 오류 상태를 돌려줬을 때."""

    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        human = STATUS_TEXT.get(status, "알 수 없는 오류")
        super().__init__(f"[{status}] {human}" + (f" (DART: {message})" if message else ""))


def api_key(explicit: str | None = None) -> str:
    """인증키를 찾습니다. 인자 → 환경변수 순서."""
    if explicit and explicit.strip():
        return explicit.strip()
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise DartNotConfigured(
            "DART_API_KEY 환경변수가 비어 있습니다.\n"
            "  1) https://opendart.fss.or.kr 에서 인증키를 발급받고\n"
            "  2) PowerShell 에서:  $env:DART_API_KEY = \"발급받은키\"\n"
            "키를 코드나 설정 파일에 적지 마세요. 이 저장소는 공개되어 있습니다."
        )
    return key


def _get(path: str, key: str, **params: str) -> dict:
    """DART REST 호출 한 번. 상태 코드를 사람 말로 바꿔 던집니다."""
    query = urllib.parse.urlencode({"crtfc_key": key, **params})
    url = f"{API_BASE}/{path}?{query}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        raw = resp.read()
    time.sleep(PAUSE)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:      # 점검 안내 HTML 등
        head = raw[:200].decode("utf-8", "replace")
        raise DartError("900", f"응답이 JSON 이 아닙니다: {head!r}") from exc
    status = str(payload.get("status", "900"))
    if status != "000":
        raise DartError(status, str(payload.get("message", "")))
    return payload


# ────────────────────────────── 회사 고유번호 ──────────────────────────────
# DART 는 종목코드가 아니라 자체 8자리 고유번호로 회사를 식별합니다.
# 전체 목록을 한 번 받아서 저장해 두고 씁니다 (10만 건, zip 으로 몇 MB).

def _corp_index_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "corp_codes.csv"


def download_corp_index(key: str, cache_dir: Path | str = CACHE_DIR) -> pd.DataFrame:
    """회사 고유번호 전체 목록을 내려받아 저장합니다."""
    query = urllib.parse.urlencode({"crtfc_key": key})
    url = f"{API_BASE}/corpCode.xml?{query}"
    with urllib.request.urlopen(url, timeout=TIMEOUT * 3) as resp:
        raw = resp.read()

    if raw[:2] != b"PK":                      # zip 이 아니면 오류 XML 입니다
        text = raw[:500].decode("utf-8", "replace")
        status = "900"
        for code in STATUS_TEXT:
            if f"<status>{code}</status>" in text:
                status = code
                break
        raise DartError(status, text.strip()[:200])

    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        name = bundle.namelist()[0]
        xml = bundle.read(name)

    rows = []
    for corp in ET.fromstring(xml).iter("list"):
        rows.append({
            "corp_code": (corp.findtext("corp_code") or "").strip(),
            "corp_name": (corp.findtext("corp_name") or "").strip(),
            "stock_code": (corp.findtext("stock_code") or "").strip(),
        })
    frame = pd.DataFrame(rows)

    path = _corp_index_path(Path(cache_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return frame


def load_corp_index(key: str, cache_dir: Path | str = CACHE_DIR,
                    refresh: bool = False) -> pd.DataFrame:
    """저장된 목록을 읽고, 없으면 내려받습니다."""
    path = _corp_index_path(Path(cache_dir))
    if not refresh and path.exists():
        try:
            return pd.read_csv(path, dtype=str).fillna("")
        except Exception:                      # 파일이 깨졌으면 다시 받습니다
            pass
    return download_corp_index(key, cache_dir)


def find_corp_code(index: pd.DataFrame, code_or_name: str) -> str | None:
    """종목코드(6자리) 또는 회사명으로 DART 고유번호를 찾습니다.

    우선주 코드처럼 글자가 섞인 것도 그대로 받습니다.
    """
    needle = str(code_or_name).strip()
    if not needle:
        return None
    hit = index[index["stock_code"] == needle]
    if hit.empty:
        hit = index[index["corp_name"] == needle]
    if hit.empty:                              # 상장사(종목코드 있는 것) 중에서 부분일치
        listed = index[index["stock_code"].str.len() == 6]
        hit = listed[listed["corp_name"].str.contains(needle, regex=False, na=False)]
    return None if hit.empty else str(hit.iloc[0]["corp_code"])


def corp_name(index: pd.DataFrame, corp_code: str) -> str:
    hit = index[index["corp_code"] == str(corp_code)]
    return "" if hit.empty else str(hit.iloc[0]["corp_name"])


# ────────────────────────────── 공시 목록 ──────────────────────────────

def filings(key: str, corp_code: str, start: str, end: str,
            kind: str = "") -> pd.DataFrame:
    """기간 안의 공시 목록.

    start/end 는 'YYYYMMDD'. kind 는 A=정기 B=주요사항 C=발행 D=지분 ... 빈값이면 전체.
    자료가 없으면 빈 DataFrame 을 돌려줍니다 (오류가 아닙니다).
    """
    params = {"corp_code": corp_code, "bgn_de": start, "end_de": end,
              "page_count": "100", "page_no": "1"}
    if kind:
        params["pblntf_ty"] = kind

    rows: list[dict] = []
    while True:
        try:
            payload = _get("list.json", key, **params)
        except DartError as exc:
            if exc.status == NO_DATA:
                break
            raise
        rows.extend(payload.get("list", []))
        page = int(payload.get("page_no", 1))
        total = int(payload.get("total_page", 1))
        if page >= total:
            break
        params["page_no"] = str(page + 1)

    if not rows:
        return pd.DataFrame(columns=["rcept_dt", "report_nm", "flr_nm", "rcept_no"])
    frame = pd.DataFrame(rows)
    return frame.sort_values("rcept_dt", ascending=False).reset_index(drop=True)


# ────────────────────────────── 경고 플래그 ──────────────────────────────
# 공시 제목만 보고 걸러냅니다. 본문을 읽지 않으므로 '있다/없다' 만 말하고
# '좋다/나쁘다' 는 말하지 않습니다. 다만 왜 봐야 하는지는 적어 둡니다.

@dataclass(frozen=True)
class EventRule:
    label: str
    keywords: tuple[str, ...]
    severity: str          # 높음 / 보통
    why: str


EVENT_RULES: tuple[EventRule, ...] = (
    EventRule("감사의견 비적정", ("감사의견거절", "의견거절", "한정의견", "부적정"),
              "높음", "상장폐지 사유가 될 수 있습니다."),
    EventRule("횡령·배임", ("횡령", "배임"),
              "높음", "상장적격성 실질심사 대상이 될 수 있습니다."),
    EventRule("거래정지·관리종목", ("관리종목", "매매거래정지", "상장폐지", "실질심사"),
              "높음", "주식을 팔지 못하게 될 수 있습니다."),
    EventRule("자본잠식", ("자본잠식",),
              "높음", "자본이 마이너스면 상장폐지 요건에 걸립니다."),
    EventRule("유상증자", ("유상증자",),
              "보통", "주식 수가 늘어 기존 주주 지분이 희석됩니다."),
    EventRule("전환사채·신주인수권", ("전환사채", "신주인수권부사채", "교환사채", "CB발행", "BW발행"),
              "보통", "나중에 주식으로 바뀌면 물량 부담이 됩니다."),
    EventRule("최대주주 변경", ("최대주주변경", "최대주주가변경"),
              "보통", "경영권이 바뀌면 사업 방향도 바뀝니다."),
    EventRule("소송", ("소송등의제기", "소송등의판결"),
              "보통", "규모에 따라 실적에 영향을 줍니다."),
    EventRule("유형자산·영업 양수도", ("영업양수", "영업양도", "자산양수", "자산양도"),
              "보통", "회사의 사업 구성이 바뀝니다."),
    EventRule("무상증자", ("무상증자",),
              "보통", "주식 수가 늘지만 자본은 그대로입니다."),
    EventRule("액면분할·병합", ("액면분할", "액면병합"),
              "보통", "주가 표시가 바뀝니다. 가치는 그대로입니다."),
    EventRule("자기주식 취득", ("자기주식취득", "자기주식신탁"),
              "보통", "회사가 자기 주식을 삽니다."),
    EventRule("현금배당", ("현금ㆍ현물배당", "현금배당"),
              "보통", "배당 결정입니다."),
)


def _squeeze(text: str) -> str:
    return "".join(str(text).split())


def flag_events(frame: pd.DataFrame) -> pd.DataFrame:
    """공시 목록에서 눈여겨볼 건만 골라 이유를 붙입니다."""
    columns = ["rcept_dt", "label", "severity", "report_nm", "why", "rcept_no"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for _, row in frame.iterrows():
        title = _squeeze(row.get("report_nm", ""))
        for rule in EVENT_RULES:
            if any(word in title for word in rule.keywords):
                rows.append({
                    "rcept_dt": row.get("rcept_dt", ""),
                    "label": rule.label,
                    "severity": rule.severity,
                    "report_nm": str(row.get("report_nm", "")).strip(),
                    "why": rule.why,
                    "rcept_no": row.get("rcept_no", ""),
                })
                break                          # 규칙 하나만 붙입니다
    if not rows:
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame(rows)
    order = {"높음": 0, "보통": 1}
    out["_rank"] = out["severity"].map(order).fillna(9)
    return (out.sort_values(["_rank", "rcept_dt"], ascending=[True, False])
               .drop(columns="_rank").reset_index(drop=True))


# ────────────────────────────── 재무 추세 ──────────────────────────────
# fnlttSinglAcnt 는 '주요계정' 만 줍니다. 매출·영업이익·순이익·자산·부채·자본.
# 한 번 호출하면 당해 + 직전 2개 사업연도가 함께 옵니다.

WANTED = ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계")


def _to_number(text: object) -> float:
    raw = str(text).strip().replace(",", "")
    if raw in ("", "-", "nan", "None"):
        return float("nan")
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    try:
        value = float(raw)
    except ValueError:
        return float("nan")
    return -value if negative else value


def finstate(key: str, corp_code: str, year: int, report: str = "11011") -> pd.DataFrame:
    """한 사업연도의 주요계정. 자료가 없으면 빈 DataFrame."""
    try:
        payload = _get("fnlttSinglAcnt.json", key, corp_code=corp_code,
                       bsns_year=str(year), reprt_code=report)
    except DartError as exc:
        if exc.status == NO_DATA:
            return pd.DataFrame()
        raise
    return pd.DataFrame(payload.get("list", []))


def financial_trend(key: str, corp_code: str, years: int = 5,
                    end_year: int | None = None) -> pd.DataFrame:
    """연도별 주요계정 표. 행=연도, 열=계정.

    한 번 호출에 3개 연도가 오므로 2~3년 간격으로만 부릅니다.
    """
    end_year = end_year or (pd.Timestamp.today().year - 1)
    collected: dict[int, dict[str, float]] = {}

    for target in range(end_year, end_year - years, -3):
        raw = finstate(key, corp_code, target)
        if raw.empty:
            continue
        # 연결(CFS) 우선, 없으면 개별(OFS)
        for div in ("CFS", "OFS"):
            part = raw[raw.get("fs_div", "") == div] if "fs_div" in raw else raw
            if not part.empty:
                raw = part
                break
        for _, row in raw.iterrows():
            account = str(row.get("account_nm", "")).strip()
            if account not in WANTED:
                continue
            for column, offset in (("thstrm_amount", 0),
                                   ("frmtrm_amount", 1),
                                   ("bfefrmtrm_amount", 2)):
                value = _to_number(row.get(column))
                if pd.isna(value):
                    continue
                slot = collected.setdefault(target - offset, {})
                slot.setdefault(account, value)

    if not collected:
        return pd.DataFrame()

    frame = pd.DataFrame(collected).T.sort_index()
    frame = frame.reindex(columns=[c for c in WANTED if c in frame.columns])
    frame = frame.tail(years)
    frame.index.name = "사업연도"
    return frame


# fnlttSinglAcntAll 은 재무제표 전체를 줍니다 — 현금흐름표 포함.
# 주요계정(fnlttSinglAcnt)에는 현금흐름이 없어서 따로 부릅니다.

CASHFLOW_KEYS = {
    "영업활동현금흐름": ("영업활동현금흐름", "영업활동으로인한현금흐름",
                    "영업활동으로 인한 현금흐름"),
    "설비투자": ("유형자산의취득", "유형자산의 취득",
              "유형자산의증가", "유형자산의 증가"),
}


def finstate_all(key: str, corp_code: str, year: int,
                 report: str = "11011", fs_div: str = "CFS") -> pd.DataFrame:
    """한 사업연도의 재무제표 전체. 자료가 없으면 빈 DataFrame."""
    try:
        payload = _get("fnlttSinglAcntAll.json", key, corp_code=corp_code,
                       bsns_year=str(year), reprt_code=report, fs_div=fs_div)
    except DartError as exc:
        if exc.status == NO_DATA:
            return pd.DataFrame()
        raise
    return pd.DataFrame(payload.get("list", []))


def cash_flow(key: str, corp_code: str, years: int = 5,
              end_year: int | None = None) -> pd.DataFrame:
    """연도별 영업활동현금흐름·설비투자·잉여현금흐름.

    잉여현금흐름 = 영업활동현금흐름 − 설비투자.
    설비투자를 못 찾으면 잉여현금흐름도 빈칸으로 둡니다. 0 으로 채우면
    투자를 안 한 회사처럼 보여 현금이 남아도는 것으로 둔갑합니다.
    """
    end_year = end_year or (pd.Timestamp.today().year - 1)
    collected: dict[int, dict[str, float]] = {}

    for target in range(end_year, end_year - years, -3):
        raw = pd.DataFrame()
        for div in ("CFS", "OFS"):
            raw = finstate_all(key, corp_code, target, fs_div=div)
            if not raw.empty:
                break
        if raw.empty or "sj_div" not in raw.columns:
            continue
        flows = raw[raw["sj_div"] == "CF"]
        if flows.empty:
            continue

        for _, row in flows.iterrows():
            account = _squeeze(row.get("account_nm", ""))
            for label, needles in CASHFLOW_KEYS.items():
                if any(_squeeze(n) == account for n in needles):
                    for column, offset in (("thstrm_amount", 0),
                                           ("frmtrm_amount", 1),
                                           ("bfefrmtrm_amount", 2)):
                        value = _to_number(row.get(column))
                        if pd.isna(value):
                            continue
                        collected.setdefault(target - offset, {}).setdefault(label, value)
                    break

    if not collected:
        return pd.DataFrame()

    frame = pd.DataFrame(collected).T.sort_index()
    for column in ("영업활동현금흐름", "설비투자"):
        if column not in frame.columns:
            frame[column] = float("nan")
    # 설비투자는 유출이라 보고서에 음수로 적히기도 합니다. 크기로 통일합니다.
    frame["설비투자"] = frame["설비투자"].abs()
    frame["잉여현금흐름"] = frame["영업활동현금흐름"] - frame["설비투자"]
    frame.index.name = "사업연도"
    return frame.tail(years)


def derived(trend: pd.DataFrame) -> pd.DataFrame:
    """추세표에서 바로 계산되는 비율들. 계산이 안 되면 그 열은 빼놓습니다."""
    out = pd.DataFrame(index=trend.index)
    if {"영업이익", "매출액"} <= set(trend.columns):
        out["영업이익률%"] = trend["영업이익"] / trend["매출액"] * 100.0
    if {"부채총계", "자본총계"} <= set(trend.columns):
        out["부채비율%"] = trend["부채총계"] / trend["자본총계"] * 100.0
    if "매출액" in trend.columns:
        out["매출증가율%"] = trend["매출액"].pct_change() * 100.0
    return out.replace([float("inf"), float("-inf")], float("nan"))


def health_flags(trend: pd.DataFrame) -> list[str]:
    """재무제표에서 곧바로 읽히는 사실만 적습니다. 해석은 하지 않습니다."""
    notes: list[str] = []
    if trend.empty:
        return notes

    if "자본총계" in trend.columns:
        negative = trend.index[trend["자본총계"] < 0].tolist()
        if negative:
            notes.append(f"자본총계가 마이너스인 해가 있습니다: {', '.join(map(str, negative))}")

    if "영업이익" in trend.columns:
        losses = trend.index[trend["영업이익"] < 0].tolist()
        if len(losses) >= 3:
            notes.append(f"영업적자가 {len(losses)}개 연도입니다: {', '.join(map(str, losses))}")
        elif losses:
            notes.append(f"영업적자 연도: {', '.join(map(str, losses))}")

    ratios = derived(trend)
    if "부채비율%" in ratios.columns and len(ratios) >= 2:
        last, prev = ratios["부채비율%"].iloc[-1], ratios["부채비율%"].iloc[-2]
        if pd.notna(last) and pd.notna(prev) and last > 200 and last > prev:
            notes.append(f"부채비율이 {prev:,.0f}% → {last:,.0f}% 로 200% 를 넘었습니다.")

    if "매출액" in trend.columns and len(trend) >= 2:
        drops = (trend["매출액"].pct_change() < -0.20).sum()
        if drops:
            notes.append(f"매출이 전년 대비 20% 넘게 줄어든 해가 {int(drops)}번 있습니다.")

    return notes


# ────────────────────────────── 연결해서 보기 ──────────────────────────────

@dataclass
class CompanyBrief:
    code: str
    name: str
    corp_code: str
    trend: pd.DataFrame = field(default_factory=pd.DataFrame)
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    notes: list[str] = field(default_factory=list)
    filing_count: int = 0
    window_days: int = 0


def brief(key: str, code_or_name: str, index: pd.DataFrame,
          years: int = 5, days: int = 365) -> CompanyBrief:
    """한 회사를 공시로 훑습니다."""
    corp_code = find_corp_code(index, code_or_name)
    if not corp_code:
        raise DartError(NO_DATA, f"'{code_or_name}' 에 해당하는 회사를 못 찾았습니다.")

    today = pd.Timestamp.today().normalize()
    start = (today - pd.Timedelta(days=days)).strftime("%Y%m%d")
    listing = filings(key, corp_code, start, today.strftime("%Y%m%d"))
    trend = financial_trend(key, corp_code, years=years)

    return CompanyBrief(
        code=str(code_or_name),
        name=corp_name(index, corp_code) or str(code_or_name),
        corp_code=corp_code,
        trend=trend,
        events=flag_events(listing),
        notes=health_flags(trend),
        filing_count=len(listing),
        window_days=days,
    )


def _money(value: float) -> str:
    """원 단위 숫자를 억/조로 줄여 씁니다."""
    if pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    size = abs(value)
    if size >= 1e12:
        return f"{sign}{size / 1e12:,.2f}조"
    if size >= 1e8:
        return f"{sign}{size / 1e8:,.0f}억"
    return f"{sign}{size:,.0f}"


def report(item: CompanyBrief) -> str:
    """사실과 해석을 갈라서 적습니다. 매매 판단은 넣지 않습니다."""
    lines = [
        f"📄 {item.name} ({item.code})  DART 고유번호 {item.corp_code}",
        f"   출처: 금융감독원 전자공시 opendart.fss.or.kr",
        "",
    ]

    lines.append("[사실] 재무 추세 — 사업보고서 주요계정")
    if item.trend.empty:
        lines.append("   재무 자료를 받지 못했습니다. 신규 상장이거나 공시가 아직 없습니다.")
    else:
        header = "   연도    " + "".join(f"{c:>12}" for c in item.trend.columns)
        lines.append(header)
        for year, row in item.trend.iterrows():
            cells = "".join(f"{_money(row[c]):>12}" for c in item.trend.columns)
            lines.append(f"   {year}  {cells}")
        ratios = derived(item.trend)
        if not ratios.empty:
            lines.append("")
            head = "   연도    " + "".join(f"{c:>12}" for c in ratios.columns)
            lines.append(head)
            for year, row in ratios.iterrows():
                cells = "".join(
                    f"{'—' if pd.isna(row[c]) else format(row[c], ',.1f'):>12}"
                    for c in ratios.columns
                )
                lines.append(f"   {year}  {cells}")
    lines.append("")

    lines.append(f"[사실] 최근 {item.window_days}일 공시 {item.filing_count}건 중 눈여겨볼 것")
    if item.events.empty:
        lines.append("   해당 없음. (공시가 없다는 뜻이 아니라, 규칙에 걸린 게 없다는 뜻입니다)")
    else:
        for _, row in item.events.iterrows():
            mark = "🔴" if row["severity"] == "높음" else "🟡"
            lines.append(f"   {mark} {row['rcept_dt']}  [{row['label']}] {row['report_nm']}")
            lines.append(f"        → {row['why']}")
    lines.append("")

    lines.append("[사실] 재무제표에서 바로 읽히는 것")
    if item.notes:
        for note in item.notes:
            lines.append(f"   · {note}")
    else:
        lines.append("   규칙에 걸린 항목 없음.")
    lines.append("")

    lines.append("[해석] 여기서부터는 프로그램이 판단하지 않습니다.")
    lines.append("   위 항목들은 '확인해 볼 거리' 이지 매수·매도 신호가 아닙니다.")
    lines.append("   공시는 결산 후 최대 90일 뒤에 올라옵니다. 오늘의 주가와는 시차가 큽니다.")
    lines.append("   판단이 필요하면 원문을 직접 읽으세요: dart.fss.or.kr 에서 회사명 검색.")
    return "\n".join(lines)


@dataclass
class CheckResult:
    ok: bool
    message: str
    companies: int = 0


def check(key: str, cache_dir: Path | str = CACHE_DIR) -> CheckResult:
    """키가 실제로 동작하는지 확인합니다. 안내하기 전에 제가 먼저 확인하려고 만든 것."""
    try:
        index = load_corp_index(key, cache_dir, refresh=False)
    except DartError as exc:
        return CheckResult(False, f"회사 목록을 받지 못했습니다. {exc}")
    except Exception as exc:                   # 네트워크·압축 해제 실패 등
        return CheckResult(False, f"회사 목록을 받지 못했습니다: {exc}")

    listed = int((index["stock_code"].str.len() == 6).sum())
    samsung = find_corp_code(index, "005930")
    if not samsung:
        return CheckResult(False, "회사 목록은 받았는데 삼성전자를 못 찾습니다. 목록이 깨진 것 같습니다.",
                           companies=listed)
    try:
        probe = filings(key, samsung, "20240101", "20241231", kind="A")
    except DartError as exc:
        return CheckResult(False, f"공시 조회에 실패했습니다. {exc}", companies=listed)

    return CheckResult(
        True,
        f"정상입니다. 상장사 {listed:,}개를 인식했고, 삼성전자 2024년 정기공시 "
        f"{len(probe)}건을 읽었습니다.",
        companies=listed,
    )
