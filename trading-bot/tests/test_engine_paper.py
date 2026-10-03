"""네트워크 없이 모의투자 엔진 전체 흐름 검증"""
import numpy as np
import pandas as pd
import pytest

from bot import data
from bot.config import Config, RiskConfig
from bot.engine import Trader
from bot.exchange.paper import PaperExchange
from bot.models import Order, Side
from bot.store import Store
from bot.strategies.base import Strategy


class Scripted(Strategy):
    name = "scripted"; interval = "day"; candles = 3
    def __init__(self): self.next = None
    def decide(self, df, position, now): return self.next


@pytest.fixture
def market(monkeypatch):
    state = {"price": 100.0}
    def ohlcv(ticker, interval, count):
        idx = pd.date_range("2026-01-01 09:00", periods=count, freq="D")
        c = np.full(count, state["price"])
        return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1}, index=idx)
    monkeypatch.setattr(data, "get_price", lambda t: state["price"])
    monkeypatch.setattr(data, "get_ohlcv", ohlcv)
    return state


def test_paper_buy_sell_cycle(tmp_path, market):
    db = tmp_path / "t.db"
    cfg = Config(tickers=["KRW-BTC"], initial_krw=100_000, fee_rate=0.001, db_path=str(db),
                 risk=RiskConfig(max_positions=1, order_krw_ratio=1.0, min_order_krw=5000, stop_loss_pct=-10))
    store = Store(db)
    ex = PaperExchange(store, cfg.initial_krw, cfg.fee_rate)
    strat = Scripted()
    tr = Trader(cfg, ex, strat, store)

    # 트리거 가격 미도달 -> 매수 안 함
    strat.next = Order(Side.BUY, price=150)
    tr.step()
    assert ex.get_position("KRW-BTC") is None

    # 트리거 도달 -> 매수
    market["price"] = 160
    tr.step()
    pos = ex.get_position("KRW-BTC")
    assert pos is not None and pos.avg_price == 160 and pos.opened_at is not None
    assert ex.get_krw() <= 100  # 수수료 여유 0.1% 만 남음

    # 포지션 있으면 BUY 는 무시
    tr.step()
    assert len(store.trades()) == 1

    # 가격 상승 후 매도 -> 실현손익 양수
    market["price"] = 200
    strat.next = Order(Side.SELL, reason="테스트 매도")
    tr.step()
    assert ex.get_position("KRW-BTC") is None
    trades = store.trades()
    assert trades[0]["side"] == "SELL" and trades[0]["pnl_krw"] > 0
    assert ex.get_krw() > 100_000

    # 잔고가 DB 에 저장되어 재시작해도 유지
    ex2 = PaperExchange(Store(db), 1, cfg.fee_rate)
    assert abs(ex2.get_krw() - ex.get_krw()) < 1e-6

    # 자산 스냅샷/상태 기록
    st = store.status()
    assert st["mode"] == "paper" and st["total_krw"] == pytest.approx(ex.get_krw())
    assert len(store.equity()) == 4


def test_stop_loss_overrides_strategy(tmp_path, market):
    db = tmp_path / "t.db"
    cfg = Config(tickers=["KRW-BTC"], initial_krw=100_000, db_path=str(db),
                 risk=RiskConfig(max_positions=1, order_krw_ratio=1.0, stop_loss_pct=-5))
    store = Store(db)
    ex = PaperExchange(store, cfg.initial_krw)
    strat = Scripted(); strat.next = Order(Side.BUY)
    tr = Trader(cfg, ex, strat, store)
    tr.step()
    assert ex.get_position("KRW-BTC") is not None
    market["price"] = 94  # -6%
    strat.next = None     # 전략은 아무 말 없어도 손절은 동작
    tr.step()
    assert ex.get_position("KRW-BTC") is None
    assert "손절" in store.trades()[0]["reason"]


def test_max_positions_respected(tmp_path, market):
    db = tmp_path / "t.db"
    cfg = Config(tickers=["KRW-BTC", "KRW-ETH"], initial_krw=100_000, db_path=str(db),
                 risk=RiskConfig(max_positions=1, order_krw_ratio=0.5))
    store = Store(db)
    ex = PaperExchange(store, cfg.initial_krw)
    strat = Scripted(); strat.next = Order(Side.BUY)
    Trader(cfg, ex, strat, store).step()
    assert len(ex.positions(cfg.tickers)) == 1
