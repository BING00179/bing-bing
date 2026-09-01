"""두 축으로 보기 — 좋은 기업인가, 값이 괜찮은가.

사장님이 정하신 기준입니다.

    좋은 기업도 너무 비싸게 사면 오랫동안 손실을 볼 수 있고,
    싼 주식도 나쁜 기업이면 계속 싸질 수 있다.
    원하는 것은 단순한 저가주가 아니라,
    가치가 유지되거나 성장하는 기업을 합리적인 가격에 사는 것.

그래서 점수를 **하나로 합치지 않습니다.** 합치면 '싸지만 망해가는
회사' 와 '좋지만 너무 비싼 회사' 가 같은 점수로 섞여, 무엇이 문제인지
알 수 없게 됩니다.

    기업 점수   실적 · 현금흐름 · 부채 · 이익률
    가격 점수   PBR · PER · 성장 대비 PER · 최근 1년 위치

둘 다 좋아야 후보입니다. 한쪽만 좋으면 후보가 아니라 '왜 한쪽만
좋은지 확인해 볼 것' 입니다.

⚠️ 점수는 순위를 매기는 도구일 뿐, 이 점수가 수익을 예측한다는
   근거는 아직 없습니다. 전에 만든 점수 체계는 상위 종목이 오히려
   더 나빴습니다(PF 0.779 → 0.626). 그래서 점수만 보지 말고 항목별로
   무엇이 좋고 나쁜지 같이 냅니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(np.nan, index=frame.index)


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    """0 이나 마이너스로는 나누지 않습니다. 결과를 지어내지 않으려고."""
    return (a / b.where(b > 0)).replace([np.inf, -np.inf], np.nan)


def _cagr(끝: pd.Series, 처음: pd.Series, 해: int = 2) -> pd.Series:
    """연평균 성장률(%). 처음이 0 이하면 계산하지 않습니다."""
    비율 = (끝 / 처음.where(처음 > 0)).replace([np.inf, -np.inf], np.nan)
    return ((비율.where(비율 > 0) ** (1.0 / 해)) - 1.0) * 100.0


# ─────────────────────────── ① 기업이 좋은가 ───────────────────────────

def business_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """실적·현금흐름·부채·이익률. 계산이 안 되는 칸은 비워 둡니다."""
    out = pd.DataFrame(index=frame.index)

    매출0, 매출2 = _num(frame, "매출액_y0"), _num(frame, "매출액_y2")
    영업0, 영업1 = _num(frame, "영업이익_y0"), _num(frame, "영업이익_y1")
    영업2 = _num(frame, "영업이익_y2")
    순이익0 = _num(frame, "당기순이익_y0")
    부채0, 자본0 = _num(frame, "부채총계_y0"), _num(frame, "자본총계_y0")
    현금0 = _num(frame, "영업활동현금흐름_y0")
    설비0 = _num(frame, "설비투자_y0")

    out["매출성장%"] = _cagr(매출0, 매출2, 해=2)
    out["영업이익성장%"] = _cagr(영업0, 영업2, 해=2)
    out["영업이익률%"] = _safe_div(영업0, 매출0) * 100.0
    out["부채비율%"] = _safe_div(부채0, 자본0) * 100.0

    # 장부상 이익이 실제 현금으로 들어오나. 1 에 가까울수록 좋습니다.
    out["현금전환배수"] = _safe_div(현금0, 순이익0)
    out["잉여현금"] = 현금0 - 설비0.abs()

    # 세 해 모두 영업흑자였나 — 한 해만 좋았던 것과 다릅니다.
    셋다 = pd.concat([영업0, 영업1, 영업2], axis=1)
    out["흑자연수"] = (셋다 > 0).sum(axis=1).where(셋다.notna().any(axis=1))
    return out


BUSINESS_RULES = (
    # (이름, 어떻게 재나, 만점, 없을 때 설명)
    ("매출성장", "매출성장%", 20, "매출이 늘고 있나 (3년 연평균)"),
    ("이익성장", "영업이익성장%", 20, "영업이익이 늘고 있나 (3년 연평균)"),
    ("수익성", "영업이익률%", 20, "팔아서 얼마나 남기나"),
    ("현금창출", "현금전환배수", 20, "장부상 이익이 실제 현금으로 들어오나"),
    ("재무안정", "부채비율%", 20, "빚이 갚을 만한 수준인가"),
)


def business_score(metrics: pd.DataFrame) -> pd.DataFrame:
    """항목별 0~20점. 합쳐서 100점 만점.

    구간은 미리 정해 둡니다 — 결과를 보고 경계를 옮기면 원하는 그림을
    만들 수 있습니다.
    """
    out = pd.DataFrame(index=metrics.index)

    성장 = metrics["매출성장%"]
    out["매출성장"] = pd.cut(성장, [-np.inf, 0, 5, 10, 20, np.inf],
                          labels=[0, 5, 10, 15, 20]).astype("float")
    이익성장 = metrics["영업이익성장%"]
    out["이익성장"] = pd.cut(이익성장, [-np.inf, 0, 5, 10, 20, np.inf],
                          labels=[0, 5, 10, 15, 20]).astype("float")
    이익률 = metrics["영업이익률%"]
    out["수익성"] = pd.cut(이익률, [-np.inf, 0, 5, 10, 15, np.inf],
                        labels=[0, 5, 10, 15, 20]).astype("float")
    현금 = metrics["현금전환배수"]
    out["현금창출"] = pd.cut(현금, [-np.inf, 0, 0.5, 0.8, 1.2, np.inf],
                         labels=[0, 5, 12, 20, 15]).astype("float")
    부채 = metrics["부채비율%"]
    out["재무안정"] = pd.cut(부채, [-np.inf, 50, 100, 150, 200, np.inf],
                         labels=[20, 15, 10, 5, 0]).astype("float")

    out["기업점수"] = out[[n for n, *_ in BUSINESS_RULES]].sum(axis=1, min_count=1)
    # 몇 항목이 실제로 계산됐는지. 적으면 점수를 믿을 수 없습니다.
    out["기업항목수"] = out[[n for n, *_ in BUSINESS_RULES]].notna().sum(axis=1)
    return out


# ─────────────────────────── ② 값이 괜찮은가 ───────────────────────────

def price_metrics(frame: pd.DataFrame, prices: pd.DataFrame | None = None
                  ) -> pd.DataFrame:
    """PBR·PER·성장 대비 PER·최근 1년 위치·아래쪽 여유."""
    out = pd.DataFrame(index=frame.index)
    시총 = _num(frame, "marcap")
    자본0 = _num(frame, "자본총계_y0")
    순이익0 = _num(frame, "당기순이익_y0")
    영업0 = _num(frame, "영업이익_y0")

    out["PBR"] = _safe_div(시총, 자본0)
    out["PER"] = _safe_div(시총, 순이익0)
    out["영업PER"] = _safe_div(시총, 영업0)

    # 성장률에 견주어도 싼가. 1 아래면 성장 대비 싸다고들 합니다.
    # ⚠️ 성장률이 앞으로도 이어진다는 보장은 없습니다. 참고 지표입니다.
    성장 = _cagr(_num(frame, "영업이익_y0"), _num(frame, "영업이익_y2"), 해=2)
    out["성장대비PER"] = (out["PER"] / 성장.where(성장 > 0)).replace(
        [np.inf, -np.inf], np.nan)

    if prices is not None and not prices.empty:
        for 열 in ("high_52w", "low_52w", "close"):
            if 열 in prices.columns:
                out[열] = pd.to_numeric(prices[열], errors="coerce")
        높, 낮, 현재 = out.get("high_52w"), out.get("low_52w"), out.get("close")
        if 높 is not None and 낮 is not None and 현재 is not None:
            폭 = (높 - 낮).where(높 > 낮)
            out["1년위치%"] = ((현재 - 낮) / 폭 * 100.0).replace(
                [np.inf, -np.inf], np.nan)
            # 최근 1년 저점까지 얼마나 남았나 — 최악을 가늠하는 거친 눈금
            out["저점까지%"] = ((낮 / 현재 - 1.0) * 100.0).replace(
                [np.inf, -np.inf], np.nan)
    return out


PRICE_RULES = (
    ("PBR값", "PBR", 25, "순재산에 견주어 싼가"),
    ("PER값", "PER", 25, "이익에 견주어 싼가"),
    ("성장대비", "성장대비PER", 25, "성장률에 견주어도 싼가"),
    ("가격위치", "1년위치%", 25, "최근 1년 범위에서 아래쪽인가"),
)


def price_score(metrics: pd.DataFrame) -> pd.DataFrame:
    """항목별 0~25점. 합쳐서 100점 만점. 쌀수록 높습니다."""
    out = pd.DataFrame(index=metrics.index)

    pbr = metrics.get("PBR", pd.Series(np.nan, index=metrics.index))
    out["PBR값"] = pd.cut(pbr, [-np.inf, 0.5, 0.8, 1.2, 2.0, np.inf],
                        labels=[25, 20, 15, 8, 0]).astype("float")
    per = metrics.get("PER", pd.Series(np.nan, index=metrics.index))
    out["PER값"] = pd.cut(per, [-np.inf, 6, 10, 15, 25, np.inf],
                        labels=[25, 20, 15, 8, 0]).astype("float")
    peg = metrics.get("성장대비PER", pd.Series(np.nan, index=metrics.index))
    out["성장대비"] = pd.cut(peg, [-np.inf, 0.5, 1.0, 1.5, 3.0, np.inf],
                         labels=[25, 20, 15, 8, 0]).astype("float")
    위치 = metrics.get("1년위치%", pd.Series(np.nan, index=metrics.index))
    out["가격위치"] = pd.cut(위치, [-np.inf, 25, 50, 75, 90, np.inf],
                         labels=[25, 20, 12, 5, 0]).astype("float")

    out["가격점수"] = out[[n for n, *_ in PRICE_RULES]].sum(axis=1, min_count=1)
    out["가격항목수"] = out[[n for n, *_ in PRICE_RULES]].notna().sum(axis=1)
    return out


# ─────────────────────────── 두 축을 합쳐 보기 ───────────────────────────

MIN_ITEMS = 3          # 이보다 적게 계산되면 점수를 믿지 않습니다
GOOD_BUSINESS = 60     # 기업 점수 합격선
GOOD_PRICE = 55        # 가격 점수 합격선


@dataclass
class Verdict:
    label: str
    meaning: str


VERDICTS = {
    "후보": Verdict("후보", "기업도 값도 괜찮습니다 — 열어서 확인해 볼 것"),
    "비쌈": Verdict("비쌈", "좋은 기업인데 값이 비쌉니다 — 기다려 볼 것"),
    "함정?": Verdict("함정?", "싼데 기업이 약합니다 — 계속 싸질 수 있습니다"),
    "제외": Verdict("제외", "기업도 값도 아닙니다"),
    "판단보류": Verdict("판단보류", "계산된 항목이 모자라 점수를 믿을 수 없습니다"),
}


def verdict(business: float, price: float,
            b_items: float, p_items: float) -> str:
    """두 축을 각각 보고 한 마디로. 합쳐서 평균내지 않습니다."""
    if (pd.isna(business) or pd.isna(price)
            or b_items < MIN_ITEMS or p_items < MIN_ITEMS):
        return "판단보류"
    좋은기업 = business >= GOOD_BUSINESS
    좋은값 = price >= GOOD_PRICE
    if 좋은기업 and 좋은값:
        return "후보"
    if 좋은기업:
        return "비쌈"
    if 좋은값:
        return "함정?"
    return "제외"


def report(evaluated: pd.DataFrame, top: int = 15) -> str:
    """두 축을 나눠서 보여줍니다. 하나로 합친 점수는 내지 않습니다."""
    lines = ["=" * 88,
             "[두 축으로 보기] 좋은 기업인가 · 값이 괜찮은가",
             "=" * 88, ""]

    if evaluated.empty:
        lines.append("볼 종목이 없습니다.")
        lines.append("=" * 88)
        return "\n".join(lines)

    세기 = evaluated["판정"].value_counts()
    lines.append("[사실] 판정별 종목 수")
    for 이름 in ("후보", "비쌈", "함정?", "제외", "판단보류"):
        수 = int(세기.get(이름, 0))
        if 수:
            lines.append(f"   {이름:<6} {수:>5}종목   {VERDICTS[이름].meaning}")
    lines.append("")

    후보 = evaluated[evaluated["판정"] == "후보"].sort_values(
        ["기업점수", "가격점수"], ascending=False)
    lines.append(f"[사실] 기업도 값도 괜찮은 것 — {len(후보)}종목")
    lines.append("")
    if 후보.empty:
        lines.append("   없습니다. 두 축을 다 만족하는 종목은 원래 드뭅니다.")
        lines.append("   조건을 풀기 전에, 어느 쪽이 모자라는지 먼저 보십시오 —")
        lines.append("   '비쌈' 이 많으면 시장이 비싼 것이고,")
        lines.append("   '함정?' 이 많으면 싼 것들이 다 이유가 있는 것입니다.")
    else:
        lines.append("   종목명            코드     기업  가격  "
                     "매출성장 이익률 부채  현금  PBR   PER  1년위치")
        lines.append("   " + "-" * 82)
        for _, row in 후보.head(top).iterrows():
            def g(이름, 꼴=".1f"):
                값 = row.get(이름)
                return "—" if 값 is None or pd.isna(값) else format(float(값), 꼴)
            lines.append(
                f"   {str(row.get('name', ''))[:14]:<14}  {row['code']}"
                f"  {g('기업점수', '.0f'):>4} {g('가격점수', '.0f'):>4}"
                f"  {g('매출성장%'):>7}% {g('영업이익률%'):>5}%"
                f" {g('부채비율%', '.0f'):>4}% {g('현금전환배수', '.2f'):>5}"
                f" {g('PBR', '.2f'):>5} {g('PER'):>5} {g('1년위치%', '.0f'):>6}%"
            )
    lines.append("")

    # 아깝게 놓친 것 — 한쪽만 좋은 것들
    비쌈 = evaluated[evaluated["판정"] == "비쌈"].sort_values(
        "기업점수", ascending=False)
    if not 비쌈.empty:
        lines.append(f"[사실] 좋은 기업인데 값이 비싼 것 — {len(비쌈)}종목 (기다려 볼 것)")
        for _, row in 비쌈.head(5).iterrows():
            lines.append(f"   {str(row.get('name',''))[:14]:<14}({row['code']})"
                         f"  기업 {row['기업점수']:.0f}점 · 가격 {row['가격점수']:.0f}점"
                         f"  PBR {row['PBR']:.2f}" if pd.notna(row.get("PBR"))
                         else f"   {str(row.get('name',''))[:14]}({row['code']})")
        lines.append("")

    lines.append("[해석] 두 축을 따로 보는 이유")
    lines.append("   · 좋은 기업도 너무 비싸게 사면 오래 손실을 봅니다 → '비쌈'")
    lines.append("   · 싼 주식도 기업이 나쁘면 계속 싸집니다 → '함정?'")
    lines.append("   · 점수를 하나로 합치면 이 둘이 섞여 무엇이 문제인지")
    lines.append("     알 수 없게 됩니다. 그래서 합치지 않습니다.")
    lines.append("")
    lines.append("   ⚠️ 이 점수가 수익을 예측한다는 근거는 아직 없습니다.")
    lines.append("      전에 만든 점수 체계는 상위 종목이 오히려 더 나빴습니다")
    lines.append("      (PF 0.779 → 0.626). 순위를 매기는 도구일 뿐입니다.")
    lines.append("   · 후보로 나와도 하나씩 열어서 왜 그런지 보셔야 합니다:")
    lines.append("       python -m src.cli dart-dashboard --code 종목코드")
    lines.append("=" * 88)
    return "\n".join(lines)


def evaluate(frame: pd.DataFrame, prices: pd.DataFrame | None = None
             ) -> pd.DataFrame:
    """두 축을 재고 한 표로 묶습니다."""
    사업 = business_metrics(frame)
    사업점수 = business_score(사업)
    값 = price_metrics(frame, prices)
    값점수 = price_score(값)

    out = pd.concat([frame.reset_index(drop=True),
                     사업.reset_index(drop=True),
                     사업점수.reset_index(drop=True),
                     값.reset_index(drop=True),
                     값점수.reset_index(drop=True)], axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    out["판정"] = [
        verdict(b, p, bi, pi) for b, p, bi, pi in zip(
            out["기업점수"], out["가격점수"],
            out["기업항목수"], out["가격항목수"])
    ]
    return out
