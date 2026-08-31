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
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import backtest as bt_module
from . import market_filter as mf_module
from . import notify_policy
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

    frames: dict[str, pd.DataFrame] = {}
    for code in codes:
        try:
            daily = fetch_daily_kr(code, years=args.years)
        except DataUnavailable:
            continue
        except Exception:  # noqa: BLE001
            continue
        if len(daily) >= cfg.scanner_b.sma_slow + 5:
            frames[code] = daily
    print(f"시세 확보 {len(frames)}종목 (요청 {len(codes)}종목)")

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
    frames: dict[str, pd.DataFrame] = {}
    for code in codes:
        try:
            daily = fetch_daily_kr(code, years=args.years)
        except DataUnavailable as exc:
            print(f"  ! {code}: {exc}")
            continue
        if len(daily) < cfg.scanner_b.sma_slow + 5:
            print(f"  ! {code}: 일봉 {len(daily)}개로는 200일선 검증이 어렵습니다.")
            continue
        frames[code] = daily

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
    kc.set_defaults(func=cmd_backtest_kr)

    ku = sub.add_parser("kr-universe", help="[국내] 전 종목 목록 뽑기")
    ku.add_argument("--market", default="KOSPI", help="KOSPI / KOSDAQ / KRX")
    ku.add_argument("--out", default="data/universe_kr_all.txt", help="저장할 파일")
    ku.set_defaults(func=cmd_kr_universe)

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
