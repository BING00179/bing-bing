"""스캔 결과를 웹페이지로 만듭니다.

깃허브 서버가 스캔을 마치면 이 모듈이 HTML 을 만들어 저장소에
올리고, GitHub Pages 가 그것을 웹페이지로 서비스합니다. 폰이든
PC 든 주소만 열면 오늘 신호를 볼 수 있고, 컴퓨터를 켜둘 필요가
없습니다.

각 종목마다 "왜 뽑혔는지"를 실제 숫자로 남깁니다.
  · 5가지 조건 각각의 비교값과 통과 여부
  · 점수 네 항목의 계산 과정
  · 시가총액 · 업종 · PER · PBR
  · 최근 60일 주가 흐름과 이동평균선

기록은 stocks/history.json 에 날짜별로 쌓입니다.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

HISTORY_LIMIT = 60
SHOW_DAYS = 7
CHART_W, CHART_H = 280, 64


def _esc(value) -> str:
    return html.escape(str(value))


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_history(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries[-HISTORY_LIMIT:], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def build_entry(when: str, market_state, signals, top_n: int) -> dict:
    rows = []
    for i, s in enumerate(signals, 1):
        fund = s.fundamentals
        rows.append(
            {
                "rank": i,
                "code": s.code,
                "name": s.name,
                "price": s.price,
                "gap_pct": round(s.gap_pct, 2),
                "turnover": s.turnover,
                "score": s.score.total if s.score else None,
                "parts": asdict(s.score) if s.score else None,
                "checks": [asdict(c) for c in (s.checks or [])],
                "closes": [round(v, 2) for v in (s.closes or [])],
                "prev_high": s.prev_high,
                "prev_close": s.prev_close,
                "sma_slow": s.sma_slow,
                "sma_fast": s.sma_fast_v,
                "sma_mid": s.sma_mid_v,
                "open": s.open_price,
                "today_high": s.today_high,
                "fundamentals": asdict(fund) if is_dataclass(fund) else None,
                "anomaly": (
                    {
                        "level": s.anomaly.level,
                        "flags": [asdict(f) for f in s.anomaly.flags],
                    }
                    if s.anomaly is not None else None
                ),
                "supply": s.supply_summary,
                "size_label": getattr(fund, "size_label", ""),
                "market_cap_label": getattr(fund, "market_cap_label", ""),
                "recommended": i <= top_n,
            }
        )
    return {
        "when": when,
        "date": when.split()[0] if when else "",
        "market": asdict(market_state) if is_dataclass(market_state) else None,
        "signals": rows,
        "count": len(rows),
    }


STYLE = """
:root{
  --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --text:#12151a; --muted:#6b7280;
  --accent:#1f6feb; --green:#128a4a; --amber:#a86800; --red:#c02b2b;
  --bar:#dfe3e8; --shadow:0 1px 2px rgba(16,20,28,.06),0 4px 12px rgba(16,20,28,.05);
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --bg:#0f1216; --card:#171b21; --line:#252b34; --text:#e7ebf0; --muted:#9aa4b2;
  --accent:#5b9dff; --green:#3fbb7d; --amber:#e0a33c; --red:#f0736b;
  --bar:#2a313b; --shadow:0 1px 2px rgba(0,0,0,.4);
}}
:root[data-theme="dark"]{
  --bg:#0f1216; --card:#171b21; --line:#252b34; --text:#e7ebf0; --muted:#9aa4b2;
  --accent:#5b9dff; --green:#3fbb7d; --amber:#e0a33c; --red:#f0736b;
  --bar:#2a313b; --shadow:0 1px 2px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;
  -webkit-text-size-adjust:100%}
.wrap{max-width:840px;margin:0 auto;padding:20px 16px 64px}
header{margin:8px 0 20px}
h1{font-size:20px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:16px;margin-bottom:14px;box-shadow:var(--shadow)}
h2{font-size:14px;margin:24px 0 10px;color:var(--muted);font-weight:600}
.state{display:flex;align-items:center;gap:10px;font-weight:600;font-size:16px}
.state .dot{width:10px;height:10px;border-radius:50%;flex:0 0 auto}
.ok .dot{background:var(--green)} .warn .dot{background:var(--amber)} .bad .dot{background:var(--red)}
.ok{color:var(--green)} .warn{color:var(--amber)} .bad{color:var(--red)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(84px,1fr));gap:10px;margin-top:12px}
.metric{background:var(--bg);border-radius:10px;padding:9px 10px}
.metric .k{font-size:11px;color:var(--muted)}
.metric .v{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.pick{padding:15px 0;border-top:1px solid var(--line)}
.pick:first-of-type{border-top:0}
.top{display:flex;gap:12px;align-items:flex-start}
.no{flex:0 0 26px;height:26px;border-radius:8px;background:var(--accent);color:#fff;
  display:grid;place-items:center;font-size:13px;font-weight:700}
.pick.dim .no{background:var(--bar);color:var(--muted)}
.hd{flex:1;min-width:0}
.nm{font-weight:600}
.cd{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums;margin-left:6px}
.tags{margin-top:3px;display:flex;flex-wrap:wrap;gap:5px}
.tag{font-size:10px;background:var(--bg);border:1px solid var(--line);
  border-radius:5px;padding:1px 6px;color:var(--muted)}
.px{font-variant-numeric:tabular-nums;font-size:13px;color:var(--muted);margin-top:4px}
.sc{text-align:right;flex:0 0 auto}
.sc .n{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.sc .l{font-size:10px;color:var(--muted)}
.chart{margin-top:10px}
.chart svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:12px;font-size:10px;color:var(--muted);margin-top:3px}
.legend i{display:inline-block;width:10px;height:2px;vertical-align:middle;margin-right:3px}
.bars{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}
.bar .t{font-size:10px;color:var(--muted);margin-bottom:3px}
.bar .track{height:4px;background:var(--bar);border-radius:2px;overflow:hidden}
.bar .fill{height:100%;background:var(--accent);border-radius:2px}
details{margin-top:10px}
summary{cursor:pointer;font-size:12px;color:var(--accent);list-style:none;padding:5px 0}
summary::-webkit-details-marker{display:none}
summary::before{content:"\25b8  "}
details[open] summary::before{content:"\25be  "}
.why{margin-top:8px;border-top:1px solid var(--line);padding-top:10px}
.chk{display:flex;gap:9px;padding:7px 0;align-items:flex-start}
.chk .ic{flex:0 0 16px;font-size:12px}
.chk .lb{font-size:12px;font-weight:600}
.chk .dt{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;margin-top:1px;word-break:keep-all}
.chk .wy{font-size:11px;color:var(--muted);opacity:.8;margin-top:2px}
.pass{color:var(--green)} .fail{color:var(--red)}
.box{font-size:11px;color:var(--muted);margin-top:10px;background:var(--bg);
  border-radius:8px;padding:10px;line-height:1.8}
.box b{color:var(--text)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:11px;margin-top:4px}
.kv .k{color:var(--muted)}
.kv .v{font-variant-numeric:tabular-nums}
.empty{color:var(--muted);text-align:center;padding:22px 0}
.risk{margin-top:9px;border-radius:9px;padding:9px 11px;font-size:11px;line-height:1.7}
.risk.정상{background:color-mix(in srgb,var(--green) 8%,transparent);
  border:1px solid color-mix(in srgb,var(--green) 25%,transparent)}
.risk.주의{background:color-mix(in srgb,var(--amber) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--amber) 30%,transparent)}
.risk.경고{background:color-mix(in srgb,var(--red) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--red) 32%,transparent)}
.risk b{font-size:12px}
.risk .row{margin-top:5px}
.risk .bs{opacity:.75;font-size:10px}
.note{color:var(--muted);font-size:12px;line-height:1.7;margin-top:26px;
  border-top:1px solid var(--line);padding-top:16px}
.hist{display:flex;justify-content:space-between;gap:10px;padding:9px 0;
  border-bottom:1px solid var(--line);font-size:13px}
.hist:last-child{border-bottom:0}
.hist .d{color:var(--muted);font-variant-numeric:tabular-nums}
"""


def _sparkline(closes: list[float], sma_slow: float) -> str:
    """최근 종가 흐름과 200일선을 겹쳐 그립니다."""
    pts = [c for c in closes if c and c > 0]
    if len(pts) < 5:
        return ""

    lo, hi = min(pts), max(pts)
    if sma_slow > 0:
        lo, hi = min(lo, sma_slow), max(hi, sma_slow)
    span = (hi - lo) or 1.0
    pad = 4

    def y(v: float) -> float:
        return CHART_H - pad - (v - lo) / span * (CHART_H - pad * 2)

    step = CHART_W / max(len(pts) - 1, 1)
    line = " ".join(f"{i * step:.1f},{y(v):.1f}" for i, v in enumerate(pts))
    area = f"0,{CHART_H} {line} {CHART_W},{CHART_H}"

    ma_line = ""
    if sma_slow > 0:
        yy = y(sma_slow)
        ma_line = (
            f'<line x1="0" y1="{yy:.1f}" x2="{CHART_W}" y2="{yy:.1f}" '
            'stroke="var(--amber)" stroke-width="1" stroke-dasharray="3 3"/>'
        )

    rising = pts[-1] >= pts[0]
    color = "var(--green)" if rising else "var(--red)"
    return f"""<div class="chart">
<svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none" role="img"
     aria-label="최근 {len(pts)}일 주가 흐름">
  <polygon points="{area}" fill="{color}" opacity="0.10"/>
  {ma_line}
  <polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.6"
            stroke-linejoin="round" stroke-linecap="round"/>
</svg>
<div class="legend"><span><i style="background:{color}"></i>최근 {len(pts)}일 종가</span>
<span><i style="background:var(--amber)"></i>200일선</span></div>
</div>"""


def _market_card(market: dict | None) -> str:
    if not market:
        return ('<div class="card"><div class="state warn"><span class="dot"></span>'
                "시장 상태를 판정하지 못했습니다</div></div>")
    cls = {"정상": "ok", "주의": "warn", "위험": "bad"}.get(market["verdict"], "warn")
    reasons = market.get("reasons") or []
    reason_html = (f'<div class="sub" style="margin-top:8px">{_esc(", ".join(reasons))}</div>'
                   if reasons else "")
    blocked = ('<div class="sub" style="margin-top:6px">신호를 내보내지 않는 상태입니다.</div>'
               if not market.get("tradable", True) else "")
    return f"""<div class="card">
  <div class="state {cls}"><span class="dot"></span>시장 {_esc(market['verdict'])}</div>
  {reason_html}{blocked}
  <div class="metrics">
    <div class="metric"><div class="k">{_esc(market['index_name'])}</div>
      <div class="v">{market['close']:,.1f}</div></div>
    <div class="metric"><div class="k">200일선</div>
      <div class="v">{'위' if market['above_sma_slow'] else '아래'}</div></div>
    <div class="metric"><div class="k">고점대비</div>
      <div class="v">-{market['drawdown_pct']:.1f}%</div></div>
    <div class="metric"><div class="k">변동성</div>
      <div class="v">{market['volatility_pct']:.0f}%</div></div>
    <div class="metric"><div class="k">RSI</div>
      <div class="v">{market['rsi']:.0f}</div></div>
  </div>
</div>"""


def _company_box(row: dict) -> str:
    f = row.get("fundamentals") or {}
    if not f:
        return ""
    per = f.get("per")
    pbr = f.get("pbr")
    kv = ""
    if row.get("market_cap_label"):
        kv += f'<div class="k">시가총액</div><div class="v">{_esc(row["market_cap_label"])}</div>'
    if f.get("sector"):
        kv += f'<div class="k">업종</div><div class="v">{_esc(f["sector"])}</div>'
    kv += f'<div class="k">PER</div><div class="v">{per:,.1f}배</div>' if per else \
          '<div class="k">PER</div><div class="v">— (적자 또는 미집계)</div>'
    kv += f'<div class="k">PBR</div><div class="v">{pbr:,.2f}배</div>' if pbr else \
          '<div class="k">PBR</div><div class="v">—</div>'
    if f.get("shares"):
        kv += f'<div class="k">상장주식수</div><div class="v">{f["shares"]:,.0f}주</div>'
    return (f'<div class="box"><b>기업 정보</b><div class="kv">{kv}</div>'
            "<div style=\"margin-top:6px;opacity:.8\">PER·PBR 은 참고용입니다. "
            "이 전략은 추세추종이라 매수 판단에 쓰지 않습니다.</div></div>")


def _anomaly_box(row: dict, compact: bool = False) -> str:
    """평소와 다른 점. 시세조종 판정이 아니라 참고용 표시입니다."""
    a = row.get("anomaly")
    if not a:
        return ""
    level = a.get("level", "정상")
    flags = a.get("flags") or []
    shown = [f for f in flags if f.get("level") != "정상"] if compact else flags
    if compact and not shown:
        return ""

    icon = {"정상": "OK", "주의": "주의", "경고": "경고"}.get(level, level)
    rows = ""
    for f in shown:
        mark = {"정상": "·", "주의": "!", "경고": "!!"}.get(f.get("level"), "·")
        rows += (f'<div class="row"><b>{mark} {_esc(f.get("label"))}</b> '
                 f'{_esc(f.get("value"))}')
        if not compact:
            rows += f'<div class="bs">{_esc(f.get("basis"))}</div>'
        rows += "</div>"

    supply = row.get("supply")
    if supply and not compact:
        rows += f'<div class="row bs">{_esc(supply)}</div>'

    tail = ""
    if not compact:
        tail = ('<div class="bs" style="margin-top:8px">'
                "이 항목은 시세조종 여부를 판정하지 않습니다. "
                "공개 데이터로는 증명할 수 없습니다. "
                "평소와 얼마나 다른지만 보여주는 참고 자료입니다.</div>")

    return f'<div class="risk {level}"><b>이상 징후 {icon}</b>{rows}{tail}</div>'


def _evidence(row: dict) -> str:
    checks = row.get("checks") or []
    parts = row.get("parts") or {}
    items = ""
    for c in checks:
        ok = c.get("passed")
        items += (f'<div class="chk"><div class="ic {"pass" if ok else "fail"}">'
                  f'{"O" if ok else "X"}</div><div>'
                  f'<div class="lb">{_esc(c.get("label", ""))}</div>'
                  f'<div class="dt">{_esc(c.get("detail", ""))}</div>'
                  f'<div class="wy">{_esc(c.get("why", ""))}</div></div></div>')

    formula = ""
    if parts:
        formula = ('<div class="box"><b>점수 계산</b><br>'
                   f'갭 {parts.get("gap", 0):.0f} x 1.0 &nbsp;+&nbsp; '
                   f'대금 {parts.get("turnover", 0):.0f} x 1.0 &nbsp;+&nbsp; '
                   f'추세 {parts.get("trend", 0):.0f} x 1.5 &nbsp;+&nbsp; '
                   f'신고가 {parts.get("near_high", 0):.0f} x 1.5<br>'
                   f'= 가중합 / 5.0 = <b>{parts.get("total", 0):.1f}점</b></div>')

    numbers = ('<div class="box"><b>사용한 값</b><div class="kv">'
               f'<div class="k">현재가</div><div class="v">{row["price"]:,.0f}원</div>'
               f'<div class="k">오늘 시가</div><div class="v">{row.get("open", 0):,.0f}원</div>'
               f'<div class="k">오늘 고가</div><div class="v">{row.get("today_high", 0):,.0f}원</div>'
               f'<div class="k">전날 종가</div><div class="v">{row.get("prev_close", 0):,.0f}원</div>'
               f'<div class="k">전날 고가</div><div class="v">{row.get("prev_high", 0):,.0f}원</div>'
               f'<div class="k">20일선</div><div class="v">{row.get("sma_fast", 0):,.0f}원</div>'
               f'<div class="k">50일선</div><div class="v">{row.get("sma_mid", 0):,.0f}원</div>'
               f'<div class="k">200일선</div><div class="v">{row.get("sma_slow", 0):,.0f}원</div>'
               f'<div class="k">거래대금</div><div class="v">{row.get("turnover", 0) / 1e8:,.0f}억원</div>'
               "</div></div>")

    return (f'<details><summary>선정 근거 전체 보기</summary>'
            f'<div class="why">{items}{numbers}{formula}{_company_box(row)}'
            f'{_anomaly_box(row)}</div></details>')


def _pick(row: dict, dim: bool = False) -> str:
    parts = row.get("parts") or {}
    bars = ""
    if parts:
        labels = [("갭", "gap"), ("대금", "turnover"), ("추세", "trend"), ("신고가", "near_high")]
        bars = '<div class="bars">' + "".join(
            f'<div class="bar"><div class="t">{lab} {parts.get(key, 0):.0f}</div>'
            f'<div class="track"><div class="fill" style="width:'
            f'{max(0, min(100, parts.get(key, 0))):.0f}%"></div></div></div>'
            for lab, key in labels) + "</div>"

    score_html = ""
    if row.get("score") is not None:
        score_html = (f'<div class="sc"><div class="n">{row["score"]:.0f}</div>'
                      '<div class="l">점수</div></div>')

    tags = ""
    for t in (row.get("size_label"), (row.get("fundamentals") or {}).get("sector")):
        if t:
            tags += f'<span class="tag">{_esc(t)}</span>'
    tags = f'<div class="tags">{tags}</div>' if tags else ""

    return f"""<div class="pick{' dim' if dim else ''}">
  <div class="top">
    <div class="no">{row['rank']}</div>
    <div class="hd">
      <div><span class="nm">{_esc(row['name'] or row['code'])}</span>
        <span class="cd">{_esc(row['code'])}</span></div>
      {tags}
      <div class="px">{row['price']:,.0f}원 &middot; 시가갭 {row['gap_pct']:+.2f}%
        &middot; 대금 {row['turnover'] / 1e8:,.0f}억</div>
    </div>
    {score_html}
  </div>
  {_sparkline(row.get("closes") or [], row.get("sma_slow", 0))}
  {bars}
  {_anomaly_box(row, compact=True)}
  {_evidence(row)}
</div>"""


def _signals_section(entry: dict) -> str:
    rows = entry.get("signals") or []
    if not rows:
        return '<div class="card"><div class="empty">오늘 조건을 통과한 종목이 없습니다.</div></div>'
    top = [r for r in rows if r.get("recommended")]
    rest = [r for r in rows if not r.get("recommended")]
    out = ""
    if top:
        out += f'<h2>추천 상위 {len(top)}종목</h2><div class="card">'
        out += "".join(_pick(r) for r in top) + "</div>"
    if rest:
        out += f'<h2>나머지 조건 통과 {len(rest)}종목</h2><div class="card">'
        out += "".join(_pick(r, dim=True) for r in rest) + "</div>"
    return out


def _history_section(entries: list[dict]) -> str:
    past = entries[:-1][-SHOW_DAYS:][::-1]
    if not past:
        return ""
    rows = ""
    for e in past:
        verdict = (e.get("market") or {}).get("verdict", "-")
        names = ", ".join((r.get("name") or r.get("code"))
                          for r in (e.get("signals") or [])[:3])
        rows += (f'<div class="hist"><span class="d">{_esc(e.get("date", ""))}</span>'
                 f'<span style="flex:1;min-width:0">{_esc(names) or "신호 없음"}</span>'
                 f'<span class="d">{_esc(verdict)}</span></div>')
    return f'<h2>지난 기록</h2><div class="card">{rows}</div>'


def render(entries: list[dict]) -> str:
    entry = entries[-1] if entries else {"when": "", "signals": [], "market": None}
    when = entry.get("when", "")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>종목 스캐너</title>
<style>{STYLE}</style>
</head><body>
<div class="wrap">
  <header>
    <h1>종목 스캐너</h1>
    <div class="sub">{_esc(when) or '아직 스캔 기록이 없습니다'} &middot; Trend Join Long</div>
  </header>
  {_market_card(entry.get("market"))}
  {_signals_section(entry)}
  {_history_section(entries)}
  <div class="note">
    각 종목의 <b>선정 근거 전체 보기</b>를 누르면 5가지 조건의 실제 비교값,
    사용한 모든 숫자, 점수 계산 과정, 기업 정보를 확인할 수 있습니다.<br>
    점수는 같은 조건을 통과한 종목들 중 상대적으로 뚜렷한 쪽을 고르는 장치입니다.
    점수가 높다고 더 오른다는 근거는 없습니다.<br>
    여기 표시되는 것은 매수 신호 후보일 뿐 매매 권유가 아닙니다.
    최종 판단은 본인 기준으로 내리시기 바랍니다.<br>
    한국시간(KST) 기준이며 평일 장중에 자동 갱신됩니다.
  </div>
</div>
</body></html>"""


def update(out_dir: Path, when: str, market_state, signals, top_n: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "history.json"
    entries = load_history(history_path)
    entry = build_entry(when, market_state, signals, top_n)
    if entries and entries[-1].get("date") == entry["date"]:
        entries[-1] = entry
    else:
        entries.append(entry)
    save_history(history_path, entries)
    page = out_dir / "index.html"
    page.write_text(render(entries[-HISTORY_LIMIT:]), encoding="utf-8")
    return page
