"""SQLite 기록 저장소 (체결, 자산 추이, 상태, 모의투자 잔고)"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from bot.models import Fill, Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    mode TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    volume REAL NOT NULL,
    krw REAL NOT NULL,
    fee REAL NOT NULL,
    strategy TEXT,
    reason TEXT,
    pnl_krw REAL
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    total_krw REAL NOT NULL,
    krw REAL NOT NULL,
    positions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS paper_balance (
    currency TEXT PRIMARY KEY,
    volume REAL NOT NULL,
    avg_price REAL NOT NULL,
    opened_at TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- trades ----
    def add_trade(self, fill: Fill, mode: str, strategy: str, reason: str, pnl_krw: Optional[float] = None) -> None:
        self.conn.execute(
            "INSERT INTO trades (ts, mode, ticker, side, price, volume, krw, fee, strategy, reason, pnl_krw)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fill.ts.isoformat(timespec="seconds"), mode, fill.ticker, fill.side.value, fill.price,
             fill.volume, fill.krw, fill.fee, strategy, reason, pnl_krw),
        )
        self.conn.commit()

    def trades(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- equity ----
    def add_equity(self, ts: datetime, total_krw: float, krw: float, positions: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO equity (ts, total_krw, krw, positions) VALUES (?,?,?,?)",
            (ts.isoformat(timespec="seconds"), total_krw, krw, json.dumps(positions, ensure_ascii=False)),
        )
        self.conn.commit()

    def equity(self, limit: int = 2000) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, total_krw, krw, positions FROM (SELECT * FROM equity ORDER BY id DESC LIMIT ?) ORDER BY id ASC", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["positions"] = json.loads(d["positions"])
            out.append(d)
        return out

    # ---- status ----
    def set_status(self, **kv: Any) -> None:
        for k, v in kv.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO status (key, value) VALUES (?,?)",
                (k, json.dumps(v, ensure_ascii=False, default=str)),
            )
        self.conn.commit()

    def status(self) -> dict[str, Any]:
        rows = self.conn.execute("SELECT key, value FROM status").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    # ---- logs ----
    def log(self, level: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO logs (ts, level, message) VALUES (?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), level, message),
        )
        self.conn.execute("DELETE FROM logs WHERE id < (SELECT MAX(id) FROM logs) - 2000")
        self.conn.commit()

    def logs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- paper balance ----
    def load_paper_balance(self) -> tuple[Optional[float], dict[str, Position]]:
        rows = self.conn.execute("SELECT * FROM paper_balance").fetchall()
        krw: Optional[float] = None
        positions: dict[str, Position] = {}
        for r in rows:
            if r["currency"] == "KRW":
                krw = r["volume"]
            else:
                opened = datetime.fromisoformat(r["opened_at"]) if r["opened_at"] else None
                positions[r["currency"]] = Position(r["currency"], r["volume"], r["avg_price"], opened)
        return krw, positions

    def save_paper_balance(self, krw: float, positions: dict[str, Position]) -> None:
        self.conn.execute("DELETE FROM paper_balance")
        self.conn.execute(
            "INSERT INTO paper_balance (currency, volume, avg_price, opened_at) VALUES ('KRW', ?, 0, NULL)", (krw,)
        )
        for t, p in positions.items():
            self.conn.execute(
                "INSERT INTO paper_balance (currency, volume, avg_price, opened_at) VALUES (?,?,?,?)",
                (t, p.volume, p.avg_price, p.opened_at.isoformat() if p.opened_at else None),
            )
        self.conn.commit()

    def reset_paper(self) -> None:
        self.conn.execute("DELETE FROM paper_balance")
        self.conn.execute("DELETE FROM trades WHERE mode='paper'")
        self.conn.execute("DELETE FROM equity")
        self.conn.execute("DELETE FROM logs")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
