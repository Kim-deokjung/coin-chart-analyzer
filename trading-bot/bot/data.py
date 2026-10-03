"""업비트 공개 시세 (API 키 불필요)"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import pyupbit


def get_ohlcv(ticker: str, interval: str = "day", count: int = 200) -> pd.DataFrame:
    """캔들 조회. count 가 200 을 넘으면 여러 번 나눠 받는다 (업비트 1회 최대 200)."""
    frames: list[pd.DataFrame] = []
    remaining = count
    to: Optional[pd.Timestamp] = None
    while remaining > 0:
        n = min(remaining, 200)
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=n, to=to)
        if df is None or df.empty:
            break
        frames.append(df)
        remaining -= len(df)
        to = df.index[0]
        if len(df) < n:
            break
        time.sleep(0.12)  # 초당 요청 제한 여유
    if not frames:
        raise RuntimeError(f"{ticker} {interval} 캔들을 받아오지 못했습니다")
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def get_price(ticker: str) -> float:
    p = pyupbit.get_current_price(ticker)
    if p is None:
        raise RuntimeError(f"{ticker} 현재가 조회 실패")
    return float(p)


def get_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    res = pyupbit.get_current_price(tickers)
    if isinstance(res, dict):
        return {k: float(v) for k, v in res.items()}
    return {tickers[0]: float(res)}
