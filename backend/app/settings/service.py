"""系统设置服务：LLM 配置读写、连接测试、Embedding 后端信息."""
from __future__ import annotations

import json

from ..database import session
from ..models import business as bm
from ..llm import LLMConfig, test_connection


def get_public_settings() -> dict:
    """返回不含密钥的公开设置 + 当前 embedding 实际后端."""
    cfg = LLMConfig.from_db()
    data = cfg.to_dict()
    # 安全：不回传完整 api_key
    if data.get("api_key"):
        data["api_key_masked"] = data["api_key"][:6] + "***"
    data.pop("api_key", None)
    actual = _get_val("embedding_backend_actual") or "fallback"
    return {"llm": data, "embedding_backend": actual}


def save_llm(api_base: str, api_key: str, model: str, light_model: str = "",
             timeout: float = 90.0) -> dict:
    payload = {"api_base": api_base.strip(), "api_key": api_key.strip(),
               "model": model.strip(), "light_model": light_model.strip(),
               "timeout": timeout}
    with session() as db:
        row = db.get(bm.Setting, "llm_config")
        if row:
            row.value = json.dumps(payload, ensure_ascii=False)
        else:
            db.add(bm.Setting(key="llm_config", value=json.dumps(payload, ensure_ascii=False)))
    return {"ok": True}


def test() -> dict:
    cfg = LLMConfig.from_db()
    if not cfg.configured:
        return {"ok": False, "message": "未配置 LLM"}
    return test_connection(cfg)


def _get_val(key: str) -> str:
    try:
        with session() as db:
            row = db.get(bm.Setting, key)
            return row.value if row else ""
    except Exception:  # noqa: BLE001
        return ""