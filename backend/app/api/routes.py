"""审批流 / 产物中心 / 数据看板 / 审计 / 知识库 / 工具 / 任务 / 设置 / 导入 API."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from datetime import datetime, date

from ..approval import service as approval_service
from ..approval import policy as approval_policy
from ..artifacts import service as artifact_service
from ..dashboard import service as dashboard_service
from ..audit import service as audit_service
from ..knowledge import service as knowledge_service
from ..tools import registry as tools_registry
from ..imports import service as import_service
from ..settings import service as settings_service
from ..memory import service as memory_service
from ..compliance import service as compliance_service
from ..database import session
from ..models import business as bm

approvals = APIRouter(prefix="/api/approvals", tags=["approval"])
artifacts = APIRouter(prefix="/api/artifacts", tags=["artifact"])
dashboard = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
audit = APIRouter(prefix="/api/audit", tags=["audit"])
knowledge = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
tools = APIRouter(prefix="/api/tools", tags=["tools"])
tasks = APIRouter(prefix="/api/tasks", tags=["tasks"])
settings_router = APIRouter(prefix="/api/settings", tags=["settings"])
import_router = APIRouter(prefix="/api/import", tags=["import"])
memories = APIRouter(prefix="/api/memories", tags=["memories"])
compliance = APIRouter(prefix="/api/compliance", tags=["compliance"])


# ────────────────────────── 审批 ──────────────────────────
@approvals.get("")
def list_approvals(status: str | None = None, agent_code: str | None = None):
    return {"approvals": approval_service.list_approvals(status, agent_code)}


@approvals.get("/pending-count")
def pending():
    return {"pending": approval_service.pending_count()}


@approvals.get("/{approval_id}")
def get_approval(approval_id: str):
    return approval_service.get(approval_id)


class DecideBody(BaseModel):
    decision: str
    reviewer: str = "user"
    note: str = ""
    modified_changes: dict | None = None


@approvals.post("/{approval_id}/decide")
def decide(approval_id: str, body: DecideBody):
    return approval_service.decide(approval_id, body.decision, body.reviewer,
                                   body.note, body.modified_changes)


# ────────────────────────── 产物 ──────────────────────────
@artifacts.get("")
def list_arts(scope: str | None = None, agent_code: str | None = None,
              session_id: str | None = None, art_type: str | None = None,
              is_temp: bool | None = None, include_expired: bool = False):
    return {"artifacts": artifact_service.list_artifacts(
        scope, agent_code, session_id, art_type, is_temp, include_expired)}


@artifacts.get("/{artifact_id}")
def get_art(artifact_id: str):
    a = artifact_service.get(artifact_id)
    return {"artifact": a} if a else {"artifact": None}


@artifacts.delete("/{artifact_id}")
def del_art(artifact_id: str):
    return artifact_service.delete(artifact_id)


class SetTtlBody(BaseModel):
    days: int = 15
    is_temp: bool = True


@artifacts.post("/{artifact_id}/ttl")
def set_ttl(artifact_id: str, body: SetTtlBody):
    return artifact_service.set_ttl(artifact_id, body.days, body.is_temp)


# ────────────────────────── 看板 ──────────────────────────
@dashboard.get("/overview")
def overview():
    return dashboard_service.overview()


@dashboard.get("/op-by-action")
def op_by_action():
    return {"items": dashboard_service.op_by_action()}


@dashboard.get("/trend")
def trend(days: int = 14, scope: str = "all"):
    return {"items": dashboard_service.trend(days, scope)}


@dashboard.get("/alerts")
def dashboard_alerts():
    """预警看板 + 联动统计指标（FR-DB-06 / FR-DB-09）."""
    return dashboard_service.alerts_panel()


# ────────────────────────── 审计 ──────────────────────────
@audit.get("/logs")
def logs(table_name: str | None = None, agent_code: str | None = None,
         op_type: str | None = None):
    return {"logs": audit_service.list_logs(table_name, agent_code, op_type)}


@audit.get("/approval-records")
def approval_records():
    return {"records": audit_service.list_approval_records()}


@audit.get("/export")
def audit_export(table_name: str | None = None, agent_code: str | None = None,
                 op_type: str | None = None):
    """审计记录 CSV 导出（FR-AU-04）."""
    import csv, io
    from fastapi.responses import StreamingResponse
    rows = audit_service.list_logs(table_name, agent_code, op_type, limit=5000)
    cols = ["audit_id", "op_id", "task_id", "operator", "agent_code", "op_type",
            "action", "table_name", "result", "reviewer", "approved_at", "created_at"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"})


# ────────────────────────── 知识库 ──────────────────────────
@knowledge.get("")
def kb_list():
    return {"documents": knowledge_service.list_documents()}


@knowledge.get("/stats")
def kb_stats():
    return knowledge_service.stats()


@knowledge.get("/sync")
def kb_sync():
    return {"sources": knowledge_service.sync_sources()}


class IngestBody(BaseModel):
    title: str
    content: str
    scope: str = "general"
    source: str = ""


@knowledge.post("/ingest")
def kb_ingest(body: IngestBody):
    return knowledge_service.ingest_text(body.title, body.scope, body.content, body.source)


class IngestTableBody(BaseModel):
    fields: list = Field(default_factory=list)


@knowledge.post("/ingest-table/{table}")
def kb_ingest_table(table: str, body: IngestTableBody | None = None):
    fields = body.fields if body else []
    return knowledge_service.ingest_business_table(table, fields)


@knowledge.delete("/{doc_id}")
def kb_delete(doc_id: str):
    return knowledge_service.delete_document(doc_id)


# ────────────────────────── 工具 ──────────────────────────
@tools.get("")
def list_tools():
    return {"tools": tools_registry.list_tools()}


class ToolUpdateBody(BaseModel):
    name: str | None = None
    description: str | None = None
    permission: str | None = None
    scope: str | None = None
    table_name: str | None = None
    agent_codes: list | None = None


@tools.put("/{code}")
def update_tool(code: str, body: ToolUpdateBody):
    """更新工具元数据（名称/描述/权限/作用域等），供业务规则变化时调整."""
    r = tools_registry.update_tool(
        code, name=body.name, description=body.description,
        permission=body.permission, scope=body.scope, table_name=body.table_name,
        agent_codes=body.agent_codes)
    if not r.get("ok"):
        from fastapi import HTTPException
        raise HTTPException(404, r.get("message", "工具不存在"))
    return r


class ToolRunBody(BaseModel):
    code: str
    args: dict = Field(default_factory=dict)


@tools.post("/run")
def run_tool(body: ToolRunBody):
    """同步调用注册的只读/安全技能插件（写型技能不可直接执行，须走审批）."""
    return tools_registry.call_tool(body.code, **body.args)


class ToolRegisterBody(BaseModel):
    code: str
    name: str
    description: str = ""
    permission: str = "read"
    scope: str = "operations"
    table_name: str = ""
    agent_codes: list | None = None


@tools.post("/register")
def register_tool(body: ToolRegisterBody):
    """注册自定义技能插件（携 execute 回调的代码在 skills.py 中定义，此处仅登记元数据）."""
    return tools_registry.register_tool(
        code=body.code, name=body.name, description=body.description,
        permission=body.permission, scope=body.scope, table_name=body.table_name,
        agent_codes=body.agent_codes)


@tools.post("/rebuild")
def rebuild_tools():
    """按当前数据库表结构重建工具集（新表/新字段自动扩展，FR-TL-06）. """
    old_tools = {t["code"]: t for t in tools_registry.list_tools()}
    tools_registry.rebuild()
    new_tools = {t["code"]: t for t in tools_registry.list_tools()}
    added = [c for c in new_tools if c not in old_tools]
    return {"ok": True, "tool_count": len(new_tools), "added": added,
            "message": f"工具集重建完成，新增 {len(added)} 个工具，共 {len(new_tools)} 个"}


# ────────────────────────── 任务（调度中心状态） ──────────────────────────
_AGENT_BY_SCOPE = {"operations": "ops_query", "supply": "supply_query", "ads": "ads_query"}


def _infer_agent(t) -> str:
    """任务真实 agent：优先执行轨迹中的 recorded agent，否则按 scope+模式推断."""
    for e in (t.trace or []):
        if isinstance(e, dict) and e.get("agent"):
            return e["agent"]
    if (t.intent or "") == "write":
        return "ops_listing"
    return _AGENT_BY_SCOPE.get(t.scope or "operations", "ops_query")


def _task_dict(t) -> dict:
    d = {}
    for c in t.__table__.columns:
        v = getattr(t, c.name)
        if isinstance(v, (datetime, date)):
            v = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v.isoformat()
        d[c.name] = v
    d["agent_code"] = _infer_agent(t)
    return d


def _parse_ts(s: str | None, end: bool = False):
    """把前端传来的日期/时间串解析为 datetime；end=True 时未含时刻按当天末尾."""
    if not s:
        return None
    s = s.strip().replace(" ", "T").replace("Z", "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:
        if not end:
            return datetime.fromisoformat(s + "T00:00:00")
        return datetime.fromisoformat(s + "T00:00:00").replace(hour=23, minute=59, second=59)
    except ValueError:
        return None


@tasks.get("")
def list_tasks(page: int = 1, page_size: int = 20, agent_code: str | None = None,
               start_from: str | None = None, start_to: str | None = None,
               keyword: str | None = None):
    from sqlalchemy import select, desc, func, or_
    page = max(1, page)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size

    conds = []
    if keyword:
        kw = f"%{keyword.strip()}%"
        conds.append(or_(bm.Task.user_message.like(kw), bm.Task.id.like(kw)))
    df = _parse_ts(start_from, end=False)
    dt = _parse_ts(start_to, end=True)
    if df:
        conds.append(bm.Task.started_at >= df)
    if dt:
        conds.append(bm.Task.started_at <= dt)

    with session() as db:
        base = select(bm.Task).where(*conds)
        if agent_code:
            # agent 由执行轨迹推断（非库内列），需在内存侧过滤后再分页
            rows = db.execute(base).scalars().all()
            items = [_task_dict(t) for t in rows if _infer_agent(t) == agent_code]
            items.sort(key=lambda d: d.get("started_at") or d.get("created_at") or "", reverse=True)
            total = len(items)
            return {"tasks": items[offset:offset + page_size], "total": total}
        total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
        # 先只取排序用 id 再按 id 取行，避免超大 result/trace/artifacts 列卷入 filesort → MySQL 1038
        ids = db.execute(
            select(bm.Task.id).where(*conds).order_by(desc(bm.Task.created_at))
            .offset(offset).limit(page_size)).scalars().all()
        rows = []
        if ids:
            fetched = db.execute(
                select(bm.Task).where(bm.Task.id.in_(ids))).scalars().all()
            by_id = {t.id: t for t in fetched}
            rows = [by_id[i] for i in ids if i in by_id]
    return {"tasks": [_task_dict(t) for t in rows], "total": total}


@tasks.get("/{task_id}")
def get_task(task_id: str):
    with session() as db:
        t = db.get(bm.Task, task_id)
        return {"task": _task_dict(t) if t else None}


# ────────────────────────── 设置 ──────────────────────────
class LLMBody(BaseModel):
    api_base: str
    api_key: str = ""
    model: str
    light_model: str = ""


@settings_router.get("")
def get_settings():
    return settings_service.get_public_settings()


@settings_router.post("/llm")
def save_llm(body: LLMBody):
    return settings_service.save_llm(body.api_base, body.api_key, body.model, body.light_model)


@settings_router.post("/llm/test")
def test_llm():
    return settings_service.test()


class RuleItem(BaseModel):
    table: str = ""
    field: str = ""
    operator: str = "lt"  # lt|le|eq|ne|ge|gt|pct_lt|pct_le|pct_ge|pct_gt
    threshold: float = 0
    action: str = "auto_approve"  # auto_approve|escalate
    description: str = ""


class ApprovalPolicyBody(BaseModel):
    enabled: bool = False
    auto_approve_tables: list = Field(default_factory=list)
    default_reviewer: str = "user"
    timeout_hours: int | None = None
    rules: list[RuleItem] = Field(default_factory=list)


@settings_router.get("/approval-policy")
def get_approval_policy():
    return approval_policy.get_policy()


@settings_router.put("/approval-policy")
def save_approval_policy(body: ApprovalPolicyBody):
    return approval_policy.save_policy(body.model_dump())


# ────────────────────────── 导入 ──────────────────────────
class ImportBody(BaseModel):
    table: str
    rows: list[dict]
    store_id: str = "store_1001"


@import_router.post("/rows")
def import_rows(body: ImportBody):
    return import_service.import_rows(body.table, body.rows, body.store_id)


@import_router.post("/csv")
def import_csv(table: str, body: dict):
    return import_service.import_rows(table, import_service.parse_csv(body.get("text", "")))


# ────────────────────────── 记忆管理（P1） ──────────────────────────
@memories.get("")
def list_memories(mem_type: str | None = None, scope: str | None = None,
                  keyword: str | None = None):
    return {"memories": memory_service.list_memories(mem_type, scope, keyword)}


@memories.get("/stats")
def memory_stats():
    return memory_service.stats()


@memories.get("/{memory_id}")
def get_memory(memory_id: str):
    return {"memory": memory_service.get_memory(memory_id)}


class MemoryBody(BaseModel):
    mem_type: str = "fact"
    content: str
    source: str = ""
    scope_tags: list = Field(default_factory=list)


@memories.post("")
def add_memory(body: MemoryBody):
    return memory_service.create_memory(body.mem_type, body.content,
                                        body.source, body.scope_tags)


class MemoryUpdateBody(BaseModel):
    content: str | None = None
    mem_type: str | None = None
    source: str | None = None
    scope_tags: list | None = None


@memories.put("/{memory_id}")
def edit_memory(memory_id: str, body: MemoryUpdateBody):
    return memory_service.update_memory(
        memory_id, content=body.content, mem_type=body.mem_type,
        source=body.source, scope_tags=body.scope_tags)


@memories.delete("/{memory_id}")
def del_memory(memory_id: str):
    return memory_service.delete_memory(memory_id)


# ────────────────────────── 记忆治理（P2） ──────────────────────────
@memories.get("/governance")
def get_governance():
    """获取记忆治理设置（PII / 容量 / 过期）."""
    return memory_service.get_governance_settings()


class MemoryGovernanceBody(BaseModel):
    pii_enabled: bool = True
    pii_block: bool = True
    pii_blocked_types: list = Field(default_factory=lambda: ["phone", "email", "id_card", "address"])
    max_entries: int = 1000
    ttl_days: int = 365
    auto_expire_enabled: bool = True
    review_required: bool = True


@memories.put("/governance")
def update_governance(body: MemoryGovernanceBody):
    """更新记忆治理设置."""
    return memory_service.update_governance_settings(body.model_dump())


@memories.get("/pii-report")
def pii_report():
    """获取 PII 检测统计."""
    return memory_service.get_pii_report()


@memories.post("/auto-expire")
def trigger_auto_expire():
    """手动触发自动过期."""
    return memory_service.auto_expire()


# ────────────────────────── 合规审计（P2） ──────────────────────────
@compliance.get("/overview")
def compliance_overview():
    """合规审计概览（FR-DB-07）."""
    return compliance_service.overview()


@compliance.get("/export")
def compliance_export():
    """导出合规报告 CSV."""
    import csv as _csv
    from fastapi.responses import StreamingResponse
    content = compliance_service.export()
    return StreamingResponse(
        iter([content]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance_report.csv"})


@compliance.get("/checklist")
def compliance_checklist():
    """GDPR 合规检查项状态."""
    return {"items": compliance_service.get_gdpr_checklist()}