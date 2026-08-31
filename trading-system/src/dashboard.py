"""기업분석 화면 — 받아온 사실만으로 만든 한 장.

증권앱처럼 위에서 아래로 읽히는 화면을 HTML 한 파일로 만듭니다.
브라우저로 열면 되고, 인터넷 없이도 열립니다.

지키는 것 세 가지.

  1. 여기 적힌 숫자는 전부 DART 공시와 시세에서 온 것입니다.
     계산식은 화면에 같이 적습니다. 어디서 나온 값인지 알아야
     틀렸을 때 찾아낼 수 있습니다.
  2. 없는 것은 '확인 어려움' 이라고 적고 비웁니다. 사업부별 매출,
     증권사 추정치, 시장점유율은 국내 무료 자료로 확보되지 않습니다.
     비슷하게 지어내면 화면만 그럴듯해지고 판단은 망가집니다.
  3. 사실과 해석을 갈라 적습니다. 해석은 계산으로 곧장 나오는
     것만 적고, 매수·매도는 말하지 않습니다.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MISSING = "확인 어려움"


def _fmt_money(value: float) -> str:
    if value is None or pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    size = abs(float(value))
    if size >= 1e12:
        return f"{sign}{size / 1e12:,.2f}조"
    if size >= 1e8:
        return f"{sign}{size / 1e8:,.0f}억"
    return f"{sign}{size:,.0f}"


def _fmt(value: float, spec: str = ",.2f", suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    return format(float(value), spec) + suffix


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


# ─────────────────────────── 담아 나르는 것 ───────────────────────────

@dataclass
class Snapshot:
    """화면 한 장을 그리는 데 필요한 사실 전부."""
    code: str
    name: str
    market: str = ""
    price: float = float("nan")
    price_date: str = ""
    change_pct: float = float("nan")
    marcap: float = float("nan")
    high_52w: float = float("nan")
    low_52w: float = float("nan")
    trend: pd.DataFrame = field(default_factory=pd.DataFrame)      # 연도별 주요계정
    ratios: pd.DataFrame = field(default_factory=pd.DataFrame)     # 연도별 비율
    cash: pd.DataFrame = field(default_factory=pd.DataFrame)       # 연도별 현금흐름
    events: pd.DataFrame = field(default_factory=pd.DataFrame)     # 눈여겨볼 공시
    notes: list[str] = field(default_factory=list)                 # 재무에서 읽히는 사실
    filing_count: int = 0
    window_days: int = 365
    corp_code: str = ""
    fetched_at: str = ""

    # ── 계산되는 값들 ──
    @property
    def latest_year(self) -> int | None:
        return None if self.trend.empty else int(self.trend.index[-1])

    def _latest(self, column: str) -> float:
        if self.trend.empty or column not in self.trend.columns:
            return float("nan")
        return float(self.trend[column].iloc[-1])

    @property
    def per(self) -> float:
        이익 = self._latest("당기순이익")
        if pd.isna(self.marcap) or pd.isna(이익) or 이익 <= 0:
            return float("nan")
        return self.marcap / 이익

    @property
    def pbr(self) -> float:
        자본 = self._latest("자본총계")
        if pd.isna(self.marcap) or pd.isna(자본) or 자본 <= 0:
            return float("nan")
        return self.marcap / 자본

    @property
    def roe(self) -> float:
        이익, 자본 = self._latest("당기순이익"), self._latest("자본총계")
        if pd.isna(이익) or pd.isna(자본) or 자본 <= 0:
            return float("nan")
        return 이익 / 자본 * 100.0

    @property
    def position_52w(self) -> float:
        """52주 저점(0) ~ 고점(100) 사이 어디쯤인가."""
        if any(pd.isna(v) for v in (self.price, self.high_52w, self.low_52w)):
            return float("nan")
        span = self.high_52w - self.low_52w
        return float("nan") if span <= 0 else (self.price - self.low_52w) / span * 100.0


# ─────────────────────────── 10초 요약 ───────────────────────────
# 문장을 지어내지 않습니다. 계산된 값에서 곧장 나오는 것만 잇습니다.

def ten_second(snap: Snapshot) -> list[str]:
    말: list[str] = []
    if snap.trend.empty:
        return ["재무 자료를 받지 못했습니다. 신규 상장이거나 공시가 아직 없습니다."]

    매출 = snap.trend.get("매출액")
    if 매출 is not None and len(매출.dropna()) >= 2:
        변화 = 매출.iloc[-1] / 매출.iloc[-2] - 1.0
        방향 = "늘었습니다" if 변화 > 0 else "줄었습니다"
        말.append(f"{snap.latest_year}년 매출은 {_fmt_money(매출.iloc[-1])}으로 "
                  f"전년 대비 {abs(변화) * 100:.1f}% {방향}.")

    영업 = snap.trend.get("영업이익")
    if 영업 is not None and pd.notna(영업.iloc[-1]):
        if 영업.iloc[-1] < 0:
            말.append(f"영업이익은 {_fmt_money(영업.iloc[-1])}으로 적자입니다.")
        elif 매출 is not None and pd.notna(매출.iloc[-1]) and 매출.iloc[-1] > 0:
            말.append(f"영업이익은 {_fmt_money(영업.iloc[-1])}, "
                      f"영업이익률 {영업.iloc[-1] / 매출.iloc[-1] * 100:.1f}%입니다.")

    if pd.notna(snap.pbr):
        말.append(f"주가는 회사 순재산의 {snap.pbr:.2f}배에 거래되고 있습니다"
                  + (f" (PER {snap.per:.1f}배)." if pd.notna(snap.per) else "."))

    if pd.notna(snap.position_52w):
        말.append(f"현재가는 최근 1년 최저가와 최고가 사이에서 "
                  f"{snap.position_52w:.0f}% 지점에 있습니다.")

    높음 = snap.events[snap.events["severity"] == "높음"] if not snap.events.empty else None
    if 높음 is not None and not 높음.empty:
        말.append(f"최근 {snap.window_days}일 공시 중 눈여겨볼 것이 "
                  f"{len(높음)}건 있습니다 (아래 공시 탭).")
    return 말


# ─────────────────────────── 그림 ───────────────────────────
# 라이브러리를 쓰지 않습니다. 인터넷 없이 열려야 하고, 막대 몇 개에
# 외부 스크립트를 불러올 이유가 없습니다.

def bar_chart(series: pd.Series, label: str, money: bool = True) -> str:
    values = series.dropna()
    if values.empty:
        return f'<p class="missing">{_esc(label)}: {MISSING}</p>'

    가장큰것 = max(abs(float(v)) for v in values) or 1.0
    막대 = []
    for year, value in values.items():
        높이 = abs(float(value)) / 가장큰것 * 100.0
        음수 = float(value) < 0
        보임 = _fmt_money(value) if money else _fmt(value, ",.1f", "%")
        막대.append(
            f'<div class="bar-col">'
            f'<div class="bar-val">{_esc(보임)}</div>'
            f'<div class="bar-track"><div class="bar-fill{" neg" if 음수 else ""}"'
            f' style="height:{높이:.1f}%"></div></div>'
            f'<div class="bar-year">{_esc(year)}</div>'
            f'</div>'
        )
    return f'<div class="bars">{"".join(막대)}</div>'


def position_bar(snap: Snapshot) -> str:
    위치 = snap.position_52w
    if pd.isna(위치):
        return f'<p class="missing">최근 1년 가격 범위: {MISSING}</p>'
    return (
        '<div class="range">'
        f'<div class="range-ends"><span>최저 {_fmt(snap.low_52w, ",.0f")}원</span>'
        f'<span>최고 {_fmt(snap.high_52w, ",.0f")}원</span></div>'
        '<div class="range-track">'
        f'<div class="range-dot" style="left:{max(0, min(100, 위치)):.1f}%"></div>'
        '</div>'
        f'<div class="range-note">지금은 {위치:.0f}% 지점</div>'
        '</div>'
    )


def _table(frame: pd.DataFrame, money_columns: tuple[str, ...] = ()) -> str:
    if frame.empty:
        return f'<p class="missing">{MISSING}</p>'
    머리 = "".join(f"<th>{_esc(c)}</th>" for c in frame.columns)
    줄 = []
    for index, row in frame.iterrows():
        칸 = []
        for column in frame.columns:
            값 = row[column]
            if column in money_columns:
                칸.append(f"<td>{_esc(_fmt_money(값))}</td>")
            elif isinstance(값, (int, float, np.floating)):
                칸.append(f"<td>{_esc(_fmt(값, ',.1f'))}</td>")
            else:
                칸.append(f"<td>{_esc(값)}</td>")
        줄.append(f"<tr><th scope=\"row\">{_esc(index)}</th>{''.join(칸)}</tr>")
    return (f'<div class="scroll"><table><thead><tr><th></th>{머리}</tr></thead>'
            f'<tbody>{"".join(줄)}</tbody></table></div>')


# ─────────────────────────── 화면 ───────────────────────────

STYLE = """
:root{--ink:#1a1a1a;--dim:#6b7280;--line:#eceef1;--bg:#fff;--soft:#f7f8fa;
--up:#e5484d;--down:#2f6df6;--mark:#111}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.65 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 2px;letter-spacing:-.02em}
h2{font-size:19px;margin:38px 0 12px;letter-spacing:-.01em}
h3{font-size:15px;margin:22px 0 6px;color:var(--dim);font-weight:600}
p{margin:8px 0}
.sub{color:var(--dim);font-size:13px}
.price{font-size:40px;font-weight:700;letter-spacing:-.03em;margin:14px 0 2px}
.meta{color:var(--dim);font-size:13px;margin-top:10px;line-height:1.9}
.meta b{color:var(--ink);font-weight:600}
.summary{background:var(--soft);border-radius:14px;padding:18px 20px;margin:18px 0}
.summary p{margin:6px 0}
.keys{display:flex;flex-wrap:wrap;gap:26px 34px;margin:16px 0 6px}
.key{min-width:120px}
.key .n{font-size:24px;font-weight:700;letter-spacing:-.02em}
.key .l{color:var(--dim);font-size:12.5px;margin-top:2px}
.tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);
margin:30px 0 0;padding-bottom:0}
.tab{appearance:none;background:none;border:0;padding:11px 13px;font:inherit;
font-size:14px;color:var(--dim);cursor:pointer;border-bottom:2px solid transparent;
white-space:nowrap}
.tab[aria-selected="true"]{color:var(--ink);font-weight:600;border-bottom-color:var(--mark)}
.panel{padding-top:6px}
.bars{display:flex;align-items:flex-end;gap:10px;height:210px;margin:14px 0 6px}
.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;height:100%}
.bar-val{font-size:11.5px;color:var(--dim);margin-bottom:6px;white-space:nowrap}
.bar-track{flex:1;width:100%;display:flex;align-items:flex-end}
.bar-fill{width:100%;background:var(--mark);border-radius:5px 5px 0 0;min-height:2px}
.bar-fill.neg{background:var(--up)}
.bar-year{font-size:12px;color:var(--dim);margin-top:8px}
.range{margin:14px 0 4px}
.range-ends{display:flex;justify-content:space-between;font-size:12.5px;color:var(--dim)}
.range-track{position:relative;height:5px;background:var(--line);border-radius:3px;margin:8px 0}
.range-dot{position:absolute;top:-4px;width:13px;height:13px;border-radius:50%;
background:var(--mark);transform:translateX(-50%)}
.range-note{font-size:12.5px;color:var(--dim);text-align:center}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:10px 0}
th,td{padding:9px 10px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap}
thead th{color:var(--dim);font-weight:600;font-size:12.5px}
tbody th{text-align:left;font-weight:600}
.scroll{overflow-x:auto}
.missing{color:var(--dim);font-size:13.5px;font-style:normal}
.fact,.view{border-left:3px solid var(--line);padding:2px 0 2px 14px;margin:14px 0}
.fact{border-left-color:var(--mark)}
.view{border-left-color:#c8ccd2}
.fact>.tag,.view>.tag{display:block;font-size:12px;color:var(--dim);
font-weight:600;margin-bottom:4px}
ul{padding-left:19px;margin:8px 0}li{margin:5px 0}
.ev{display:flex;gap:10px;padding:11px 0;border-bottom:1px solid var(--line)}
.ev .d{color:var(--dim);font-size:12.5px;min-width:78px}
.ev .t{flex:1;font-size:14px}
.ev .w{color:var(--dim);font-size:12.5px;margin-top:3px}
.sev{font-size:11.5px;padding:1px 7px;border-radius:20px;background:var(--soft);
color:var(--dim);align-self:flex-start;white-space:nowrap}
.sev.hi{background:#fdecec;color:var(--up)}
.foot{margin-top:52px;padding-top:18px;border-top:1px solid var(--line);
color:var(--dim);font-size:12.5px;line-height:1.8}
@media (max-width:520px){.price{font-size:33px}.keys{gap:20px 24px}}
"""

SCRIPT = """
document.querySelectorAll('.tab').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(b){
      b.setAttribute('aria-selected', String(b === btn));
    });
    document.querySelectorAll('.panel').forEach(function(p){
      p.hidden = (p.id !== btn.dataset.panel);
    });
  });
});
"""


def _fact(title: str, body: str) -> str:
    return f'<div class="fact"><span class="tag">확인된 사실</span><b>{_esc(title)}</b>{body}</div>'


def _view(body: str) -> str:
    return f'<div class="view"><span class="tag">계산에서 바로 나오는 해석</span>{body}</div>'


def _panel_overview(snap: Snapshot) -> str:
    부분 = ["<h2>이 회사는 무엇으로 돈을 버나?</h2>"]
    부분.append(
        f'<p class="missing">사업부별 매출 구성: {MISSING} — 국내 사업보고서는 '
        "사업부 구분 형식이 회사마다 달라, 자동으로 읽어오면 틀린 숫자가 "
        "나옵니다. 원문에서 직접 보셔야 합니다.</p>"
    )
    부분.append(f'<p class="sub">→ dart.fss.or.kr 에서 «{_esc(snap.name)}» 검색 → '
                "사업보고서 → 'II. 사업의 내용'</p>")

    부분.append("<h2>재무제표에서 바로 읽히는 것</h2>")
    if snap.notes:
        부분.append(_fact("규칙에 걸린 항목",
                         "<ul>" + "".join(f"<li>{_esc(n)}</li>" for n in snap.notes) + "</ul>"))
    else:
        부분.append(_fact("규칙에 걸린 항목", "<p>없습니다.</p>"))

    부분.append("<h2>최근 1년 가격 범위</h2>")
    부분.append(position_bar(snap))
    return "".join(부분)


def _panel_earnings(snap: Snapshot) -> str:
    if snap.trend.empty:
        return f'<h2>실적</h2><p class="missing">재무 자료 {MISSING}</p>'

    부분 = ["<h2>매출은 늘고 있나?</h2>",
            bar_chart(snap.trend.get("매출액", pd.Series(dtype=float)), "매출액")]

    매출 = snap.trend.get("매출액")
    if 매출 is not None and len(매출.dropna()) >= 2:
        처음, 끝 = 매출.dropna().iloc[0], 매출.dropna().iloc[-1]
        해 = len(매출.dropna()) - 1
        연평균 = ((끝 / 처음) ** (1 / 해) - 1) * 100 if 처음 > 0 and 해 > 0 else float("nan")
        부분.append(_view(f"<p>{해}년 동안 매출이 {_fmt_money(처음)} → {_fmt_money(끝)} "
                         f"으로 바뀌었습니다. 연평균 성장률 {_fmt(연평균, '.1f', '%')}.</p>"))

    부분.append("<h2>이익도 같이 늘고 있나?</h2>")
    부분.append(bar_chart(snap.trend.get("영업이익", pd.Series(dtype=float)), "영업이익"))

    부분.append("<h2>예전보다 효율적으로 벌고 있나?</h2>")
    if not snap.ratios.empty and "영업이익률%" in snap.ratios:
        부분.append(bar_chart(snap.ratios["영업이익률%"], "영업이익률", money=False))
    else:
        부분.append(f'<p class="missing">영업이익률: {MISSING}</p>')

    부분.append("<h3>자세한 실적</h3>")
    부분.append(_table(snap.trend, money_columns=tuple(snap.trend.columns)))
    if not snap.ratios.empty:
        부분.append(_table(snap.ratios.round(1)))
    return "".join(부분)


def _panel_cash(snap: Snapshot) -> str:
    부분 = ["<h2>장부상 이익 말고 실제 현금도 벌고 있나?</h2>"]
    if snap.cash.empty:
        부분.append(f'<p class="missing">현금흐름표: {MISSING} — 이 회사의 '
                    "현금흐름표를 DART 에서 받지 못했습니다.</p>")
        return "".join(부분)

    최근 = snap.cash.iloc[-1]
    부분.append('<div class="keys">')
    for 이름, 설명 in (("영업활동현금흐름", "본업에서 들어온 현금"),
                    ("설비투자", "설비·인프라에 쓴 돈"),
                    ("잉여현금흐름", "투자 후 남은 현금")):
        부분.append(f'<div class="key"><div class="n">{_esc(_fmt_money(최근.get(이름)))}</div>'
                    f'<div class="l">{_esc(설명)}<br><span style="font-size:11.5px">'
                    f'{_esc(이름)}</span></div></div>')
    부분.append("</div>")

    부분.append("<h3>본업에서 들어온 현금</h3>")
    부분.append(bar_chart(snap.cash["영업활동현금흐름"], "영업활동현금흐름"))
    부분.append("<h3>투자 후 남은 현금</h3>")
    부분.append(bar_chart(snap.cash["잉여현금흐름"], "잉여현금흐름"))

    영업, 순이익 = 최근.get("영업활동현금흐름"), None
    if not snap.trend.empty and "당기순이익" in snap.trend:
        순이익 = snap.trend["당기순이익"].iloc[-1]
    if pd.notna(영업) and 순이익 is not None and pd.notna(순이익):
        if 순이익 > 0 and 영업 < 순이익 * 0.5:
            부분.append(_view("<p>장부상 순이익보다 실제로 들어온 현금이 "
                             "절반 이하입니다. 이익이 현금으로 바뀌지 않고 있다는 뜻이라, "
                             "매출채권·재고가 늘었는지 원문에서 보셔야 합니다.</p>"))
        elif 영업 > 0 and 순이익 <= 0:
            부분.append(_view("<p>장부상으로는 적자인데 본업에서 현금은 들어오고 "
                             "있습니다. 감가상각 같은 현금이 나가지 않는 비용이 큰 경우입니다.</p>"))
    부분.append(_table(snap.cash, money_columns=tuple(snap.cash.columns)))
    return "".join(부분)


def _panel_value(snap: Snapshot) -> str:
    부분 = ["<h2>지금 주가는 비싼 편일까?</h2>"]
    부분.append('<div class="keys">')
    for 이름, 값, 설명 in (
        ("PBR", _fmt(snap.pbr, ".2f", "배"),
         "회사 순재산의 몇 배에 거래되는지"),
        ("PER", _fmt(snap.per, ".1f", "배"),
         "지금 이익이 이어지면 원금 회수에 몇 년"),
        ("ROE", _fmt(snap.roe, ".1f", "%"),
         "주주 돈으로 얼마나 벌었는지"),
    ):
        부분.append(f'<div class="key"><div class="n">{_esc(값)}</div>'
                    f'<div class="l"><b>{_esc(이름)}</b> · {_esc(설명)}</div></div>')
    부분.append("</div>")

    부분.append(_fact("계산식", "<ul>"
                     f"<li>PBR = 시가총액 {_fmt_money(snap.marcap)} ÷ "
                     f"자본총계 ({snap.latest_year}년)</li>"
                     f"<li>PER = 시가총액 ÷ 당기순이익 ({snap.latest_year}년)</li>"
                     f"<li>ROE = 당기순이익 ÷ 자본총계 × 100</li>"
                     "</ul>"))

    if pd.isna(snap.per):
        부분.append(_view("<p>당기순이익이 없거나 적자여서 PER 을 계산할 수 없습니다. "
                         "적자 회사는 PER 로 비싸다·싸다를 말할 수 없습니다.</p>"))

    부분.append(f'<p class="missing">Forward PER · PEG · EV/EBITDA: {MISSING} — '
                "증권사 이익 추정치가 필요한데 국내는 무료로 안정적인 경로가 없습니다. "
                "없는 값을 지어내지 않습니다.</p>")
    부분.append(f'<p class="missing">동종업계 비교: {MISSING} — 업종 분류가 같아도 '
                "사업 내용이 크게 달라, 자동으로 고른 '경쟁사' 는 오해를 부릅니다.</p>")
    return "".join(부분)


def _panel_events(snap: Snapshot) -> str:
    부분 = [f"<h2>최근 {snap.window_days}일 공시</h2>",
            f'<p class="sub">전체 {snap.filing_count:,}건 중 눈여겨볼 것만 골랐습니다.</p>']
    if snap.events.empty:
        부분.append('<p class="missing">규칙에 걸린 공시가 없습니다. '
                    "(공시가 없다는 뜻이 아니라 규칙에 걸린 게 없다는 뜻입니다)</p>")
    else:
        for _, row in snap.events.iterrows():
            높음 = row["severity"] == "높음"
            부분.append(
                f'<div class="ev"><div class="d">{_esc(row["rcept_dt"])}</div>'
                f'<div class="t">{_esc(row["report_nm"])}'
                f'<div class="w">{_esc(row["why"])}</div></div>'
                f'<span class="sev{" hi" if 높음 else ""}">{_esc(row["label"])}</span></div>'
            )
    부분.append('<p class="sub" style="margin-top:16px">공시 원문: '
                f'dart.fss.or.kr 에서 «{_esc(snap.name)}» 검색</p>')
    return "".join(부분)


def _panel_wrapup(snap: Snapshot) -> str:
    부분 = ["<h2>결국 무엇을 봐야 하나?</h2>"]
    부분.append(_view("<p>이 화면은 공시된 사실을 모아 보여줄 뿐, "
                     "사도 된다·팔아야 한다를 판단하지 않습니다. "
                     "여기 없는 것 — 사업 내용, 경쟁 구도, 앞으로의 계획 — 이 "
                     "실제 주가를 움직입니다. 그건 원문을 읽으셔야 합니다.</p>"))

    확인할것 = []
    if snap.notes:
        확인할것 += [f"{n} — 왜 그런지 사업보고서에서 확인" for n in snap.notes[:3]]
    if not snap.events.empty:
        높음 = snap.events[snap.events["severity"] == "높음"]
        for _, row in 높음.head(3).iterrows():
            확인할것.append(f"{row['rcept_dt']} {row['label']} 공시 원문 확인")
    if pd.notna(snap.position_52w) and snap.position_52w > 80:
        확인할것.append("현재가가 1년 범위의 위쪽에 있습니다 — 왜 올랐는지 확인")
    if pd.isna(snap.per):
        확인할것.append("적자 또는 순이익 미확인 — 언제 흑자로 돌아서는지 확인")
    if not 확인할것:
        확인할것.append("규칙에 걸린 항목이 없습니다. 사업 내용을 직접 보십시오.")

    부분.append("<h3>다음에 확인할 것</h3><ul>"
                + "".join(f"<li>{_esc(x)}</li>" for x in 확인할것) + "</ul>")

    부분.append("<h3>기록해 두기</h3>")
    부분.append('<p class="sub">사도 되겠다 싶으면 사지 마시고 먼저 기록만 하십시오. '
                "90일 뒤에 코스닥 지수 대비로 채점됩니다.</p>")
    부분.append(f'<pre class="sub" style="background:var(--soft);padding:12px;'
                f'border-radius:10px;overflow-x:auto">python -m src.cli journal-add '
                f'--code {_esc(snap.code)} --name {_esc(snap.name)} '
                f'--conviction 중 --why "왜 그렇게 보는지"</pre>')
    return "".join(부분)


TABS = (("overview", "개요"), ("earnings", "실적"), ("cash", "현금흐름"),
        ("value", "밸류에이션"), ("events", "공시"), ("wrapup", "한눈에"))


def render(snap: Snapshot) -> str:
    """화면 한 장을 HTML 로."""
    변화 = ""
    if pd.notna(snap.change_pct):
        방향 = "up" if snap.change_pct >= 0 else "down"
        변화 = (f' · <span style="color:var(--{방향})">'
                f'{snap.change_pct:+.2f}%</span>')

    요약 = "".join(f"<p>{_esc(line)}</p>" for line in ten_second(snap))

    핵심 = []
    if not snap.trend.empty:
        매출 = snap.trend.get("매출액")
        if 매출 is not None and len(매출.dropna()) >= 2:
            변화율 = (매출.iloc[-1] / 매출.iloc[-2] - 1) * 100
            핵심.append((f"{변화율:+.1f}%", f"매출 증가율 · {snap.latest_year}년"))
        if not snap.ratios.empty and "영업이익률%" in snap.ratios:
            핵심.append((_fmt(snap.ratios["영업이익률%"].iloc[-1], ".1f", "%"), "영업이익률"))
    핵심.append((_fmt(snap.pbr, ".2f", "배"), "PBR"))
    핵심.append((_fmt(snap.per, ".1f", "배"), "PER"))
    핵심.append((_fmt(snap.roe, ".1f", "%"), "ROE"))
    if not snap.cash.empty:
        핵심.append((_fmt_money(snap.cash["잉여현금흐름"].iloc[-1]), "투자 후 남은 현금"))

    키칸 = "".join(
        f'<div class="key"><div class="n">{_esc(v)}</div>'
        f'<div class="l">{_esc(l)}</div></div>' for v, l in 핵심[:6]
    )

    탭단추 = "".join(
        f'<button class="tab" data-panel="{i}" role="tab" '
        f'aria-selected="{"true" if n == 0 else "false"}">{_esc(t)}</button>'
        for n, (i, t) in enumerate(TABS)
    )
    본문 = {
        "overview": _panel_overview(snap), "earnings": _panel_earnings(snap),
        "cash": _panel_cash(snap), "value": _panel_value(snap),
        "events": _panel_events(snap), "wrapup": _panel_wrapup(snap),
    }
    패널 = "".join(
        f'<section class="panel" id="{i}"{"" if n == 0 else " hidden"}>{본문[i]}</section>'
        for n, (i, _) in enumerate(TABS)
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(snap.name)} ({_esc(snap.code)}) 기업분석</title>
<style>{STYLE}</style></head><body><div class="wrap">
<h1>{_esc(snap.name)}</h1>
<div class="sub">{_esc(snap.code)}{" · " + _esc(snap.market) if snap.market else ""}</div>
<div class="price">{_esc(_fmt(snap.price, ",.0f"))}원</div>
<div class="sub">{_esc(snap.price_date)} 종가{변화}</div>
<div class="meta">
시가총액 <b>{_esc(_fmt_money(snap.marcap))}</b> ·
최근 사업연도 <b>{_esc(snap.latest_year or "—")}</b> ·
DART 고유번호 <b>{_esc(snap.corp_code)}</b><br>
자료 기준 <b>{_esc(snap.fetched_at)}</b> · 출처 금융감독원 전자공시(opendart.fss.or.kr),
시세 FinanceDataReader
</div>
<h2>지금 {_esc(snap.name)}은</h2>
<div class="summary">{요약}</div>
<div class="keys">{키칸}</div>
<div class="tabs" role="tablist">{탭단추}</div>
{패널}
<div class="foot">
이 화면의 숫자는 전부 DART 공시와 시세에서 받아온 것입니다. 계산식은 밸류에이션 탭에
적어 두었습니다.<br>
'{MISSING}' 이라고 적힌 항목은 국내 무료 자료로 확보되지 않는 것입니다. 비슷하게
지어내지 않았습니다.<br>
공시는 결산 후 최대 90일 뒤에 올라옵니다. 오늘의 주가와는 시차가 큽니다.<br>
<b>이 화면은 매수·매도를 판단하지 않습니다.</b> 확인해 볼 거리를 모아 놓은 것입니다.
</div>
</div><script>{SCRIPT}</script></body></html>"""
