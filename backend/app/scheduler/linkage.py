"""Agent 联动事件机制 v1：事件总线 + 去重防抖 + 循环检测 + 链路留痕.

模式②（Agent 联动）：任一 Agent 发现增长点/告警点后发布事件，调度中心按
「事件类型 → 响应 Agent」编排拉起响应。约束（源自 PRD 边界声明）：
  + 写操作独立审批（联动不整体放行，审批隔离由调用方把写操作加入 proposed_writes 实现）；
  + 同 SKU 同类型 24h 内去重/防抖（FR-AD-12 / AC-AD-07）；
  + 循环检测：A→B→A 在 1 层内终止（AC-AD-06）；
  + 最大联动深度可配置，默认 2 层；
  + 联动链路通过 chain_id 贯穿，审计 op_type="linkage" 全量留痕（FR-AU-07 / AC-AU-04）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from .. import ids
from ..audit import service as audit_service
from ..config import get_settings
from ..database import session
from ..models import business as bm


DEDUP_WINDOW_HOURS = 24      # 同类型同目标事件合并窗口
MAX_LINKAGE_DEPTH = 2        # 最大联动深度
_MAX_TEXT_BYTES = 40_000     # evidence/message 写入上限（Text 为 65535 字节，留足余量）


def _fit_text(s, max_bytes: int = _MAX_TEXT_BYTES) -> str:
    """将字符串按 UTF-8 字节安全截断，避免 Data too long / 切断多字节字符."""
    if not s:
        return s or ""
    if len(s.encode("utf-8")) <= max_bytes:
        return s
    b = s.encode("utf-8")[:max_bytes]
    while b and (b[-1] & 0xC0) == 0x80:   # 剥掉被切断的多字节字符的续字节
        b = b[:-1]
    return b.decode("utf-8", "replace") + "…[已截断]"

# 事件类型 → 响应 Agent（联动编排矩阵，PRD 4.4）
RESPONSE_MATRIX = {
    "inventory_shortage": ["supply_query", "ads_query"],   # 库存分析自查 → 补货建议 + 广告降出价建议
    "logistics_delay": ["supply_query", "ads_query"],
    "spend_surge": ["ads_query", "ops_query"],
    "conversion_drop": ["ads_query", "ops_query"],
    "budget_depleted": ["ads_query"],
    "ctr_abnormal": ["ads_query"],
    "price_mutation": ["ops_query", "ads_query", "supply_query"],
    "review_surge": ["ops_query", "ads_query", "supply_query"],
}


def _dedup_key(event_type: str, target: str, store_id: str = "") -> str:
    return f"{event_type}|{store_id}|{target}"


def _recent_duplicate(db, dedup_key: str) -> bool:
    """同链去重：窗口期内已存在相同去重键的事件即视为重复（AC-AD-07）."""
    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)
    row = db.execute(
        select(bm.LinkageEvent).where(
            bm.LinkageEvent.dedup_key == dedup_key,
            bm.LinkageEvent.created_at >= cutoff,
        ).limit(1)).scalars().first()
    return row is not None


def _path_has_event(db, chain_id: str, dedup_key: str) -> bool:
    """循环检测：同一链路内已出现相同事件即终止（AC-AD-06）."""
    from sqlalchemy import func
    if not chain_id:
        return False
    row = db.execute(
        select(func.count()).where(
            bm.LinkageEvent.chain_id == chain_id,
            bm.LinkageEvent.dedup_key == dedup_key)).scalar()
    return (row or 0) > 0


def publish(*, event_type: str, target: str, origin_agent: str,
            message: str = "", evidence: str = "",
            suggested_actions: list | None = None,
            mode: str = "auto", store_id: str = "",
            parent_event_id: str = "") -> dict:
    """发布一个联动事件（去重/循环/深度约束后入账）。

    带 parent_event_id 表示是链上的响应子事件，保存在同一链路（chain_id）内。
    返回 {ok, event, suppressed, reason}。
    """
    dk = _dedup_key(event_type, target, store_id)
    with session() as db:
        if _recent_duplicate(db, dk):
            return {"ok": False, "suppressed": True,
                    "reason": f"{DEDUP_WINDOW_HOURS}h 内已有同类事件（去重）"}
        # 循环检测 / 深度
        depth = 0
        chain_id = ""
        seq = 1
        if parent_event_id:
            parent = db.get(bm.LinkageEvent, parent_event_id)
            if parent:
                chain_id = parent.chain_id or parent.id
                seq = (parent.seq or 1) + 1
                depth = (parent.depth or 0) + 1
                if _path_has_event(db, chain_id, dk):
                    return {"ok": False, "suppressed": True,
                            "reason": "循环联动，已终止（1 层内）"}
                if depth > MAX_LINKAGE_DEPTH:
                    return {"ok": False, "suppressed": True,
                            "reason": f"超过最大联动深度（{MAX_LINKAGE_DEPTH}）"}
        evt_id = ids.event_id()
        chain_id = chain_id or evt_id
        evt = bm.LinkageEvent(
            id=evt_id, event_type=event_type, target=target,
            origin_agent=origin_agent, evidence=_fit_text(evidence), status="created",
            chain_id=chain_id, seq=seq, parent_event_id=parent_event_id,
            mode=mode, message=_fit_text(message), response_agent=origin_agent,
            suggested_actions=[dict(a) for a in (suggested_actions or [])],
            depth=depth, dedup_key=dk,
        )
        db.add(evt)
        d = {c.name: _fmt(getattr(evt, c.name)) for c in evt.__table__.columns}
    audit_service.record(
        op_id=evt_id, action=f"linkage_{event_type}", op_type="linkage",
        agent_code=origin_agent, table_name="linkage_events",
        params={"target": target, "store_id": store_id,
                "chain_id": chain_id, "seq": seq, "depth": depth,
                "suggested_actions": suggested_actions},
        result="created")
    return {"ok": True, "event": d, "chain_id": chain_id}


def list_chains(limit: int = 50) -> list[dict]:
    """按联动链路聚合返回：每个链路含根事件与响应子事件，按最新排序."""
    with session() as db:
        idset = db.execute(
            select(bm.LinkageEvent.chain_id).distinct().limit(limit)).scalars().all()
        out = []
        for cid in idset:
            rows = db.execute(
                select(bm.LinkageEvent).where(bm.LinkageEvent.chain_id == cid)
                .order_by(bm.LinkageEvent.seq)).scalars().all()
            if not rows:
                continue
            root = rows[0]
            out.append({
                "chain_id": cid,
                "event_type": root.event_type,
                "target": root.target,
                "origin_agent": root.origin_agent,
                "message": root.message,
                "evidence": root.evidence,
                "created_at": dtiso(root),
                "seq_count": len(rows),
                "nodes": [_event_dict(r) for r in rows],
            })
        out.sort(key=lambda c: c["created_at"], reverse=True)
    return out


def list_events(limit: int = 100) -> list[dict]:
    with session() as db:
        rows = db.execute(
            select(bm.LinkageEvent).order_by(
                getattr(bm.LinkageEvent, "created_at").desc()).limit(limit)
        ).scalars().all()
    return [_event_dict(r) for r in rows]


def stats() -> dict:
    from sqlalchemy import func
    with session() as db:
        total = db.execute(select(func.count()).select_from(bm.LinkageEvent)).scalar() or 0
        chains = db.execute(
            select(func.count(func.distinct(bm.LinkageEvent.chain_id))).select_from(
                bm.LinkageEvent)).scalar() or 0
        by_type = dict(db.execute(
            select(bm.LinkageEvent.event_type, func.count()).group_by(
                bm.LinkageEvent.event_type)).all())
    return {"total": total, "chains": chains, "by_type": by_type}


def _event_dict(e: bm.LinkageEvent) -> dict:
    return {c.name: _fmt(getattr(e, c.name)) for c in e.__table__.columns}


def _fmt(v):
    if isinstance(v, (datetime,)):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return v


def dtiso(t) -> str:
    return t.created_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(t, "created_at", None) else ""