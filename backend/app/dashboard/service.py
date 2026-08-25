"""数据看板：任务 / 工具调用 / 知识库检索 / 审批 / 产物基础指标."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, func, desc
from ..database import session
from ..models import business as bm
from ..models import audit as am

# Agent -> 业务域（与调度中心 agent 定义保持一致）
AGENT_SCOPE = {
    "ops_query": "operations", "ops_listing": "operations",
    "supply_query": "supply", "ads_query": "ads",
}
_KB_RETRIEVAL_KEY = "kb_retrieval_count"
_KB_RETRIEVAL_OK_KEY = "kb_retrieval_ok"
_LLM_TOKEN_KEY = "llm_token_count"
_LLM_COST_KEY = "llm_cost_usd"
_HALLUCINATION_KEY = "hallucination_risk_count"


def _get_count(key: str) -> int:
    with session() as db:
        s = db.execute(
            select(bm.Setting).where(bm.Setting.key == key)).scalar()
        # 兼容历史浮点串（如 '46874.0'）与整数串
        return int(float(s.value)) if s and s.value else 0


def _get_float_count(key: str) -> float:
    with session() as db:
        s = db.execute(
            select(bm.Setting).where(bm.Setting.key == key)).scalar()
        return round(float(s.value), 4) if s and s.value else 0.0


def _get_retrieval_count() -> int:
    """知识库累计检索次数（RAG search 时递增落库）."""
    return _get_count(_KB_RETRIEVAL_KEY)


def _get_retrieval_ok() -> int:
    """知识库检索成功次数（返回结果非空时递增）."""
    return _get_count(_KB_RETRIEVAL_OK_KEY)


def _get_token_count() -> int:
    """全平台 LLM 累计 token 消耗（llm._chat 时递增落库）."""
    return _get_count(_LLM_TOKEN_KEY)


def _get_token_today() -> int:
    """今日（东八区自然日）LLM token 消耗，与官方控制台口径对齐."""
    from datetime import timedelta
    day = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
    return _get_count(f"{_LLM_TOKEN_KEY}_{day}")


def _get_cost_total() -> float:
    """LLM 累计估算成本（美元）."""
    return _get_float_count(_LLM_COST_KEY)


def _get_cost_today() -> float:
    day = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
    return _get_float_count(f"{_LLM_COST_KEY}_{day}")


def _get_hallucination_risks() -> int:
    """幻觉雷达：疑似无源数据断言累计次数."""
    return _get_count(_HALLUCINATION_KEY)


def overview() -> dict:
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    with session() as db:
        total_tasks = db.execute(select(func.count()).select_from(bm.Task)).scalar() or 0
        comp_tasks = db.execute(
            select(func.count()).select_from(bm.Task).where(
                bm.Task.status.in_(["completed"]))).scalar() or 0
        awaiting = db.execute(
            select(func.count()).select_from(bm.Task).where(
                bm.Task.status == "awaiting_approval")).scalar() or 0
        failed = db.execute(
            select(func.count()).select_from(bm.Task).where(
                bm.Task.status == "failed")).scalar() or 0
        tasks_week = db.execute(
            select(func.count()).select_from(bm.Task).where(
                bm.Task.created_at >= week_ago)).scalar() or 0

        # 工具调用维度基于 ToolRecord（含读工具）：读无需审计，但仍计入工具调用/读次数
        tr = db.execute(
            select(func.coalesce(func.sum(bm.ToolRecord.call_count), 0),
                   func.coalesce(func.sum(bm.ToolRecord.success_count), 0))).first()
        tool_total = int(tr[0] or 0)
        tool_ok = int(tr[1] or 0)
        read_ops = int(db.execute(
            select(func.coalesce(func.sum(bm.ToolRecord.call_count), 0)).where(
                bm.ToolRecord.permission == "read")).scalar() or 0)
        write_ops = db.execute(
            select(func.count()).select_from(am.AuditLog).where(
                am.AuditLog.op_type == "write")).scalar() or 0
        applied_writes = db.execute(
            select(func.count()).select_from(am.AuditLog).where(
                am.AuditLog.op_type == "write",
                am.AuditLog.result == "applied")).scalar() or 0
        failed_ops = tool_total - tool_ok
        total_ops = read_ops + write_ops

        approvals = db.execute(select(func.count()).select_from(bm.Approval)).scalar() or 0
        ap_pending = db.execute(
            select(func.count()).select_from(bm.Approval).where(
                bm.Approval.status == "pending")).scalar() or 0
        ap_approved = db.execute(
            select(func.count()).select_from(bm.Approval).where(
                bm.Approval.status == "approved")).scalar() or 0
        ap_rejected = db.execute(
            select(func.count()).select_from(bm.Approval).where(
                bm.Approval.status == "rejected")).scalar() or 0
        ap_timeout = db.execute(
            select(func.count()).select_from(bm.Approval).where(
                bm.Approval.status == "timeout")).scalar() or 0

        artifacts = db.execute(select(func.count()).select_from(bm.Artifact)).scalar() or 0
        kb_docs = db.execute(
            select(func.count()).select_from(bm.KnowledgeDocument)).scalar() or 0

        # 失败原因分布
        fail_by_agent = db.execute(
            select(bm.Task.agent_code, func.count()).where(
                bm.Task.status == "failed").group_by(bm.Task.agent_code)).all() \
            if hasattr(bm.Task, "agent_code") else []
        recent_tasks = _recent_tasks(db, 8)

    completion = round(comp_tasks / total_tasks * 100, 1) if total_tasks else 0
    approval_rate = round(ap_approved / max(approvals, 1) * 100, 1)
    success_rate = round(tool_ok / tool_total * 100, 1) if tool_total else 0
    failure_rate = round((tool_total - tool_ok) / tool_total * 100, 1) if tool_total else 0
    kb_retrieval = _get_retrieval_count()
    kb_ok = _get_retrieval_ok()
    llm_tokens = _get_token_count()
    llm_tokens_today = _get_token_today()
    return {
        "tasks_total": total_tasks, "tasks_completed": comp_tasks,
        "tasks_awaiting": awaiting, "tasks_failed": failed, "tasks_week": tasks_week,
        "task_completion_rate": completion,
        "db_ops_total": total_ops, "db_read": read_ops, "db_write": write_ops,
        "applied_writes": applied_writes,
        # 工具调用维度（基于 ToolRecord，保留读工具）：调用总数 / 失败次数 / 成功率 / 失败率
        "tool_calls_total": tool_total, "tool_failed": failed_ops,
        "tool_success_rate": success_rate, "tool_failure_rate": failure_rate,
        "approvals_total": approvals, "approvals_pending": ap_pending,
        "approvals_approved": ap_approved, "approvals_rejected": ap_rejected,
        "approvals_timeout": ap_timeout, "approval_rate": approval_rate,
        "artifacts_total": artifacts, "kb_docs": kb_docs, "kb_retrieval": kb_retrieval,
        "kb_retrieval_ok": kb_ok,
        "kb_success_rate": round(kb_ok / max(kb_retrieval, 1) * 100, 1),
        "llm_tokens": llm_tokens, "llm_tokens_today": llm_tokens_today,
        # 成本 / 幻觉雷达（P1 看板扩展）
        "llm_cost_usd": _get_cost_total(),
        "llm_cost_usd_today": _get_cost_today(),
        "hallucination_risks": _get_hallucination_risks(),
        "recent_tasks": recent_tasks,
    }


def op_by_action(limit: int = 10) -> list[dict]:
    """操作/工具调用分布（基于 ToolRecord，保留读工具）."""
    with session() as db:
        rows = db.execute(
            select(bm.ToolRecord.code, bm.ToolRecord.call_count,
                   bm.ToolRecord.success_count)
            .order_by(bm.ToolRecord.call_count.desc()).limit(limit)).all()
    return [{"action": c, "count": int(co or 0), "success": int(su or 0)}
            for c, co, su in rows]


def alerts_panel(limit: int = 50) -> dict:
    """预警看板（FR-DB-06）+ 联动事件流（FR-DB-09）指标."""
    from ..alerts import service as alerts_service
    from ..scheduler import linkage
    return {
        "alerts": alerts_service.stats(),
        "recent_alerts": alerts_service.list_alerts(limit=12),
        "linkage": linkage.stats(),
    }


def boss_view() -> dict:
    """老板全局视图（FR-DB-09）：三板块指标并排聚合 + 全局预警汇总 + 联动事件流.

    只读：本接口无任何写操作入口。
    """
    from ..alerts import service as alerts_service
    from ..scheduler import linkage
    from sqlalchemy import func as _f

    panels = {}
    with session() as db:
        # 运营板块：营收 / 订单 / 在售商品 / Listing 产出
        revenue = db.execute(
            select(_f.coalesce(_f.sum(bm.SalesOrder.revenue), 0))).scalar() or 0
        orders = db.execute(select(_f.count()).select_from(bm.SalesOrder)).scalar() or 0
        products = db.execute(select(_f.count()).select_from(bm.Product)).scalar() or 0
        listings = db.execute(select(_f.count()).select_from(bm.Listing)).scalar() or 0
        refunds = db.execute(
            select(_f.count()).select_from(bm.SalesOrder).where(
                bm.SalesOrder.order_status.in_(["refunded", "returned"]))).scalar() or 0
        panels["operations"] = {
            "revenue": round(float(revenue), 2), "orders": orders,
            "products": products, "listings": listings, "refunds": refunds,
        }

        # 供应链板块：库存总量 / 缺货风险 / 在途 / 补货计划
        onhand = db.execute(
            select(_f.coalesce(_f.sum(bm.Inventory.available), 0))).scalar() or 0
        in_transit = db.execute(
            select(_f.coalesce(_f.sum(bm.Inventory.in_transit), 0))).scalar() or 0
        low_stock = db.execute(
            select(_f.count()).select_from(bm.Inventory).where(
                bm.Inventory.available <= bm.Inventory.safety_stock)).scalar() or 0
        plans = db.execute(select(_f.count()).select_from(bm.ReplenishmentPlan)).scalar() or 0
        panels["supply"] = {
            "onhand": int(onhand), "in_transit": int(in_transit),
            "low_stock": int(low_stock), "replenishment_plans": plans,
        }

        # 广告板块：花费 / 销售额 / ACOS / 预算
        ad_spend = db.execute(
            select(_f.coalesce(_f.sum(bm.AdPerformance.spend), 0))).scalar() or 0
        ad_sales = db.execute(
            select(_f.coalesce(_f.sum(bm.AdPerformance.sales), 0))).scalar() or 0
        budgets = db.execute(select(_f.count()).select_from(bm.AdBudget)).scalar() or 0
        panels["ads"] = {
            "spend": round(float(ad_spend), 2),
            "sales": round(float(ad_sales), 2),
            "acos": round(ad_spend / ad_sales, 3) if ad_sales else 0,
            "budgets": budgets,
        }

    return {
        "panels": panels,
        "alerts": alerts_service.stats(),
        "recent_alerts": alerts_service.list_alerts(limit=10),
        "linkage": linkage.stats(),
        "linkage_chains": linkage.list_chains(limit=12),
        # 成本雷达 / 幻觉雷达（P1 看板扩展）
        "cost": {"total_usd": _get_cost_total(), "today_usd": _get_cost_today(),
                 "tokens": _get_token_count(), "tokens_today": _get_token_today()},
        "hallucination": {"risk_count": _get_hallucination_risks(),
                          "recent": alerts_service.list_alerts(
                              alert_type="hallucination", limit=5)},
    }


def trend(days: int = 14, scope: str = "all") -> list[dict]:
    from datetime import date as _date
    start = datetime.utcnow() - timedelta(days=days)
    ags: list[str] = []
    if scope and scope != "all":
        ags = [c for c, s in AGENT_SCOPE.items() if s == scope]
    with session() as db:
        tq = select(func.date(bm.Task.created_at), func.count()).where(
            bm.Task.created_at >= start)
        oq = select(func.date(am.AuditLog.created_at), func.count()).where(
            am.AuditLog.created_at >= start)
        if scope and scope != "all":
            tq = tq.where(bm.Task.scope == scope)
        if ags:
            oq = oq.where(am.AuditLog.agent_code.in_(ags))
        tasks = db.execute(
            tq.group_by(func.date(bm.Task.created_at))).all()
        ops = db.execute(
            oq.group_by(func.date(am.AuditLog.created_at))).all()
    task_map = {str(_to_date(d)): c for d, c in tasks}
    op_map = {str(_to_date(d)): c for d, c in ops}
    out = []
    for i in range(days + 1):
        d = start + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        out.append({"date": d.strftime("%m-%d"), "tasks": task_map.get(key, 0),
                    "ops": op_map.get(key, 0)})
    return out


def _to_date(v):
    if isinstance(v, str):
        return v
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v)


def _recent_tasks(db, limit: int) -> list[dict]:
    # 先只取排序用的 id，再按 id 取完整行，避免把超大 result/trace/artifacts 列卷入 filesort → 1038
    ids = db.execute(
        select(bm.Task.id).order_by(desc(bm.Task.created_at)).limit(limit)
    ).scalars().all()
    if not ids:
        return []
    rows = db.execute(
        select(bm.Task).where(bm.Task.id.in_(ids))).scalars().all()
    by_id = {t.id: t for t in rows}
    out = []
    for i in ids:
        t = by_id.get(i)
        if not t:
            continue
        out.append({"id": t.id, "message": (t.user_message or "")[:60],
                    "status": t.status, "scope": t.scope,
                    "created_at": dtiso(t)})
    return out


def dtiso(t) -> str:
    return t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""