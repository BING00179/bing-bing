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

# 합격선을 넘은 것 중에서도 위쪽만 봅니다. 73종목이 나오면 고를 수가
# 없습니다. 사장님이 원하신 것은 '확실한 2~3종목' 이지 목록이 아닙니다.
STRICT_BUSINESS = 80
STRICT_PRICE = 75


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


def report(evaluated: pd.DataFrame, top: int = 8) -> str:
    """터미널에는 짧게만. 표를 쏟아내면 아무것도 눈에 안 들어옵니다."""
    if evaluated.empty:
        return "볼 종목이 없습니다."

    lines = []
    세기 = evaluated["판정"].value_counts()
    좁힌것 = shortlist(evaluated)

    lines.append("")
    lines.append(f"  전체 {len(evaluated):,}종목을 두 축으로 봤습니다.")
    lines.append("")
    for 이름 in ("후보", "비쌈", "함정?", "제외", "판단보류"):
        수 = int(세기.get(이름, 0))
        if 수:
            lines.append(f"    {이름:<6} {수:>5}종목  {VERDICTS[이름].meaning}")
    lines.append("")

    if 좁힌것.empty:
        lines.append("  ★ 양쪽 다 높은 것: 없습니다.")
        lines.append("")
        lines.append("    두 축을 다 만족하는 종목은 원래 드뭅니다.")
        lines.append("    '비쌈' 이 많으면 시장이 비싼 것이고,")
        lines.append("    '함정?' 이 많으면 싼 것들이 다 이유가 있는 것입니다.")
        return "\n".join(lines)

    lines.append(f"  ★ 양쪽 다 높은 것 — {len(좁힌것)}종목")
    lines.append("     (기업 {}점↑ · 가격 {}점↑)".format(
        STRICT_BUSINESS, STRICT_PRICE))
    lines.append("")
    for i, (_, row) in enumerate(좁힌것.head(top).iterrows(), 1):
        def g(이름, 꼴=".1f", 뒤=""):
            값 = row.get(이름)
            return "—" if 값 is None or pd.isna(값) else format(float(값), 꼴) + 뒤
        lines.append(
            f"   {i}. {str(row.get('name', ''))[:16]} ({row['code']})"
            f"   기업 {g('기업점수', '.0f')}점 · 가격 {g('가격점수', '.0f')}점"
        )
        lines.append(
            f"      매출 {g('매출성장%', '.0f', '%')} 성장 ·"
            f" 이익률 {g('영업이익률%', '.0f', '%')} ·"
            f" 부채 {g('부채비율%', '.0f', '%')}"
        )
        lines.append(
            f"      PBR {g('PBR', '.2f')} · PER {g('PER', '.1f')} ·"
            f" 1년 범위의 {g('1년위치%', '.0f', '%')} 지점"
        )
        lines.append("")

    if len(좁힌것) > top:
        lines.append(f"   ... 외 {len(좁힌것) - top}종목")
        lines.append("")
    return "\n".join(lines)


def shortlist(evaluated: pd.DataFrame,
              business: float = STRICT_BUSINESS,
              price: float = STRICT_PRICE) -> pd.DataFrame:
    """후보 중에서도 양쪽 다 높은 것만. 몇 개 안 남는 게 정상입니다."""
    if evaluated.empty:
        return evaluated
    좁힘 = evaluated[(evaluated["판정"] == "후보")
                   & (evaluated["기업점수"] >= business)
                   & (evaluated["가격점수"] >= price)]
    return 좁힘.sort_values(["기업점수", "가격점수"], ascending=False)


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


# ─────────────────────────── 보기 좋은 한 장 ───────────────────────────
# 터미널에 표를 쏟아내면 아무것도 눈에 안 들어옵니다. 브라우저로
# 여는 한 장을 따로 냅니다. 외부에서 아무것도 불러오지 않으니
# 인터넷 없이도 열립니다.

import html as _html


def _esc(text) -> str:
    return _html.escape(str(text), quote=True)


def _cell(row, 이름, 꼴=".1f", 뒤=""):
    값 = row.get(이름)
    if 값 is None or pd.isna(값):
        return "—"
    return format(float(값), 꼴) + 뒤


HTML_STYLE = """
:root{--ink:#1a1a1a;--dim:#6b7280;--line:#eceef1;--soft:#f7f8fa;
--good:#0f9d58;--warn:#e5a04d;--bad:#e5484d;--mark:#111}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);
font:15px/1.6 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--dim);font-size:13px;margin-bottom:28px}
h2{font-size:17px;margin:36px 0 4px}
.note{color:var(--dim);font-size:13px;margin:0 0 16px}
.counts{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 8px}
.count{background:var(--soft);border-radius:10px;padding:10px 14px;min-width:120px}
.count .n{font-size:20px;font-weight:700}
.count .l{font-size:12px;color:var(--dim);margin-top:1px}
.pick{border:1px solid var(--line);border-radius:14px;padding:18px 20px;
margin:12px 0;background:#fff}
.pick.star{border-color:var(--mark);border-width:2px}
.pick h3{margin:0;font-size:17px;display:flex;align-items:baseline;gap:8px;
flex-wrap:wrap}
.pick h3 .code{color:var(--dim);font-size:13px;font-weight:400}
.bars{display:flex;gap:16px;margin:12px 0 4px;flex-wrap:wrap}
.axis{flex:1;min-width:190px}
.axis .top{display:flex;justify-content:space-between;font-size:12.5px;
color:var(--dim);margin-bottom:4px}
.axis .top b{color:var(--ink)}
.track{height:8px;background:var(--line);border-radius:5px;overflow:hidden}
.fill{height:100%;border-radius:5px;background:var(--mark)}
.fill.b{background:#2f6df6}.fill.p{background:#0f9d58}
.facts{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:12px;
font-size:13.5px;color:var(--dim)}
.facts b{color:var(--ink);font-weight:600}
.facts i{font-style:normal;font-size:11.5px;color:#9aa0a8;margin-left:2px}
.plain{margin:12px 0 0;font-size:14.5px;line-height:1.7}
.points{display:flex;gap:16px;margin:14px 0 0;flex-wrap:wrap}
.points>div{flex:1;min-width:230px}
.points .t{font-size:13px;font-weight:600;margin-bottom:4px}
.points ul{margin:0;padding-left:18px;font-size:13.5px;line-height:1.65}
.points li{margin:3px 0}
.points .good .t{color:var(--good)}
.points .bad .t{color:var(--warn)}
.rule{border-left:3px solid var(--mark);padding:2px 0 2px 14px;margin:14px 0}
.rule .t{font-weight:600;font-size:14.5px}
.rule p{margin:4px 0;font-size:13.5px;line-height:1.65}
.rule .src{font-size:12px;color:#9aa0a8}
.levels{margin-top:14px;border:1px solid var(--line);border-radius:10px;
padding:12px 16px}
.levels .t{font-size:13px;font-weight:600;margin-bottom:8px}
.lvs{display:flex;flex-wrap:wrap;gap:14px 22px}
.lv{min-width:110px}
.lv .n{font-size:17px;font-weight:700;letter-spacing:-.02em}
.lv .l{font-size:12.5px;color:var(--dim);margin-top:1px}
.lv .w{font-size:11.5px;color:#9aa0a8;margin-top:2px;line-height:1.4}
.levels>.w{font-size:12.5px;color:var(--dim);margin:10px 0 0}
.steps{margin-top:14px;background:var(--soft);border-radius:10px;padding:12px 16px}
.steps .t{font-size:13px;font-weight:600;margin-bottom:6px}
.steps ol{margin:0;padding-left:20px;font-size:13.5px;line-height:1.75}
.steps li{margin:5px 0}
details{margin-top:12px}
summary{cursor:pointer;font-size:13px;color:var(--dim)}
.risk{margin-top:12px;padding:10px 12px;background:#fdecec;border-radius:9px;
font-size:13px}
.risk.check{background:#fff6e8}
.risk .t{font-weight:600;margin-bottom:6px}
.risk ul{margin:0;padding-left:18px;line-height:1.6}
.risk li{margin:4px 0}
.risk .w{color:var(--dim);font-size:12.5px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}
th,td{padding:8px 9px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12px}
td:first-child,th:first-child{text-align:left}
.scroll{overflow-x:auto}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);
color:var(--dim);font-size:12.5px;line-height:1.8}
"""


# 숫자만 늘어놓으면 아무 뜻이 없습니다. 무슨 말인지 풀어 씁니다.
PLAIN = {
    "기업점수": ("회사가 튼튼한가", "매출·이익이 늘고, 현금이 들어오고, 빚이 적은가"),
    "가격점수": ("지금 값이 싼가", "가진 것과 버는 것에 견주어, 그리고 최근 1년에 견주어"),
    "매출성장%": ("매출이 늘고 있나", "최근 3년 평균으로 해마다 몇 %씩"),
    "영업이익률%": ("100원 팔면 얼마 남나", "본업으로 남기는 몫"),
    "부채비율%": ("빚이 얼마나 되나", "자기 돈 대비 빌린 돈의 비율. 낮을수록 안전"),
    "현금전환배수": ("장부 이익이 진짜 현금인가", "1 에 가까울수록 좋습니다"),
    "PBR": ("회사 재산의 몇 배 값인가", "1 보다 낮으면 재산보다 싸게 팔리는 중"),
    "PER": ("원금 회수에 몇 년", "지금 이익이 계속된다고 치면"),
    "1년위치%": ("최근 1년에서 어디쯤", "0% 가 1년 최저, 100% 가 1년 최고"),
}


def one_line(row) -> str:
    """이 회사가 어떤 회사인지 한 문장으로. 숫자에서 곧장 나오는 말만."""
    조각 = []
    성장 = row.get("매출성장%")
    if pd.notna(성장):
        조각.append("매출이 해마다 늘고 있고" if 성장 > 5
                  else ("매출이 제자리이고" if 성장 > -5 else "매출이 줄고 있고"))
    이익률 = row.get("영업이익률%")
    if pd.notna(이익률):
        조각.append(f"100원 팔면 {이익률:.0f}원 남기며" if 이익률 > 0
                  else "본업에서는 아직 못 남기며")
    부채 = row.get("부채비율%")
    if pd.notna(부채):
        조각.append("빚도 적은 회사입니다" if 부채 < 100
                  else ("빚이 좀 있는 회사입니다" if 부채 < 200
                        else "빚이 많은 회사입니다"))
    앞 = ", ".join(조각) if 조각 else "재무를 다 읽지는 못했습니다"

    뒤 = []
    pbr = row.get("PBR")
    if pd.notna(pbr):
        뒤.append(f"가진 재산보다 {(1 - pbr) * 100:.0f}% 싸게 거래되고" if pbr < 1
                 else f"가진 재산의 {pbr:.1f}배 값이고")
    per = row.get("PER")
    if pd.notna(per):
        뒤.append(f"지금 이익이면 {per:.0f}년이면 원금을 뽑습니다")
    위치 = row.get("1년위치%")
    if pd.notna(위치):
        뒤.append("최근 1년 중에서도 싼 쪽입니다" if 위치 < 35
                 else ("한가운데쯤입니다" if 위치 < 70 else "비싼 쪽입니다"))
    return 앞 + ". " + (", ".join(뒤) + "." if 뒤 else "")


# 사장님이 정하신 값 (2026-09-01, 장부 판 v1)
TARGET_PCT = 20.0        # 목표: 진입가 대비 +20%
INVALID_PCT = -20.0      # 무효: 진입가 대비 -20% (장부와 같은 값)


def price_levels(row) -> dict:
    """지금 값에서 목표·무효선이 얼마인지. 예측이 아니라 산수입니다.

    사장님이 정하신 +20% / -20% 를 현재가에 곱한 것뿐입니다.
    '이 가격에 오른다' 는 뜻이 아니라 '샀다면 여기가 목표이고 여기가
    무효선' 이라는 뜻입니다.
    """
    현재 = row.get("close")
    if 현재 is None or pd.isna(현재) or float(현재) <= 0:
        return {}
    현재 = float(현재)
    값 = {
        "현재가": 현재,
        "목표가": 현재 * (1 + TARGET_PCT / 100.0),
        "무효선": 현재 * (1 + INVALID_PCT / 100.0),
    }
    for 이름, 열 in (("1년최저", "low_52w"), ("1년최고", "high_52w")):
        v = row.get(열)
        if v is not None and pd.notna(v):
            값[이름] = float(v)
    pbr = row.get("PBR")
    if pd.notna(pbr) and float(pbr) > 0:
        # 회사가 가진 순재산만큼의 값. 여기 아래면 재산보다 싸게 사는 것.
        값["재산값"] = 현재 / float(pbr)
    return 값


# ── 샀더니 떨어지는 것을 줄이는 규칙 ──
# 예측이 아닙니다. 우리가 5년치 코스닥을 돌려서 잰 숫자에서 나온
# 것입니다. 표본과 함께 적어 두어야, 나중에 '왜 이렇게 하지?' 를
# 물었을 때 근거를 찾을 수 있습니다.
BUY_RULES = (
    ("아침에 갭이 뜨면 그날은 사지 않기",
     "다음날 아침 5% 넘게 오른 채로 시작한 건은 5일 뒤 평균 -4.2%, "
     "승률 30% 였습니다. 갭 없이 시작한 건은 평균 -0.08% 였습니다.",
     "코스닥 5년, 갭 5%↑ 155건 vs 갭 없음 2,194건"),
    ("손절을 3% 로 잡지 않기",
     "손절 3% 는 진입 첫날에 46.8% 가 닿습니다. 신호가 맞든 틀리든 "
     "절반이 먼저 잘려나갑니다. 8% 면 첫날 도달이 6.0% 입니다.",
     "코스닥 5년, 신호 3,830건의 진입일 저가"),
    ("한 번에 다 사지 않기",
     "나눠 사면 하루 흔들림에 전부 잘리지 않고, 평균 단가도 한쪽으로 "
     "쏠리지 않습니다. 사장님이 우리기술에서 하신 방식입니다.",
     "측정값이 아니라 위 두 사실에서 따라오는 것"),
    ("판단이 틀렸을 때 나올 선을 먼저 정하기",
     f"진입가 대비 {INVALID_PCT:g}% 를 무효선으로 정해 두셨습니다. "
     "여기 닿으면 '판단이 틀렸다' 로 보고 나옵니다. 사고 나서 정하면 "
     "늘 조금만 더 기다리게 됩니다.",
     "사장님이 정하신 값 (2026-09-01)"),
)


def good_points(row) -> list[str]:
    """이 회사의 좋은 점. 숫자에서 곧장 나오는 것만."""
    말: list[str] = []
    성장 = row.get("매출성장%")
    if pd.notna(성장) and 성장 >= 10:
        말.append(f"매출이 3년째 해마다 {성장:.0f}%씩 늘고 있습니다")
    이익률 = row.get("영업이익률%")
    if pd.notna(이익률) and 이익률 >= 10:
        말.append(f"100원 팔면 {이익률:.0f}원 남깁니다 (제조업 평균보다 높은 편)")
    부채 = row.get("부채비율%")
    if pd.notna(부채) and 부채 <= 50:
        말.append(f"빚이 자기 돈의 {부채:.0f}%뿐입니다 (아주 안전한 편)")
    elif pd.notna(부채) and 부채 <= 100:
        말.append(f"빚이 자기 돈보다 적습니다 ({부채:.0f}%)")
    현금 = row.get("현금전환배수")
    if pd.notna(현금) and 현금 >= 0.8:
        말.append("장부에 적힌 이익이 실제 현금으로 들어옵니다")
    pbr = row.get("PBR")
    if pd.notna(pbr) and pbr < 1:
        말.append(f"회사가 가진 재산보다 {(1 - pbr) * 100:.0f}% 싸게 거래됩니다")
    per = row.get("PER")
    if pd.notna(per) and per <= 10:
        말.append(f"지금 이익이면 {per:.0f}년이면 원금을 뽑습니다")
    위치 = row.get("1년위치%")
    if pd.notna(위치) and 위치 <= 30:
        말.append(f"최근 1년 가격 범위에서 아래쪽({위치:.0f}%)에 있습니다")
    return 말


def worry_points(row) -> list[str]:
    """걸리는 점. 여기가 사장님이 직접 확인하셔야 할 자리입니다."""
    말: list[str] = []
    성장 = row.get("매출성장%")
    if pd.notna(성장) and 성장 < 0:
        말.append(f"매출이 해마다 {abs(성장):.0f}%씩 줄고 있습니다 — 왜 줄까요")
    이익률 = row.get("영업이익률%")
    if pd.notna(이익률) and 이익률 < 5:
        말.append(f"100원 팔아 {이익률:.0f}원밖에 못 남깁니다 — 경쟁이 심한 곳일 수 있습니다")
    부채 = row.get("부채비율%")
    if pd.notna(부채) and 부채 > 150:
        말.append(f"빚이 자기 돈의 {부채:.0f}%입니다 — 이자 부담을 확인하십시오")
    현금 = row.get("현금전환배수")
    if pd.notna(현금) and 현금 < 0.5:
        말.append("장부 이익이 현금으로 안 들어오고 있습니다 — "
                 "물건은 팔았는데 돈을 못 받았을 수 있습니다")
    per = row.get("PER")
    영업per = row.get("영업PER")
    if pd.notna(per) and pd.notna(영업per) and 영업per > per * 2:
        말.append(f"PER {per:.0f}배는 싸 보이지만 본업만 보면 {영업per:.0f}배입니다 — "
                 "일회성 이익이 섞였을 수 있습니다")
    위치 = row.get("1년위치%")
    if pd.notna(위치) and 위치 >= 70:
        말.append(f"최근 1년 중 위쪽({위치:.0f}%)입니다 — 이미 오른 뒤일 수 있습니다")
    if not 말:
        말.append("숫자에서 걸리는 점은 없습니다. "
                 "다만 숫자로 안 보이는 것이 더 많습니다")
    return 말


def next_steps(row) -> list[str]:
    """그래서 무엇을 하면 되는가. 순서대로."""
    code = str(row.get("code", ""))
    이름 = str(row.get("name", ""))
    단계 = [
        f"① 이 회사가 뭘 파는 회사인지 보십시오 — "
        f"dart.fss.or.kr 에서 «{이름}» 검색 → 사업보고서 → 'II. 사업의 내용'",
        f"② 5년 실적과 최근 공시를 한 화면으로 보십시오 — "
        f"python -m src.cli dart-dashboard --code {code}",
    ]
    부채 = row.get("부채비율%")
    if pd.notna(부채) and 부채 > 150:
        단계.append("③ 빚이 많으니 이자를 감당하는지 보십시오 — "
                   "대시보드의 '현금흐름' 탭에서 본업 현금이 플러스인지")
    현금 = row.get("현금전환배수")
    if pd.notna(현금) and 현금 < 0.5:
        단계.append("③ 이익이 현금으로 안 들어오니, 매출채권·재고가 늘었는지 "
                   "사업보고서 재무제표 주석에서 보십시오")
    단계.append(
        f"마지막. 사도 되겠다 싶으면 **사지 마시고 먼저 기록만** 하십시오 — "
        f"python -m src.cli journal-add --code {code} --name {이름} "
        f"--conviction 중 --why \"왜 그렇게 보는지\"")
    return 단계


def _pick_card(row, star: bool = False, risks: list | None = None) -> str:
    좋은것 = "".join(f"<li>{_esc(x)}</li>" for x in good_points(row)) or "<li>—</li>"
    걸리는것 = "".join(f"<li>{_esc(x)}</li>" for x in worry_points(row))
    단계 = "".join(f"<li>{_esc(x)}</li>" for x in next_steps(row))

    # 최근 공시에서 걸린 것. 배당·자사주 같은 호재는 여기 안 옵니다.
    공시칸 = ""
    if risks:
        줄 = "".join(
            f"<li><b>{_esc(r.get('label', ''))}</b> "
            f"{_esc(str(r.get('rcept_dt', ''))[:8])} — "
            f"{_esc(r.get('report_nm', ''))}<br>"
            f"<span class=\"w\">{_esc(r.get('why', ''))}</span></li>"
            for r in risks[:3]
        )
        위험있음 = any(r.get("severity") == "위험" for r in risks)
        제목 = ("🔴 최근 공시에 이런 것이 있습니다"
              if 위험있음 else "🟡 최근 공시에 확인할 것이 있습니다")
        공시칸 = (f'<div class="risk{"" if 위험있음 else " check"}">'
                f'<div class="t">{제목}</div><ul>{줄}</ul></div>')

    # 얼마에 사면 목표·무효선이 얼마인지. 예측이 아니라 산수입니다.
    선 = price_levels(row)
    가격칸 = ""
    if 선:
        칸들 = [
            ("지금 값", 선["현재가"], ""),
            (f"목표 (+{TARGET_PCT:g}%)", 선["목표가"], "여기 닿으면 목표 달성으로 기록"),
            (f"무효선 ({INVALID_PCT:g}%)", 선["무효선"], "여기 닿으면 판단이 틀렸던 것"),
        ]
        if "재산값" in 선:
            칸들.append(("회사 재산만큼의 값", 선["재산값"],
                       "이 아래면 재산보다 싸게 사는 셈"))
        if "1년최저" in 선 and "1년최고" in 선:
            칸들.append(("최근 1년 범위", None,
                       f"{선['1년최저']:,.0f} ~ {선['1년최고']:,.0f}원"))
        줄 = "".join(
            f'<div class="lv"><div class="n">'
            f'{"" if 값 is None else format(값, ",.0f") + "원"}</div>'
            f'<div class="l">{_esc(이름)}</div>'
            f'<div class="w">{_esc(설명)}</div></div>'
            for 이름, 값, 설명 in 칸들
        )
        가격칸 = (f'<div class="levels"><div class="t">💰 얼마에 사면 어떻게 되나</div>'
                f'<div class="lvs">{줄}</div>'
                f'<p class="w">위 값은 지금 가격에 사장님이 정하신 +{TARGET_PCT:g}% / '
                f'{INVALID_PCT:g}% 를 곱한 것입니다. '
                f'<b>오른다는 예측이 아닙니다.</b></p></div>')

    기업 = row.get("기업점수")
    가격 = row.get("가격점수")
    기업폭 = 0 if pd.isna(기업) else max(0, min(100, float(기업)))
    가격폭 = 0 if pd.isna(가격) else max(0, min(100, float(가격)))
    return f"""
<div class="pick{' star' if star else ''}">
  <h3>{_esc(row.get('name', ''))}<span class="code">{_esc(row['code'])}</span></h3>
  <div class="bars">
    <div class="axis">
      <div class="top"><span>회사가 튼튼한가</span><b>{_cell(row,'기업점수','.0f')}점</b></div>
      <div class="track"><div class="fill b" style="width:{기업폭:.0f}%"></div></div>
    </div>
    <div class="axis">
      <div class="top"><span>지금 값이 싼가</span><b>{_cell(row,'가격점수','.0f')}점</b></div>
      <div class="track"><div class="fill p" style="width:{가격폭:.0f}%"></div></div>
    </div>
  </div>
  <p class="plain">{_esc(one_line(row))}</p>
  <div class="points">
    <div class="good"><div class="t">✅ 좋은 점</div><ul>{좋은것}</ul></div>
    <div class="bad"><div class="t">⚠️ 걸리는 점</div><ul>{걸리는것}</ul></div>
  </div>
  {가격칸}
  {공시칸}

  <div class="steps"><div class="t">🔍 그래서 뭘 하면 되나</div>
    <ol>{단계}</ol></div>
  <details><summary>숫자로 보기</summary>
  <div class="facts">
    <span>매출이 늘고 있나 <b>{_cell(row,'매출성장%','.0f','%')}</b>
      <i>해마다</i></span>
    <span>100원 팔면 얼마 남나 <b>{_cell(row,'영업이익률%','.0f','원')}</b></span>
    <span>빚이 얼마나 <b>{_cell(row,'부채비율%','.0f','%')}</b>
      <i>자기 돈 대비</i></span>
    <span>장부 이익이 진짜 현금인가 <b>{_cell(row,'현금전환배수','.2f')}</b>
      <i>1이면 딱 맞음</i></span>
    <span>재산의 몇 배 값 <b>{_cell(row,'PBR','.2f')}</b>
      <i>PBR</i></span>
    <span>원금 회수 <b>{_cell(row,'PER','.0f','년')}</b>
      <i>PER</i></span>
    <span>최근 1년에서 <b>{_cell(row,'1년위치%','.0f','%')}</b>
      <i>0=최저 100=최고</i></span>
  </div>
  </details>
</div>"""


def render_html(evaluated: pd.DataFrame, top: int = 10,
                risks: dict | None = None) -> str:
    """브라우저로 여는 한 장. 별표 목록을 맨 위에 크게 놓습니다."""
    세기 = evaluated["판정"].value_counts() if not evaluated.empty else {}
    좁힌것 = shortlist(evaluated)
    후보 = (evaluated[evaluated["판정"] == "후보"]
           .sort_values(["기업점수", "가격점수"], ascending=False)
           if not evaluated.empty else pd.DataFrame())

    칸 = "".join(
        f'<div class="count"><div class="n">{int(세기.get(이름, 0)):,}</div>'
        f'<div class="l">{_esc(이름)}</div></div>'
        for 이름 in ("후보", "비쌈", "함정?", "제외", "판단보류")
        if int(세기.get(이름, 0))
    )

    if 좁힌것.empty:
        고른것 = ('<p class="note">양쪽 다 높은 종목이 없습니다. '
                "두 축을 다 만족하는 것은 원래 드뭅니다. '비쌈' 이 많으면 시장이 "
                "비싼 것이고, '함정?' 이 많으면 싼 것들이 다 이유가 있는 것입니다.</p>")
    else:
        risks = risks or {}
        고른것 = "".join(
            _pick_card(r, star=True, risks=risks.get(str(r["code"])))
            for _, r in 좁힌것.head(top).iterrows())

    나머지 = 후보[~후보["code"].isin(좁힌것["code"])] if not 좁힌것.empty else 후보
    줄 = "".join(
        "<tr>"
        f"<td>{_esc(r.get('name',''))}</td><td>{_esc(r['code'])}</td>"
        f"<td>{_cell(r,'기업점수','.0f')}</td><td>{_cell(r,'가격점수','.0f')}</td>"
        f"<td>{_cell(r,'매출성장%','.0f','%')}</td>"
        f"<td>{_cell(r,'영업이익률%','.0f','%')}</td>"
        f"<td>{_cell(r,'부채비율%','.0f','%')}</td>"
        f"<td>{_cell(r,'PBR','.2f')}</td><td>{_cell(r,'PER','.1f')}</td>"
        f"<td>{_cell(r,'1년위치%','.0f','%')}</td></tr>"
        for _, r in 나머지.head(60).iterrows()
    )

    규칙칸 = "".join(
        f'<div class="rule"><div class="t">{i}. {_esc(제목)}</div>'
        f'<p>{_esc(설명)}</p>'
        f'<div class="src">근거 — {_esc(근거)}</div></div>'
        for i, (제목, 설명, 근거) in enumerate(BUY_RULES, 1)
    )

    from datetime import datetime
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>종목 선별 — 기업이 좋은가 · 값이 괜찮은가</title>
<style>{HTML_STYLE}</style></head><body><div class="wrap">
<h1>종목 선별</h1>
<div class="sub">{datetime.now():%Y-%m-%d %H:%M} 기준 ·
전체 {len(evaluated):,}종목 · 출처 DART 사업보고서 + FinanceDataReader</div>

<div class="counts">{칸}</div>

<h2>★ 양쪽 다 높은 것</h2>
<p class="note">기업 {STRICT_BUSINESS}점 이상 · 가격 {STRICT_PRICE}점 이상.
여기부터 하나씩 열어 보십시오.</p>
{고른것}

<h2>샀더니 떨어지는 것을 줄이려면</h2>
<p class="note">예측이 아닙니다. 코스닥 5년치를 돌려서 잰 숫자에서
나온 규칙입니다. 근거가 되는 표본을 같이 적어 두었습니다.</p>
{규칙칸}

<h2>그다음 후보</h2>
<p class="note">합격선은 넘었지만 한쪽이 조금 모자란 것들입니다.</p>
<div class="scroll"><table>
<thead><tr><th>종목명</th><th>코드</th><th>기업</th><th>가격</th>
<th>매출성장</th><th>이익률</th><th>부채</th><th>PBR</th><th>PER</th>
<th>1년위치</th></tr></thead><tbody>{줄}</tbody></table></div>

<div class="foot">
두 축을 따로 봅니다. 좋은 기업도 너무 비싸게 사면 오래 손실을 보고,
싼 주식도 기업이 나쁘면 계속 싸집니다. 점수를 하나로 합치면 이 둘이
섞여 무엇이 문제인지 알 수 없게 됩니다.<br>
⚠️ 이 점수가 수익을 예측한다는 근거는 아직 없습니다. 전에 만든 점수
체계는 상위 종목이 오히려 더 나빴습니다(PF 0.779 → 0.626).
순위를 매기는 도구일 뿐입니다.<br>
<b>이 화면은 매수·매도를 판단하지 않습니다.</b> 확인해 볼 거리를 모아
놓은 것입니다. 하나씩 열어 보십시오 —
<code>python -m src.cli dart-dashboard --code 종목코드</code>
</div>
</div></body></html>"""
