"""매매 루프: 시세 조회 -> 리스크 체크 -> 전략 판단 -> 주문 -> 기록"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

from bot.config import Config
from bot.exchange.base import Exchange
from bot.models import Fill, Order, Position, Side
from bot.store import Store
from bot.strategies.base import Strategy

log = logging.getLogger("bot")


class Trader:
    def __init__(self, cfg: Config, exchange: Exchange, strategy: Strategy, store: Store):
        self.cfg = cfg
        self.ex = exchange
        self.strategy = strategy
        self.store = store
        self._opened_at: dict[str, datetime] = {}
        saved = store.status().get("opened_at") or {}
        for t, s in saved.items():
            try:
                self._opened_at[t] = datetime.fromisoformat(s)
            except ValueError:
                pass
        self._initial_equity: Optional[float] = store.status().get("initial_equity")

    # ------------------------------------------------------------------ helpers
    def _log(self, level: str, msg: str) -> None:
        getattr(log, level.lower(), log.info)(msg)
        self.store.log(level.upper(), msg)

    def _position(self, ticker: str) -> Optional[Position]:
        pos = self.ex.get_position(ticker)
        if pos is not None and pos.opened_at is None:
            pos.opened_at = self._opened_at.get(ticker)
        return pos

    def _record(self, fill: Fill, reason: str, pos_before: Optional[Position]) -> None:
        pnl = None
        if fill.side == Side.SELL and pos_before is not None:
            pnl = (fill.price - pos_before.avg_price) * fill.volume - fill.fee
        self.store.add_trade(fill, self.ex.mode, self.strategy.name, reason, pnl)
        pnl_txt = f" 손익 {pnl:+,.0f}원" if pnl is not None else ""
        self._log("info", f"[{self.ex.mode}] {fill.side.value} {fill.ticker} {fill.volume:.6f}개 @ {fill.price:,.0f}"
                          f" ({fill.krw:,.0f}원) - {reason}{pnl_txt}")

    def _order_krw(self, open_positions: int) -> float:
        r = self.cfg.risk
        if open_positions >= r.max_positions:
            return 0.0
        krw = self.ex.get_krw()
        amount = krw * r.order_krw_ratio
        amount = min(amount, krw * 0.999)  # 수수료 여유
        return amount if amount >= r.min_order_krw else 0.0

    # ------------------------------------------------------------------ core
    def _check_risk(self, ticker: str, pos: Position, price: float) -> Optional[Order]:
        r = self.cfg.risk
        pnl = pos.pnl_pct(price)
        if r.stop_loss_pct and pnl <= r.stop_loss_pct:
            return Order(Side.SELL, reason=f"손절 {pnl:+.2f}%")
        if r.take_profit_pct and pnl >= r.take_profit_pct:
            return Order(Side.SELL, reason=f"익절 {pnl:+.2f}%")
        return None

    def _execute(self, ticker: str, order: Order, pos: Optional[Position], price: float, open_positions: int) -> bool:
        if order.side == Side.BUY:
            if pos is not None:
                return False
            if order.price is not None and price < order.price:
                return False  # 트리거 가격 미도달
            krw = self._order_krw(open_positions)
            if krw <= 0:
                return False
            fill = self.ex.buy_market(ticker, krw)
            self._opened_at[ticker] = fill.ts
            self.store.set_status(opened_at={t: d.isoformat() for t, d in self._opened_at.items()})
            self._record(fill, order.reason, None)
            return True

        if pos is None:
            return False
        if order.price is not None and price > order.price:
            return False
        fill = self.ex.sell_market(ticker, pos.volume)
        self._opened_at.pop(ticker, None)
        self.store.set_status(opened_at={t: d.isoformat() for t, d in self._opened_at.items()})
        self._record(fill, order.reason, pos)
        return True

    def step(self) -> None:
        now = datetime.now()
        positions = {t: p for t in self.cfg.tickers if (p := self._position(t)) is not None}
        prices: dict[str, float] = {}

        for ticker in self.cfg.tickers:
            try:
                df = self.ex.get_ohlcv(ticker, self.strategy.interval, self.strategy.candles)
                price = float(df["close"].iloc[-1])
                prices[ticker] = price
                pos = positions.get(ticker)

                order = self._check_risk(ticker, pos, price) if pos else None
                if order is None:
                    order = self.strategy.decide(df, pos, now)
                if order is None:
                    continue

                done = self._execute(ticker, order, pos, price, len(positions))
                if done:
                    p = self._position(ticker)
                    if p is None:
                        positions.pop(ticker, None)
                    else:
                        positions[ticker] = p
            except Exception as e:  # 한 종목 오류가 전체를 멈추지 않도록
                self._log("error", f"{ticker} 처리 중 오류: {e}")
                log.debug(traceback.format_exc())

        self._snapshot(now, positions, prices)

    def _snapshot(self, now: datetime, positions: dict[str, Position], prices: dict[str, float]) -> None:
        krw = self.ex.get_krw()
        pos_info = []
        total = krw
        for t, p in positions.items():
            price = prices.get(t) or p.avg_price
            value = p.value(price)
            total += value
            pos_info.append({"ticker": t, "volume": p.volume, "avg_price": p.avg_price,
                             "price": price, "value": value, "pnl_pct": p.pnl_pct(price),
                             "opened_at": p.opened_at.isoformat() if p.opened_at else None})
        if self._initial_equity is None:
            self._initial_equity = total
        self.store.add_equity(now, total, krw, {t: p.volume for t, p in positions.items()})
        self.store.set_status(
            mode=self.ex.mode, strategy=self.strategy.name, strategy_desc=self.strategy.describe(),
            tickers=self.cfg.tickers, last_run=now.isoformat(timespec="seconds"),
            krw=krw, total_krw=total, initial_equity=self._initial_equity, positions=pos_info,
            prices=prices, poll_seconds=self.cfg.poll_seconds, risk=self.cfg.risk.__dict__,
        )

    def run_forever(self, stop: Optional[threading.Event] = None) -> None:
        stop = stop or threading.Event()
        self._log("info", f"봇 시작: mode={self.ex.mode} strategy={self.strategy.describe()} "
                          f"tickers={','.join(self.cfg.tickers)} poll={self.cfg.poll_seconds}s")
        self.store.set_status(running=True)
        try:
            while not stop.is_set():
                t0 = time.time()
                try:
                    self.step()
                except Exception as e:
                    self._log("error", f"루프 오류: {e}")
                    log.debug(traceback.format_exc())
                elapsed = time.time() - t0
                stop.wait(max(1.0, self.cfg.poll_seconds - elapsed))
        finally:
            self.store.set_status(running=False)
            self._log("info", "봇 정지")
