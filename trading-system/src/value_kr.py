"""저평가 찾기 — 앱으로 하나씩 보던 것을 1,800종목 한 번에.

사장님이 앱으로 하시던 일을 그대로 옮깁니다. 회사가 버는 돈과 가진
재산에 견주어 주가가 싼가. 다른 점은 하나뿐입니다 — 종목 하나씩이
아니라 코스닥 전체를 한 번에 훑습니다.

보는 지표.

    PBR   시가총액 ÷ 자본총계    회사가 가진 순재산의 몇 배에 팔리나
                                1배면 '회사를 통째로 사서 다 팔면 본전'
    PER   시가총액 ÷ 당기순이익  지금 이익이 계속되면 원금 회수에 몇 년
    PSR   시가총액 ÷ 매출액      적자라 PER 이 없을 때 쓰는 대용

⚠️ 싼 데는 이유가 있습니다. 이게 제일 중요합니다.

  PBR 0.3 인 회사는 시장이 바보라서 싼 게 아니라, 그 재산이 실제로는
  그 값이 아니거나 계속 까먹고 있을 가능성이 큽니다. 이걸 '가치 함정'
  이라고 부릅니다. 싸다는 이유만으로 사면 계속 싸지는 것을 삽니다.

  그래서 싼 것만 고르지 않고 **거르는 조건**을 같이 겁니다 —
  영업적자, 자본잠식, 과도한 부채, 거래가 거의 없는 종목.

⚠️ 그리고 이 화면은 검증된 것이 아닙니다.
  "이 조건으로 골랐더니 과거에 잘 됐다" 는 아직 확인하지 않았습니다.
  여기서 나오는 것은 **사장님이 직접 볼 후보 목록**이지 매수 신호가
  아닙니다. 앱에서 조건 걸어 나온 목록과 같은 성격입니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# DART 주요계정에서 쓸 항목
NEEDED = ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계")

# DART 주요계정의 계정명은 회사마다 조금씩 다릅니다. 같은 뜻으로 묶습니다.
# 이걸 안 하면 당기순이익이 통째로 안 읽히고, PER 이 전부 빈칸이 됩니다.
ALIASES = {
    "매출액": ("매출액", "수익(매출액)", "영업수익", "매출"),
    "영업이익": ("영업이익", "영업이익(손실)", "영업손실"),
    "당기순이익": ("당기순이익", "당기순이익(손실)", "당기순손실",
               "당기순이익(당기순손실)", "분기순이익", "반기순이익"),
    "자산총계": ("자산총계",),
    "부채총계": ("부채총계",),
    "자본총계": ("자본총계",),
}


def _canonical(account_name: str) -> str | None:
    """공시에 적힌 계정명을 우리가 쓰는 이름으로 옮깁니다."""
    squeezed = "".join(str(account_name).split())
    for label, names in ALIASES.items():
        if any("".join(n.split()) == squeezed for n in names):
            return label
    return None

FIN_COLUMNS = ("code", "bsns_year", "rcept_dt", *NEEDED)


def listing_with_cap(market: str = "KOSDAQ") -> pd.DataFrame:
    """전 종목 목록에 시가총액·현재가·거래대금을 붙여 받아옵니다.

    FinanceDataReader 가 주는 컬럼 이름이 판마다 조금씩 달라서
    소문자로 맞춰 찾습니다. 없는 값은 빈칸으로 두고, 시가총액이
    아예 없으면 계산 자체가 불가능하므로 그때만 실패로 처리합니다.
    """
    from .data_kr import DataUnavailable, _fdr

    fdr = _fdr()
    key = market.strip().upper()
    try:
        raw = fdr.StockListing(key)
    except Exception as exc:  # noqa: BLE001
        raise DataUnavailable(f"{key} 종목 목록 조회 실패 - {exc}") from exc
    if raw is None or raw.empty:
        raise DataUnavailable(f"{key} 종목 목록이 비어 있습니다.")

    lower = {str(c).strip().lower(): c for c in raw.columns}

    def pick(*names: str):
        for n in names:
            if n in lower:
                return raw[lower[n]]
        return None

    code = pick("code", "symbol")
    name = pick("name")
    if code is None or name is None:
        raise DataUnavailable(
            f"{key} 목록에서 종목코드/종목명을 못 찾았습니다: {list(raw.columns)}"
        )

    marcap = pick("marcap", "시가총액")
    if marcap is None:
        raise DataUnavailable(
            "종목 목록에 시가총액이 없습니다. PBR·PER 을 계산할 수 없습니다.\n"
            f"받은 컬럼: {list(raw.columns)}"
        )

    out = pd.DataFrame({
        "code": code.astype(str).str.zfill(6),
        "name": name.astype(str),
        "marcap": pd.to_numeric(marcap, errors="coerce"),
    })
    close = pick("close", "종가")
    out["close"] = pd.to_numeric(close, errors="coerce") if close is not None else np.nan
    amount = pick("amount", "거래대금")
    out["turnover"] = (pd.to_numeric(amount, errors="coerce")
                       if amount is not None else np.nan)
    return out.dropna(subset=["marcap"]).reset_index(drop=True)


def latest_financials(key: str, index: pd.DataFrame, codes: list[str],
                      years_back: int = 2,
                      progress: int = 100) -> tuple[pd.DataFrame, list[str]]:
    """종목별로 가장 최근 사업보고서의 주요계정을 모읍니다.

    돌려주는 표에는 rcept_dt(공시 접수일) 가 같이 들어갑니다. 지금
    화면을 보는 데는 필요 없지만, 나중에 과거 검증을 할 때 '이 숫자를
    언제부터 알 수 있었나' 를 지키려면 반드시 있어야 합니다.
    """
    from . import dart_kr

    rows: list[dict] = []
    실패: list[str] = []
    올해 = pd.Timestamp.today().year

    for i, code in enumerate(codes, 1):
        corp = dart_kr.find_corp_code(index, code)
        if not corp:
            실패.append(code)
            continue

        찾음 = None
        for year in range(올해 - 1, 올해 - 1 - years_back, -1):
            try:
                raw = dart_kr.finstate(key, corp, year)
            except dart_kr.DartError:
                break
            if raw.empty:
                continue
            찾음 = (year, raw)
            break

        if 찾음 is None:
            실패.append(code)
            continue

        year, raw = 찾음
        if "fs_div" in raw.columns:                 # 연결 우선, 없으면 개별
            for div in ("CFS", "OFS"):
                part = raw[raw["fs_div"] == div]
                if not part.empty:
                    raw = part
                    break

        row = {"code": code, "bsns_year": year,
               "rcept_dt": str(raw["rcept_no"].iloc[0])[:8] if "rcept_no" in raw else ""}
        for _, item in raw.iterrows():
            label = _canonical(item.get("account_nm", ""))
            if label and label not in row:
                row[label] = dart_kr._to_number(item.get("thstrm_amount"))
        rows.append(row)

        if progress and i % progress == 0:
            print(f"  {i}/{len(codes)}... (실패 {len(실패)})")

    if not rows:
        return pd.DataFrame(columns=list(FIN_COLUMNS)), 실패
    frame = pd.DataFrame(rows)
    for column in NEEDED:
        if column not in frame.columns:
            frame[column] = np.nan
    return frame[list(FIN_COLUMNS)], 실패


def valuation(listing: pd.DataFrame, fin: pd.DataFrame) -> pd.DataFrame:
    """시가총액과 재무를 붙여 PBR·PER·PSR 을 계산합니다.

    listing 에는 code, name, close, marcap 이 있어야 합니다.
    나눗셈이 안 되는 자리(0 이나 마이너스)는 빈칸으로 둡니다.
    없는 것을 0 으로 채우면 '아주 싼 종목' 으로 둔갑합니다.
    """
    merged = listing.merge(fin, on="code", how="inner")
    if merged.empty:
        return merged

    def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        denom = denominator.where(denominator > 0)      # 0·마이너스는 계산 안 함
        return (numerator / denom).replace([np.inf, -np.inf], np.nan)

    merged["PBR"] = _ratio(merged["marcap"], merged["자본총계"])
    merged["PER"] = _ratio(merged["marcap"], merged["당기순이익"])
    merged["PSR"] = _ratio(merged["marcap"], merged["매출액"])
    merged["영업이익률%"] = _ratio(merged["영업이익"], merged["매출액"]) * 100.0
    merged["부채비율%"] = _ratio(merged["부채총계"], merged["자본총계"]) * 100.0
    return merged


# ─────────────────────────── 거르기 ───────────────────────────
# 싸다는 이유만으로 사면 계속 싸지는 것을 삽니다. 먼저 거릅니다.

@dataclass
class Screen:
    max_pbr: float = 1.0
    max_per: float = 15.0
    require_profit: bool = True        # 영업이익 흑자만
    max_debt_ratio: float = 200.0      # 부채비율 상한 (%)
    min_marcap: float = 30_000_000_000  # 시가총액 하한 (300억)
    min_turnover: float = 500_000_000   # 하루 거래대금 하한 (5억)


REJECT_REASONS = {
    "자본잠식": "자본총계가 0 이하 — 상장폐지 요건에 걸릴 수 있습니다",
    "영업적자": "영업이익이 마이너스 — 싼 데는 이유가 있습니다",
    "PBR높음": "순재산 대비 비쌉니다",
    "PER높음": "이익 대비 비쌉니다",
    "순재산자료없음": "자본총계를 못 읽었습니다 — 조건이 아니라 자료 문제입니다",
    "이익자료없음": "당기순이익을 못 읽었거나 적자입니다 — PER 을 계산할 수 없습니다",
    "부채과다": "부채비율이 너무 높습니다",
    "너무작음": "시가총액이 작아 흔들림이 큽니다",
    "거래부족": "거래가 적어 사고팔기 어렵습니다",
}


def screen(frame: pd.DataFrame, rule: Screen) -> pd.DataFrame:
    """조건에 걸린 이유를 종목마다 적어서 돌려줍니다.

    통과한 것만 주지 않고 탈락 이유도 함께 남깁니다. '왜 이 종목이
    안 나왔지' 를 물을 수 있어야 조건을 고칠 수 있습니다.
    """
    if frame.empty:
        return frame

    out = frame.copy()

    def _col(name: str) -> pd.Series:
        return out[name] if name in out.columns else pd.Series(np.nan, index=out.index)

    자본, 영업 = _col("자본총계"), _col("영업이익")
    pbr, per = _col("PBR"), _col("PER")
    부채비율, 시총, 거래대금 = _col("부채비율%"), _col("marcap"), _col("turnover")

    # 조건 이름 → 걸린 종목 (True 면 탈락)
    걸림 = {
        "자본잠식": 자본.notna() & (자본 <= 0),
        "영업적자": 영업.notna() & (영업 < 0) if rule.require_profit
                    else pd.Series(False, index=out.index),
        # 계산이 안 된 것(빈칸)도 탈락입니다. 모르는 것을 통과시키면 안 됩니다.
        # 다만 '비싸서 떨어진 것' 과 '숫자를 못 읽어서 떨어진 것' 은 갈라 적습니다.
        # 뭉뚱그리면 자료가 안 들어온 것을 시장이 비싼 것으로 오해합니다.
        "순재산자료없음": pbr.isna(),
        "PBR높음": pbr.notna() & (pbr > rule.max_pbr),
        "이익자료없음": per.isna() if rule.max_per > 0
                    else pd.Series(False, index=out.index),
        "PER높음": (per.notna() & (per > rule.max_per)) if rule.max_per > 0
                   else pd.Series(False, index=out.index),
        "부채과다": 부채비율.notna() & (부채비율 > rule.max_debt_ratio),
        "너무작음": 시총.notna() & (시총 < rule.min_marcap),
        "거래부족": 거래대금.notna() & (거래대금 < rule.min_turnover),
    }

    사유 = pd.Series("", index=out.index)
    for 이름, 마스크 in 걸림.items():
        마스크 = 마스크.fillna(False).astype(bool)
        사유 = sum_reason(사유, 마스크, 이름)

    out["탈락사유"] = 사유
    out["통과"] = out["탈락사유"] == ""
    return out


def sum_reason(current: pd.Series, mask: pd.Series, label: str) -> pd.Series:
    """탈락 사유를 쉼표로 이어 붙입니다."""
    added = current.where(~mask, current.where(current == "", current + ",") + label)
    return added.fillna("")


def rank(passed: pd.DataFrame) -> pd.DataFrame:
    """통과한 것들을 싼 순으로. PBR 과 PER 순위를 더해 씁니다.

    한 지표만 쓰면 그 지표가 이상한 종목이 1등을 합니다. 둘의 순위를
    더하면 양쪽 다 괜찮은 종목이 위로 옵니다.
    """
    if passed.empty:
        return passed
    out = passed.copy()
    pbr순위 = out["PBR"].rank(method="min")
    per순위 = out["PER"].rank(method="min")
    out["저평가점수"] = pd.concat([pbr순위, per순위], axis=1).mean(axis=1)
    return out.sort_values("저평가점수")


def _num(value, fmt: str) -> str:
    return "—" if pd.isna(value) else format(value, fmt)


def reject_counts(screened: pd.DataFrame) -> dict[str, int]:
    """탈락 사유별 종목 수."""
    세기: dict[str, int] = {}
    if screened.empty or "탈락사유" not in screened:
        return 세기
    for 사유들 in screened.loc[~screened["통과"], "탈락사유"]:
        for 사유 in str(사유들).split(","):
            if 사유:
                세기[사유] = 세기.get(사유, 0) + 1
    return 세기


def completeness(frame: pd.DataFrame) -> pd.DataFrame:
    """항목별로 숫자가 실제로 들어온 종목 수.

    조건이 빡빡해서 안 나온 것과 자료가 안 들어와서 안 나온 것은
    완전히 다른 문제입니다. 이 표가 없으면 둘을 구분할 수 없습니다.
    """
    if frame.empty:
        return pd.DataFrame()
    보고싶은것 = [*NEEDED, "PBR", "PER"]
    rows = [
        {"항목": column,
         "값이 있는 종목": int(frame[column].notna().sum()),
         "비율%": round(frame[column].notna().mean() * 100, 1)}
        for column in 보고싶은것 if column in frame.columns
    ]
    return pd.DataFrame(rows)


def report(screened: pd.DataFrame, rule: Screen, top: int = 30) -> str:
    lines = ["=" * 88,
             "[저평가 후보] 회사가 가진 것·버는 것에 견주어 싼 종목",
             "=" * 88, ""]

    lines.append("[사실] 건 조건")
    lines.append(f"   PBR ≤ {rule.max_pbr}  ·  PER ≤ {rule.max_per}"
                 f"  ·  부채비율 ≤ {rule.max_debt_ratio}%")
    lines.append(f"   영업흑자만: {'예' if rule.require_profit else '아니오'}"
                 f"  ·  시가총액 ≥ {rule.min_marcap / 1e8:,.0f}억"
                 f"  ·  거래대금 ≥ {rule.min_turnover / 1e8:,.1f}억")
    lines.append("")

    if screened.empty:
        lines.append("[사실] 재무를 붙일 수 있는 종목이 없습니다.")
        lines.append("=" * 88)
        return "\n".join(lines)

    통과 = rank(screened[screened["통과"]])
    lines.append(f"[사실] 전체 {len(screened):,}종목 중 {len(통과):,}종목 통과")
    lines.append("")

    갖춤 = completeness(screened)
    if not 갖춤.empty:
        모자란것 = 갖춤[갖춤["비율%"] < 80]
        if not 모자란것.empty:
            lines.append("[사실] ⚠️ 자료가 덜 들어온 항목이 있습니다")
            lines.append("   " + 갖춤.to_string(index=False).replace("\n", "\n   "))
            lines.append("")
            lines.append("   비율이 낮은 항목은 조건이 빡빡해서가 아니라 숫자를 못 읽어서")
            lines.append("   걸린 것입니다. 조건을 풀어도 안 나옵니다.")
            lines.append("")

    if 통과.empty:
        자료탓 = {"이익자료없음", "순재산자료없음"} & set(reject_counts(screened))
        if 자료탓:
            lines.append("   통과한 종목이 없습니다. 다만 원인이 조건이 아니라 자료입니다 —")
            lines.append(f"   {', '.join(sorted(자료탓))}. 조건을 풀어도 안 나옵니다.")
        else:
            lines.append("   조건을 통과한 종목이 없습니다. 조건을 조금 풀어보세요.")
    else:
        lines.append("   순위  종목명            코드      현재가"
                     "     PBR     PER   영업이익률  부채비율")
        lines.append("   " + "-" * 78)
        for i, (_, row) in enumerate(통과.head(top).iterrows(), 1):
            lines.append(
                f"   {i:>3}  {str(row.get('name', ''))[:14]:<14}"
                f"  {row['code']}  {_num(row.get('close'), ',.0f'):>9}"
                f"  {_num(row.get('PBR'), '.2f'):>6}"
                f"  {_num(row.get('PER'), '.1f'):>6}"
                f"   {_num(row.get('영업이익률%'), '.1f'):>7}%"
                f"   {_num(row.get('부채비율%'), '.0f'):>6}%"
            )

    세기 = reject_counts(screened)
    if 세기:
        lines.append("")
        lines.append("[사실] 탈락 사유별 종목 수")
        for 사유, 수 in sorted(세기.items(), key=lambda x: -x[1]):
            lines.append(f"   {사유:<8} {수:>5}종목   {REJECT_REASONS.get(사유, '')}")

    lines.append("")
    lines.append("[해석] 이 목록은 검증된 것이 아닙니다.")
    lines.append("   · '이 조건으로 고르면 과거에 잘 됐다' 는 아직 확인하지 않았습니다.")
    lines.append("   · 앱에서 조건 걸어 나온 목록과 같은 성격입니다. 후보일 뿐입니다.")
    lines.append("   · 싼 데는 이유가 있습니다. 하나씩 열어서 왜 싼지 보셔야 합니다.")
    lines.append("     → python -m src.cli dart-company --code 종목코드")
    lines.append("=" * 88)
    return "\n".join(lines)
