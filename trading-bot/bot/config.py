"""설정 로드: config.yaml + .env"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class RiskConfig:
    max_positions: int = 2
    order_krw_ratio: float = 0.5
    min_order_krw: float = 5000
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0


@dataclass
class Config:
    mode: str = "paper"
    tickers: list[str] = field(default_factory=lambda: ["KRW-BTC"])
    strategy: str = "volatility_breakout"
    strategy_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    poll_seconds: int = 60
    initial_krw: float = 1_000_000
    fee_rate: float = 0.0005
    risk: RiskConfig = field(default_factory=RiskConfig)
    db_path: str = "data/bot.db"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    access_key: str = ""
    secret_key: str = ""

    def params_for(self, strategy_name: str) -> dict[str, Any]:
        return dict(self.strategy_params.get(strategy_name, {}))


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    load_dotenv(path.parent / ".env")
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    risk = RiskConfig(**(raw.get("risk") or {}))
    dash = raw.get("dashboard") or {}
    cfg = Config(
        mode=str(raw.get("mode", "paper")).lower(),
        tickers=list(raw.get("tickers") or ["KRW-BTC"]),
        strategy=raw.get("strategy", "volatility_breakout"),
        strategy_params=raw.get("strategy_params") or {},
        poll_seconds=int(raw.get("poll_seconds", 60)),
        initial_krw=float(raw.get("initial_krw", 1_000_000)),
        fee_rate=float(raw.get("fee_rate", 0.0005)),
        risk=risk,
        db_path=str(raw.get("db_path", "data/bot.db")),
        dashboard_host=dash.get("host", "127.0.0.1"),
        dashboard_port=int(dash.get("port", 8000)),
        access_key=os.getenv("UPBIT_ACCESS_KEY", ""),
        secret_key=os.getenv("UPBIT_SECRET_KEY", ""),
    )
    if cfg.mode not in ("paper", "live"):
        raise ValueError(f"mode 는 paper 또는 live 여야 합니다: {cfg.mode}")
    if cfg.mode == "live" and not (cfg.access_key and cfg.secret_key):
        raise ValueError("live 모드에는 .env 에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 가 필요합니다")
    return cfg
