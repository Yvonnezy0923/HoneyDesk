"""操作留痕与审批记录：只经本服务追加，禁止改删."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, desc

from ..database import session
from ..models.audit import AuditLog, ApprovalRecord


def record(op_id: str, action: str, op_type: str = "read", *,
           operator: str = "agent", agent_code: str = "", task_id: str = "",
           table_name: str = "", params: dict | None = None,
           before: dict | None = None, after: dict | None = None,
           result: str = "success", reviewer: str = "",
           approved_at: datetime | None = None, audit_id: str | None = None) -> str:
    from .. import ids
    aid = audit_id or ids.audit_id()
    log = AuditLog(
        audit_id=aid,
        op_id=op_id,
        task_id=task_id,
        operator=operator,
        agent_code=agent_code,
        op_type=op_type,
        action=action,
        table_name=table_name,
        params=params,
        before=before,
        after=after,
        result=result,
        reviewer=reviewer,
        approved_at=approved_at,
        immutable=True,
    )
    with session() as db:
        db.add(log)
    return aid


def record_approval(approval_id: str, op_id: str, task_id: str, agent_code: str,
                    table_name: str, changes: dict | None, decision: str,
                    reviewer: str, note: str, decided_at: datetime | None = None) -> None:
    rec = ApprovalRecord(
        approval_id=approval_id,
        op_id=op_id,
        task_id=task_id,
        agent_code=agent_code,
        table_name=table_name,
        changes=changes,
        decision=decision,
        reviewer=reviewer,
        note=note,
        decided_at=decided_at or datetime.utcnow(),
    )
    with session() as db:
        db.add(rec)


# ────────────────────────── 查询（只读） ──────────────────────────
def list_logs(table_name: str | None = None, agent_code: str | None = None,
              op_type: str | None = None, limit: int = 100) -> list[dict]:
    with session() as db:
        stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        # 操作日志只反映真实读/写/审批操作；artifact 属 agent 中间产物，默认过滤
        stmt = stmt.where(AuditLog.op_type != "artifact")
        if table_name:
            stmt = stmt.where(AuditLog.table_name == table_name)
        if agent_code:
            stmt = stmt.where(AuditLog.agent_code == agent_code)
        if op_type:
            stmt = stmt.where(AuditLog.op_type == op_type)
        return [_row_to_dict(r) for r in db.execute(stmt).scalars().all()]


def list_approval_records(limit: int = 200) -> list[dict]:
    with session() as db:
        stmt = select(ApprovalRecord).order_by(desc(ApprovalRecord.created_at)).limit(limit)
        return [_row_to_dict(r) for r in db.execute(stmt).scalars().all()]


def _row_to_dict(r: Any) -> dict:
    # 用 mapper 属性键取值：before/after 在表列映射为 before_state/after_state
    mapper = type(r).__mapper__
    return {col.name: getattr(r, prop.key)
            for prop in mapper.column_attrs for col in prop.columns}