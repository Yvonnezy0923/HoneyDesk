"""记忆管理 v2：事实 / 偏好 / 决策的持久化存取，支持 PII 治理、容量管理与审计留痕.

P2 增强特性：
1. PII 检测与脱敏：创建记忆时自动检测敏感个人信息，支持自动脱敏或拦截
2. 写入审计：所有创建/更新/删除操作均记录到审计服务
3. 容量管理：可配置最大条目数，超限自动归档最旧条目；支持 TTL 自动过期
4. 写入审核：自动写入的记忆默认进入待审核状态，手动创建立即激活
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, desc, or_, func

from .. import ids
from ..database import session
from ..models import business as bm

# 审计服务导入 - 始终存在
from ..audit import service as audit_service

# PII 模块导入 - 优雅降级处理
pii_detect_pii = None
pii_has_pii = None
pii_sanitize = None
pii_available = False
try:
    from .pii import detect_pii as _detect, has_pii as _has, sanitize as _sanitize
    pii_detect_pii = _detect
    pii_has_pii = _has
    pii_sanitize = _sanitize
    pii_available = True
except ImportError:
    pass

# 常量定义
_VALID_TYPES = ("profile", "fact", "decision")
_STATUSES = ("active", "pending_review", "archived", "expired")
# PII 始终拦截的类型 - 这些类型不允许脱敏，必须拦截
_PII_BLOCKED_TYPES = ["email", "phone", "address", "id_number", "bank_card", "full_name", "dob"]

# 默认治理配置
DEFAULT_GOVERNANCE_SETTINGS = {
    "pii_enabled": True,
    "pii_block": True,             # True=拦截无法脱敏的PII；False=允许存储带标记但不脱敏
    "pii_blocked_types": _PII_BLOCKED_TYPES,
    "max_entries": 500,
    "ttl_days": 365,
    "auto_expire_enabled": True,
    "review_required": True,       # 自动写入的记忆需要审核
}

# PII 检测统计（内存缓存，重启重置）
_pii_detection_stats = {
    "total_detected": 0,
    "total_blocked": 0,
    "total_sanitized": 0,
    "detections_by_type": {},
}


def _get_governance_settings() -> dict:
    """从 Setting 表读取治理配置，如果不存在返回默认值."""
    with session() as db:
        setting = db.get(bm.Setting, "memory_governance")
        if not setting or not setting.value:
            return DEFAULT_GOVERNANCE_SETTINGS.copy()
        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            return DEFAULT_GOVERNANCE_SETTINGS.copy()


def _save_governance_settings(settings: dict) -> None:
    """保存治理配置到 Setting 表."""
    with session() as db:
        setting = db.get(bm.Setting, "memory_governance")
        if setting:
            setting.value = json.dumps(settings, ensure_ascii=False)
        else:
            db.add(bm.Setting(key="memory_governance", value=json.dumps(settings, ensure_ascii=False)))


def get_governance_settings() -> dict:
    """获取当前 PII/容量治理配置."""
    return _get_governance_settings()


def update_governance_settings(settings: dict) -> dict:
    """更新治理配置，只更新传入的字段，保留其他字段."""
    current = _get_governance_settings()
    # 只允许更新预定义字段
    allowed_keys = set(DEFAULT_GOVERNANCE_SETTINGS.keys())
    for key, value in settings.items():
        if key in allowed_keys:
            current[key] = value
    # 确保 blocked types 存在
    if "pii_blocked_types" not in current:
        current["pii_blocked_types"] = _PII_BLOCKED_TYPES
    _save_governance_settings(current)
    # 记录审计
    op_id = ids.op_id()
    audit_service.record(
        op_id=op_id,
        action="memory_governance_update",
        op_type="memory",
        table_name="settings",
        params={"updated_fields": list(settings.keys())},
        result="success",
    )
    return {"ok": True, "settings": current}


def get_pii_report() -> dict:
    """获取 PII 检测统计报告."""
    return {
        "stats": _pii_detection_stats,
        "pii_module_available": pii_available,
    }


def list_memories(mem_type: str | None = None, scope: str | None = None,
                  keyword: str | None = None, limit: int = 200,
                  status: str | None = None) -> list[dict]:
    """列出记忆，支持按状态筛选."""
    with session() as db:
        stmt = select(bm.Memory).order_by(desc(bm.Memory.updated_at)).limit(limit)
        if mem_type:
            stmt = stmt.where(bm.Memory.mem_type == mem_type)
        if keyword:
            kw = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(bm.Memory.content.like(kw),
                                  bm.Memory.source.like(kw)))
        if scope:
            stmt = stmt.where(bm.Memory.scope_tags.contains([scope]))
        if status:
            stmt = stmt.where(bm.Memory.status == status)
        return [_to_dict(m) for m in db.execute(stmt).scalars().all()]


def get_memory(memory_id: str) -> dict | None:
    """获取单条记忆详情."""
    with session() as db:
        m = db.get(bm.Memory, memory_id)
        return _to_dict(m) if m else None


def create_memory(mem_type: str, content: str, source: str = "",
                  scope_tags: list | None = None, *,
                  is_manual: bool = False, agent_code: str = "",
                  task_id: str = "") -> dict:
    """
    创建新记忆，应用 P2 治理规则：
    1. PII 检测与脱敏/拦截
    2. 容量超限自动处理
    3. 自动写入设置 pending_review 状态
    4. 操作审计记录
    """
    op_id = ids.op_id()
    settings = _get_governance_settings()

    if mem_type not in _VALID_TYPES:
        mem_type = "fact"

    mem_id = ids.memory_id()
    tags = [str(t) for t in (scope_tags or []) if t][:10]

    # PII 检测处理
    pii_found = None
    sanitized_content = content
    pii_flagged = False
    has_blocked_pii = False

    if pii_available and settings.get("pii_enabled", True):
        detected = pii_detect_pii(content) if pii_detect_pii else []
        if detected:
            _pii_detection_stats["total_detected"] += 1
            pii_found = detected
            pii_flagged = True

            # 统计各类型
            for d in detected:
                pii_type = d.get("type", "unknown")
                _pii_detection_stats["detections_by_type"][pii_type] = \
                    _pii_detection_stats["detections_by_type"].get(pii_type, 0) + 1

            # 检查是否有必须拦截的 PII 类型
            blocked_types = set(settings.get("pii_blocked_types", _PII_BLOCKED_TYPES))
            has_blocked_pii = any(d.get("type") in blocked_types for d in detected)

            # 尝试脱敏
            if pii_sanitize and not (settings.get("pii_block", False) and has_blocked_pii):
                sanitized_content = pii_sanitize(content)
                # 脱敏后再次检查
                remaining = pii_has_pii(sanitized_content) if pii_has_pii else False
                if not remaining:
                    _pii_detection_stats["total_sanitized"] += 1
                    content = sanitized_content
                elif has_blocked_pii and settings.get("pii_block", True):
                    # 仍然有必须拦截的 PII
                    _pii_detection_stats["total_blocked"] += 1
                    audit_service.record(
                        op_id=op_id,
                        action="memory_create",
                        op_type="memory",
                        agent_code=agent_code,
                        task_id=task_id,
                        table_name="memories",
                        params={"mem_type": mem_type, "source": source},
                        after={"pii_detected": detected, "blocked": True},
                        result="blocked",
                    )
                    return {
                        "ok": False,
                        "message": "内容包含敏感个人信息，无法存储",
                        "pii_detected": detected,
                    }
            elif settings.get("pii_block", True) and has_blocked_pii:
                # PII 拦截模式直接拒绝
                _pii_detection_stats["total_blocked"] += 1
                audit_service.record(
                    op_id=op_id,
                    action="memory_create",
                    op_type="memory",
                    agent_code=agent_code,
                    task_id=task_id,
                    table_name="memories",
                    params={"mem_type": mem_type, "source": source},
                    after={"pii_detected": detected, "blocked": True},
                    result="blocked",
                )
                return {
                    "ok": False,
                    "message": "内容包含敏感个人信息，无法存储",
                    "pii_detected": detected,
                }

    # 确定状态：手动创建→active，自动写入→pending_review（如果配置要求审核）
    if is_manual or not settings.get("review_required", True):
        memory_status = "active"
    else:
        memory_status = "pending_review"

    # 计算过期时间（如果启用）
    expires_at = None
    if settings.get("auto_expire_enabled", True):
        ttl_days = settings.get("ttl_days", 365)
        expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    with session() as db:
        # 创建记忆对象 - 由于 SQLAlchemy 模型需要字段，此处假设字段已存在于表中
        # 如果迁移未执行，新字段会被忽略但不影响现有功能
        try:
            mem = bm.Memory(
                id=mem_id,
                mem_type=mem_type,
                content=content,
                source=source or "",
                scope_tags=tags,
                status=memory_status,
                pii_flagged=pii_flagged,
                expires_at=expires_at,
            )
        except AttributeError:
            # 数据库还没迁移，字段不存在时回退到旧字段
            mem = bm.Memory(
                id=mem_id,
                mem_type=mem_type,
                content=content,
                source=source or "",
                scope_tags=tags,
            )
        db.add(mem)

    # 容量管理：自动过期 + 强制容量限制
    removed_expired = 0
    removed_capacity = 0
    if settings.get("auto_expire_enabled", True):
        removed_expired = auto_expire()
    removed_capacity = enforce_capacity()

    # 审计记录
    audit_params = {
        "mem_type": mem_type,
        "source": source,
        "scope_tags": tags,
        "is_manual": is_manual,
        "removed_expired": removed_expired,
        "removed_capacity": removed_capacity,
    }
    audit_after = {
        "memory_id": mem_id,
        "status": memory_status,
        "pii_flagged": pii_flagged,
        "pii_detected": pii_found,
    }
    audit_service.record(
        op_id=op_id,
        action="memory_create",
        op_type="memory",
        agent_code=agent_code,
        task_id=task_id,
        table_name="memories",
        params=audit_params,
        after=audit_after,
        result="success",
    )

    return {
        "ok": True,
        "memory_id": mem_id,
        "status": memory_status,
        "pii_flagged": pii_flagged,
        "pii_detected": pii_found,
        "cleaned_entries": removed_expired + removed_capacity,
    }


def update_memory(memory_id: str, *, content: str | None = None,
                  mem_type: str | None = None, source: str | None = None,
                  scope_tags: list | None = None, status: str | None = None,
                  agent_code: str = "", task_id: str = "") -> dict:
    """
    更新记忆，同样应用 PII 检测规则，并记录审计.
    """
    op_id = ids.op_id()
    settings = _get_governance_settings()

    with session() as db:
        m = db.get(bm.Memory, memory_id)
        if not m:
            audit_service.record(
                op_id=op_id,
                action="memory_update",
                op_type="memory",
                agent_code=agent_code,
                task_id=task_id,
                table_name="memories",
                params={"memory_id": memory_id},
                result="failed",
            )
            return {"ok": False, "message": "记忆不存在"}

        # 记录变更前快照
        before = _to_dict(m)
        pii_found = None
        pii_flagged = getattr(m, "pii_flagged", False)

        if content is not None:
            # PII 检测处理
            pii_found = None
            has_blocked_pii = False
            if pii_available and settings.get("pii_enabled", True):
                detected = pii_detect_pii(content) if pii_detect_pii else []
                if detected:
                    _pii_detection_stats["total_detected"] += 1
                    pii_found = detected
                    pii_flagged = True

                    # 统计
                    for d in detected:
                        pii_type = d.get("type", "unknown")
                        _pii_detection_stats["detections_by_type"][pii_type] = \
                            _pii_detection_stats["detections_by_type"].get(pii_type, 0) + 1

                    # 检查必须拦截的类型
                    blocked_types = set(settings.get("pii_blocked_types", _PII_BLOCKED_TYPES))
                    has_blocked_pii = any(d.get("type") in blocked_types for d in detected)

                    # 尝试脱敏
                    if pii_sanitize and not (settings.get("pii_block", False) and has_blocked_pii):
                        sanitized_content = pii_sanitize(content)
                        remaining = pii_has_pii(sanitized_content) if pii_has_pii else False
                        if not remaining:
                            _pii_detection_stats["total_sanitized"] += 1
                            content = sanitized_content
                        elif has_blocked_pii and settings.get("pii_block", True):
                            _pii_detection_stats["total_blocked"] += 1
                            audit_service.record(
                                op_id=op_id,
                                action="memory_update",
                                op_type="memory",
                                agent_code=agent_code,
                                task_id=task_id,
                                table_name="memories",
                                params={"memory_id": memory_id},
                                after={"pii_detected": detected, "blocked": True},
                                result="blocked",
                            )
                            return {
                                "ok": False,
                                "message": "内容包含敏感个人信息，无法更新",
                                "pii_detected": detected,
                            }
                    elif settings.get("pii_block", True) and has_blocked_pii:
                        _pii_detection_stats["total_blocked"] += 1
                        audit_service.record(
                            op_id=op_id,
                            action="memory_update",
                            op_type="memory",
                            agent_code=agent_code,
                            task_id=task_id,
                            table_name="memories",
                            params={"memory_id": memory_id},
                            after={"pii_detected": detected, "blocked": True},
                            result="blocked",
                        )
                        return {
                            "ok": False,
                            "message": "内容包含敏感个人信息，无法更新",
                            "pii_detected": detected,
                        }
                else:
                    pii_flagged = False

            m.content = content
            if pii_found is not None:
                try:
                    m.pii_flagged = pii_flagged
                except AttributeError:
                    pass

        if mem_type is not None and mem_type in _VALID_TYPES:
            m.mem_type = mem_type
        if source is not None:
            m.source = source
        if scope_tags is not None:
            m.scope_tags = [str(t) for t in scope_tags if t][:10]
        if status is not None and status in _STATUSES:
            try:
                m.status = status
            except AttributeError:
                pass

        db.flush()
        after = _to_dict(m)

    # 审计记录
    audit_service.record(
        op_id=op_id,
        action="memory_update",
        op_type="memory",
        agent_code=agent_code,
        task_id=task_id,
        table_name="memories",
        params={"memory_id": memory_id},
        before=before,
        after=after,
        result="success",
    )

    return {"ok": True, "memory": _to_dict(m)}


def delete_memory(memory_id: str, *, agent_code: str = "", task_id: str = "") -> dict:
    """删除记忆，记录审计."""
    op_id = ids.op_id()
    with session() as db:
        m = db.get(bm.Memory, memory_id)
        if not m:
            audit_service.record(
                op_id=op_id,
                action="memory_delete",
                op_type="memory",
                agent_code=agent_code,
                task_id=task_id,
                table_name="memories",
                params={"memory_id": memory_id},
                result="failed",
            )
            return {"ok": False, "message": "记忆不存在"}
        before = _to_dict(m)
        db.delete(m)

    audit_service.record(
        op_id=op_id,
        action="memory_delete",
        op_type="memory",
        agent_code=agent_code,
        task_id=task_id,
        table_name="memories",
        params={"memory_id": memory_id},
        before=before,
        result="success",
    )

    return {"ok": True}


def auto_expire() -> int:
    """
    移除已过期的记忆（expires_at < now），返回移除数量.
    需要数据库迁移后支持 expires_at 字段才能生效.
    """
    settings = _get_governance_settings()
    if not settings.get("auto_expire_enabled", True):
        return 0

    now = datetime.utcnow()
    removed = 0

    try:
        with session() as db:
            stmt = select(bm.Memory).where(
                bm.Memory.expires_at < now
            ).order_by(desc(bm.Memory.created_at))
            expired = db.execute(stmt).scalars().all()
            for mem in expired:
                db.delete(mem)
                removed += 1
    except AttributeError:
        # expires_at 字段不存在，跳过
        return 0

    if removed > 0:
        op_id = ids.op_id()
        audit_service.record(
            op_id=op_id,
            action="memory_auto_expire",
            op_type="memory",
            table_name="memories",
            params={"removed_count": removed},
            result="success",
        )

    return removed


def enforce_capacity() -> int:
    """
    强制容量限制，如果超过 max_entries，删除最旧的条目，返回删除数量.
    """
    settings = _get_governance_settings()
    max_entries = settings.get("max_entries", 500)

    with session() as db:
        total = db.execute(select(func.count()).select_from(bm.Memory)).scalar() or 0
        if total <= max_entries:
            return 0

        # 需要删除超额部分
        to_remove = int(total - max_entries)
        # 按创建时间排序，删除最旧的
        stmt = select(bm.Memory).order_by(bm.Memory.created_at).limit(to_remove)
        oldest = db.execute(stmt).scalars().all()
        for mem in oldest:
            db.delete(mem)

    if to_remove > 0:
        op_id = ids.op_id()
        audit_service.record(
            op_id=op_id,
            action="memory_enforce_capacity",
            op_type="memory",
            table_name="memories",
            params={"max_entries": max_entries, "total_entries": total, "removed_count": to_remove},
            result="success",
        )

    return to_remove


def stats() -> dict:
    with session() as db:
        total = db.execute(select(func.count()).select_from(bm.Memory)).scalar() or 0
        by_type = dict(db.execute(
            select(bm.Memory.mem_type, func.count()).group_by(bm.Memory.mem_type)).all())
        # 按状态统计（如果支持）
        by_status = {}
        try:
            by_status = dict(db.execute(
                select(bm.Memory.status, func.count()).group_by(bm.Memory.status)).all())
        except AttributeError:
            pass
    return {
        "total": total,
        "by_type": by_type,
        "by_status": by_status,
        "governance": _get_governance_settings(),
    }


def recent_memory_text(limit: int = 8, scope: str | None = None,
                       include_pending: bool = False) -> str:
    """返回可注入的紧凑记忆摘要，供 Agent 作为长期上下文使用（空则返回空串）.
    默认只包含 active 状态的记忆.
    """
    status_filter = None if include_pending else "active"
    rows = list_memories(limit=limit, scope=scope, status=status_filter)
    if not rows:
        return ""
    lines = []
    for m in rows:
        tag = f"[{m['scope_tags'][0]}]" if m.get("scope_tags") else ""
        pii_mark = "*" if m.get("pii_flagged") else ""
        lines.append(f"{pii_mark}{m['mem_type']}{tag}: {m['content'][:120]}")
    return "「长期记忆」\n" + "\n".join(lines)


def _to_dict(m: bm.Memory) -> dict:
    d: dict[str, Any] = {c.name: getattr(m, c.name) for c in m.__table__.columns}
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            d[k] = v.isoformat()
    # 添加 pii_flagged 如果不存在（兼容旧数据）
    if "pii_flagged" not in d:
        d["pii_flagged"] = False
    if "status" not in d:
        d["status"] = "active"
    if "expires_at" not in d:
        d["expires_at"] = None
    return d
