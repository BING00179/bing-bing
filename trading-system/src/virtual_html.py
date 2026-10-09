"""「가상 계좌」 탭 — stocks/virtual.json 을 만들고, 그것으로 HTML 을 그립니다.

여기 숫자는 전부 가상입니다. 돈은 0원. 기준일을 숫자 옆에 적습니다 (§1).
없는 값은 0 이 아니라 None(JSON null) 으로 남기고 화면에는 '-' 로 보입니다 (§9).
"""
from __future__ import annotations

import html
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

from .virtual_account import VIRTUAL_VERSION, Rules, replay, value_of
from .virtual_store import Store


def _esc(v) -> str:
    return html.escape(str(v))


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _ok(v) -> bool:
    """숫자이고 NaN 이 아닌가 (None·빈 문자열·NaN 은 '없음')."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _n(x):
    """JSON 에 쓸 수 있는 숫자 — NaN 은 None 으로 (NaN 은 JSON 표준이 아니라 브라우저가 못 읽음)."""
    v = _f(x)
    return v if v == v else None


def _truthy(x) -> bool:
    return str(x).strip().lower() in ("true", "1")


def write_json(path: Path, store: Store, rules: Rules, closes: dict[str, float],
               names: dict[str, str], as_of: str, substituted: dict[str, str] | None = None) -> dict:
    """substituted[code] — 오늘 종가가 없어 대신 쓴 값의 설명 ("2026-10-05 종가" 또는 "평단").
    closes 는 평가에 실제로 쓴 값이어야 합니다 (대체된 값 포함)."""
    substituted = substituted or {}
    trades = store.load_trades()
    positions, cash = replay(trades, rules)
    daily = store.load_daily().sort_values("date")
    log = store.load_log()
    last = daily.iloc[-1].to_dict() if not daily.empty else {}
    equity = _f(last.get("equity")) if last else float("nan")
    if equity != equity:
        equity = cash + value_of(positions, closes)
    # 코스닥 "같은 기간" — 값이 있는 첫날~마지막 날. 양 끝 날짜를 같이 남겨 기준일을 숨기지 않습니다.
    kq_pts = [(str(r["date"]), _f(r["kosdaq_close"])) for r in daily.to_dict("records")]
    kq_pts = [(d, v) for d, v in kq_pts if v == v and v]
    kq_ret = round((kq_pts[-1][1] / kq_pts[0][1] - 1) * 100, 2) if len(kq_pts) >= 2 else None
    kq_from = kq_pts[0][0] if len(kq_pts) >= 2 else None
    kq_to = kq_pts[-1][0] if len(kq_pts) >= 2 else None
    valued_on = str(last["date"]) if last else None

    pos_rows = []
    for code, p in sorted(positions.items()):
        close = closes.get(code)
        note = substituted.get(code)
        if close is None or close != close:
            close = p.avg_price      # 평가 종가를 못 받았다 — 평단으로 대체하고 화면에 표시
            note = note or "평단"
        ret = (close / p.avg_price - 1) * 100 if p.avg_price else 0.0
        next_target = (rules.sell_tranches[p.sells_done][0] if p.sells_done < len(rules.sell_tranches) else None)
        pos_rows.append({
            "code": code, "name": names.get(code, p.name), "shares": p.shares,
            "avg_price": round(p.avg_price, 2), "close": close, "close_note": note,
            "return_pct": round(ret, 2),
            "tranche_done": p.tranche_done, "sells_done": p.sells_done, "cost": round(p.cost, 2),
            "to_target_pct": round(next_target - ret, 2) if next_target is not None else None,
            "to_invalid_pct": round(rules.invalid_pct - ret, 2),
        })

    cutoff = str((pd.Timestamp(as_of).to_pydatetime() - timedelta(days=30)).date())
    log_rows = [r for r in log.sort_values("date", ascending=False, kind="stable").to_dict("records")
                if str(r["date"]) >= cutoff]
    data = {
        "as_of": as_of, "version": VIRTUAL_VERSION,
        "rules": {k: (list(v) if isinstance(v, tuple) else v) for k, v in rules.__dict__.items()},
        "summary": {
            "capital": rules.capital, "equity": round(equity, 2), "cash": round(cash, 2),
            "positions_value": round(equity - cash, 2),
            "total_return_pct": round((equity / rules.capital - 1) * 100, 2),
            "day_pnl": _n(last.get("day_pnl")) if last else None,
            "day_pnl_pct": _n(last.get("day_pnl_pct")) if last else None,
            "halted": _truthy(last.get("halted", "")) if last else False,
            "valued_on": valued_on,
            "n_positions": len(positions), "max_positions": rules.max_positions,
            "kosdaq_return_pct": kq_ret, "kosdaq_from": kq_from, "kosdaq_to": kq_to,
        },
        "curve": [{"date": str(r["date"]), "equity": _n(r["equity"]), "kosdaq_close": _n(r["kosdaq_close"])}
                  for r in daily.to_dict("records")],
        "positions": pos_rows,
        "log": [{k: str(r[k]) for k in ("date", "code", "name", "action", "gate", "detail")} for r in log_rows],
        "trades": [{k: (str(r[k]) if k in ("date", "code", "name", "side", "tranche", "reason") else _n(r[k]))
                    for k in ("date", "code", "name", "side", "tranche", "shares", "price", "fee", "tax", "slippage", "amount", "reason")}
                   for r in trades.sort_values("date", ascending=False, kind="stable").to_dict("records")],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def svg_curve(curve: list[dict], capital: float, w: int = 640, h: int = 180) -> str:
    """원금 대비 평가액과 코스닥(같은 기간 % 환산)을 한 축에. 라이브러리 없이."""
    pts = [c for c in curve if _ok(c.get("equity"))]
    if len(pts) < 2:
        return '<div class="empty">기록이 이틀 이상 쌓이면 곡선이 그려집니다.</div>'
    eq = [(c["equity"] / capital - 1) * 100 for c in pts]
    kq0 = next((c["kosdaq_close"] for c in pts if _ok(c.get("kosdaq_close")) and c["kosdaq_close"]), None)
    kq = [((c["kosdaq_close"] / kq0 - 1) * 100 if kq0 and _ok(c.get("kosdaq_close")) else None) for c in pts]
    vals = eq + [v for v in kq if v is not None]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = 12

    def x(i): return pad + (w - 2 * pad) * i / (len(pts) - 1)
    def y(v): return pad + (h - 2 * pad) * (hi - v) / (hi - lo)

    def path(series):
        # 값이 빠진 날은 선을 잇지 않고 끊습니다 (M 으로 다시 시작)
        out, pen = [], False
        for i, v in enumerate(series):
            if v is None:
                pen = False
                continue
            out.append(f"{'L' if pen else 'M'}{x(i):.1f},{y(v):.1f}")
            pen = True
        return " ".join(out)

    zero = y(0.0)
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:auto;display:block" role="img" aria-label="가상 계좌 자산 곡선">'
            f'<line x1="{pad}" y1="{zero:.1f}" x2="{w - pad}" y2="{zero:.1f}" style="stroke:var(--line)" />'
            f'<path d="{path(kq)}" fill="none" style="stroke:var(--muted)" stroke-width="1.5" stroke-dasharray="4 3"/>'
            f'<path d="{path(eq)}" fill="none" style="stroke:var(--accent)" stroke-width="2"/>'
            f'<text x="{pad}" y="{pad + 10}" font-size="11" style="fill:var(--muted)">{hi:+.1f}%</text>'
            f'<text x="{pad}" y="{h - 2}" font-size="11" style="fill:var(--muted)">{lo:+.1f}%</text>'
            f'</svg><div class="sub">— 가상 계좌 &nbsp; ╌ 코스닥 지수 (같은 기간 %) · {_esc(pts[0]["date"])} ~ {_esc(pts[-1]["date"])}</div>')


def _won(v) -> str:
    return f"{v:,.0f}원" if _ok(v) else "-"


def _num(v, spec: str = ",.0f", suffix: str = "") -> str:
    return f"{v:{spec}}{suffix}" if _ok(v) else "-"


def _md(day) -> str:
    return str(day)[5:] if day else "?"


def _대체(p: dict) -> str:
    note = p.get("close_note")
    return f' <span class="sub">(오늘 종가 없음 — {_esc(note)} 로 평가)</span>' if note else ""


def _목표(v) -> str:
    if v is None:
        return "완료"
    return "도달 — 내일 매도 주문" if v <= 0 else f"{v:+.1f}%p"


def render_tab(d: dict) -> str:
    s, r, as_of = d["summary"], d["rules"], d["as_of"]
    valued_on = s.get("valued_on")
    기준 = f"{as_of} 종가 기준"
    카드기준 = f"{valued_on} 종가 기준" if valued_on else f"{as_of} 기준 — 아직 스냅샷 없음"
    경고 = (f'<div class="sub warn">⚠️ 오늘({_esc(as_of)}) 스냅샷 없음 — {_esc(valued_on)} 평가</div>'
          if valued_on and valued_on != as_of else "")
    kq기간 = (f' ({_md(s.get("kosdaq_from"))}~{_md(s.get("kosdaq_to"))})' if s.get("kosdaq_from") else "")
    일손익 = f'{_num(s["day_pnl"], "+,.0f")}원 ({_num(s["day_pnl_pct"], "+.2f")}%)' if _ok(s.get("day_pnl")) else "-"
    카드 = (f'<div class="card"><div class="state {"warn" if s["halted"] else "ok"}"><span class="dot"></span>'
          f'가상 계좌 · 돈 0원 · {"⚠️ 일일 손실 한도 발동" if s["halted"] else "정상"}</div>'
          f'<div class="sub">{_esc(카드기준)}</div>{경고}<div class="metrics">'
          + "".join(f'<div class="metric"><div class="k">{k}</div><div class="v vnum">{v}</div></div>' for k, v in [
              ("원금", _won(s["capital"])), ("평가액", _won(s["equity"])), ("현금", _won(s["cash"])),
              ("누적 수익률", _num(s["total_return_pct"], "+.2f", "%")), ("오늘 손익", 일손익),
              ("보유", f'{s["n_positions"]}/{s["max_positions"]}'),
              (f"코스닥 같은 기간{kq기간}", _num(s["kosdaq_return_pct"], "+.2f", "%"))])
          + "</div></div>")
    곡선 = f'<h2>자산 곡선</h2><div class="card">{svg_curve(d["curve"], s["capital"])}</div>'
    보유 = "".join(
        f'<tr><td>{_esc(p["name"])}<div class="sub">{_esc(p["code"])}</div></td><td>{p["tranche_done"]}차 / 매도 {p["sells_done"]}</td>'
        f'<td>{p["shares"]:,}</td><td>{p["avg_price"]:,.0f}</td>'
        f'<td>{p["close"]:,.0f}{_대체(p)}</td>'
        f'<td class="{"ok" if p["return_pct"] >= 0 else "bad"}">{p["return_pct"]:+.2f}%</td>'
        f'<td>{_목표(p["to_target_pct"])} / {p["to_invalid_pct"]:+.1f}%p</td></tr>'
        for p in d["positions"]) or '<tr><td colspan="7" class="empty">보유 종목이 없습니다 — 현금만 들고 기다리는 것도 기록입니다.</td></tr>'
    보유표 = (f'<h2>보유 종목 <span class="sub">({_esc(기준)})</span></h2><div class="card tbl"><table>'
            '<tr><th>종목</th><th>단계</th><th>주 수</th><th>평단</th><th>현재가</th><th>수익률</th><th>다음 목표 / 무효선까지</th></tr>'
            f'{보유}</table></div>')
    로그 = "".join(f'<tr><td>{_esc(x["date"])}</td><td>{_esc(x["name"])}</td><td>{_esc(x["action"])}</td><td>{_esc(x["gate"])}</td><td>{_esc(x["detail"])}</td></tr>'
                 for x in d["log"]) or '<tr><td colspan="5" class="empty">아직 결정 기록이 없습니다.</td></tr>'
    로그표 = ('<h2>결정 로그 — 낸 것도 막힌 것도 (최근 30일)</h2><div class="card tbl"><table>'
            f'<tr><th>날짜</th><th>종목</th><th>행동</th><th>관문</th><th>이유</th></tr>{로그}</table></div>')
    체결 = "".join(f'<tr><td>{_esc(t["date"])}</td><td>{_esc(t["name"])}</td><td>{_esc(t["side"])} {_esc(t["tranche"])}</td>'
                 f'<td>{_num(t["shares"])}</td><td>{_num(t["price"])}</td>'
                 f'<td>{_num((t["fee"] or 0) + (t["tax"] or 0))} / {_num(t["slippage"])}</td></tr>'
                 for t in d["trades"]) or '<tr><td colspan="6" class="empty">체결이 없습니다.</td></tr>'
    체결표 = ('<h2>체결 내역</h2><div class="card tbl"><table>'
            f'<tr><th>날짜</th><th>종목</th><th>구분</th><th>주 수</th><th>가격</th><th>수수료+세금 / 슬리피지(가정)</th></tr>{체결}</table></div>')
    규칙 = (f'<h2>규칙 (판 v{_esc(d["version"])})</h2><div class="card"><div class="sub">'
          f'원금 {_won(r["capital"])} · 최대 {r["max_positions"]}종목 · 종목당 {r["position_cap_pct"]:g}% · 현금 예비 {_won(r["cash_reserve"])}<br>'
          f'분할 매수 {"·".join(str(x) for x in r["buy_tranches_pct"])} (2차 +{r["tranche2_trigger_pct"]:g}%, 3차 {r["tranche3_trigger_pct"]:g}% — 가정)<br>'
          f'분할 매도 {" / ".join(f"+{p:g}%에 {w}%" for p, w in r["sell_tranches"])} · 무효선 {r["invalid_pct"]:g}% · 일일 손실 한도 {r["daily_loss_halt_pct"]:g}%<br>'
          f'비용 매수 {r["fee_buy_pct"]}% · 매도 {r["fee_sell_pct"]}% · 세금 {r["tax_pct"]}% (확인됨) · 슬리피지 {r["slippage_pct"]}% (가정)<br>'
          '근거 사라짐 = 월말 판정 함정?·제외 (가정) · 그 달 판정 뒤 다 판 종목은 다음 판정까지 다시 사지 않음 (가정) · '
          '실행을 놓쳐 하루 넘게 묵은 주문은 만료<br>'
          '판단은 그날 종가, 체결은 다음날 시가. 이 화면의 모든 숫자는 가상이며 매매 권유가 아닙니다.</div></div>')
    return 카드 + 곡선 + 보유표 + 로그표 + 체결표 + 규칙
