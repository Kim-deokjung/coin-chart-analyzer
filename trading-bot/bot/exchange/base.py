from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from bot.models import Fill, Position


class Exchange(ABC):
    mode: str = "base"

    @abstractmethod
    def get_price(self, ticker: str) -> float: ...

    @abstractmethod
    def get_ohlcv(self, ticker: str, interval: str, count: int) -> pd.DataFrame: ...

    @abstractmethod
    def get_krw(self) -> float:
        """주문 가능한 KRW 잔고"""

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]: ...

    @abstractmethod
    def buy_market(self, ticker: str, krw: float) -> Fill: ...

    @abstractmethod
    def sell_market(self, ticker: str, volume: float) -> Fill: ...

    def positions(self, tickers: list[str]) -> dict[str, Position]:
        out = {}
        for t in tickers:
            p = self.get_position(t)
            if p is not None:
                out[t] = p
        return out
