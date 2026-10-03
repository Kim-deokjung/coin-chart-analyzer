"""이동평균 교차 (골든크로스 매수 / 데드크로스 매도)"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from bot.indicators import sma
from bot.models import Order, Position, Side
from .base import Strategy, register


@register
class MACross(Strategy):
    name = "ma_cross"
    label = "이동평균 교차"
    interval = "day"
    short: int = 5
    long: int = 20

    def __init__(self, **params):
        super().__init__(**params)
        if self.short >= self.long:
            raise ValueError("short 는 long 보다 작아야 합니다")
        self.candles = self.long + 5

    def decide(self, df: pd.DataFrame, position: Optional[Position], now: datetime) -> Optional[Order]:
        if len(df) < self.long + 1:
            return None
        close = df["close"]
        s = sma(close, self.short)
        l = sma(close, self.long)
        prev_above = s.iloc[-2] > l.iloc[-2]
        now_above = s.iloc[-1] > l.iloc[-1]

        if position is None and now_above and not prev_above:
            return Order(Side.BUY, reason=f"골든크로스 MA{self.short}>MA{self.long}")
        if position is not None and not now_above and prev_above:
            return Order(Side.SELL, reason=f"데드크로스 MA{self.short}<MA{self.long}")
        return None

    def describe(self) -> str:
        return f"MA교차({self.short}/{self.long}, {self.interval})"
