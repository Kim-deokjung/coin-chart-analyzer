"""기술적 지표"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out


def trading_day(ts: pd.Timestamp) -> pd.Timestamp:
    """업비트 일봉 기준일. 일봉은 KST 09:00 에 시작하므로 9시간을 빼서 날짜를 구한다."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Seoul").tz_localize(None)
    return (t - pd.Timedelta(hours=9)).normalize()
