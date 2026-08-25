"""审批策略配置：白名单自动通过 / 默认审批人 / 超时时长 / 阈值规则引擎.

P1「审批策略配置」：策略以 JSON 存于 settings 表（key="approval_policy"），前端可查看/编辑。
P2「审批规则引擎（阈值自动规则）」：新增 rules 字段，支持按表/字段/数值阈值自动放行。

规则引擎逻辑：
  - enabled=False（默认）：所有写操作仍必须人工审批；
  - enabled=True 时，命中规则且满足阈值条件的写操作自动通过（仍留完整审批记录）；
  - 规则优先级：先匹配 auto_approve_tables，再匹配 rules 列表。
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..database import session
from ..models import business as bm

_SETTING_KEY = "approval_policy"

_DEFAULT: dict = {
    "enabled": False,
    "auto_approve_tables": [],
    "default_reviewer": "user",
    "timeout_hours": None,
    # P2 阈值规则引擎
    "rules": [],
}

# 支持的比较运算符
_COMPARATORS = {
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "pct_lt": lambda a, b: _pct_change(a, b) < b if isinstance(b, (int, float)) else False,
    "pct_le": lambda a, b: _pct_change(a, b) <= b if isinstance(b, (int, float)) else False,
    "pct_ge": lambda a, b: _pct_change(a, b) >= b if isinstance(b, (int, float)) else False,
    "pct_gt": lambda a, b: _pct_change(a, b) > b if isinstance(b, (int, float)) else False,
}


def _pct_change(new_val: float, old_val: float) -> float:
    """计算百分比变化 |new - old| / max(old, 1)."""
    old = max(abs(old_val), 1)
    return abs(float(new_val) - float(old_val)) / old * 100


def get_policy() -> dict:
    try:
        with session() as db:
            row = db.get(bm.Setting, _SETTING_KEY)
    except Exception:  # noqa: BLE001  表未就绪时返回默认策略
        return dict(_DEFAULT)
    if not row or not row.value:
        return dict(_DEFAULT)
    try:
        p = json.loads(row.value)
    except Exception:  # noqa: BLE001  配置损坏时回退默认
        return dict(_DEFAULT)
    d = dict(_DEFAULT)
    d.update(p or {})
    return d


def save_policy(policy: dict | None = None) -> dict:
    d = dict(_DEFAULT)
    d.update(policy or {})
    d["enabled"] = bool(d.get("enabled"))
    d["auto_approve_tables"] = [str(t) for t in (d.get("auto_approve_tables") or []) if t]
    d["default_reviewer"] = str(d.get("default_reviewer") or "user")
    d["timeout_hours"] = int(d["timeout_hours"]) if d.get("timeout_hours") else None
    # P2 规则引擎：验证并清理规则
    d["rules"] = _validate_rules(d.get("rules") or [])
    payload = json.dumps(d, ensure_ascii=False)
    with session() as db:
        row = db.get(bm.Setting, _SETTING_KEY)
        if row:
            row.value = payload
        else:
            db.add(bm.Setting(key=_SETTING_KEY, value=payload))
    return d


def _validate_rules(rules: list) -> list:
    """验证规则格式，去除无效规则."""
    valid = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        table = str(r.get("table", "")).strip()
        field = str(r.get("field", "")).strip()
        operator = str(r.get("operator", "")).strip()
        threshold = r.get("threshold")
        if table and field and operator in _COMPARATORS and threshold is not None:
            # 确保阈值可转为数值
            try:
                float(threshold)
            except (ValueError, TypeError):
                continue
            valid.append({
                "table": table,
                "field": field,
                "operator": operator,
                "threshold": threshold,
                "action": r.get("action", "auto_approve"),
                "description": str(r.get("description", "")),
            })
    return valid


def needs_manual(table: str, changes: dict | None = None) -> bool:
    """该表的写操作是否仍需人工审批.

    先检查 enabled；再检查 auto_approve_tables；最后检查阈值规则。
    changes 格式：{"field_name": [old_val, new_val], ...}
    """
    p = get_policy()
    if not p.get("enabled"):
        return True

    # 1) 白名单表直接放行
    if table in (p.get("auto_approve_tables") or []):
        return False

    # 2) 阈值规则匹配
    rules = p.get("rules") or []
    if rules and changes:
        for rule in rules:
            if rule["table"] != table:
                continue
            field = rule["field"]
            if field not in changes:
                continue
            old_val, new_val = changes[field]
            # 尝试转为数值比较
            try:
                old_num = float(old_val) if old_val is not None else 0
                new_num = float(new_val) if new_val is not None else 0
            except (ValueError, TypeError):
                continue
            operator_fn = _COMPARATORS.get(rule["operator"])
            if operator_fn and operator_fn(new_num, float(rule["threshold"])):
                # 规则命中，检查动作
                if rule.get("action") == "auto_approve":
                    return False
                if rule.get("action") == "escalate":
                    # 升级审批：始终需要人工
                    return True
    return True


def default_reviewer() -> str:
    return str(get_policy().get("default_reviewer") or "user")


def get_rules() -> list[dict]:
    """返回当前配置的活跃规则列表."""
    p = get_policy()
    return p.get("rules") or []


def evaluate_rules(table: str, changes: dict) -> list[dict]:
    """评估所有规则，返回命中规则列表.

    Returns:
        [{rule: dict, matched: bool, action: str, reason: str}]
    """
    p = get_policy()
    if not p.get("enabled"):
        return []

    rules = p.get("rules") or []
    hits = []
    for rule in rules:
        if rule["table"] != table:
            continue
        field = rule["field"]
        if field not in changes:
            continue
        old_val, new_val = changes[field]
        try:
            old_num = float(old_val) if old_val is not None else 0
            new_num = float(new_val) if new_val is not None else 0
        except (ValueError, TypeError):
            continue
        operator_fn = _COMPARATORS.get(rule["operator"])
        if operator_fn and operator_fn(new_num, float(rule["threshold"])):
            hits.append({
                "rule": rule,
                "matched": True,
                "action": rule.get("action", "auto_approve"),
                "reason": f"字段[{field}] {rule['operator']} {rule['threshold']} "
                          f"(旧值={old_val}, 新值={new_val})",
            })
    return hits