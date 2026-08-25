"""预警记录服务：预警写入 / 列表查询 / 状态更新 / 统计（P1）.

预警记录属「记录类变更」，是监控机制本身的产物，直接落库并留痕；
不影响业务数据的写操作（补货计划 / 广告出价）仍走审批流。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, desc

from ..audit import service as audit_service
from ..database import session
from ..models import business as bm


def write(*, alert_type: str, scope: str = "supply", store_id: str = "",
          sku: str = "", market: str = "US", severity: str = "medium",
          title: str = "", message: str = "", evidence: dict | None = None,
          source_task: str = "") -> dict:
    """写入一条预警记录并审计留痕（op_type='alert'）. 返回记录 dict."""
    from .. import ids
    alert_id = ids.op_id().replace("OP", "ALT")
    rec = bm.AlertRecord(
        id=alert_id, alert_type=alert_type, scope=scope, store_id=store_id,
        sku=sku, market=market, severity=_severity(severity),
        title=title, message=message, evidence=evidence or {},
        status="new", source_task=source_task,
    )
    with session() as db:
        db.add(rec)
        d = {c.name: getattr(rec, c.name) for c in rec.__table__.columns}
    aid = audit_service.record(
        op_id=alert_id, action=f"alert_{alert_type}", op_type="alert",
        agent_code=_scope_code(scope), task_id=source_task, table_name="alerts",
        params={"sku": sku, "store_id": store_id, "scope": scope,
                "severity": d["severity"]},
        result="success")
    d["audit_id"] = aid
    return d


def _severity(s: str) -> str:
    return s if s in ("high", "medium", "low") else "medium"


def _scope_code(scope: str) -> str:
    return {"supply": "supply_query", "ads": "ads_query",
            "operations": "ops_query"}.get(scope, "ops_query")


def list_alerts(scope: str | None = None, alert_type: str | None = None,
                status: str | None = None, sku: str | None = None,
                limit: int = 100) -> list[dict]:
    with session() as db:
        stmt = select(bm.AlertRecord).order_by(desc(bm.AlertRecord.created_at)).limit(limit)
        if scope:
            stmt = stmt.where(bm.AlertRecord.scope == scope)
        if alert_type:
            stmt = stmt.where(bm.AlertRecord.alert_type == alert_type)
        if status:
            stmt = stmt.where(bm.AlertRecord.status == status)
        if sku:
            stmt = stmt.where(bm.AlertRecord.sku == sku)
        rows = db.execute(stmt).scalars().all()
    return [_row_dict(r) for r in rows]


def update_status(alert_id: str, status: str, resolution: str = "") -> dict:
    status = status if status in ("acknowledged", "resolved", "ignored") else "acknowledged"
    with session() as db:
        r = db.get(bm.AlertRecord, alert_id)
        if not r:
            return {"ok": False, "message": "预警不存在"}
        r.status = status
        if resolution:
            r.resolution = resolution
        d = _row_dict(r)
    audit_service.record(
        op_id=alert_id, action=f"alert_status_{status}", op_type="alert",
        agent_code=_scope_code(r.scope), table_name="alerts",
        params={"alert_id": alert_id, "resolution": resolution},
        result="success")
    return {"ok": True, "alert": d}


def stats() -> dict:
    from sqlalchemy import func
    with session() as db:
        total = db.execute(select(func.count()).select_from(bm.AlertRecord)).scalar() or 0
        open_cnt = db.execute(
            select(func.count()).select_from(bm.AlertRecord).where(
                bm.AlertRecord.status == "new")).scalar() or 0
        high = db.execute(
            select(func.count()).select_from(bm.AlertRecord).where(
                bm.AlertRecord.severity == "high")).scalar() or 0
        by_type = dict(db.execute(
            select(bm.AlertRecord.alert_type, func.count()).group_by(
                bm.AlertRecord.alert_type)).all())
        by_scope = dict(db.execute(
            select(bm.AlertRecord.scope, func.count()).group_by(
                bm.AlertRecord.scope)).all())
    return {"total": total, "open": open_cnt, "severe": high,
            "by_type": by_type, "by_scope": by_scope}


def _row_dict(r) -> dict:
    out = {}
    for c in r.__table__.columns:
        v = getattr(r, c.name)
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d %H:%M:%S")
        out[c.name] = v
    return out