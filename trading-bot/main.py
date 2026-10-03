"""업비트 자동매매 봇 CLI

  python main.py run                      # 봇 실행 (config.yaml 의 mode 에 따라 paper/live)
  python main.py dashboard                # 관리자 웹 (봇 시작/정지, 설정, 백테스트) http://127.0.0.1:8000
  ./start.command                         # 위와 동일, 더블클릭 실행용
  python main.py backtest                 # config 의 전략/종목으로 백테스트
  python main.py backtest --all --days 365 --ticker KRW-BTC
  python main.py backtest --strategy ma_cross --param short=10 --param long=30
  python main.py reset-paper              # 모의투자 잔고/기록 초기화
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from bot import data, strategies
from bot.backtest import run_backtest
from bot.config import load_config
from bot.store import Store


def _parse_params(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if not _:
            raise SystemExit(f"--param 형식은 key=value 입니다: {it}")
        try:
            out[k] = int(v)
        except ValueError:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def cmd_run(args: argparse.Namespace) -> None:
    from bot.engine import Trader
    from bot.exchange import PaperExchange, UpbitLiveExchange

    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    strategy = strategies.create(cfg.strategy, **cfg.params_for(cfg.strategy))

    if cfg.mode == "live":
        print("!!! LIVE 모드: 실제 주문이 나갑니다. 10초 후 시작 (Ctrl+C 로 취소) !!!")
        import time
        time.sleep(10)
        ex = UpbitLiveExchange(cfg.access_key, cfg.secret_key)
    else:
        ex = PaperExchange(store, cfg.initial_krw, cfg.fee_rate)

    trader = Trader(cfg, ex, strategy, store)
    if args.once:
        trader.step()
        print("1회 실행 완료")
        return
    try:
        trader.run_forever()
    except KeyboardInterrupt:
        print("\n종료")


def cmd_dashboard(args: argparse.Namespace) -> None:
    import uvicorn
    from dashboard.app import create_app

    cfg = load_config(args.config)
    host = args.host or cfg.dashboard_host
    port = args.port or cfg.dashboard_port
    print(f"관리자 화면: http://{host}:{port}  (Ctrl+C 로 종료)")
    uvicorn.run(create_app(args.config), host=host, port=port, log_level="warning")


def cmd_backtest(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    ticker = args.ticker or cfg.tickers[0]
    names = strategies.names() if args.all else [args.strategy or cfg.strategy]
    extra = _parse_params(args.param)
    results = []
    for name in names:
        params = {**cfg.params_for(name), **(extra if not args.all else {})}
        strat = strategies.create(name, **params)
        interval = strat.interval
        per_day = {"day": 1, "minute240": 6, "minute60": 24, "minute30": 48, "minute15": 96,
                   "minute10": 144, "minute5": 288, "minute3": 480, "minute1": 1440, "week": 1 / 7}.get(interval, 1)
        count = int(args.days * per_day) + strat.candles
        print(f"[{name}] {ticker} {interval} 캔들 {count}개 수신 중...", file=sys.stderr)
        df = data.get_ohlcv(ticker, interval, count)
        res = run_backtest(strat, df, ticker, cfg.initial_krw, cfg.fee_rate,
                           cfg.risk.stop_loss_pct, cfg.risk.take_profit_pct)
        results.append(res)
        if not args.all:
            print(res.summary())
            if args.trades:
                print("\n--- 체결 ---")
                for t in res.trades:
                    pnl = f" 손익 {t.pnl_krw:+,.0f}" if t.pnl_krw is not None else ""
                    print(f"{t.ts} {t.side.value:4} {t.price:>14,.0f} {t.volume:.6f} {t.reason}{pnl}")
        if args.csv:
            path = f"data/backtest_{name}_{ticker}.csv"
            res.equity.to_csv(path, header=True)
            print(f"자산 추이 저장: {path}", file=sys.stderr)

    if args.all:
        print(f"\n{ticker} 최근 {args.days}일 전략 비교 (초기 {cfg.initial_krw:,.0f}원)")
        print(f"{'전략':<32}{'수익률':>10}{'단순보유':>10}{'MDD':>9}{'거래':>6}{'승률':>8}")
        for r in results:
            m = r.metrics
            print(f"{r.strategy:<32}{m['total_return_pct']:>+9.2f}%{m['buy_hold_return_pct']:>+9.2f}%"
                  f"{m['mdd_pct']:>8.2f}%{m['n_trades']:>6}{m['win_rate_pct']:>7.1f}%")


def cmd_reset_paper(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    Store(cfg.db_path).reset_paper()
    print("모의투자 잔고/체결/자산 기록을 초기화했습니다.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="봇 실행")
    r.add_argument("--once", action="store_true", help="루프 1회만 실행")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("dashboard", help="관리자 웹 (모니터링+봇 제어+설정+백테스트)")
    d.add_argument("--host")
    d.add_argument("--port", type=int)
    d.set_defaults(func=cmd_dashboard)

    b = sub.add_parser("backtest", help="백테스트")
    b.add_argument("--strategy", help="전략 이름 (기본: config)")
    b.add_argument("--all", action="store_true", help="모든 전략 비교")
    b.add_argument("--ticker", help="종목 (기본: config 첫 종목)")
    b.add_argument("--days", type=int, default=365)
    b.add_argument("--param", action="append", help="전략 파라미터 덮어쓰기 key=value")
    b.add_argument("--trades", action="store_true", help="체결 내역 출력")
    b.add_argument("--csv", action="store_true", help="자산 추이 CSV 저장")
    b.set_defaults(func=cmd_backtest)

    s = sub.add_parser("reset-paper", help="모의투자 초기화")
    s.set_defaults(func=cmd_reset_paper)

    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args.func(args)


if __name__ == "__main__":
    main()
