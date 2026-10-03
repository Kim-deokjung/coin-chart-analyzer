"""실거래: pyupbit 로 실제 주문. 실제 돈이 움직입니다."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import pyupbit

from bot import data
from bot.models import Fill, Position, Side
from .base import Exchange


class UpbitLiveExchange(Exchange):
    mode = "live"

    def __init__(self, access_key: str, secret_key: str):
        self.api = pyupbit.Upbit(access_key, secret_key)
        # 키 검증
        bal = self.api.get_balances()
        if not isinstance(bal, list):
            raise RuntimeError(f"업비트 API 키 검증 실패: {bal}")

    def get_price(self, ticker: str) -> float:
        return data.get_price(ticker)

    def get_ohlcv(self, ticker: str, interval: str, count: int) -> pd.DataFrame:
        return data.get_ohlcv(ticker, interval, count)

    def get_krw(self) -> float:
        v = self.api.get_balance("KRW")
        return float(v or 0)

    def get_position(self, ticker: str) -> Optional[Position]:
        coin = ticker.split("-")[1]
        for b in self.api.get_balances() or []:
            if b.get("currency") == coin:
                vol = float(b.get("balance", 0))
                if vol <= 0:
                    return None
                avg = float(b.get("avg_buy_price", 0))
                # 업비트는 매수 시각을 안 주므로 포지션 시작 시각은 알 수 없음 -> None
                return Position(ticker, vol, avg, None)
        return None

    def _wait_order(self, uuid: str, timeout: float = 10.0) -> dict[str, Any]:
        """시장가 주문 체결 완료까지 대기 후 주문 상세 반환"""
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.api.get_order(uuid) or {}
            if last.get("state") in ("done", "cancel"):
                return last
            time.sleep(0.5)
        return last

    @staticmethod
    def _summarize(order: dict[str, Any]) -> tuple[float, float, float]:
        """(평균체결가, 체결수량, 체결금액)"""
        trades = order.get("trades") or []
        vol = sum(float(t["volume"]) for t in trades)
        funds = sum(float(t["funds"]) for t in trades)
        price = funds / vol if vol > 0 else 0.0
        return price, vol, funds

    def buy_market(self, ticker: str, krw: float) -> Fill:
        res = self.api.buy_market_order(ticker, krw)
        if not isinstance(res, dict) or "uuid" not in res:
            raise RuntimeError(f"매수 주문 실패: {res}")
        order = self._wait_order(res["uuid"])
        price, vol, funds = self._summarize(order)
        if vol <= 0:
            # 체결 정보가 아직 없으면 현재가로 추정
            price = self.get_price(ticker)
            fee = krw * 0.0005
            vol = (krw - fee) / price
            funds = krw - fee
        fee = float(order.get("paid_fee") or 0)
        return Fill(ticker, Side.BUY, price, vol, funds, fee, datetime.now())

    def sell_market(self, ticker: str, volume: float) -> Fill:
        res = self.api.sell_market_order(ticker, volume)
        if not isinstance(res, dict) or "uuid" not in res:
            raise RuntimeError(f"매도 주문 실패: {res}")
        order = self._wait_order(res["uuid"])
        price, vol, funds = self._summarize(order)
        if vol <= 0:
            price = self.get_price(ticker)
            vol = volume
            funds = price * volume
        fee = float(order.get("paid_fee") or 0)
        return Fill(ticker, Side.SELL, price, vol, funds, fee, datetime.now())
