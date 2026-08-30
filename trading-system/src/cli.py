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
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import backtest as bt_module
from . import market_filter as mf_module
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
    hits, errors = scanner_kr.scan_a(codes, kr, names)

    report = scanner_kr.format_report_a(hits, _timestamp_kr(), errors, scanned=len(codes))
    report = _with_market_state(report, state, state_error)

    out = _output_dir(cfg) / f"kr_scan_a_{now_kst():%Y%m%d_%H%M}.csv"
    scanner_kr.to_frame_a(hits).to_csv(out, index=False)
    print(f"\n결과 저장: {out}")

    _notify(report, not args.no_telegram)
    return 1 if errors and len(errors) >= len(codes) else 0


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
            print(f"스캐너 A 결과 사용: {files[-1].name}")
        if not codes:
            print("스캐너 A 결과가 없어 전체 종목 목록으로 대체합니다.")
            path = _resolve(cfg.universe_file_kr)
            codes = read_universe_kr(path)
        else:
            path = _resolve(cfg.universe_file_kr)

    names = _names_for(codes, path)
    state, state_error = _market_state(cfg)

    print(f"국내 전략 스캔 시작 — 대상 {len(codes)}종목")
    results, errors = scanner_kr.scan_b(codes, cfg.scanner_b, names)
    results = scanner_kr.rank(results, cfg.ranking)

    report = scanner_kr.format_report_b(
        results, _timestamp_kr(), errors, scanned=len(codes),
        top_n=cfg.ranking.top_n if cfg.ranking.enabled else 0,
    )
    report = _with_market_state(report, state, state_error)

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

    _notify(report, not args.no_telegram)
    return 1 if errors and len(errors) >= len(codes) else 0


def cmd_market(args: argparse.Namespace) -> int:
    """시장 상태만 확인합니다."""
    cfg = Config.load(args.config)
    index = fetch_index(cfg.market_filter.index_code)
    state = mf_module.evaluate(index, cfg.market_filter, cfg.market_filter.index_name)
    report = f"[시장 상태] {_timestamp_kr()}\n{state.as_report()}"
    _notify(report, not args.no_telegram)
    return 0


def cmd_backtest_kr(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    path = _resolve(args.universe or cfg.universe_file_kr)
    codes = read_universe_kr(path)
    names = _names_for(codes, path)

    all_trades: list[bt_module.Trade] = []
    per_code: list[dict] = []

    for code in codes:
        try:
            daily = fetch_daily_kr(code, years=args.years)
        except DataUnavailable as exc:
            print(f"  ! {code}: {exc}")
            continue
        if len(daily) < cfg.scanner_b.sma_slow + 5:
            print(f"  ! {code}: 일봉 {len(daily)}개로는 200일선 검증이 어렵습니다.")
            continue

        trades = bt_module.run(code, daily, cfg.backtest_kr, cfg.scanner_b)
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

    out = _output_dir(cfg)
    bt_module.trades_to_frame(all_trades).to_csv(out / "kr_backtest_trades.csv", index=False)
    pd.DataFrame(per_code).to_csv(out / "kr_backtest_by_code.csv", index=False)

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
    print(f"\n결과 저장: {out}/kr_backtest_trades.csv")
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
    ka.set_defaults(func=cmd_scan_kr_a)

    kb = sub.add_parser("scan-kr-b", help="[국내] 전략 스캐너 (Trend Join Long)")
    kb.add_argument("--universe", help="종목코드 목록 파일 (없으면 스캐너 A 결과 사용)")
    kb.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    kb.add_argument("--force", action="store_true", help="실행 시간대 밖에서도 실행")
    kb.set_defaults(func=cmd_scan_kr_b)

    m = sub.add_parser("market", help="[국내] 시장 상태만 확인")
    m.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    m.set_defaults(func=cmd_market)

    kc = sub.add_parser("backtest-kr", help="[국내] 과거 데이터로 전략 검증")
    kc.add_argument("--universe", help="종목코드 목록 파일")
    kc.add_argument("--years", type=float, default=3.0, help="검증 기간 (년, 기본 3)")
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
