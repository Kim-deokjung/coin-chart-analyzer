import numpy as np
import pandas as pd

from bot import strategies
from bot.backtest import run_backtest
from bot.models import Side


def synth(n=200, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
    idx = pd.date_range("2025-01-01 09:00", periods=n, freq="D")
    op = np.roll(close, 1); op[0] = close[0]
    hi = np.maximum(op, close) * (1 + rng.uniform(0, 0.03, n))
    lo = np.minimum(op, close) * (1 - rng.uniform(0, 0.03, n))
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": 1}, index=idx)


def test_backtest_runs_and_is_consistent():
    df = synth()
    for name in strategies.names():
        strat = strategies.create(name, **({"interval": "day"} if name == "rsi" else {}))
        res = run_backtest(strat, df, "TEST", 1_000_000, 0.0005)
        assert len(res.equity) == len(df)
        assert res.final_krw > 0
        # 매수/매도가 교대로 나와야 함
        sides = [t.side for t in res.trades]
        for a, b in zip(sides, sides[1:]):
            assert a != b
        assert "total_return_pct" in res.metrics


def test_breakout_fill_rules():
    df = synth(60, seed=3)
    strat = strategies.create("volatility_breakout", k=0.5)
    res = run_backtest(strat, df, "TEST", 1_000_000, 0.0)
    for t in res.trades:
        bar = df.loc[t.ts]
        if t.side == Side.BUY:
            assert bar["low"] - 1e-9 <= t.price <= bar["high"] + 1e-9
            assert t.price >= bar["open"] - 1e-9  # 갭상승이면 시가
        else:
            assert abs(t.price - bar["open"]) < 1e-9  # 다음날 시가 매도


def test_stop_loss_triggers():
    n = 30
    close = np.linspace(100, 50, n)
    idx = pd.date_range("2025-01-01 09:00", periods=n, freq="D")
    df = pd.DataFrame({"open": close + 1, "high": close + 2, "low": close - 2, "close": close, "volume": 1}, index=idx)
    strat = strategies.create("ma_cross", short=2, long=3)
    # 강제로 첫 봉에 매수시키는 전략 대신 손절 동작만 확인: 매수 후 하락
    from bot.models import Order
    class AlwaysBuy(strategies.Strategy):
        name = "always_buy"; interval = "day"; candles = 1
        def decide(self, df, position, now):
            return None if position else Order(Side.BUY)
    res = run_backtest(AlwaysBuy(), df, "TEST", 1_000_000, 0.0, stop_loss_pct=-5.0)
    sells = [t for t in res.trades if t.side == Side.SELL]
    assert sells and all("손절" in t.reason for t in sells)
