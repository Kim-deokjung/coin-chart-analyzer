from datetime import datetime

import numpy as np
import pandas as pd

from bot import strategies
from bot.indicators import rsi, sma
from bot.models import Position, Side


def make_df(closes, start="2026-01-01 09:00", freq="D"):
    idx = pd.date_range(start, periods=len(closes), freq=freq)
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"open": c * 0.99, "high": c * 1.02, "low": c * 0.97, "close": c, "volume": 1.0}, index=idx)


def test_registry_has_all_strategies():
    assert set(strategies.names()) >= {"volatility_breakout", "ma_cross", "rsi"}


def test_unknown_param_rejected():
    import pytest
    with pytest.raises(TypeError):
        strategies.create("rsi", foo=1)


def test_volatility_breakout_target_and_sell():
    s = strategies.create("volatility_breakout", k=0.5)
    df = make_df([100, 110, 105])
    # 전일(110) 고가 112.2 저가 106.7 -> 범위 5.5, 당일 시가 103.95 -> 목표 106.7
    order = s.decide(df, None, datetime.now())
    assert order.side == Side.BUY
    assert abs(order.price - (103.95 + 5.5 * 0.5)) < 1e-6
    # 전날 산 포지션은 다음날 시가 매도
    pos = Position("KRW-BTC", 1, 100, df.index[-2].to_pydatetime())
    order = s.decide(df, pos, datetime.now())
    assert order.side == Side.SELL and order.at == "open"
    # 오늘 산 포지션은 유지
    pos_today = Position("KRW-BTC", 1, 100, df.index[-1].to_pydatetime())
    assert s.decide(df, pos_today, datetime.now()) is None


def test_ma_cross_signals():
    s = strategies.create("ma_cross", short=2, long=3)
    down = [10, 9, 8, 7, 6]
    up = [7, 8, 9, 10]
    df = make_df(down + up)
    sig = [s.decide(df.iloc[: i + 1], None, datetime.now()) for i in range(len(df))]
    buys = [o for o in sig if o and o.side == Side.BUY]
    assert buys, "상승 전환 시 골든크로스 매수 신호가 있어야 함"
    df2 = make_df(up + down)
    pos = Position("X", 1, 1, None)
    sells = [o for i in range(len(df2)) if (o := s.decide(df2.iloc[: i + 1], pos, datetime.now())) and o.side == Side.SELL]
    assert sells


def test_rsi_bounds_and_signal():
    closes = list(range(100, 60, -2)) + list(range(60, 100, 2))
    df = make_df(closes, freq="h")
    r = rsi(df["close"], 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    s = strategies.create("rsi", period=14, buy_below=30, sell_above=70)
    orders = [s.decide(df.iloc[: i + 1], None, datetime.now()) for i in range(len(df))]
    assert any(o and o.side == Side.BUY for o in orders)


def test_sma():
    s = sma(pd.Series([1, 2, 3, 4]), 2)
    assert s.tolist()[1:] == [1.5, 2.5, 3.5]
