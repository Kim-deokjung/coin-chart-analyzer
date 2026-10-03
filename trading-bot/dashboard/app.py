"""관리자 웹: 모니터링 + 봇 시작/정지 + 설정 편집 + 백테스트"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pyupbit
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from bot import config_io, strategies
from bot.config import load_config
from bot.manager import BacktestRunner, BotManager
from bot.store import Store

HERE = Path(__file__).parent


class StartBody(BaseModel):
    confirm_live: bool = False


class BacktestBody(BaseModel):
    strategy: str
    ticker: str = "KRW-BTC"
    days: int = 365
    params: dict[str, Any] = {}
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    initial_krw: Optional[float] = None


def create_app(config_path: str = "config.yaml") -> FastAPI:
    app = FastAPI(title="Upbit Bot Admin")
    bot = BotManager(config_path)
    backtests = BacktestRunner(config_path)

    def cfg():
        return load_config(config_path)

    def with_store(fn):
        s = Store(cfg().db_path)
        try:
            return fn(s)
        finally:
            s.close()

    # ---------------- 페이지
    @app.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "static" / "index.html").read_text(encoding="utf-8")

    # ---------------- 모니터링
    @app.get("/api/status")
    def status():
        c = cfg()
        st = with_store(lambda s: s.status())
        st.setdefault("mode", c.mode)
        st.setdefault("strategy", c.strategy)
        st.setdefault("tickers", c.tickers)
        st["config_initial_krw"] = c.initial_krw
        st["config_mode"] = c.mode
        st["bot"] = bot.info()
        st["running"] = bot.running
        return JSONResponse(st)

    @app.get("/api/trades")
    def trades(limit: int = 100):
        return JSONResponse(with_store(lambda s: s.trades(limit)))

    @app.get("/api/equity")
    def equity(limit: int = 2000):
        return JSONResponse(with_store(lambda s: s.equity(limit)))

    @app.get("/api/logs")
    def logs(limit: int = 100):
        return JSONResponse(with_store(lambda s: s.logs(limit)))

    # ---------------- 봇 제어
    @app.post("/api/bot/start")
    def bot_start(body: StartBody):
        try:
            bot.start(confirm_live=body.confirm_live)
        except PermissionError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(400, str(e))
        return bot.info()

    @app.post("/api/bot/stop")
    def bot_stop():
        bot.stop()
        return bot.info()

    @app.post("/api/paper/reset")
    def paper_reset():
        if bot.running:
            raise HTTPException(409, "봇을 먼저 정지하세요")
        with_store(lambda s: s.reset_paper())
        return {"ok": True}

    # ---------------- 설정
    @app.get("/api/config")
    def get_config():
        raw = config_io.read_raw(config_path)
        c = cfg()
        return JSONResponse({"config": raw, "has_api_key": bool(c.access_key and c.secret_key)})

    @app.put("/api/config")
    def put_config(changes: dict[str, Any]):
        if bot.running:
            raise HTTPException(409, "봇 실행 중에는 설정을 바꿀 수 없습니다. 먼저 정지하세요")
        allowed = {"mode", "tickers", "strategy", "strategy_params", "poll_seconds", "initial_krw", "fee_rate", "risk"}
        bad = set(changes) - allowed
        if bad:
            raise HTTPException(400, f"변경 불가 항목: {', '.join(sorted(bad))}")
        try:
            raw = config_io.update(config_path, changes)
        except Exception as e:
            raise HTTPException(400, str(e))
        return JSONResponse({"config": raw})

    @app.get("/api/strategies")
    def list_strategies():
        return JSONResponse([
            {"name": n, "label": strategies.REGISTRY[n].label or n, "params": strategies.REGISTRY[n].param_schema(),
             "doc": (strategies.REGISTRY[n].__doc__ or "").strip()}
            for n in strategies.names()
        ])

    @app.get("/api/tickers")
    def list_tickers():
        try:
            return JSONResponse(sorted(pyupbit.get_tickers(fiat="KRW")))
        except Exception as e:
            raise HTTPException(502, f"업비트 종목 조회 실패: {e}")

    # ---------------- 백테스트
    @app.post("/api/backtest")
    def backtest_submit(body: BacktestBody):
        if body.strategy not in strategies.names():
            raise HTTPException(400, f"알 수 없는 전략: {body.strategy}")
        if not (1 <= body.days <= 2000):
            raise HTTPException(400, "days 는 1~2000")
        job_id = backtests.submit(body.strategy, body.ticker, body.days, body.params,
                                  body.stop_loss_pct, body.take_profit_pct, body.initial_krw)
        return {"id": job_id}

    @app.get("/api/backtest")
    def backtest_list():
        return JSONResponse(backtests.list())

    @app.get("/api/backtest/{job_id}")
    def backtest_get(job_id: str):
        job = backtests.get(job_id)
        if job is None:
            raise HTTPException(404, "없는 작업")
        return JSONResponse(job)

    @app.on_event("shutdown")
    def _shutdown():
        bot.stop()

    return app
