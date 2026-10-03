"""캔들 기반 백테스트 (단일 종목)"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from bot.models import Order, Position, Side
from bot.strategies.base import Strategy


@dataclass
class BTTrade:
    ts: pd.Timestamp
    side: Side
    price: float
    volume: float
    krw: float
    fee: float
    reason: str
    pnl_krw: Optional[float] = None


@dataclass
class BacktestResult:
    strategy: str
    ticker: str
    initial_krw: float
    final_krw: float
    trades: list[BTTrade]
    equity: pd.Series
    metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        lines = [
            f"전략        : {self.strategy}",
            f"종목        : {self.ticker}",
            f"기간        : {m['start']} ~ {m['end']} ({m['bars']}봉)",
            f"초기자본    : {self.initial_krw:,.0f}원",
            f"최종자산    : {self.final_krw:,.0f}원",
            f"수익률      : {m['total_return_pct']:+.2f}%",
            f"단순보유    : {m['buy_hold_return_pct']:+.2f}%",
            f"최대낙폭MDD : {m['mdd_pct']:.2f}%",
            f"거래횟수    : {m['n_trades']}회 (왕복)",
            f"승률        : {m['win_rate_pct']:.1f}%",
            f"평균손익    : {m['avg_pnl_pct']:+.2f}%/거래",
        ]
        return "\n".join(lines)


def _metrics(df: pd.DataFrame, equity: pd.Series, trades: list[BTTrade], initial: float) -> dict[str, Any]:
    final = float(equity.iloc[-1])
    peak = equity.cummax()
    dd = (equity / peak - 1) * 100
    sells = [t for t in trades if t.side == Side.SELL and t.pnl_krw is not None]
    wins = [t for t in sells if t.pnl_krw > 0]
    pnl_pcts = []
    buy_price = None
    for t in trades:
        if t.side == Side.BUY:
            buy_price = t.price
        elif buy_price:
            pnl_pcts.append((t.price / buy_price - 1) * 100)
            buy_price = None
    return {
        "start": str(df.index[0].date()), "end": str(df.index[-1].date()), "bars": len(df),
        "total_return_pct": (final / initial - 1) * 100,
        "buy_hold_return_pct": (float(df["close"].iloc[-1]) / float(df["open"].iloc[0]) - 1) * 100,
        "mdd_pct": float(dd.min()),
        "n_trades": len(sells),
        "win_rate_pct": (len(wins) / len(sells) * 100) if sells else 0.0,
        "avg_pnl_pct": float(np.mean(pnl_pcts)) if pnl_pcts else 0.0,
    }


def run_backtest(strategy: Strategy, df: pd.DataFrame, ticker: str = "", initial_krw: float = 1_000_000,
                 fee_rate: float = 0.0005, stop_loss_pct: float = 0.0, take_profit_pct: float = 0.0,
                 warmup: Optional[int] = None) -> BacktestResult:
    """df: open/high/low/close 캔들. 각 봉에서 전략이 낸 주문을 봉 안에서 체결시킨다.

    - price 가 있는 매수: 봉의 high >= price 면 max(price, open) 에 체결 (갭상승 시 시가)
    - price 가 있는 매도: 봉의 low <= price 면 min(price, open) 에 체결
    - price 없는 주문: at="open" 이면 시가, 아니면 종가 체결
    """
    krw = initial_krw
    pos: Optional[Position] = None
    trades: list[BTTrade] = []
    equity_vals: list[float] = []
    warmup = warmup if warmup is not None else max(1, min(strategy.candles, len(df) - 1))

    def do_buy(ts, price, reason):
        nonlocal krw, pos
        fee = krw * fee_rate
        vol = (krw - fee) / price
        trades.append(BTTrade(ts, Side.BUY, price, vol, krw - fee, fee, reason))
        pos = Position(ticker, vol, price, ts.to_pydatetime())
        krw = 0.0

    def do_sell(ts, price, reason):
        nonlocal krw, pos
        gross = pos.volume * price
        fee = gross * fee_rate
        pnl = (price - pos.avg_price) * pos.volume - fee
        trades.append(BTTrade(ts, Side.SELL, price, pos.volume, gross, fee, reason, pnl))
        krw += gross - fee
        pos = None

    def try_fill(order: Order, bar: pd.Series, ts) -> bool:
        if order.side == Side.BUY:
            if pos is not None:
                return False
            if order.price is not None:
                if bar["high"] >= order.price:
                    do_buy(ts, max(order.price, bar["open"]), order.reason)
                    return True
                return False
            do_buy(ts, bar["open"] if order.at == "open" else bar["close"], order.reason)
            return True
        if pos is None:
            return False
        if order.price is not None:
            if bar["low"] <= order.price:
                do_sell(ts, min(order.price, bar["open"]), order.reason)
                return True
            return False
        do_sell(ts, bar["open"] if order.at == "open" else bar["close"], order.reason)
        return True

    for i in range(len(df)):
        bar = df.iloc[i]
        ts = df.index[i]
        if i >= warmup:
            window = df.iloc[: i + 1]
            # 1) 리스크 (손절/익절): 봉 안에서 도달했으면 체결
            if pos is not None:
                if stop_loss_pct and bar["low"] <= pos.avg_price * (1 + stop_loss_pct / 100):
                    do_sell(ts, min(pos.avg_price * (1 + stop_loss_pct / 100), bar["open"]), f"손절 {stop_loss_pct}%")
                elif take_profit_pct and bar["high"] >= pos.avg_price * (1 + take_profit_pct / 100):
                    do_sell(ts, max(pos.avg_price * (1 + take_profit_pct / 100), bar["open"]), f"익절 {take_profit_pct}%")
            # 2) 전략: 매도 후 같은 봉에서 재매수가 가능하도록 최대 2회 판단
            for _ in range(2):
                order = strategy.decide(window, pos, ts.to_pydatetime())
                if order is None or not try_fill(order, bar, ts):
                    break
                if order.side == Side.BUY:
                    break
        equity_vals.append(krw + (pos.volume * float(bar["close"]) if pos else 0.0))

    equity = pd.Series(equity_vals, index=df.index, name="equity")
    final = float(equity.iloc[-1])
    res = BacktestResult(strategy.describe(), ticker, initial_krw, final, trades, equity)
    res.metrics = _metrics(df, equity, trades, initial_krw)
    return res
