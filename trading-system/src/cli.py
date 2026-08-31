"""명령줄 진입점.

    python -m src.cli scan-a               # 프리마켓 갭 스캐너
    python -m src.cli scan-b               # 전략 스캐너 (스캐너 A 결과 사용)
    python -m src.cli backtest --csv-dir data/daily
    python -m src.cli test-telegram

공통 옵션
    --config PATH     설정 파일 (기본 config.json)
    --universe PATH   티커 목록 파일
    --no-telegram     알림 없이 화면에만 출력
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import backtest as bt_module
from . import breakout_kr as bo_module
from . import case as case_module
from . import dart_kr
from . import dashboard as dash_module
from . import journal as jn_module
from . import value_kr as val_module
from . import diagnose as dg_module
from . import market_filter as mf_module
from . import notify_policy
from . import analyze
from .cache import PriceCache
from . import walkforward as wf_module
from . import factor_data, factors
from . import portfolio as pf_module
from . import ranking
from . import watchlist as wl_module
from . import report_html
from . import scanner_a, scanner_b, scanner_kr
from .config import Config
from .data import NY, DataUnavailable, fetch_daily, load_csv, read_universe
from .data_kr import fetch_index
from .data_kr import fetch_daily as fetch_daily_kr
from .data_kr import list_market, read_universe_kr
from .market_time import now_et, now_kst, should_run
from .notify import TelegramNotConfigured, send

ROOT = Path(__file__).resolve().parent.parent


def _force_utf8_output() -> None:
    """윈도우 콘솔에서 한글·기호가 깨지거나 오류로 죽는 것을 막습니다.

    윈도우의 기본 콘솔 인코딩은 cp949 라서 '⚠️' 같은 문자를 출력하면
    UnicodeEncodeError 로 프로그램이 통째로 멈춥니다. 알림 문구 하나
    때문에 스캔이 죽으면 안 되므로 출력 스트림을 UTF-8 로 바꿉니다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _timestamp() -> str:
    return datetime.now(NY).strftime("%Y-%m-%d %H:%M ET")


def _output_dir(cfg: Config) -> Path:
    out = _resolve(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _notify(text: str, enabled: bool) -> None:
    print(text)
    if not enabled:
        return
    try:
        send(text)
    except TelegramNotConfigured as exc:
        print(f"[알림 생략] {exc}")


def _gate(start: str, end: str, force: bool) -> bool:
    """실행 시간대인지 확인. 아니면 이유를 찍고 False."""
    if force:
        return True
    ok, reason = should_run(now_et(), start, end)
    if not ok:
        print(f"건너뜁니다 — {reason}. 지금 실행하려면 --force 를 붙이세요.")
    return ok


def cmd_scan_a(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    if not _gate(cfg.scanner_a.run_start_et, cfg.scanner_a.run_end_et, args.force):
        return 0
    universe = read_universe(_resolve(args.universe or cfg.universe_file))
    print(f"프리마켓 갭 스캔 시작 — 대상 {len(universe)}종목")

    hits, errors = scanner_a.scan(universe, cfg.scanner_a, with_news=not args.no_news)
    report = scanner_a.format_report(hits, _timestamp(), errors, scanned=len(universe))

    out = _output_dir(cfg) / f"scan_a_{datetime.now(NY):%Y%m%d_%H%M}.csv"
    scanner_a.to_frame(hits).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    _notify(report, not args.no_telegram)
    return 1 if errors and len(errors) >= len(universe) else 0


def _latest_scan_a(cfg: Config) -> list[str]:
    """가장 최근 스캐너 A 결과 파일에서 티커를 읽습니다."""
    out = _output_dir(cfg)
    files = sorted(out.glob("scan_a_*.csv"))
    if not files:
        return []
    frame = pd.read_csv(files[-1])
    print(f"스캐너 A 결과 사용: {files[-1].name}")
    return frame["ticker"].astype(str).tolist() if "ticker" in frame.columns else []


def cmd_scan_b(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)

    if not _gate(cfg.scanner_b.run_start_et, cfg.scanner_b.run_end_et, args.force):
        return 0

    if args.universe:
        tickers = read_universe(_resolve(args.universe))
    else:
        tickers = _latest_scan_a(cfg)
        if not tickers:
            print("스캐너 A 결과가 없어 전체 티커 목록으로 대체합니다.")
            tickers = read_universe(_resolve(cfg.universe_file))

    print(f"전략 스캔 시작 — 대상 {len(tickers)}종목")
    results, errors = scanner_b.scan(tickers, cfg.scanner_b)
    report = scanner_b.format_report(results, _timestamp(), errors, scanned=len(tickers))

    out = _output_dir(cfg) / f"scan_b_{datetime.now(NY):%Y%m%d_%H%M}.csv"
    pd.DataFrame(
        [
            {
                "ticker": r.ticker,
                "price": r.price,
                "prev_high": r.prev_high,
                "prev_close": r.prev_close,
                "sma_slow": r.sma_slow,
                "premarket_high": r.premarket_high,
                "today_high": r.today_high,
            }
            for r in results
        ]
    ).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    _notify(report, not args.no_telegram)
    return 1 if errors and len(errors) >= len(tickers) else 0


def _load_daily_for(ticker: str, csv_dir: Path | None, period: str) -> pd.DataFrame:
    if csv_dir:
        return load_csv(csv_dir / f"{ticker}.csv")
    return fetch_daily(ticker, period=period)


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    tickers = read_universe(_resolve(args.universe or cfg.universe_file))
    csv_dir = _resolve(args.csv_dir) if args.csv_dir else None

    all_trades: list[bt_module.Trade] = []
    per_ticker: list[dict] = []

    for ticker in tickers:
        try:
            daily = _load_daily_for(ticker, csv_dir, args.period)
        except DataUnavailable as exc:
            print(f"  ! {ticker}: {exc}")
            continue
        if len(daily) < cfg.scanner_b.sma_slow + 5:
            print(f"  ! {ticker}: 일봉 {len(daily)}개로는 200일선 검증이 어렵습니다.")
            continue

        trades = bt_module.run(ticker, daily, cfg.backtest, cfg.scanner_b)
        all_trades.extend(trades)
        stats = bt_module.summarize(trades)
        stats["ticker"] = ticker
        per_ticker.append(stats)
        print(
            f"  {ticker:<6} 매매 {stats['trades']:>3}건  "
            f"승률 {stats['win_rate_pct']:>5.1f}%  손익 ${stats['total_pnl']:>10,.2f}"
        )

    total = bt_module.summarize(all_trades)
    out = _output_dir(cfg)
    bt_module.trades_to_frame(all_trades).to_csv(out / "backtest_trades.csv", index=False)
    pd.DataFrame(per_ticker).to_csv(out / "backtest_by_ticker.csv", index=False)

    lines = [
        "",
        "=" * 58,
        "[백테스트 요약] Trend Join Long",
        "=" * 58,
        f"  대상 종목        {len(per_ticker)}",
        f"  총 매매          {total['trades']}건",
        f"  승률             {total['win_rate_pct']}%",
        f"  총 손익          ${total['total_pnl']:,.2f}",
        f"  평균 수익률      {total['avg_return_pct']}% / 매매",
        f"  평균 이익        {total['avg_win_pct']}%",
        f"  평균 손실        {total['avg_loss_pct']}%",
        f"  손익비(PF)       {total['profit_factor']}",
        f"  최대 낙폭        ${total['max_drawdown']:,.2f}",
        f"  평균 보유        {total['avg_hold_days']}일",
        "-" * 58,
        f"  조건: 손절 {cfg.backtest.stop_loss_pct}% / 익절 {cfg.backtest.take_profit_pct}%"
        f" / 최대보유 {cfg.backtest.max_hold_days}일",
        f"  비용: 수수료 ${cfg.backtest.commission_per_trade} x2 /"
        f" 슬리피지 {cfg.backtest.slippage_pct}% x2",
        "",
        "  ※ 일봉 백테스트라 조건 3(프리마켓 고가 돌파)은 검증에서 빠져 있습니다.",
        "  ※ 손절·익절이 같은 날 함께 닿으면 손절로 처리했습니다(보수적 가정).",
        "=" * 58,
    ]
    report = "\n".join(lines)
    print(report)
    print(f"\n결과 저장: {out}/backtest_trades.csv, {out}/backtest_by_ticker.csv")
    return 0


# ────────────────────────────── 국내장 ──────────────────────────────


def _timestamp_kr() -> str:
    return now_kst().strftime("%Y-%m-%d %H:%M KST")


def _gate_kr(start: str, end: str, force: bool) -> bool:
    if force:
        return True
    ok, reason = should_run(now_kst(), start, end)
    if not ok:
        print(f"건너뜁니다 — {reason}. 지금 실행하려면 --force 를 붙이세요.")
    return ok


def _market_state(cfg: Config):
    """시장 필터 판정. 꺼져 있거나 조회 실패면 None.

    시장 판정에 실패했다고 종목 스캔까지 멈추지는 않습니다. 다만
    '판정 못 함'을 리포트에 그대로 적어서, 필터가 걸린 것으로
    오해하지 않게 합니다.
    """
    if not cfg.market_filter.enabled:
        return None, ""
    try:
        index = fetch_index(cfg.market_filter.index_code)
        state = mf_module.evaluate(index, cfg.market_filter, cfg.market_filter.index_name)
        return state, ""
    except (DataUnavailable, ValueError) as exc:
        return None, f"⚠️ 시장 상태를 판정하지 못했습니다: {exc}"


def _names_for(codes: list[str], path: Path) -> dict[str, str]:
    """종목 목록 파일에 적어둔 이름을 코드→이름 사전으로."""
    names: dict[str, str] = {}
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            names[parts[0].zfill(6)] = parts[1].strip()
    return {c: names.get(c, "") for c in codes}


def cmd_scan_kr_a(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    kr = cfg.scanner_a_kr
    if not _gate_kr(kr.run_start_kst, kr.run_end_kst, args.force):
        return 0

    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)
    state, state_error = _market_state(cfg)

    print(f"국내 시가갭 스캔 시작 — 대상 {len(codes)}종목")
    hits, errors, closed = scanner_kr.scan_a(codes, kr, names)

    report = scanner_kr.format_report_a(
        hits, _timestamp_kr(), errors, scanned=len(codes), closed=closed
    )
    report = _with_market_state(report, state, state_error)

    out = _output_dir(cfg) / f"kr_scan_a_{now_kst():%Y%m%d_%H%M}.csv"
    scanner_kr.to_frame_a(hits).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    # 스캐너 A 는 시장 판정이 바뀔 때만 알립니다. 30분마다 같은 내용을
    # 보내면 알림을 꺼버리게 되고, 정작 진짜 신호를 놓칩니다.
    web_dir = _resolve(args.web_dir)
    today = now_kst().strftime("%Y-%m-%d")
    st = notify_policy.NotifyState.load(web_dir, today)
    verdict = state.verdict if state is not None else ""
    changed = bool(verdict) and verdict != st.market_verdict

    if changed:
        notify_policy.commit(st, [], verdict)
        st.save(web_dir)
    else:
        print("알림 생략 — 시장 판정에 변화가 없습니다.")

    _notify(report, not args.no_telegram and changed)
    return _scan_exit_code(len(codes), closed, errors)


def _scan_exit_code(total: int, closed: int, errors: list[str]) -> int:
    """스캔 결과를 종료 코드로.

    구분해야 할 세 가지가 있습니다.
      휴장일        오늘 거래된 종목이 없음. 정상입니다
      일부 실패     몇 종목만 조회 안 됨. 정상 진행으로 봅니다
      전부 실패     조회 가능했던 종목이 하나도 안 됨. 이건 문제입니다

    휴장일에 실패로 끝내면 뒤따르는 웹페이지 갱신과 저장소 커밋까지
    막힙니다. 실제로 그래서 페이지가 안 올라갔습니다.
    """
    scannable = total - closed
    if scannable <= 0:
        print(f"오늘 거래된 종목이 없습니다 ({total}종목 전부 휴장·거래정지).")
        return 0
    if errors and len(errors) >= scannable:
        print(f"⚠️ 조회 가능했던 {scannable}종목이 전부 실패했습니다.")
        return 1
    if errors:
        print(f"조회 실패 {len(errors)}종목 (거래된 {scannable}종목 중).")
    return 0


def _with_market_state(report: str, state, state_error: str) -> str:
    """리포트 앞에 시장 상태를 붙입니다."""
    if state_error:
        return f"{state_error}\n\n{report}"
    if state is None:
        return report
    if not state.tradable:
        # 시장이 위험하면 종목 목록을 아예 내보내지 않습니다.
        return state.as_report()
    return f"{state.as_report()}\n\n{report}"


def cmd_scan_kr_b(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    kr = cfg.scanner_b_kr
    if not _gate_kr(kr.run_start_kst, kr.run_end_kst, args.force):
        return 0

    out_dir = _output_dir(cfg)
    if args.universe:
        path = _resolve(args.universe)
        codes = read_universe_kr(path)
    else:
        files = sorted(out_dir.glob("kr_scan_a_*.csv"))
        codes = []
        if files:
            frame = pd.read_csv(files[-1], dtype={"code": str})
            if "code" in frame.columns:
                codes = frame["code"].astype(str).str.zfill(6).tolist()
            if codes:
                print(f"스캐너 A 결과 사용: {files[-1].name} ({len(codes)}종목)")
        if not codes:
            print("스캐너 A 결과가 없어 전체 종목 목록으로 대체합니다.")
            path = _resolve(cfg.universe_file_kr)
            codes = read_universe_kr(path)
        else:
            path = _resolve(cfg.universe_file_kr)

    names = _names_for(codes, path)
    state, state_error = _market_state(cfg)

    print(f"국내 전략 스캔 시작 — 대상 {len(codes)}종목")
    results, errors, closed = scanner_kr.scan_b(codes, cfg.scanner_b, names)
    results = scanner_kr.rank(results, cfg.ranking)

    report = scanner_kr.format_report_b(
        results, _timestamp_kr(), errors, scanned=len(codes), closed=closed,
        top_n=cfg.ranking.top_n if cfg.ranking.enabled else 0,
    )
    report = _with_market_state(report, state, state_error)

    # 웹페이지 갱신 — 깃허브가 이 파일을 저장소에 올리면 Pages 가 서비스합니다.
    if args.web:
        page = report_html.update(
            _resolve(args.web_dir), _timestamp_kr(), state, results,
            cfg.ranking.top_n if cfg.ranking.enabled else 0,
        )
        print(f"웹페이지 갱신: {page}")

    out = out_dir / f"kr_scan_b_{now_kst():%Y%m%d_%H%M}.csv"
    pd.DataFrame(
        [
            {
                "code": r.code, "name": r.name, "price": r.price,
                "prev_high": r.prev_high, "prev_close": r.prev_close,
                "sma_slow": r.sma_slow, "open": r.open_price, "today_high": r.today_high,
                "gap_pct": r.gap_pct, "turnover": r.turnover,
                "score": r.score.total if r.score else None,
            }
            for r in results
        ]
    ).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    # 오늘 이미 알린 종목만 다시 뜨면 보내지 않습니다.
    web_dir = _resolve(args.web_dir)
    today = now_kst().strftime("%Y-%m-%d")
    st = notify_policy.NotifyState.load(web_dir, today)
    codes_now = [r.code for r in results]
    decision = notify_policy.decide(st, codes_now, "")

    if decision.send:
        # 새로 뜬 종목만 앞에 따로 표시합니다.
        fresh = ", ".join(
            f"{r.name or r.code}" for r in results if r.code in decision.new_codes
        )
        report = f"🆕 새 신호: {fresh}\n\n{report}"
        notify_policy.commit(st, codes_now, "")
        st.save(web_dir)
    else:
        print(f"알림 생략 — {decision.reason}")

    _notify(report, not args.no_telegram and decision.send)
    return _scan_exit_code(len(codes), closed, errors)


def cmd_watchlist(args: argparse.Namespace) -> int:
    """장 마감 후 내일 볼 종목을 추립니다."""
    cfg = Config.load(args.config)
    wc = wl_module.WatchConfig(
        sma_slow=cfg.watchlist.sma_slow, sma_mid=cfg.watchlist.sma_mid,
        sma_fast=cfg.watchlist.sma_fast,
        near_breakout_pct=cfg.watchlist.near_breakout_pct,
        breakout_window=cfg.watchlist.breakout_window,
        strong_close_pct=cfg.watchlist.strong_close_pct,
        min_turnover=cfg.watchlist.min_turnover,
        min_price=cfg.watchlist.min_price,
        max_results=cfg.watchlist.max_results,
    )

    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)
    print(f"내일 관찰 후보 탐색 — 대상 {len(codes)}종목")

    found: list = []
    for code in codes:
        try:
            daily = fetch_daily_kr(code, years=1.5)
        except DataUnavailable:
            continue
        except Exception:  # noqa: BLE001 - 한 종목 실패로 전체를 멈추지 않음
            continue
        cand = wl_module.evaluate(code, daily, wc, names.get(code, ""))
        if cand:
            found.append(cand)

    ranked = wl_module.rank(found, wc)
    report = wl_module.format_report(ranked, _timestamp_kr(), scanned=len(codes))

    out = _output_dir(cfg) / f"kr_watchlist_{now_kst():%Y%m%d}.csv"
    pd.DataFrame([
        {"code": c.code, "name": c.name, "close": c.close,
         "recent_high": c.recent_high, "to_breakout_pct": c.to_breakout_pct,
         "sma_slow": c.sma_slow, "turnover": c.turnover,
         "day_change_pct": c.day_change_pct, "reasons": " · ".join(c.reasons)}
        for c in ranked
    ]).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    # 마감 요약에 함께 넣을 수 있도록 파일로도 남깁니다.
    web_dir = _resolve(args.web_dir)
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "watchlist.json").write_text(
        json.dumps(
            {
                "date": now_kst().strftime("%Y-%m-%d"),
                "items": [
                    {"code": c.code, "name": c.name, "close": c.close,
                     "to_breakout_pct": c.to_breakout_pct,
                     "recent_high": c.recent_high,
                     "day_change_pct": c.day_change_pct,
                     "turnover": c.turnover, "reasons": c.reasons}
                    for c in ranked
                ],
            },
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )

    _notify(report, not args.no_telegram)
    return 0


def cmd_daily_summary(args: argparse.Namespace) -> int:
    """장 마감 후 오늘 하루를 한 번에 정리해 보냅니다."""
    web_dir = _resolve(args.web_dir)
    entries = report_html.load_history(web_dir / "history.json")
    today = now_kst().strftime("%Y-%m-%d")

    entry = next((e for e in reversed(entries) if e.get("date") == today), None)
    if entry is None:
        print("오늘 스캔 기록이 없습니다. 요약을 보내지 않습니다.")
        return 0

    lines = [f"📋 오늘 마감 요약 — {today}"]

    market = entry.get("market") or {}
    if market:
        mark = {"정상": "🟢", "주의": "🟡", "위험": "🔴"}.get(market.get("verdict"), "")
        lines.append(
            f"{mark} 시장 {market.get('verdict')} · "
            f"{market.get('index_name')} {market.get('close', 0):,.1f} · "
            f"고점대비 -{market.get('drawdown_pct', 0):.1f}%"
        )

    signals = entry.get("signals") or []
    if not signals:
        lines += ["", "오늘 매수 신호는 없었습니다."]
    else:
        lines += ["", f"매수 신호 {len(signals)}종목"]
        for r in signals:
            star = "⭐ " if r.get("recommended") else "   "
            score = f" · {r['score']:.0f}점" if r.get("score") is not None else ""
            lines.append(
                f"{star}{r.get('name') or r.get('code')} "
                f"{r.get('price', 0):,.0f}원{score}"
            )

    # 내일 관찰 후보를 함께 붙입니다.
    watch_path = web_dir / "watchlist.json"
    if watch_path.exists():
        try:
            watch = json.loads(watch_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            watch = {}
        if watch.get("date") == today and watch.get("items"):
            lines += ["", f"🔭 내일 관찰 후보 {len(watch['items'])}종목 (돌파 임박 순)"]
            for item in watch["items"]:
                lines.append(
                    f"   {item.get('name') or item.get('code')} "
                    f"{item.get('close', 0):,.0f}원 · "
                    f"돌파까지 {item.get('to_breakout_pct', 0):.1f}%"
                )

    if args.url:
        lines += ["", f"자세히: {args.url}"]
    lines += ["", "※ 신호일 뿐 매매 권유가 아닙니다."]

    _notify("\n".join(lines), not args.no_telegram)
    return 0


def cmd_market(args: argparse.Namespace) -> int:
    """시장 상태만 확인합니다."""
    cfg = Config.load(args.config)
    index = fetch_index(cfg.market_filter.index_code)
    state = mf_module.evaluate(index, cfg.market_filter, cfg.market_filter.index_name)
    report = f"[시장 상태] {_timestamp_kr()}\n{state.as_report()}"

    if args.detail:
        # 판정이 이상해 보일 때 원본 값을 직접 확인할 수 있게 합니다.
        # 네이버 금융 같은 곳의 지수와 대조해 보세요.
        closes = index["close"]
        returns = closes.pct_change().dropna()
        recent = returns.tail(cfg.market_filter.volatility_window)
        print("\n── 판정에 쓴 원본 값 ──")
        print(f"  {cfg.market_filter.index_code} 일봉 {len(closes)}개 "
              f"({closes.index[0]:%Y-%m-%d} ~ {closes.index[-1]:%Y-%m-%d})")
        print("  최근 5일 종가: "
              + ", ".join(f"{v:,.2f}" for v in closes.tail(5)))
        print(f"  {cfg.market_filter.drawdown_window}일 최고: "
              f"{closes.tail(cfg.market_filter.drawdown_window).max():,.2f}")
        print(f"  최근 {len(recent)}일 일간등락 최소/최대: "
              f"{recent.min() * 100:+.2f}% / {recent.max() * 100:+.2f}%")
        print(f"  일간등락 표준편차: {recent.std() * 100:.2f}%"
              f"  → 연율화 {recent.std() * (252 ** 0.5) * 100:.1f}%")
        print("  ※ 지수 값이 실제와 다르면 데이터 출처 문제입니다.")

    _notify(report, not args.no_telegram)
    return 0


def _pick_top_signals(frames, cfg, market_ok, args) -> dict[str, set]:
    """같은 날 신호가 여럿이면 점수 상위 N종목만 남깁니다.

    실제로 쓸 때 하루에 3종목만 산다면, 검증도 그렇게 해야 합니다.
    전 종목의 신호를 한자리에 모아 날짜별로 순위를 매깁니다.
    """
    rows = [
        bt_module.signal_rows(code, daily, cfg.scanner_b, market_ok)
        for code, daily in frames.items()
    ]
    rows = [r for r in rows if not r.empty]
    if not rows:
        print("신호가 하나도 없어 점수를 매길 것이 없습니다.")
        return {}

    allsig = pd.concat(rows)
    allsig["score"] = [
        ranking.score(
            gap_pct=r.gap_pct, turnover=r.turnover, price=r.price,
            sma_slow=r.sma_slow, today_high=r.today_high, cfg=cfg.ranking,
        ).total
        for r in allsig.itertuples()
    ]

    before = len(allsig)
    kept = (
        allsig[allsig["score"] >= args.min_score]
        .groupby(level=0, group_keys=False)
        .apply(lambda g: g.nlargest(args.top_n, "score"))
    )
    print(
        f"점수 상위 {args.top_n}종목만 — 신호 {before:,}건 중 "
        f"{len(kept):,}건 선택 ({len(kept) / before * 100:.1f}%)"
    )
    if len(kept):
        print(
            f"  선택된 신호 점수: 최저 {kept['score'].min():.1f} · "
            f"중앙 {kept['score'].median():.1f} · 최고 {kept['score'].max():.1f}"
        )
    return {code: set(part.index) for code, part in kept.groupby("ticker")}


def _frames_for(
    codes: list[str],
    years: float,
    min_rows: int,
    cache_dir: Path | None,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """시세를 확보합니다. 저장된 것이 있으면 그것부터 씁니다.

    검증 시간의 대부분은 계산이 아니라 시세를 기다리는 것입니다.
    한 번 받아두면 두 번째부터는 몇 초에 끝납니다.
    """
    cache = PriceCache(cache_dir) if cache_dir else None

    if cache and not refresh:
        info = cache.info()
        if info:
            print(f"  {info.as_line()}")

    frames: dict[str, pd.DataFrame] = {}
    fetched = reused = 0

    for code in codes:
        daily = None
        if cache and not refresh:
            daily = cache.get(code)
            if daily is not None:
                reused += 1

        if daily is None:
            try:
                daily = fetch_daily_kr(code, years=years)
            except DataUnavailable:
                continue
            except Exception:  # noqa: BLE001
                continue
            fetched += 1
            if cache:
                cache.put(code, daily)
            if fetched % 100 == 0:
                print(f"  받는 중 {fetched:,}종목...")

        if len(daily) >= min_rows:
            frames[code] = daily

    if cache and fetched:
        cache.save_meta(len(cache.stored_codes()), years)

    print(f"  시세 확보 {len(frames):,}종목 "
          f"(새로 받음 {fetched:,} · 저장분 사용 {reused:,})")
    return frames


def _apply_cost_overrides(cfg: Config, args: argparse.Namespace) -> None:
    """비용 가정을 명령줄에서 덮어씁니다.

    슬리피지 0.15% 는 실측이 아니라 제가 정한 가정값입니다. 코스닥 소형주를
    시초가에 사는 전략이라 실제로는 더 나쁠 수 있습니다. 가정을 바꿔가며
    "이래도 버티나" 를 볼 수 있어야, 결과 하나만 보고 믿는 일을 막습니다.

    바꾼 값은 반드시 화면에 찍습니다 — 무엇으로 돌린 결과인지 모르면
    그 결과는 쓸모가 없습니다.
    """
    base = cfg.backtest_kr
    changes: dict[str, float] = {}
    for name, label in (("slippage", "편도 슬리피지"),
                        ("commission", "편도 수수료"),
                        ("sell_tax", "증권거래세")):
        value = getattr(args, name, None)
        if value is None:
            continue
        field_name = {"slippage": "slippage_pct", "commission": "commission_pct",
                      "sell_tax": "sell_tax_pct"}[name]
        changes[field_name] = float(value)
        print(f"⚙️  {label} {getattr(base, field_name)}% → {value}% 로 바꿔서 돌립니다")

    if changes:
        cfg.backtest_kr = replace(base, **changes)

    after = cfg.backtest_kr
    round_trip = (after.slippage_pct * 2 + after.commission_pct * 2 + after.sell_tax_pct)
    print(f"   왕복 총비용 {round_trip:.3f}% — 한 번 매매할 때마다 이만큼은 먼저 빠집니다")


def _add_cost_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--slippage", type=float,
        help="편도 슬리피지(퍼센트)를 바꿔서 돌립니다. 기본 0.15",
    )
    parser.add_argument(
        "--commission", type=float,
        help="편도 수수료율(퍼센트)을 바꿔서 돌립니다. 기본 0.015",
    )
    parser.add_argument(
        "--sell-tax", type=float, dest="sell_tax",
        help="증권거래세(퍼센트)를 바꿔서 돌립니다. 기본 0.18",
    )


def cmd_walkforward_kr(args: argparse.Namespace) -> int:
    """손절 설정을 학습 구간에서 고르고 검증 구간에서 시험합니다."""
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)

    market_ok = None
    print("=" * 84)
    _apply_cost_overrides(cfg, args)
    if args.market_filter:
        index = fetch_index(cfg.market_filter.index_code)
        market_ok = mf_module.tradable_series(index, cfg.market_filter)
        print(f"시장 필터 켬 — 매수 허용 {market_ok.mean() * 100:.1f}%")
    print(f"대상 {len(codes):,}종목 · 최근 {args.years}년 · "
          f"학습 {args.train_ratio:.0%} / 검증 {1 - args.train_ratio:.0%}")
    print("=" * 84)

    frames = _frames_for(
        codes, args.years, cfg.scanner_b.sma_slow + 60,
        _resolve(args.cache_dir) if args.cache_dir else None,
        refresh=args.refresh,
    )
    if len(frames) < 30:
        print("시세를 받은 종목이 너무 적습니다.")
        return 1
    print()

    all_days = pd.DatetimeIndex(sorted(set().union(*(f.index for f in frames.values()))))
    splits = wf_module.make_splits(all_days, train_ratio=args.train_ratio)

    # 비교할 손절 설정들. 학습 구간 성적으로 고르고 검증 구간에서 시험합니다.
    base = cfg.backtest_kr
    settings: list[tuple[str, object]] = [
        ("고정 3% (지금)", replace(base, atr_stop_mult=0.0, stop_loss_pct=3.0)),
        ("고정 5%", replace(base, atr_stop_mult=0.0, stop_loss_pct=5.0)),
        ("고정 8%", replace(base, atr_stop_mult=0.0, stop_loss_pct=8.0)),
        ("변동성 ATR×1.5", replace(base, atr_stop_mult=1.5)),
        ("변동성 ATR×2", replace(base, atr_stop_mult=2.0)),
        ("변동성 ATR×3", replace(base, atr_stop_mult=3.0)),
    ]

    results = []
    for name, setting in settings:
        print(f"  {name} 검증 중...")
        results.append(
            wf_module.evaluate_setting(
                name, frames, setting, cfg.scanner_b, splits, market_ok
            )
        )

    print()
    print(wf_module.report(results, splits))

    out = _output_dir(cfg)
    pd.DataFrame([
        {
            "설정": r.setting,
            "학습PF": r.train["profit_factor"], "검증PF": r.test["profit_factor"],
            "변화율": round(r.decay, 1),
            "학습매매": r.train_trades, "검증매매": r.test_trades,
            "학습승률": r.train["win_rate_pct"], "검증승률": r.test["win_rate_pct"],
            "통과": r.survives,
        }
        for r in results
    ]).to_csv(out / "kr_walkforward.csv", index=False)
    print(f"\n결과 저장: {out}/kr_walkforward.csv")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """저장된 시세 상태를 보거나 지웁니다."""
    cache = PriceCache(_resolve(args.cache_dir))

    if args.clear:
        removed = cache.clear()
        print(f"{removed:,}개 파일을 지웠습니다: {cache.directory}")
        return 0

    info = cache.info()
    codes = cache.stored_codes()
    print(f"폴더: {cache.directory}")
    if not codes:
        print("저장된 시세가 없습니다. 백테스트를 한 번 돌리면 쌓입니다.")
        return 0

    print(f"{info.as_line()}" if info else f"파일 {len(codes):,}개")
    total = sum(
        path.stat().st_size
        for path in (cache.path_for(c) for c in codes)
        if path.exists()
    )
    print(f"파일 {len(codes):,}개 · {total / 1024 / 1024:.1f} MB")
    print(f"예시: {', '.join(codes[:8])}{' ...' if len(codes) > 8 else ''}")
    print()
    print("지우려면 --clear 를 붙이세요. 다음 실행에서 새로 받습니다.")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """이미 나온 백테스트 결과를 뜯어봅니다. 새 데이터가 필요 없습니다."""
    cfg = Config.load(args.config)
    out = _output_dir(cfg)

    path = _resolve(args.file) if args.file else None
    if path is None:
        candidates = sorted(out.glob("kr_backtest_trades*.csv")) + sorted(
            out.glob("kr_portfolio_*.csv")
        )
        if not candidates:
            print(f"매매 기록을 찾지 못했습니다. {out} 안에 CSV 가 있어야 합니다.")
            print("먼저 backtest-kr 또는 portfolio-kr 을 돌려 주세요.")
            return 1
        path = candidates[-1]
        print(f"파일: {path.name}\n")

    try:
        trades = analyze.load(path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"오류: {exc}")
        return 1

    if trades.empty:
        print("매매 기록이 비어 있습니다.")
        return 1

    print(analyze.report(trades, top=args.top))

    if args.by_period:
        print()
        print("── 분기별 성적 ──")
        print(analyze.by_period(trades).to_string(
            float_format=lambda v: f"{v:,.2f}"
        ))
    return 0


def cmd_factors_kr(args: argparse.Namespace) -> int:
    """알려진 요인들이 국내장에서 실제로 통했는지 확인합니다."""
    print("=" * 74)
    print(f"[요인 검정] {args.market} · 최근 {args.years}년 · 월 단위 리밸런싱")
    print("=" * 74)
    print("전략을 만들어 검증하는 게 아니라, 기준 하나로 종목을 줄 세워")
    print("상위 그룹과 하위 그룹의 이후 수익률을 비교합니다.")
    print("차이가 없으면 그 기준은 쓸모가 없다는 뜻입니다.\n")

    if args.source == "krx":
        days = factor_data.month_ends(args.years)
        print(f"리밸런싱일 {len(days)}회 — KRX 에서 전 종목 단면을 받아옵니다.")
        try:
            snapshots = factor_data.collect(days, market=args.market)
        except DataUnavailable as exc:
            print(f"\nKRX 를 쓸 수 없습니다: {exc}")
            print("--source fdr 로 다시 시도해 보세요 (로그인 불필요).")
            return 1
        if len(snapshots) < 3:
            print("\n받아온 회차가 너무 적어 검정할 수 없습니다.")
            return 1
        prices, matrices = factor_data.build_matrices(
            snapshots,
            momentum_months=args.momentum_months,
            volatility_months=args.volatility_months,
        )
    else:
        print(f"{args.market} 종목 목록을 받아옵니다...")
        listing = factor_data.listing_with_size(args.market, top=args.top)
        print(f"대상 {len(listing):,}종목 — 시세를 받아옵니다 (종목당 1~2초).")
        frames = factor_data.collect_fdr(listing["code"].tolist(), years=args.years)
        if len(frames) < 30:
            print("\n시세를 받은 종목이 너무 적어 검정할 수 없습니다.")
            return 1
        prices, matrices = factor_data.build_from_fdr(
            frames,
            momentum_months=args.momentum_months,
            volatility_months=args.volatility_months,
            listing=listing,
        )
    print(f"\n요인 {len(matrices)}개 · 종목 {prices.shape[1]:,}개 · 회차 {len(prices)}회\n")

    if args.debug:
        # 수익률이 이상할 때 원본 가격을 직접 봅니다. 계산이 틀린 것인지
        # 데이터가 이상한 것인지는 숫자를 봐야 알 수 있습니다.
        print("── 가격 원본 확인 ──")
        sample = prices.iloc[:6, :4]
        print(sample.to_string(float_format=lambda v: f"{v:,.0f}"))
        print()
        first = prices.iloc[:6]
        step = first.pct_change() * 100.0
        print("회차별 전 종목 평균 등락률 (앞 6회)")
        for day, row in step.iterrows():
            valid = row.dropna()
            if valid.empty:
                continue
            print(f"  {day:%Y-%m-%d}  평균 {valid.mean():>+7.2f}%  "
                  f"중앙 {valid.median():>+7.2f}%  종목 {len(valid):,}")
        print()
        counts = prices.notna().sum(axis=1)
        print("회차별 가격이 있는 종목 수")
        print("  " + " · ".join(
            f"{d:%y-%m}:{c:,}" for d, c in list(counts.items())[:10]
        ))
        print("── 확인 끝 ──\n")

    results = []
    for name, matrix in matrices.items():
        try:
            r = factors.evaluate(
                name,
                factor_data.replace_inf(matrix),
                prices,
                higher_is_better=factor_data.direction_for(name),
                quantiles=args.quantiles,
                min_names=args.min_names,
            )
        except ValueError as exc:
            print(f"  ! {name}: {exc}")
            continue
        results.append(r)
        print(r.as_report())
        print()

    print(factors.compare(results))

    cfg = Config.load(args.config)
    out = _output_dir(cfg)
    pd.DataFrame([
        {
            "요인": r.name,
            "스프레드": r.mean_spread,
            "t값": r.t_stat,
            "Q1승률": r.hit_rate,
            "계단": r.monotonic,
            "회차": r.periods,
            **{q: v for q, v in r.mean_by_quantile.items()},
        }
        for r in results
    ]).to_csv(out / f"kr_factors_{args.market}.csv", index=False)
    print(f"\n결과 저장: {out}/kr_factors_{args.market}.csv")
    return 0


def cmd_portfolio_kr(args: argparse.Namespace) -> int:
    """실제로 돈을 굴리듯 검증합니다 — 자본 한도와 보유 종목 수 제한."""
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)

    market_ok = None
    print("=" * 58)
    print(f"자본 {args.cash:,.0f}원 · 동시 보유 최대 {args.max_positions}종목")
    _apply_cost_overrides(cfg, args)
    if args.market_filter:
        index = fetch_index(cfg.market_filter.index_code)
        market_ok = mf_module.tradable_series(index, cfg.market_filter)
        print(
            f"✅ 시장 필터 켬 — 전체 {len(market_ok)}일 중 "
            f"매수 허용 {int(market_ok.sum())}일 "
            f"({market_ok.mean() * 100:.1f}%)"
        )
    else:
        print("⚠️ 시장 필터 꺼짐 — 하락장에서도 매수합니다 (--market-filter 로 켬)")
    print("=" * 58)

    frames = _frames_for(
        codes, args.years, cfg.scanner_b.sma_slow + 5,
        _resolve(args.cache_dir) if args.cache_dir else None,
        refresh=args.refresh,
    )

    rows = [
        bt_module.signal_rows(code, daily, cfg.scanner_b, market_ok)
        for code, daily in frames.items()
    ]
    rows = [r for r in rows if not r.empty]
    if not rows:
        print("신호가 하나도 없습니다.")
        return 0

    allsig = pd.concat(rows)
    allsig["score"] = [
        ranking.score(
            gap_pct=r.gap_pct, turnover=r.turnover, price=r.price,
            sma_slow=r.sma_slow, today_high=r.today_high, cfg=cfg.ranking,
        ).total
        for r in allsig.itertuples()
    ]
    print(f"신호 {len(allsig):,}건 — 이 중 자리가 나는 것만 삽니다.")

    result = pf_module.run(
        allsig, frames, cfg.backtest_kr,
        start_cash=args.cash, max_positions=args.max_positions, names=names,
    )
    st = pf_module.summarize(result)

    out = _output_dir(cfg)
    tag = f"pos{args.max_positions}" + ("_filtered" if args.market_filter else "")
    pd.DataFrame([t.__dict__ for t in result.trades]).to_csv(
        out / f"kr_portfolio_{tag}.csv", index=False
    )
    if result.equity is not None:
        result.equity.to_frame("equity").to_csv(out / f"kr_equity_{tag}.csv")

    print("\n".join([
        "", "=" * 58,
        "[포트폴리오 검증] 실제로 굴렸다면",
        "=" * 58,
        f"  시작 자본       {st['start_cash']:>15,.0f}원",
        f"  최종 자산       {st['end_value']:>15,.0f}원",
        f"  총 수익률       {st['total_return_pct']:>14.2f}%   ({st['years']}년)",
        f"  연평균(CAGR)    {st['cagr_pct']:>14.2f}%",
        f"  최대 낙폭       {st['max_drawdown_pct']:>14.2f}%   ← 중간에 얼마나 물렸나",
        "-" * 58,
        f"  매매            {st['trades']:>14,}건",
        f"  승률            {st['win_rate_pct']:>14.2f}%",
        f"  평균 이익       {st['avg_win_pct']:>14.2f}%",
        f"  평균 손실       {st['avg_loss_pct']:>14.2f}%",
        f"  손익비(PF)      {st['profit_factor']:>14}",
        f"  평균 보유       {st['avg_hold_days']:>14.1f}일",
        "-" * 58,
        f"  자리가 없어 넘긴 신호  {st['skipped_no_slot']:,}건",
        f"  현금이 모자라 넘긴 신호 {st['skipped_no_cash']:,}건",
        "",
        "  ※ 신호는 종가로 판정하고 진입은 다음날 시가입니다.",
        "  ※ 손절과 익절이 같은 날 닿으면 손절로 처리했습니다.",
        "  ※ 수수료·증권거래세·슬리피지가 모두 반영된 금액입니다.",
        "=" * 58,
    ]))
    print(f"\n결과 저장: {out}/kr_portfolio_{tag}.csv")
    return 0


def cmd_backtest_kr(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)

    # 시장 필터를 켜면 지수 상태가 나쁜 날의 신호는 버립니다.
    # 켜졌는지 여부를 시작할 때 크게 보여줍니다. 1~2시간 돌린 뒤에야
    # 옵션이 빠진 걸 알게 되면 그 시간이 통째로 날아갑니다.
    market_ok = None
    print("=" * 58)
    _apply_cost_overrides(cfg, args)
    if args.market_filter:
        index = fetch_index(cfg.market_filter.index_code)
        market_ok = mf_module.tradable_series(index, cfg.market_filter)
        allowed, total_days = int(market_ok.sum()), len(market_ok)
        print(
            f"✅ 시장 필터 켬 — {cfg.market_filter.index_name} 기준\n"
            f"   전체 {total_days}일 중 매수 허용 {allowed}일 "
            f"({allowed / total_days * 100:.1f}%)"
        )
    else:
        print(
            "⚠️ 시장 필터 꺼짐 — 하락장에서도 매수한 것으로 계산됩니다.\n"
            "   켜려면 명령 끝에 --market-filter 를 붙이세요."
        )
    if args.top_n:
        print(f"✅ 점수 상위 켬 — 하루 최대 {args.top_n}종목, 최소 {args.min_score}점")
    print("=" * 58)

    # 시세를 한 번만 받아 재사용합니다. 점수 상위만 고르려면 전 종목의
    # 신호를 먼저 모아야 해서 두 번 훑어야 하는데, 두 번 받으면
    # 시간이 두 배로 걸립니다.
    frames = _frames_for(
        codes, args.years, cfg.scanner_b.sma_slow + 5,
        _resolve(args.cache_dir) if args.cache_dir else None,
        refresh=args.refresh,
    )

    picked = _pick_top_signals(frames, cfg, market_ok, args) if args.top_n else None

    all_trades: list[bt_module.Trade] = []
    per_code: list[dict] = []

    for code, daily in frames.items():
        allowed = picked.get(code, set()) if picked is not None else None
        trades = bt_module.run(
            code, daily, cfg.backtest_kr, cfg.scanner_b, market_ok, allowed
        )
        all_trades.extend(trades)
        stats = bt_module.summarize(trades)
        stats["code"] = code
        stats["name"] = names.get(code, "")
        per_code.append(stats)
        print(
            f"  {code} {names.get(code, ''):<12} 매매 {stats['trades']:>3}건  "
            f"승률 {stats['win_rate_pct']:>5.1f}%  손익 {stats['total_pnl']:>12,.0f}원"
        )

    total = bt_module.summarize(all_trades)
    if total["trades"] == 0 and per_code:
        print(
            "\n⚠️ 매매가 한 건도 없습니다. 전략 결과가 아니라 설정 문제일 수 있습니다.\n"
            f"   지금 투입금은 {cfg.backtest_kr.capital_per_trade:,.0f}원입니다. "
            "주가보다 작으면 한 주도 못 사서 신호가 전부 무시됩니다.\n"
            "   config.json 의 backtest_kr.capital_per_trade 를 확인하세요."
        )

    # 조건마다 결과 파일을 구분해 나중에 나란히 비교할 수 있게 합니다.
    suffix = ("_filtered" if args.market_filter else "") + (
        f"_top{args.top_n}" if args.top_n else ""
    )
    out = _output_dir(cfg)
    bt_module.trades_to_frame(all_trades).to_csv(
        out / f"kr_backtest_trades{suffix}.csv", index=False
    )
    pd.DataFrame(per_code).to_csv(out / f"kr_backtest_by_code{suffix}.csv", index=False)

    bt = cfg.backtest_kr
    print("\n".join([
        "", "=" * 58,
        "[국내장 백테스트 요약] Trend Join Long",
        "=" * 58,
        f"  대상 종목        {len(per_code)}",
        f"  총 매매          {total['trades']}건",
        f"  승률             {total['win_rate_pct']}%",
        f"  총 손익          {total['total_pnl']:,.0f}원",
        f"  평균 수익률      {total['avg_return_pct']}% / 매매",
        f"  평균 이익        {total['avg_win_pct']}%",
        f"  평균 손실        {total['avg_loss_pct']}%",
        f"  손익비(PF)       {total['profit_factor']}",
        f"  최대 낙폭        {total['max_drawdown']:,.0f}원",
        f"  평균 보유        {total['avg_hold_days']}일",
        "-" * 58,
        f"  조건: 손절 {bt.stop_loss_pct}% / 익절 {bt.take_profit_pct}%"
        f" / 최대보유 {bt.max_hold_days}일",
        f"  시장 필터: {'켬' if args.market_filter else '끔'}",
        f"  점수 상위: {f'하루 {args.top_n}종목 (최소 {args.min_score}점)' if args.top_n else '전체'}",
        f"  투입금: 1회 {bt.capital_per_trade:,.0f}원",
        f"  비용: 수수료 {bt.commission_pct}% x2 / 증권거래세 {bt.sell_tax_pct}%"
        f" / 슬리피지 {bt.slippage_pct}% x2",
        "",
        "  ※ 조건 3(시가 위 유지)은 일봉 백테스트에서 빠져 있습니다.",
        "  ※ 손절·익절이 같은 날 함께 닿으면 손절로 처리했습니다.",
        "  ※ 증권거래세율은 해마다 바뀝니다. 현재 요율과 본인 증권사",
        "     수수료로 config.json 의 backtest_kr 을 맞춰 주세요.",
        "=" * 58,
    ]))
    print(f"\n결과 저장: {out}/kr_backtest_trades{suffix}.csv")
    return 0


def cmd_kr_universe(args: argparse.Namespace) -> int:
    """코스피·코스닥 전 종목 목록을 뽑아 파일로 저장합니다."""
    frame = list_market(args.market)
    lines = [
        f"# {args.market} 전 종목 ({len(frame)}종목)",
        f"# 생성: {_timestamp_kr()}",
        "",
    ]
    lines += [f"{r.code}  {r.name}" for r in frame.itertuples()]
    target = _resolve(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(frame)}종목 저장: {target}")
    return 0


def cmd_test_telegram(args: argparse.Namespace) -> int:
    text = f"[연결 테스트] {_timestamp()}\n텔레그램 알림이 정상 동작합니다."
    try:
        ok = send(text, dry_run=args.dry_run)
    except TelegramNotConfigured as exc:
        print(f"실패: {exc}")
        return 1
    print("전송 성공" if ok else "전송 실패 — 위 오류 메시지를 확인하세요.")
    return 0 if ok else 1


def cmd_dart_check(args: argparse.Namespace) -> int:
    """인증키가 실제로 동작하는지 먼저 확인합니다."""
    try:
        key = dart_kr.api_key(getattr(args, "api_key", None))
    except dart_kr.DartNotConfigured as exc:
        print(f"실패: {exc}")
        return 1

    print("DART 에 연결해 회사 목록을 받는 중입니다. 처음이면 30초쯤 걸립니다...")
    result = dart_kr.check(key, cache_dir=args.cache_dir)
    print(("✅ " if result.ok else "❌ ") + result.message)
    return 0 if result.ok else 1


def cmd_dart_company(args: argparse.Namespace) -> int:
    """한 회사를 공시로 훑습니다."""
    try:
        key = dart_kr.api_key(getattr(args, "api_key", None))
    except dart_kr.DartNotConfigured as exc:
        print(f"실패: {exc}")
        return 1

    try:
        index = dart_kr.load_corp_index(key, args.cache_dir, refresh=args.refresh)
        item = dart_kr.brief(key, args.code, index, years=args.years, days=args.days)
    except dart_kr.DartError as exc:
        print(f"실패: {exc}")
        return 1

    print(dart_kr.report(item))

    if args.out:
        target = _resolve(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dart_kr.report(item) + "\n", encoding="utf-8")
        print(f"\n저장: {target}")
    return 0


def cmd_dart_events(args: argparse.Namespace) -> int:
    """여러 종목의 최근 공시에서 눈여겨볼 건만 모아 봅니다."""
    try:
        key = dart_kr.api_key(getattr(args, "api_key", None))
    except dart_kr.DartNotConfigured as exc:
        print(f"실패: {exc}")
        return 1

    if args.universe:
        codes = [r.code for r in read_universe_kr(args.universe)]
    else:
        codes = [c.strip() for c in (args.codes or "").split(",") if c.strip()]
    if not codes:
        print("종목이 없습니다. --codes 또는 --universe 를 주세요.")
        return 1
    if args.limit:
        codes = codes[: args.limit]

    try:
        index = dart_kr.load_corp_index(key, args.cache_dir, refresh=args.refresh)
    except dart_kr.DartError as exc:
        print(f"실패: {exc}")
        return 1

    today = pd.Timestamp.today().normalize()
    start = (today - pd.Timedelta(days=args.days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    print(f"{len(codes)}종목의 최근 {args.days}일 공시를 확인합니다...")
    found, missing, failed = [], 0, 0
    for i, code in enumerate(codes, 1):
        corp_code = dart_kr.find_corp_code(index, code)
        if not corp_code:
            missing += 1
            continue
        try:
            flagged = dart_kr.flag_events(
                dart_kr.filings(key, corp_code, start, end)
            )
        except dart_kr.DartError as exc:
            failed += 1
            if failed <= 3:
                print(f"  {code} 조회 실패: {exc}")
            continue
        for _, row in flagged.iterrows():
            found.append({"code": code,
                          "name": dart_kr.corp_name(index, corp_code),
                          **row.to_dict()})
        if i % 50 == 0:
            print(f"  {i}/{len(codes)}...")

    if not found:
        print(f"\n규칙에 걸린 공시가 없습니다. (조회 실패 {failed}건, 미등록 {missing}건)")
        return 0

    frame = pd.DataFrame(found)
    order = {"높음": 0, "보통": 1}
    frame["_rank"] = frame["severity"].map(order).fillna(9)
    frame = (frame.sort_values(["_rank", "rcept_dt"], ascending=[True, False])
                  .drop(columns="_rank"))

    print(f"\n[사실] 최근 {args.days}일, {len(frame)}건이 규칙에 걸렸습니다.")
    print(f"       (조회 실패 {failed}건, DART 미등록 {missing}건)\n")
    for _, row in frame.iterrows():
        mark = "🔴" if row["severity"] == "높음" else "🟡"
        print(f"{mark} {row['rcept_dt']}  {row['name']}({row['code']})"
              f"  [{row['label']}] {row['report_nm']}")

    print("\n[해석] 이 목록은 '확인해 볼 거리' 입니다. 매수·매도 신호가 아닙니다.")

    if args.out:
        target = _resolve(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False, encoding="utf-8-sig")
        print(f"저장: {target}")
    return 0


def cmd_diagnose_kr(args: argparse.Namespace) -> int:
    """신호에 우위가 있는지만 봅니다 — 손절도 익절도 비용도 끄고."""
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)

    market_ok = None
    print("=" * 78)
    if args.market_filter:
        index = fetch_index(cfg.market_filter.index_code)
        market_ok = mf_module.tradable_series(index, cfg.market_filter)
        print(f"✅ 시장 필터 켬 — 매수 허용 {market_ok.mean() * 100:.1f}%")
    else:
        print("⚠️ 시장 필터 꺼짐")
    print(f"대상 {len(codes):,}종목 · 최근 {args.years}년")
    print("=" * 78)

    frames = _frames_for(
        codes, args.years, cfg.scanner_b.sma_slow + 30,
        _resolve(args.cache_dir) if args.cache_dir else None,
        refresh=args.refresh,
    )
    if len(frames) < 30:
        print("시세를 받은 종목이 너무 적습니다.")
        return 1

    print("\n같은 날 아무 종목이나 샀을 때의 평균을 먼저 구합니다 (비교 기준)...")
    market = dg_module.market_forward(frames)

    print(f"신호를 모으는 중... (조건: {args.setup})")
    parts = []
    if args.setup == "breakout":
        setup = bo_module.Setup()
        for code, daily in frames.items():
            dates = bo_module.signal_dates(daily, setup)
            if market_ok is not None and len(dates):
                허용 = market_ok.reindex(dates).fillna(False).astype(bool)
                dates = dates[허용.to_numpy()]
            if len(dates):
                parts.append(dg_module.signal_forward(code, daily, dates))
    else:
        for code, daily in frames.items():
            rows = bt_module.signal_rows(code, daily, cfg.scanner_b, market_ok)
            if rows.empty:
                continue
            parts.append(dg_module.signal_forward(code, daily, rows.index))

    if not parts:
        print("신호가 하나도 없습니다.")
        return 0
    signals = pd.concat(parts, ignore_index=True)

    edges = dg_module.edge(signals, market)
    gaps = dg_module.by_gap(signals, horizon=args.horizon)
    stops = dg_module.stop_reach(signals)

    print()
    print(dg_module.report(edges, gaps, stops, len(signals)))

    out = _output_dir(cfg)
    signals.to_csv(out / "kr_signal_forward.csv", index=False, encoding="utf-8-sig")
    print(f"\n신호별 원자료 저장: {out}/kr_signal_forward.csv")
    return 0


def cmd_case_kr(args: argparse.Namespace) -> int:
    """종목 하나를 통째로 뜯어봅니다 — 그때 우리 시스템은 뭐라고 했나."""
    cfg = Config.load(args.config)
    code = args.code.strip().upper()

    print(f"{code} 시세를 받는 중입니다...")
    try:
        daily = fetch_daily_kr(code, years=args.years)
    except DataUnavailable as exc:
        print(f"실패: {exc}")
        return 1
    if len(daily) < cfg.scanner_b.sma_slow + 5:
        print(f"일봉이 {len(daily)}행뿐입니다. 200일선을 못 그립니다.")
        return 1

    market_ok = None
    if args.market_filter:
        index = fetch_index(cfg.market_filter.index_code)
        market_ok = mf_module.tradable_series(index, cfg.market_filter)
        print(f"시장 필터 켬 — 매수 허용 {market_ok.mean() * 100:.1f}%")

    close = daily["close"]
    runup = case_module.biggest_runup(close)
    years_table = case_module.yearly(daily)

    rows = bt_module.signal_rows(code, daily, cfg.scanner_b, market_ok)
    timing_info = case_module.timing(
        pd.DatetimeIndex(rows.index) if not rows.empty else pd.DatetimeIndex([]),
        close, runup,
    )
    trades = bt_module.run(code, daily, cfg.backtest_kr, cfg.scanner_b, market_ok)

    # 그 상승을 우리 보유 규칙으로 견딜 수 있었는지.
    drops = case_module.pullback_summary(case_module.pullbacks(daily, runup))
    holds = [
        h for h in (
            case_module.hold_with_trailing(daily, runup, w)
            for w in (7.0, 15.0, 25.0, 40.0)
        ) if h is not None
    ]

    name = args.name or code
    text = case_module.report(
        code, name, daily, runup, years_table, timing_info, trades,
        max_trades=10_000 if args.all else 15, drops=drops, holds=holds,
    )
    print()
    print(text)

    if args.out:
        target = _resolve(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"\n저장: {target}")
    return 0


def cmd_journal_add(args: argparse.Namespace) -> int:
    """판단을 기록만 합니다. 매수는 하지 않습니다."""
    code = args.code.strip().upper()
    price = args.price

    # 시세를 받기 전에 먼저 막습니다. 30초 기다린 뒤 "이유가 없다" 는
    # 소리를 듣는 것만큼 김빠지는 일이 없습니다.
    if not args.why.strip():
        print("기록하지 않았습니다: '왜' 를 비워 둘 수 없습니다. "
              "이유가 없으면 나중에 채점해도 무엇이 통했는지 알 수 없습니다.")
        return 1

    if price is None:                       # 안 주면 오늘 종가를 받아옵니다
        try:
            daily = fetch_daily_kr(code, years=0.5)
            price = float(daily["close"].iloc[-1])
            print(f"{code} 최근 종가 {price:,.0f}원 을 기록합니다.")
        except (DataUnavailable, IndexError) as exc:
            print(f"시세를 못 받았습니다: {exc}")
            print("--price 로 직접 넣어 주세요.")
            return 1

    entry = jn_module.Entry(
        recorded_at=args.date or datetime.now().strftime("%Y-%m-%d"),
        code=code,
        name=args.name or code,
        price=float(price),
        conviction=args.conviction,
        horizon_days=args.horizon,
        why=args.why,
        note=args.note or "",
    )
    try:
        target = jn_module.append(entry, _resolve(args.file))
    except ValueError as exc:
        print(f"기록하지 않았습니다: {exc}")
        return 1

    print(f"기록했습니다 → {target}")
    print(f"   {entry.recorded_at}  {entry.name}({entry.code})  {entry.price:,.0f}원"
          f"  확신 {entry.conviction}  {entry.horizon_days}일 뒤 채점")
    print(f"   이유: {entry.why}")
    print("\n※ 매수는 하지 않았습니다. 기록만 했습니다.")
    return 0


def cmd_journal_list(args: argparse.Namespace) -> int:
    frame = jn_module.load(_resolve(args.file))
    if frame.empty:
        print("아직 기록이 없습니다.")
        return 0

    today = pd.Timestamp.today().normalize()
    recorded = pd.to_datetime(frame["recorded_at"], errors="coerce")
    남은날 = frame["horizon_days"] - (today - recorded).dt.days

    print(f"기록 {len(frame)}건\n")
    print("   기록일       종목                기록가    확신   채점까지")
    print("   " + "-" * 62)
    for (_, row), 남음 in zip(frame.iterrows(), 남은날):
        상태 = "채점 가능" if 남음 <= 0 else f"{int(남음):>3}일 남음"
        print(f"   {row['recorded_at']}  {str(row['name'])[:12]:<12}({row['code']})"
              f"  {row['price']:>9,.0f}   {row['conviction']}   {상태}")
    return 0


def cmd_journal_score(args: argparse.Namespace) -> int:
    """기간이 찬 기록을 채점합니다 — 코스닥 지수와 견주어서."""
    frame = jn_module.load(_resolve(args.file))
    if frame.empty:
        print(jn_module.report([], jn_module.summarize([]), pending=0))
        return 0

    ready = frame if args.now else jn_module.due(frame)
    pending = len(frame) - len(ready)

    if ready.empty:
        print(jn_module.report([], jn_module.summarize([]), pending=pending))
        return 0

    print(f"코스닥 지수를 받는 중입니다...")
    try:
        index = fetch_index(args.index, years=args.years)
    except DataUnavailable as exc:
        print(f"지수를 못 받았습니다: {exc}")
        return 1

    scored = []
    for _, row in ready.iterrows():
        try:
            daily = fetch_daily_kr(str(row["code"]), years=args.years)
        except DataUnavailable as exc:
            print(f"  {row['code']} 조회 실패: {exc}")
            continue
        result = jn_module.score_one(row, daily, index)
        if result is not None:
            scored.append(result)

    verdict = jn_module.summarize(scored)
    print()
    print(jn_module.report(scored, verdict, pending=pending))

    if scored:
        out = _output_dir(cfg := Config.load(args.config))
        pd.DataFrame([s.__dict__ for s in scored]).to_csv(
            out / "journal_scored.csv", index=False, encoding="utf-8-sig"
        )
        print(f"\n채점 결과 저장: {out}/journal_scored.csv")
    return 0


def cmd_value_fetch(args: argparse.Namespace) -> int:
    """DART 에서 전 종목 재무를 받아 저장합니다. 오래 걸리니 한 번만."""
    try:
        key = dart_kr.api_key(getattr(args, "api_key", None))
    except dart_kr.DartNotConfigured as exc:
        print(f"실패: {exc}")
        return 1

    print("회사 목록을 확인합니다...")
    try:
        index = dart_kr.load_corp_index(key, args.dart_cache, refresh=False)
    except dart_kr.DartError as exc:
        print(f"실패: {exc}")
        return 1

    if args.universe:
        codes = [r.code for r in read_universe_kr(_resolve(args.universe))]
    else:
        codes = list(val_module.listing_with_cap(args.market)["code"])
    if args.limit:
        codes = codes[: args.limit]

    target = _resolve(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 이미 받아 둔 것이 있으면 건너뜁니다. 20~40분짜리 작업이 중간에
    # 끊겼을 때, 다시 돌리면 끊긴 데부터 이어갑니다.
    기존 = pd.DataFrame()
    if target.exists() and not args.restart:
        try:
            기존 = pd.read_csv(target, dtype={"code": str, "rcept_dt": str})
        except Exception:                      # 파일이 깨졌으면 새로 받습니다
            기존 = pd.DataFrame()
    if not 기존.empty:
        받은것 = set(기존["code"])
        남은것 = [c for c in codes if c not in 받은것]
        print(f"이미 받아 둔 {len(받은것):,}종목은 건너뜁니다. "
              f"({len(남은것):,}종목 남음)")
        print("처음부터 다시 받으려면 --restart 를 붙이세요.")
        codes = 남은것

    if not codes:
        print(f"받을 것이 없습니다. 이미 {len(기존):,}종목이 저장돼 있습니다: {target}")
        return 0

    print(f"\n{len(codes):,}종목의 재무를 DART 에서 받습니다.")
    print("한 종목당 한 번씩 부르므로 20~40분쯤 걸립니다.")
    print("중간에 끊겨도 받은 데까지는 저장되니, 다시 돌리면 이어집니다.\n")

    def _save(부분: pd.DataFrame) -> None:
        """중간중간 저장합니다. 끊겨도 여기까지는 남습니다."""
        묶음 = pd.concat([기존, 부분], ignore_index=True) if not 기존.empty else 부분
        if not 묶음.empty:
            묶음.drop_duplicates(subset="code", keep="last").to_csv(
                target, index=False, encoding="utf-8-sig"
            )

    try:
        fin, 실패 = val_module.latest_financials(
            key, index, codes, years_back=args.years_back, on_partial=_save,
        )
    except KeyboardInterrupt:
        print("\n멈췄습니다. 받은 데까지는 저장돼 있습니다.")
        print(f"다시 돌리면 이어서 받습니다: {target}")
        return 1

    _save(fin)
    저장됨 = pd.read_csv(target, dtype={"code": str}) if target.exists() else fin
    print(f"\n{len(저장됨):,}종목 저장: {target}  (이번에 실패 {len(실패)}종목)")

    안읽힌것 = [c for c in val_module.NEEDED
                if c in 저장됨.columns and 저장됨[c].notna().mean() < 0.8]
    if 안읽힌것:
        print(f"⚠️ 절반 넘게 비어 있는 항목: {', '.join(안읽힌것)}")
        print("   조건 문제가 아니라 자료 문제입니다. value-kr 이 자세히 알려줍니다.")
    print("이제 value-kr 로 조건을 바꿔가며 몇 초 만에 볼 수 있습니다.")
    return 0


def cmd_value_kr(args: argparse.Namespace) -> int:
    """저장해 둔 재무로 저평가 후보를 추립니다. 몇 초면 끝납니다."""
    path = _resolve(args.fin)
    if not path.exists():
        print(f"재무 파일이 없습니다: {path}")
        print("먼저 한 번 받아야 합니다:")
        print("  python -m src.cli value-fetch --market KOSDAQ")
        return 1

    fin = pd.read_csv(path, dtype={"code": str, "rcept_dt": str})
    print(f"저장된 재무 {len(fin):,}종목 · 시세를 받는 중입니다...")
    try:
        listing = val_module.listing_with_cap(args.market)
    except DataUnavailable as exc:
        print(f"실패: {exc}")
        return 1

    rule = val_module.Screen(
        max_pbr=args.max_pbr, max_per=args.max_per,
        require_profit=not args.allow_loss,
        max_debt_ratio=args.max_debt, min_marcap=args.min_marcap * 1e8,
        min_turnover=args.min_turnover * 1e8,
    )
    screened = val_module.screen(val_module.valuation(listing, fin), rule)

    print()
    print(val_module.report(screened, rule, top=args.top))

    out = _output_dir(Config.load(args.config))
    val_module.rank(screened[screened["통과"]]).to_csv(
        out / "kr_value_candidates.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\n통과 종목 저장: {out}/kr_value_candidates.csv")
    return 0


def cmd_dart_dashboard(args: argparse.Namespace) -> int:
    """한 회사의 기업분석 화면을 HTML 한 장으로 만듭니다."""
    try:
        key = dart_kr.api_key(getattr(args, "api_key", None))
    except dart_kr.DartNotConfigured as exc:
        print(f"실패: {exc}")
        return 1

    code = args.code.strip().upper()
    try:
        index = dart_kr.load_corp_index(key, args.cache_dir, refresh=False)
        corp_code = dart_kr.find_corp_code(index, code)
        if not corp_code:
            print(f"'{code}' 에 해당하는 회사를 DART 에서 못 찾았습니다.")
            return 1
    except dart_kr.DartError as exc:
        print(f"실패: {exc}")
        return 1

    name = dart_kr.corp_name(index, corp_code) or code
    print(f"{name}({code}) 자료를 모읍니다...")

    snap = dash_module.Snapshot(
        code=code, name=name, corp_code=corp_code,
        window_days=args.days, fetched_at=_timestamp_kr(),
    )

    print("  시세...")
    try:
        daily = fetch_daily_kr(code, years=1.2)
        snap.price = float(daily["close"].iloc[-1])
        snap.price_date = str(daily.index[-1].date())
        if len(daily) >= 2:
            snap.change_pct = (daily["close"].iloc[-1] / daily["close"].iloc[-2] - 1) * 100
        한해 = daily.tail(250)
        snap.high_52w = float(한해["high"].max())
        snap.low_52w = float(한해["low"].min())
    except (DataUnavailable, IndexError) as exc:
        print(f"    시세를 못 받았습니다: {exc}")

    print("  시가총액...")
    try:
        listing = val_module.listing_with_cap(args.market)
        hit = listing[listing["code"] == code]
        if not hit.empty:
            snap.marcap = float(hit.iloc[0]["marcap"])
            snap.market = args.market
    except DataUnavailable as exc:
        print(f"    시가총액을 못 받았습니다: {exc}")

    print("  재무 추세...")
    try:
        snap.trend = dart_kr.financial_trend(key, corp_code, years=args.years)
        snap.ratios = dart_kr.derived(snap.trend)
        snap.notes = dart_kr.health_flags(snap.trend)
    except dart_kr.DartError as exc:
        print(f"    재무를 못 받았습니다: {exc}")

    print("  현금흐름...")
    try:
        snap.cash = dart_kr.cash_flow(key, corp_code, years=args.years)
    except dart_kr.DartError as exc:
        print(f"    현금흐름을 못 받았습니다: {exc}")

    print("  공시...")
    try:
        today = pd.Timestamp.today().normalize()
        listing_f = dart_kr.filings(
            key, corp_code,
            (today - pd.Timedelta(days=args.days)).strftime("%Y%m%d"),
            today.strftime("%Y%m%d"),
        )
        snap.filing_count = len(listing_f)
        snap.events = dart_kr.flag_events(listing_f)
    except dart_kr.DartError as exc:
        print(f"    공시를 못 받았습니다: {exc}")

    target = _resolve(args.out or f"output/{code}_기업분석.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dash_module.render(snap), encoding="utf-8")

    print(f"\n만들었습니다: {target}")
    print("브라우저로 여세요:")
    print(f"  start {target}")
    return 0


def _breakout_setup(args: argparse.Namespace) -> "bo_module.Setup":
    return bo_module.Setup(
        base_days=args.base_days, surge_days=args.surge_days,
        max_base_range_pct=args.max_range, min_volume_mult=args.min_volume_mult,
        max_runup_pct=args.max_runup, min_turnover=args.min_turnover * 1e8,
        breakout_lookback=args.base_days,
    )


def cmd_breakout_kr(args: argparse.Namespace) -> int:
    """조용하다 거래량이 터지며 깨어나는 종목을 찾습니다."""
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)
    setup = _breakout_setup(args)

    print(f"대상 {len(codes):,}종목 · 최근 {args.years}년 시세를 확인합니다...")
    frames = _frames_for(
        codes, args.years, setup.base_days + setup.surge_days + 10,
        _resolve(args.cache_dir) if args.cache_dir else None,
        refresh=args.refresh,
    )
    if not frames:
        print("시세를 하나도 받지 못했습니다.")
        return 1

    hits = bo_module.scan_today(frames, setup, names=names)
    print()
    print(bo_module.report(hits, setup, top=args.top))

    if hits:
        out = _output_dir(cfg)
        pd.DataFrame([h.__dict__ for h in hits]).to_csv(
            out / "kr_breakout.csv", index=False, encoding="utf-8-sig"
        )
        print(f"\n저장: {out}/kr_breakout.csv")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Claude + TradingView 종목 자동 분석 시스템",
    )
    parser.add_argument("--config", help="설정 파일 경로 (기본 config.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("scan-a", help="프리마켓 갭 스캐너")
    a.add_argument("--universe", help="티커 목록 파일")
    a.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    a.add_argument("--no-news", action="store_true", help="뉴스 헤드라인 조회 생략")
    a.add_argument("--force", action="store_true", help="실행 시간대 밖에서도 실행")
    a.set_defaults(func=cmd_scan_a)

    b = sub.add_parser("scan-b", help="전략 스캐너 (Trend Join Long)")
    b.add_argument("--universe", help="티커 목록 파일 (없으면 스캐너 A 결과 사용)")
    b.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    b.add_argument("--force", action="store_true", help="실행 시간대 밖에서도 실행")
    b.set_defaults(func=cmd_scan_b)

    c = sub.add_parser("backtest", help="과거 데이터로 전략 검증")
    c.add_argument("--universe", help="티커 목록 파일")
    c.add_argument("--csv-dir", help="TICKER.csv 가 든 폴더 (없으면 야후에서 내려받음)")
    c.add_argument("--period", default="2y", help="내려받을 기간 (기본 2y)")
    c.set_defaults(func=cmd_backtest)

    ka = sub.add_parser("scan-kr-a", help="[국내] 시가갭 스캐너")
    ka.add_argument("--universe", help="종목코드 목록 파일")
    ka.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    ka.add_argument("--force", action="store_true", help="실행 시간대 밖에서도 실행")
    ka.add_argument("--web-dir", default="../stocks", help="알림 기록을 둘 폴더")
    ka.set_defaults(func=cmd_scan_kr_a)

    kb = sub.add_parser("scan-kr-b", help="[국내] 전략 스캐너 (Trend Join Long)")
    kb.add_argument("--universe", help="종목코드 목록 파일 (없으면 스캐너 A 결과 사용)")
    kb.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    kb.add_argument("--force", action="store_true", help="실행 시간대 밖에서도 실행")
    kb.add_argument("--web", action="store_true", help="웹페이지(HTML) 갱신")
    kb.add_argument("--web-dir", default="../stocks", help="웹페이지를 저장할 폴더")
    kb.set_defaults(func=cmd_scan_kr_b)

    m = sub.add_parser("market", help="[국내] 시장 상태만 확인")
    m.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    m.add_argument("--detail", action="store_true", help="판정에 쓴 원본 값 표시")
    m.set_defaults(func=cmd_market)

    w = sub.add_parser("watchlist", help="[국내] 내일 관찰 후보 추리기 (장 마감 후)")
    w.add_argument("--universe", help="종목코드 목록 파일")
    w.add_argument("--web-dir", default="../stocks", help="결과를 둘 폴더")
    w.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    w.set_defaults(func=cmd_watchlist)

    ds = sub.add_parser("daily-summary", help="[국내] 오늘 마감 요약 보내기")
    ds.add_argument("--web-dir", default="../stocks", help="기록이 있는 폴더")
    ds.add_argument("--url", default="", help="웹페이지 주소 (메시지에 첨부)")
    ds.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    ds.set_defaults(func=cmd_daily_summary)

    wf = sub.add_parser(
        "walkforward-kr",
        help="[국내] 손절 설정을 앞 구간에서 고르고 뒤 구간에서 시험 (과최적화 검사)",
    )
    wf.add_argument("--universe", help="종목코드 목록 파일")
    wf.add_argument("--years", type=float, default=5.0, help="전체 기간 (년)")
    wf.add_argument(
        "--train-ratio", type=float, default=0.6,
        help="앞쪽 비율을 학습에 사용 (기본 0.6 = 앞 60퍼센트)",
    )
    wf.add_argument("--market-filter", action="store_true", help="시장 필터 적용")
    wf.add_argument(
        "--cache-dir", default="data/cache",
        help="시세 저장 폴더. 두 번째 실행부터 몇 초로 끝납니다",
    )
    wf.add_argument(
        "--refresh", action="store_true",
        help="저장된 시세를 무시하고 새로 받기",
    )
    _add_cost_args(wf)
    wf.set_defaults(func=cmd_walkforward_kr)

    ca = sub.add_parser("cache", help="저장된 시세 상태 보기 / 지우기")
    ca.add_argument("--cache-dir", default="data/cache", help="시세 저장 폴더")
    ca.add_argument("--clear", action="store_true", help="저장된 시세를 전부 지우기")
    ca.set_defaults(func=cmd_cache)

    an = sub.add_parser(
        "analyze",
        help="이미 나온 백테스트 결과 분석 (새 데이터 불필요)",
    )
    an.add_argument("--file", help="매매 기록 CSV (없으면 가장 최근 것)")
    an.add_argument("--top", type=int, default=10, help="쏠림을 볼 종목 수")
    an.add_argument("--by-period", action="store_true", help="분기별 성적도 표시")
    an.set_defaults(func=cmd_analyze)

    fk = sub.add_parser(
        "factors-kr",
        help="[국내] 알려진 요인들이 실제로 통했는지 검정 (밸류·모멘텀·소형주 등)",
    )
    fk.add_argument("--market", default="KOSDAQ", help="KOSPI / KOSDAQ (기본 KOSDAQ)")
    fk.add_argument(
        "--source", choices=["fdr", "krx"], default="fdr",
        help="fdr=로그인 불필요(기본) / krx=PER·PBR 까지 받지만 KRX 계정 필요",
    )
    fk.add_argument(
        "--top", type=int, default=500,
        help="시가총액 상위 몇 종목만 볼지 (0=전체, 기본 500)",
    )
    fk.add_argument("--years", type=float, default=5.0, help="검정 기간 (년, 기본 5)")
    fk.add_argument("--quantiles", type=int, default=5, help="몇 개 그룹으로 나눌지")
    fk.add_argument("--min-names", type=int, default=30, help="회차당 최소 종목 수")
    fk.add_argument("--momentum-months", type=int, default=6, help="모멘텀 기간 (개월)")
    fk.add_argument("--volatility-months", type=int, default=6, help="변동성 기간 (개월)")
    fk.add_argument(
        "--debug", action="store_true",
        help="가격 원본과 회차별 등락률을 출력 (수익률이 이상할 때)",
    )
    fk.set_defaults(func=cmd_factors_kr)

    pk = sub.add_parser(
        "portfolio-kr",
        help="[국내] 실제로 돈을 굴리듯 검증 (자본·보유종목 수 제한)",
    )
    pk.add_argument("--universe", help="종목코드 목록 파일")
    pk.add_argument("--years", type=float, default=3.0, help="검증 기간 (년)")
    pk.add_argument(
        "--cash", type=float, default=5_000_000.0,
        help="시작 자본 (원, 기본 500만). 종목당 배분액이 주가보다 작으면 못 삽니다",
    )
    pk.add_argument(
        "--max-positions", type=int, default=3,
        help="동시에 들고 있을 최대 종목 수 (기본 3)",
    )
    pk.add_argument(
        "--market-filter", action="store_true",
        help="지수 상태가 나쁜 날은 매수하지 않음",
    )
    pk.add_argument(
        "--cache-dir", default="data/cache",
        help="시세 저장 폴더. 두 번째 실행부터 훨씬 빠릅니다",
    )
    pk.add_argument("--refresh", action="store_true", help="시세를 새로 받기")
    _add_cost_args(pk)
    pk.set_defaults(func=cmd_portfolio_kr)

    kc = sub.add_parser("backtest-kr", help="[국내] 과거 데이터로 전략 검증")
    kc.add_argument("--universe", help="종목코드 목록 파일")
    kc.add_argument("--years", type=float, default=3.0, help="검증 기간 (년, 기본 3)")
    kc.add_argument(
        "--market-filter", action="store_true",
        help="지수 상태가 나쁜 날의 신호는 버리고 검증",
    )
    kc.add_argument(
        "--top-n", type=int, default=0,
        help="같은 날 신호가 여럿이면 점수 상위 N종목만 매수 (0=전체)",
    )
    kc.add_argument(
        "--min-score", type=float, default=0.0,
        help="이 점수 미만은 매수하지 않음",
    )
    kc.add_argument(
        "--cache-dir", default="data/cache",
        help="시세 저장 폴더. 두 번째 실행부터 훨씬 빠릅니다",
    )
    kc.add_argument("--refresh", action="store_true", help="시세를 새로 받기")
    _add_cost_args(kc)
    kc.set_defaults(func=cmd_backtest_kr)

    ku = sub.add_parser("kr-universe", help="[국내] 전 종목 목록 뽑기")
    ku.add_argument("--market", default="KOSPI", help="KOSPI / KOSDAQ / KRX")
    ku.add_argument("--out", default="data/universe_kr_all.txt", help="저장할 파일")
    ku.set_defaults(func=cmd_kr_universe)

    bk = sub.add_parser(
        "breakout-kr",
        help="[국내] 조용하다 거래량 터지며 깨어나는 종목 찾기",
    )
    bk.add_argument("--universe", help="종목 목록 파일")
    bk.add_argument("--years", type=float, default=2.0, help="시세 조회 기간(년)")
    bk.add_argument("--base-days", type=int, default=60,
                    help="'조용했나' 를 보는 기간(거래일)")
    bk.add_argument("--surge-days", type=int, default=5,
                    help="거래량이 터진 걸 보는 기간(거래일)")
    bk.add_argument("--max-range", type=float, default=45.0,
                    help="박스 폭 상한(퍼센트). 좁을수록 조용했다는 뜻")
    bk.add_argument("--min-volume-mult", type=float, default=3.0,
                    help="평소 거래대금의 몇 배 이상이어야 하는지")
    bk.add_argument("--max-runup", type=float, default=40.0,
                    help="이미 이만큼 넘게 올랐으면 제외(퍼센트)")
    bk.add_argument("--min-turnover", type=float, default=5.0,
                    help="하루 거래대금 하한(억원)")
    bk.add_argument("--top", type=int, default=20, help="몇 종목까지 보여줄지")
    bk.add_argument("--cache-dir", default="data/cache", help="시세 저장 폴더")
    bk.add_argument("--refresh", action="store_true", help="시세를 새로 받기")
    bk.set_defaults(func=cmd_breakout_kr)

    vf = sub.add_parser(
        "value-fetch",
        help="[국내] DART 에서 전 종목 재무 받아두기 (20~40분, 한 번만)",
    )
    vf.add_argument("--market", default="KOSDAQ", help="KOSPI / KOSDAQ")
    vf.add_argument("--universe", help="종목 목록 파일 (없으면 시장 전체)")
    vf.add_argument("--years-back", type=int, default=2,
                    help="최근 몇 개 사업연도까지 뒤져볼지")
    vf.add_argument("--limit", type=int, default=0, help="앞 N종목만 (시험용)")
    vf.add_argument("--out", default="data/fin_kr.csv", help="저장할 파일")
    vf.add_argument("--restart", action="store_true",
                    help="이미 받아 둔 것을 무시하고 처음부터 다시 받기")
    vf.add_argument("--api-key", help="직접 넘길 때만")
    vf.add_argument("--dart-cache", default="data/cache/dart", help="회사 목록 폴더")
    vf.set_defaults(func=cmd_value_fetch)

    vk = sub.add_parser(
        "value-kr",
        help="[국내] 저평가 후보 추리기 (받아둔 재무로, 몇 초)",
    )
    vk.add_argument("--fin", default="data/fin_kr.csv", help="받아둔 재무 파일")
    vk.add_argument("--market", default="KOSDAQ", help="KOSPI / KOSDAQ")
    vk.add_argument("--max-pbr", type=float, default=1.0, help="PBR 상한")
    vk.add_argument("--max-per", type=float, default=15.0,
                    help="PER 상한. 0 이면 PER 조건을 끕니다")
    vk.add_argument("--allow-loss", action="store_true", help="영업적자도 허용")
    vk.add_argument("--max-debt", type=float, default=200.0, help="부채비율 상한(%%)")
    vk.add_argument("--min-marcap", type=float, default=300.0,
                    help="시가총액 하한(억원)")
    vk.add_argument("--min-turnover", type=float, default=5.0,
                    help="하루 거래대금 하한(억원)")
    vk.add_argument("--top", type=int, default=30, help="몇 종목까지 보여줄지")
    vk.set_defaults(func=cmd_value_kr)

    ja = sub.add_parser(
        "journal-add",
        help="[국내] 판단을 기록만 하기 (매수 안 함)",
    )
    ja.add_argument("--code", required=True, help="종목코드 6자리")
    ja.add_argument("--name", help="종목명")
    ja.add_argument("--why", required=True, help="왜 오를 거라 보는가 — 반드시 적습니다")
    ja.add_argument("--conviction", default="중", choices=["상", "중", "하"],
                    help="확신도")
    ja.add_argument("--horizon", type=int, default=90, help="며칠 뒤에 채점할지")
    ja.add_argument("--price", type=float, help="기록가. 없으면 최근 종가를 받아옵니다")
    ja.add_argument("--date", help="기록일 YYYY-MM-DD. 없으면 오늘")
    ja.add_argument("--note", help="덧붙일 말")
    ja.add_argument("--file", default="data/journal.csv", help="기록 파일")
    ja.set_defaults(func=cmd_journal_add)

    jl = sub.add_parser("journal-list", help="[국내] 기록해 둔 판단 보기")
    jl.add_argument("--file", default="data/journal.csv", help="기록 파일")
    jl.set_defaults(func=cmd_journal_list)

    js = sub.add_parser(
        "journal-score",
        help="[국내] 기간이 찬 기록을 채점 (코스닥 지수 대비)",
    )
    js.add_argument("--file", default="data/journal.csv", help="기록 파일")
    js.add_argument("--index", default="KQ11", help="비교할 지수. KQ11=코스닥")
    js.add_argument("--years", type=float, default=2.0, help="시세 조회 기간")
    js.add_argument("--now", action="store_true",
                    help="기간이 안 찼어도 지금까지로 채점 (참고용)")
    js.set_defaults(func=cmd_journal_score)

    ck = sub.add_parser(
        "case-kr",
        help="[국내] 종목 하나를 통째로 뜯어보기 (그때 우리 신호는 뭐라고 했나)",
    )
    ck.add_argument("--code", required=True, help="종목코드 6자리")
    ck.add_argument("--name", help="화면에 보일 이름 (없으면 코드)")
    ck.add_argument("--years", type=float, default=10.0, help="조회 기간 (년)")
    ck.add_argument("--market-filter", action="store_true", help="시장 필터 적용")
    ck.add_argument("--all", action="store_true", help="매매를 전부 보여주기")
    ck.add_argument("--out", help="결과를 파일로 저장")
    ck.set_defaults(func=cmd_case_kr)

    dgk = sub.add_parser(
        "diagnose-kr",
        help="[국내] 신호에 우위가 있는지 진단 (손절·익절·비용 전부 끔)",
    )
    dgk.add_argument("--universe", help="종목코드 목록 파일")
    dgk.add_argument("--years", type=float, default=5.0, help="조회 기간 (년)")
    dgk.add_argument("--horizon", type=int, default=5, help="갭별 성적을 볼 보유일수")
    dgk.add_argument("--setup", default="trendjoin", choices=["trendjoin", "breakout"],
                     help="어떤 조건을 진단할지. trendjoin=기존 추세추종, "
                          "breakout=조용하다 깨어나는 종목")
    dgk.add_argument("--market-filter", action="store_true", help="시장 필터 적용")
    dgk.add_argument("--cache-dir", default="data/cache", help="시세 저장 폴더")
    dgk.add_argument("--refresh", action="store_true", help="시세를 새로 받기")
    dgk.set_defaults(func=cmd_diagnose_kr)

    dd = sub.add_parser(
        "dart-dashboard",
        help="[국내] 한 회사의 기업분석 화면을 HTML 한 장으로",
    )
    dd.add_argument("--code", required=True, help="종목코드 6자리 또는 회사명")
    dd.add_argument("--years", type=int, default=5, help="재무를 몇 년치 볼지")
    dd.add_argument("--days", type=int, default=365, help="공시를 며칠치 볼지")
    dd.add_argument("--market", default="KOSDAQ", help="시가총액을 찾을 시장")
    dd.add_argument("--out", help="저장할 HTML 경로")
    dd.add_argument("--api-key", help="직접 넘길 때만")
    dd.add_argument("--cache-dir", default="data/cache/dart", help="회사 목록 폴더")
    dd.set_defaults(func=cmd_dart_dashboard)

    dc = sub.add_parser("dart-check", help="[국내] DART 인증키가 동작하는지 확인")
    dc.add_argument("--api-key", help="직접 넘길 때만. 보통은 DART_API_KEY 환경변수를 씁니다")
    dc.add_argument("--cache-dir", default="data/cache/dart", help="회사 목록 저장 폴더")
    dc.set_defaults(func=cmd_dart_check)

    dco = sub.add_parser(
        "dart-company",
        help="[국내] 한 회사를 공시로 훑기 (재무 추세 + 눈여겨볼 공시)",
    )
    dco.add_argument("--code", required=True, help="종목코드 6자리 또는 회사명")
    dco.add_argument("--years", type=int, default=5, help="재무 추세를 몇 년치 볼지")
    dco.add_argument("--days", type=int, default=365, help="공시를 며칠치 볼지")
    dco.add_argument("--api-key", help="직접 넘길 때만")
    dco.add_argument("--cache-dir", default="data/cache/dart", help="회사 목록 저장 폴더")
    dco.add_argument("--refresh", action="store_true", help="회사 목록을 새로 받기")
    dco.add_argument("--out", help="결과를 파일로 저장")
    dco.set_defaults(func=cmd_dart_company)

    de = sub.add_parser(
        "dart-events",
        help="[국내] 여러 종목의 최근 공시에서 눈여겨볼 건만 모으기",
    )
    de.add_argument("--codes", help="쉼표로 구분한 종목코드")
    de.add_argument("--universe", help="종목 목록 파일")
    de.add_argument("--days", type=int, default=90, help="며칠치 공시를 볼지")
    de.add_argument("--limit", type=int, default=0, help="앞 N종목만 (0=전체)")
    de.add_argument("--api-key", help="직접 넘길 때만")
    de.add_argument("--cache-dir", default="data/cache/dart", help="회사 목록 저장 폴더")
    de.add_argument("--refresh", action="store_true", help="회사 목록을 새로 받기")
    de.add_argument("--out", help="결과를 CSV 로 저장")
    de.set_defaults(func=cmd_dart_events)

    t = sub.add_parser("test-telegram", help="텔레그램 연결 확인")
    t.add_argument("--dry-run", action="store_true", help="실제로 보내지 않고 출력만")
    t.set_defaults(func=cmd_test_telegram)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DataUnavailable as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
