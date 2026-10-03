"""모의투자: 실제 시세, 가상 잔고. 잔고는 Store 에 저장돼 재시작해도 유지."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from bot import data
from bot.models import Fill, Position, Side
from bot.store import Store
from .base import Exchange


class PaperExchange(Exchange):
    mode = "paper"

    def __init__(self, store: Store, initial_krw: float, fee_rate: float = 0.0005):
        self.store = store
        self.fee_rate = fee_rate
        krw, positions = store.load_paper_balance()
        self.krw = initial_krw if krw is None else krw
        self._positions = positions
        self._persist()

    def _persist(self) -> None:
        self.store.save_paper_balance(self.krw, self._positions)

    def get_price(self, ticker: str) -> float:
        return data.get_price(ticker)

    def get_ohlcv(self, ticker: str, interval: str, count: int) -> pd.DataFrame:
        return data.get_ohlcv(ticker, interval, count)

    def get_krw(self) -> float:
        return self.krw

    def get_position(self, ticker: str) -> Optional[Position]:
        return self._positions.get(ticker)

    def buy_market(self, ticker: str, krw: float) -> Fill:
        if krw > self.krw + 1e-9:
            raise ValueError(f"KRW 부족: 요청 {krw:,.0f} / 보유 {self.krw:,.0f}")
        price = self.get_price(ticker)
        fee = krw * self.fee_rate
        volume = (krw - fee) / price
        self.krw -= krw
        pos = self._positions.get(ticker)
        now = datetime.now()
        if pos is None:
            self._positions[ticker] = Position(ticker, volume, price, now)
        else:
            total_cost = pos.avg_price * pos.volume + price * volume
            pos.volume += volume
            pos.avg_price = total_cost / pos.volume
        self._persist()
        return Fill(ticker, Side.BUY, price, volume, krw - fee, fee, now)

    def sell_market(self, ticker: str, volume: float) -> Fill:
        pos = self._positions.get(ticker)
        if pos is None or pos.volume < volume - 1e-12:
            raise ValueError(f"{ticker} 보유 수량 부족")
        price = self.get_price(ticker)
        gross = price * volume
        fee = gross * self.fee_rate
        self.krw += gross - fee
        pos.volume -= volume
        if pos.volume <= 1e-10:
            del self._positions[ticker]
        self._persist()
        return Fill(ticker, Side.SELL, price, volume, gross, fee, datetime.now())
