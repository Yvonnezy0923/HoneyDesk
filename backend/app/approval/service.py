"""审批流：数据库变更写操作的强制人工确认闸门."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, desc

from .. import ids
from ..config import get_settings
from ..database import session
from ..models import business as bm
from ..models import audit as am
from ..audit import service as audit_service


def pending_count() -> int:
    with session() as db:
        from sqlalchemy import func
        return db.execute(
            select(func.count()).select_from(bm.Approval).where(
                bm.Approval.status == "pending")).scalar() or 0


def list_pending() -> list[dict]:
    return _list(status="pending")


def list_approvals(status: str | None = None, agent_code: str | None = None,
                   limit: int = 200) -> list[dict]:
    return _list(status=status, agent_code=agent_code, limit=limit)


def _list(status: str | None = None, agent_code: str | None = None,
          limit: int = 200) -> list[dict]:
    _expire_overdue()
    with session() as db:
        stmt = select(bm.Approval).order_by(desc(bm.Approval.created_at)).limit(limit)
        if status:
            stmt = stmt.where(bm.Approval.status == status)
        if agent_code:
            stmt = stmt.where(bm.Approval.agent_code == agent_code)
        return [_to_dict(a) for a in db.execute(stmt).scalars().all()]


def get(approval_id: str) -> dict | None:
    with session() as db:
        a = db.get(bm.Approval, approval_id)
        return _to_dict(a) if a else None


def decide(approval_id: str, decision: str, reviewer: str = "user",
           note: str = "", modified_changes: dict | None = None) -> dict:
    """批准→落库+留痕；拒绝/修改→仅留痕，不落库."""
    _expire_overdue()
    decision = decision if decision in ("approved", "rejected", "modified") else "rejected"
    with session() as db:
        a = db.get(bm.Approval, approval_id)
        if not a:
            return {"ok": False, "message": "审批不存在"}
        if a.status != "pending":
            return {"ok": False, "message": f"该审批已处理（{a.status}）"}

        a.status = decision
        a.reviewer = reviewer
        a.review_note = note
        a.reviewed_at = datetime.utcnow()

        applied = False
        if decision == "approved":
            applied = _apply_record(db, approval_id, a, a.changes)
        elif decision == "modified":
            applied = _apply_record(db, approval_id, a, modified_changes or a.changes)

        # 审批留痕
        audit_service.record_approval(
            approval_id=approval_id, op_id=a.op_id, task_id=a.task_id,
            agent_code=a.agent_code, table_name=a.table_name, changes=a.changes,
            decision=decision, reviewer=reviewer, note=note,
            decided_at=datetime.utcnow())

        # 写操作留痕
        audit_service.record(
            op_id=a.op_id, action=f"write_{a.table_name}", op_type="write",
            agent_code=a.agent_code, task_id=a.task_id, table_name=a.table_name,
            params={"_approval_id": approval_id, "_decision": decision},
            before=None,
            after=a.changes if decision == "approved" else
                  (modified_changes if decision == "modified" else None),
            result="applied" if applied else "blocked",
            reviewer=reviewer, approved_at=datetime.utcnow())

        _maybe_close_task(db, a.task_id)
        return {"ok": True, "decision": decision, "applied": applied,
                "approval_id": approval_id}


def _apply_record(db, approval_id, approval: bm.Approval, changes: dict | None) -> bool:
    if not changes or "_record" not in changes:
        return False
    from ..models import business as mb
    from ..data import access
    model = access.MODEL_MAP.get(approval.table_name)
    if model is None:
        return False
    record = dict(changes["_record"])
    obj = model(**record)
    db.add(obj)
    db.flush()
    return True


def _maybe_close_task(db, task_id: str) -> None:
    if not task_id:
        return
    task = db.get(bm.Task, task_id)
    if not task:
        return
    open_aps = db.execute(
        select(bm.Approval).where(bm.Approval.task_id == task_id,
                                  bm.Approval.status == "pending")).scalars().all()
    if not open_aps:
        task.status = "completed"
        task.finished_at = datetime.utcnow()


def _expire_overdue() -> None:
    """超时（默认24h）未处理 → 标记 timeout，不自动通过、不落库."""
    now = datetime.utcnow()
    with session() as db:
        overdue = db.execute(
            select(bm.Approval).where(bm.Approval.status == "pending",
                                      bm.Approval.timeout_at <= now)).scalars().all()
        for a in overdue:
            a.status = "timeout"
            audit_service.record_approval(
                approval_id=a.id, op_id=a.op_id, task_id=a.task_id,
                agent_code=a.agent_code, table_name=a.table_name, changes=a.changes,
                decision="timeout", reviewer="", note="审批超时，自动挂起",
                decided_at=now)


def _to_dict(a: bm.Approval) -> dict:
    return {c.name: getattr(a, c.name) for c in a.__table__.columns}