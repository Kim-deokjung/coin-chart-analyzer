"""관리자 화면용: 봇 스레드 제어, 백테스트 작업 실행"""
from __future__ import annotations

import logging
import threading
import traceback
import uuid
from datetime import datetime
from typing import Any, Optional

from bot import data, strategies
from bot.backtest import run_backtest
from bot.config import Config, load_config
from bot.engine import Trader
from bot.exchange import PaperExchange, UpbitLiveExchange
from bot.store import Store

log = logging.getLogger("bot.manager")

PER_DAY = {"day": 1, "minute240": 6, "minute60": 24, "minute30": 48, "minute15": 96,
           "minute10": 144, "minute5": 288, "minute3": 480, "minute1": 1440, "week": 1 / 7}


class BotManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.started_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.cfg: Optional[Config] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, confirm_live: bool = False) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("이미 실행 중입니다")
            cfg = load_config(self.config_path)
            if cfg.mode == "live" and not confirm_live:
                raise PermissionError("live 모드 시작은 확인이 필요합니다")
            store = Store(cfg.db_path)
            strategy = strategies.create(cfg.strategy, **cfg.params_for(cfg.strategy))
            if cfg.mode == "live":
                ex = UpbitLiveExchange(cfg.access_key, cfg.secret_key)
            else:
                ex = PaperExchange(store, cfg.initial_krw, cfg.fee_rate)
            trader = Trader(cfg, ex, strategy, store)
            self._stop = threading.Event()
            self.error = None
            self.cfg = cfg
            self.started_at = datetime.now()

            def target():
                try:
                    trader.run_forever(self._stop)
                except Exception as e:
                    self.error = str(e)
                    log.error("봇 스레드 종료: %s\n%s", e, traceback.format_exc())
                    store.log("ERROR", f"봇 비정상 종료: {e}")
                    store.set_status(running=False)

            self._thread = threading.Thread(target=target, name="bot", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        if not self.running:
            return
        self._stop.set()
        self._thread.join(timeout)

    def info(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at and self.running else None,
            "error": self.error,
            "mode": self.cfg.mode if (self.cfg and self.running) else None,
        }


class BacktestRunner:
    def __init__(self, config_path: str, keep: int = 20):
        self.config_path = config_path
        self.jobs: dict[str, dict[str, Any]] = {}
        self.keep = keep
        self._lock = threading.Lock()

    def submit(self, strategy: str, ticker: str, days: int, params: dict[str, Any],
               stop_loss_pct: Optional[float] = None, take_profit_pct: Optional[float] = None,
               initial_krw: Optional[float] = None) -> str:
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "state": "running", "submitted": datetime.now().isoformat(timespec="seconds"),
               "request": {"strategy": strategy, "ticker": ticker, "days": days, "params": params,
                           "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct}}
        with self._lock:
            self.jobs[job_id] = job
            for old in list(self.jobs)[:-self.keep]:
                del self.jobs[old]

        def target():
            try:
                cfg = load_config(self.config_path)
                merged = {**cfg.params_for(strategy), **params}
                strat = strategies.create(strategy, **merged)
                count = int(days * PER_DAY.get(strat.interval, 1)) + strat.candles
                df = data.get_ohlcv(ticker, strat.interval, count)
                sl = cfg.risk.stop_loss_pct if stop_loss_pct is None else stop_loss_pct
                tp = cfg.risk.take_profit_pct if take_profit_pct is None else take_profit_pct
                init = cfg.initial_krw if initial_krw is None else initial_krw
                res = run_backtest(strat, df, ticker, init, cfg.fee_rate, sl, tp)
                job["result"] = {
                    "strategy": res.strategy, "ticker": ticker, "initial_krw": init, "final_krw": res.final_krw,
                    "metrics": res.metrics,
                    "equity": [{"ts": str(i), "v": float(v)} for i, v in res.equity.items()],
                    "close": [{"ts": str(i), "v": float(v)} for i, v in df["close"].items()],
                    "trades": [{"ts": str(t.ts), "side": t.side.value, "price": t.price, "volume": t.volume,
                                "krw": t.krw, "fee": t.fee, "reason": t.reason, "pnl_krw": t.pnl_krw} for t in res.trades],
                }
                job["state"] = "done"
            except Exception as e:
                job["state"] = "error"
                job["error"] = str(e)
                log.error("백테스트 실패: %s\n%s", e, traceback.format_exc())

        threading.Thread(target=target, name=f"bt-{job_id}", daemon=True).start()
        return job_id

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        out = []
        for j in reversed(list(self.jobs.values())):
            d = {k: v for k, v in j.items() if k != "result"}
            if "result" in j:
                d["metrics"] = j["result"]["metrics"]
                d["final_krw"] = j["result"]["final_krw"]
            out.append(d)
        return out
