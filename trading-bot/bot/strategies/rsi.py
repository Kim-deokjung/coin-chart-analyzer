"""RSI 역추세: 과매도 매수 / 과매수 매도"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from bot.indicators import rsi
from bot.models import Order, Position, Side
from .base import Strategy, register


@register
class RSIStrategy(Strategy):
    name = "rsi"
    label = "RSI 역추세"
    interval = "minute60"
    period: int = 14
    buy_below: float = 30
    sell_above: float = 70

    def __init__(self, **params):
        super().__init__(**params)
        self.candles = self.period * 5

    def decide(self, df: pd.DataFrame, position: Optional[Position], now: datetime) -> Optional[Order]:
        if len(df) < self.period + 2:
            return None
        r = rsi(df["close"], self.period)
        prev, cur = r.iloc[-2], r.iloc[-1]
        if pd.isna(prev) or pd.isna(cur):
            return None
        # 과매도 구간에서 빠져나올 때 매수 (바닥 확인), 과매수 구간 진입 시 매도
        if position is None and prev < self.buy_below <= cur:
            return Order(Side.BUY, reason=f"RSI {prev:.1f}->{cur:.1f} 과매도 탈출")
        if position is not None and cur >= self.sell_above:
            return Order(Side.SELL, reason=f"RSI {cur:.1f} 과매수")
        return None

    def describe(self) -> str:
        return f"RSI({self.period}, {self.buy_below}/{self.sell_above}, {self.interval})"
