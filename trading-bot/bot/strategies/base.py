from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Type

import pandas as pd

from bot.models import Order, Position

REGISTRY: dict[str, Type["Strategy"]] = {}


def register(cls: Type["Strategy"]) -> Type["Strategy"]:
    REGISTRY[cls.name] = cls
    return cls


class Strategy(ABC):
    """매매 전략 인터페이스.

    decide() 는 캔들 데이터(df)와 현재 포지션을 보고 Order 또는 None 을 반환한다.
    df 의 마지막 행은 '진행 중인' 캔들이다. 실시간에서는 close 가 현재가이고,
    백테스트에서는 미래를 엿보지 않도록 open 과 가격 트리거(price)만 신뢰해야 한다.
    """

    name: str = "base"
    interval: str = "day"   # pyupbit 캔들 단위: day, minute240, minute60, minute15 ...
    candles: int = 60       # decide 에 필요한 캔들 수

    def __init__(self, **params):
        for k, v in params.items():
            if k == "interval":
                self.interval = v
            elif hasattr(self, k):
                setattr(self, k, v)
            else:
                raise TypeError(f"{self.name}: 알 수 없는 파라미터 '{k}'")

    @abstractmethod
    def decide(self, df: pd.DataFrame, position: Optional[Position], now: datetime) -> Optional[Order]:
        ...

    def describe(self) -> str:
        return f"{self.name}({self.interval})"

    @classmethod
    def param_schema(cls) -> dict[str, object]:
        """UI 에 보여줄 파라미터와 기본값. 클래스 속성 중 숫자/문자열 (name, candles 제외)."""
        out: dict[str, object] = {}
        for klass in reversed(cls.__mro__):
            for k, v in vars(klass).items():
                if k.startswith("_") or k in ("name", "candles", "label") or callable(v) or isinstance(v, (classmethod, staticmethod, property)):
                    continue
                if isinstance(v, (int, float, str)) and not isinstance(v, bool):
                    out[k] = v
        return out

    label: str = ""
