"""大模型客户端：用户自定义 API 配置（OpenAI 兼容协议，不锁定模型）."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from .config import get_settings
from .database import business_session
from .logging_config import get_llm_logger
from .models.business import Setting

_lock = threading.Lock()
_LLM_TOKEN_KEY = "llm_token_count"
_LLM_COST_KEY = "llm_cost_usd"          # 累计估算成本（美元）
# 看板「成本」指标的估算费率：按模型名子串匹配每百万 token 混合费率（$/M tokens）。
# 仅供内部成本雷达使用，非账单级精度；未知模型回退默认费率。
_MODEL_PRICE_PER_MTOK = [
    ("mini", 0.8), ("flash", 0.5), ("haiku", 1.0), ("lite", 1.0),
    ("deepseek-chat", 0.5), ("deepseek", 1.0),
    ("claude-opus", 25.0), ("claude-sonnet", 8.0), ("claude-3.5", 8.0),
    ("claude-3", 12.0), ("claude", 10.0),
    ("gpt-4o", 5.0), ("gpt-4", 15.0),
    ("glm-4", 4.0), ("glm-5", 4.0),
    ("qwen", 2.0), ("moonshot", 2.0), ("kimi", 2.0), ("abab", 2.0),
    ("llama", 1.5), ("mistral", 2.0), ("gemini", 2.0),
]
_DEFAULT_PRICE_PER_MTOK = 3.0


def _day_key() -> str:
    # 东八区自然日，用于按日统计（与官方控制台口径对齐）
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")


def estimate_cost_usd(model: str, total_tokens: int) -> float:
    """按模型名估算一次调用的美元成本（混合费率，忽略计价明细）."""
    if not total_tokens:
        return 0.0
    rate = _DEFAULT_PRICE_PER_MTOK
    name = (model or "").lower()
    for key, r in _MODEL_PRICE_PER_MTOK:
        if key in name:
            rate = r
            break
    return round(total_tokens / 1_000_000 * rate, 6)


def _record_usage(model: str, total: int) -> None:
    """累计 LLM 消耗（token + 估算成本）落库（看板统计用；失败不影响推理）."""
    if not total:
        return
    cost = estimate_cost_usd(model, total)
    with _lock:
        try:
            with business_session() as db:
                day = _day_key()
                for key, add, as_int in (
                    (_LLM_TOKEN_KEY, total, True), (f"{_LLM_TOKEN_KEY}_{day}", total, True),
                    (_LLM_COST_KEY, cost, False), (f"{_LLM_COST_KEY}_{day}", cost, False),
                ):
                    row = db.get(Setting, key)
                    prev = float(row.value or 0) if row else 0.0
                    nv = prev + add
                    if row:
                        row.value = str(int(nv)) if as_int else str(round(nv, 6))
                    else:
                        db.add(Setting(key=key, value=str(int(nv)) if as_int else str(round(nv, 6))))
        except Exception:  # noqa: BLE001
            pass


class LLMConfig:
    def __init__(self, api_base: str, api_key: str, model: str, light_model: str = "",
                 timeout: float = 90.0):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.light_model = light_model or model
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_base and self.model)

    @classmethod
    def from_db(cls) -> "LLMConfig":
        """优先读取 settings 表中用户配置，否则回退环境变量."""
        s = get_settings()
        with business_session() as db:
            row = db.get(Setting, "llm_config")
            data = json.loads(row.value) if row else {}
        cfg = LLMConfig(
            api_base=data.get("api_base") or s.llm_api_base,
            api_key=data.get("api_key") or s.llm_api_key,
            model=data.get("model") or s.llm_model,
            light_model=data.get("light_model") or s.llm_light_model,
            timeout=data.get("timeout") or s.llm_timeout,
        )
        return cfg


def _day_key() -> str:
    # 东八区自然日，用于按日统计（与官方控制台口径对齐）
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")


# ── Agent·大模型对话流日志（写入 log/agent/{date}.log，截断超长内容） ──
_LLM_LOG_MAX = 4000        # 单段消息/响应截断字符数（避免大 prompt 撑爆日志文件）


def _local8_now() -> str:
    # 东八区当下时间（日志需记录真实本地时间，不用 UTC）
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _log_interaction(cfg: LLMConfig, model: str, messages: list[dict],
                     status: str, latency_ms: int, tokens: dict,
                     response: str = "", error: str = "") -> None:
    try:
        brief = []
        for m in (messages or []):
            text = (m.get("content") or "")
            role = m.get("role", "?")
            brief.append({"role": role, "content": text[:_LLM_LOG_MAX]})
        get_llm_logger().info(
            json.dumps({
                "event": "llm_call", "ts": _local8_now(), "api_base": cfg.api_base,
                "model": model, "status": status,
                "latency_ms": latency_ms, "tokens": tokens or {},
                "response": (response or "")[:_LLM_LOG_MAX],
                "error": (error or "")[:2000],
                "messages": brief,
            }, ensure_ascii=False))
    except Exception:  # noqa: BLE001  LLM 日志失败不影响推理
        pass


def _chat(cfg: LLMConfig, messages: list[dict], model: str | None = None,
          temperature: float = 0.3, max_tokens: int = 1500,
          response_format: str | None = None) -> str:
    if not cfg.configured:
        raise RuntimeError("LLM 未配置：请在系统设置填写 API Endpoint / Key / 模型")
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    body: dict[str, Any] = {
        "model": model or cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        body["response_format"] = {"type": response_format}
    use_model = body["model"]
    started = time.time()
    try:
        with httpx.Client(timeout=cfg.timeout) as client:
            r = client.post(f"{cfg.api_base}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            total = usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
            content = data["choices"][0]["message"]["content"]
            _log_interaction(cfg, use_model, messages, status="ok",
                             latency_ms=int((time.time() - started) * 1000),
                             tokens=usage, response=content)
            if total:
                _record_usage(use_model, total)
            return content
    except Exception as e:  # noqa: BLE001
        _log_interaction(cfg, use_model, messages, status="error",
                         latency_ms=int((time.time() - started) * 1000),
                         tokens={}, error=str(e))
        raise


def chat_json(cfg: LLMConfig, system: str, user: str, model: str | None = None,
              temperature: float = 0.1, max_tokens: int = 2000) -> dict:
    """强制 JSON 结构化输出."""
    messages = [
        {"role": "system", "content": system + "\n只输出合法 JSON，不要附加任何其它文本。"},
        {"role": "user", "content": user},
    ]
    raw = _chat(cfg, messages, model=model or cfg.light_model,
                temperature=temperature, max_tokens=max_tokens, response_format="json_object")
    return _parse_json(raw)


def chat_text(cfg: LLMConfig, system: str, user: str, model: str | None = None,
              temperature: float = 0.3) -> str:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return _chat(cfg, messages, model=model or cfg.model, temperature=temperature).strip()


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # 去代码围栏
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if "```" in raw:
            raw = raw.split("```")[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 兜底：提取第一个 { ... } 块
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def test_connection(cfg: LLMConfig) -> dict:
    try:
        ans = chat_text(cfg, "你是连接测试助手。", "请只回复：ok")
        return {"ok": True, "message": ans[:120]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}