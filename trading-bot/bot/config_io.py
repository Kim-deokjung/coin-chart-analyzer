"""config.yaml 읽기/쓰기 (주석 보존)"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from bot.config import load_config

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def read_raw(path: str | Path = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return _yaml.load(f) or {}


def _merge(dst: Any, src: dict[str, Any]) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def update(path: str | Path, changes: dict[str, Any]) -> dict[str, Any]:
    """changes 를 기존 설정에 병합해 저장. 저장 전 load_config 로 검증한다."""
    path = Path(path)
    doc = read_raw(path)
    _merge(doc, changes)
    buf = io.StringIO()
    _yaml.dump(doc, buf)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    try:
        load_config(tmp)  # 검증 (live 인데 키 없으면 여기서 실패)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return read_raw(path)
