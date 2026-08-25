"""ID 生成：业务/审计/产物等使用可读前缀 + 时间戳 + 随机串."""
from __future__ import annotations

import secrets
import time

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _rand(n: int = 4) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _prefix(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d%H%M%S')}-{_rand()}"


def task_id() -> str:
    return _prefix("TASK")


def step_id() -> str:
    return _prefix("STEP")


def op_id() -> str:
    return _prefix("OP")


def approval_id() -> str:
    return _prefix("AP")


def doc_id() -> str:
    return _prefix("DOC")


def chunk_id() -> str:
    return _prefix("CHK")


def artifact_id() -> str:
    return _prefix("ART")


def session_id() -> str:
    return _prefix("SESS")


def memory_id() -> str:
    return _prefix("MEM")


def audit_id() -> str:
    return _prefix("AUD")


def event_id() -> str:
    return _prefix("EVT")


def import_batch_id() -> str:
    return _prefix("IMP")


def short_id() -> str:
    """短随机 ID（8 位字母数字），用于规则/流程等轻量实体."""
    return _rand(8)