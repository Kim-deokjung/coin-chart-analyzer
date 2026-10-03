"""변동성 돌파 (Larry Williams)

목표가 = 당일 시가 + (전일 고가 - 전일 저가) * k
현재가가 목표가를 넘으면 매수, 다음 거래일 시가(09:00)에 매도.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from bot.indicators import trading_day
from bot.models import Order, Position, Side
from .base import Strategy, register


@register
class VolatilityBreakout(Strategy):
    name = "volatility_breakout"
    label = "변동성 돌파"
    interval = "day"
    candles = 3
    k: float = 0.5

    def target_price(self, df: pd.DataFrame) -> float:
        today = df.iloc[-1]
        yday = df.iloc[-2]
        return float(today["open"] + (yday["high"] - yday["low"]) * self.k)

    def decide(self, df: pd.DataFrame, position: Optional[Position], now: datetime) -> Optional[Order]:
        if len(df) < 2:
            return None
        today = trading_day(df.index[-1])

        if position is not None:
            opened_day = trading_day(pd.Timestamp(position.opened_at)) if position.opened_at else None
            if opened_day is None or today > opened_day:
                return Order(Side.SELL, at="open", reason="다음날 시가 매도")
            return None

        target = self.target_price(df)
        return Order(Side.BUY, price=target, reason=f"목표가 {target:,.0f} 돌파")

    def describe(self) -> str:
        return f"변동성돌파(k={self.k})"
