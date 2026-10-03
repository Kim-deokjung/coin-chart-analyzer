"""공용 데이터 모델"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Position:
    ticker: str
    volume: float
    avg_price: float
    opened_at: Optional[datetime] = None

    def value(self, price: float) -> float:
        return self.volume * price

    def pnl_pct(self, price: float) -> float:
        if self.avg_price <= 0:
            return 0.0
        return (price / self.avg_price - 1) * 100


@dataclass
class Order:
    """전략이 내는 주문 의도.

    price 가 None 이면 '지금 시장가로'.
    price 가 있으면 '가격이 이 수준에 도달하면' (매수: 현재가 >= price, 매도: 현재가 <= price).
    at 은 백테스트에서 체결 가격 기준 ("close" | "open"). price 가 있으면 무시.
    """
    side: Side
    price: Optional[float] = None
    at: str = "close"
    reason: str = ""


@dataclass
class Fill:
    ticker: str
    side: Side
    price: float
    volume: float
    krw: float      # 체결 금액 (수수료 제외)
    fee: float
    ts: datetime
