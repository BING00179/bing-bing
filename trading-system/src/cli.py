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
from . import scanner_a, scanner_b
from .config import Config
from .data import NY, DataUnavailable, fetch_daily, load_csv, read_universe
from .notify import TelegramNotConfigured, send

ROOT = Path(__file__).resolve().parent.parent


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


def cmd_scan_a(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
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

    if args.universe:
        tickers = read_universe(_resolve(args.universe))
    else:
        tickers = _latest_scan_a(cfg)
        if not tickers:
            print("스캐너 A 결과가 없어 전체 티커 목록으로 대체합니다.")
            tickers = read_universe(_resolve(cfg.universe_file))

    if not scanner_b.is_after_earliest_hour(cfg.scanner_b) and not args.force:
        print(
            f"아직 ET {cfg.scanner_b.earliest_hour_et}시 전입니다. "
            "지금 실행하려면 --force 를 붙이세요."
        )
        return 1

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
    a.set_defaults(func=cmd_scan_a)

    b = sub.add_parser("scan-b", help="전략 스캐너 (Trend Join Long)")
    b.add_argument("--universe", help="티커 목록 파일 (없으면 스캐너 A 결과 사용)")
    b.add_argument("--no-telegram", action="store_true", help="알림 보내지 않기")
    b.add_argument("--force", action="store_true", help="오전 10시 전에도 실행")
    b.set_defaults(func=cmd_scan_b)

    c = sub.add_parser("backtest", help="과거 데이터로 전략 검증")
    c.add_argument("--universe", help="티커 목록 파일")
    c.add_argument("--csv-dir", help="TICKER.csv 가 든 폴더 (없으면 야후에서 내려받음)")
    c.add_argument("--period", default="2y", help="내려받을 기간 (기본 2y)")
    c.set_defaults(func=cmd_backtest)

    t = sub.add_parser("test-telegram", help="텔레그램 연결 확인")
    t.add_argument("--dry-run", action="store_true", help="실제로 보내지 않고 출력만")
    t.set_defaults(func=cmd_test_telegram)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DataUnavailable as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
