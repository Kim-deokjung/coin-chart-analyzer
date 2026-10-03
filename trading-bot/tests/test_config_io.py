import shutil
from pathlib import Path

import pytest

from bot import config_io
from bot.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def test_update_preserves_comments_and_validates(tmp_path):
    cfg = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.yaml", cfg)
    new = config_io.update(cfg, {"strategy": "rsi", "strategy_params": {"rsi": {"period": 21}}, "risk": {"stop_loss_pct": -3}})
    assert new["strategy"] == "rsi" and new["strategy_params"]["rsi"]["period"] == 21
    assert new["strategy_params"]["volatility_breakout"]["k"] == 0.5  # 다른 전략 설정은 유지
    text = cfg.read_text(encoding="utf-8")
    assert "# 업비트 자동매매 봇 설정" in text  # 주석 보존
    c = load_config(cfg)
    assert c.risk.stop_loss_pct == -3 and c.risk.max_positions == 2

    # live 인데 키가 없으면 저장 거부, 파일은 그대로
    with pytest.raises(ValueError):
        config_io.update(cfg, {"mode": "live"})
    assert load_config(cfg).mode == "paper"
