"""전략 레지스트리. 새 전략은 이 패키지에 파일을 추가하고 @register 로 등록."""
from __future__ import annotations

from typing import Any

from .base import Strategy, register, REGISTRY  # noqa: F401

# 등록을 위해 import (순서 무관)
from . import volatility_breakout, ma_cross, rsi  # noqa: E402,F401


def create(name: str, **params: Any) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"알 수 없는 전략: {name}. 사용 가능: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name](**params)


def names() -> list[str]:
    return sorted(REGISTRY)
