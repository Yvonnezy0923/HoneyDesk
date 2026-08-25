"""调度中心：基于 LangGraph 的任务编排（意图→路由→执行→汇总→写审批/产物）."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from .. import ids
from ..config import get_settings
from ..database import session
from ..models import business as bm
from ..chat import service as chat_service
from ..agents import operations, listing, supply, ads
from .intents import recognize

AGENT_RUNNERS = {
    "ops_query": operations.run,
    "ops_listing": listing.run,
    "supply_query": supply.run,
    "ads_query": ads.run,
}

_DEFAULT_TEMP_TTL_DAYS = 15


class SchedulerState(TypedDict, total=False):
    task_id: str
    message: str
    agent_override: str
    session_id: str
    intent: dict
    answer: str
    sources: list
    proposed_writes: list
    artifact: dict
    analyses: list
    insight: dict
    follow_ups: list
    cost: float
    error: str
    history: str
    linkage_chains: list


def _plan(state: SchedulerState) -> SchedulerState:
    # 读取最近 5 轮对话历史作为多轮上下文，供意图识别与回答生成使用
    state["history"] = chat_service.recent_context(state.get("session_id", ""))
    intent = recognize(state["message"], history=state["history"])
    override = state.get("agent_override")
    # 仅接受已注册 agent 的强制指定；未注册（如已下线 agent）交由意图识别自动路由
    if override and override in AGENT_RUNNERS:
        scope = _agent_scope(override)
        if scope:
            intent.scope = scope
        intent.agent_code = override
        intent.confidence = 1.0
    state["intent"] = {
        "scope": intent.scope, "work_mode": intent.work_mode,
        "agent_code": intent.agent_code, "confidence": intent.confidence,
        "params": intent.params,
    }
    # 注入与业务域匹配的长期记忆，供回答生成作为背景（不影响意图识别）
    try:
        from ..memory import service as memory_service
        mem = memory_service.recent_memory_text(scope=intent.scope)
        if mem:
            base = (state["history"] or "").strip()
            state["history"] = (base + "\n\n" + mem).strip() if base else mem
    except Exception:  # noqa: BLE001  记忆注入失败不应阻断任务
        pass
    return state


def _agent_scope(code: str) -> str:
    return {
        "ops_query": "operations", "ops_listing": "operations",
        "supply_query": "supply", "ads_query": "ads",
    }.get(code, "")


def _execute(state: SchedulerState) -> SchedulerState:
    intent = _intent_obj(state["intent"])
    runner = AGENT_RUNNERS.get(intent.agent_code, operations.run)
    try:
        res = runner(intent, state["task_id"], state["message"],
                     state.get("history", ""))
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
        state["answer"] = f"任务执行失败：{e}"
        return state
    state["answer"] = res["answer"]
    state["sources"] = res.get("sources", [])
    state["proposed_writes"] = res.get("proposed_writes", []) or []
    state["artifact"] = res.get("artifact")
    state["analyses"] = res.get("analyses", []) or []
    state["insight"] = res.get("insight", {}) or {}
    state["follow_ups"] = res.get("follow_ups", []) or []
    state["cost"] = res.get("cost", 0.0)
    state["linkage_chains"] = res.get("linkage_chains", []) or []
    return state


def _finalize(state: SchedulerState) -> SchedulerState:
    _persist_task(state)
    return state


def _intent_obj(d: dict):
    from .intents import Intent
    it = Intent(scope=d.get("scope"), work_mode=d.get("work_mode"),
                agent_code=d.get("agent_code"), confidence=d.get("confidence"),
                params=d.get("params") or {})
    return it


def _persist_task(state: SchedulerState) -> None:
    task_id = state["task_id"]
    intent = state["intent"]
    writes = state.get("proposed_writes") or []
    error = state.get("error")
    mode = intent.get("work_mode", "query")
    timeout_at = datetime.utcnow() + timedelta(hours=get_settings().approval_timeout_hours)

    # 审批与产物独立于「任务行」持久化：读操作虽不建任务，但产出的报告/审批照常落库
    with session() as db:
        approval_ids = _build_approvals(db, state, writes, timeout_at)
        artifact_ids = _build_artifact(db, state)
        should_record = bool(writes) or mode in ("write", "alert") or bool(error)
        if should_record:
            status = "awaiting_approval" if writes else ("failed" if error else "completed")
            task = bm.Task(id=task_id, user_message=state.get("message", ""))
            task.intent = mode
            task.scope = intent.get("scope", "operations")
            task.session_id = state.get("session_id", "")
            task.status = status
            task.error = error or ""
            task.finished_at = datetime.utcnow()
            task.result = {
                "answer": state.get("answer", ""),
                "sources": state.get("sources", []),
                "analyses": state.get("analyses", []),
                "insight": state.get("insight", {}),
                "follow_ups": state.get("follow_ups", []),
                "linkage_chains": state.get("linkage_chains", []),
                "intent": intent,
            }
            task.artifacts = artifact_ids
            task.trace = _trace(state, approval_ids)
            db.add(task)

    # 审批策略：命中自动通过表的写操作立即自动批准（仍走统一落库 + 完整留痕）
    if approval_ids:
        _apply_approval_policy(approval_ids)


def _build_approvals(db, state: SchedulerState, writes: list,
                     timeout_at) -> list[dict]:
    """为每个写操作生成独立审批任务（标注所属联动链路）. 返回 [{approval_id,...}]."""
    intent = state["intent"]
    approval_ids = []
    linkage_chain_id = (state.get("linkage_chains") or [""])[0]
    for w in writes:
        op_id = ids.op_id()
        approval_id = ids.approval_id()
        ap = bm.Approval(
            id=approval_id, task_id=state["task_id"], op_id=op_id,
            agent_code=intent.get("agent_code", "ops_listing"),
            table_name=w["table"], record_key=w["record_key"],
            changes={"_record": w["record"]},
            reason=w.get("reason", ""), evidence=w.get("evidence", ""),
            status="pending", timeout_at=timeout_at,
            linkage_chain_id=linkage_chain_id,
        )
        db.add(ap)
        approval_ids.append({"approval_id": approval_id, "op_id": op_id,
                             "table": w["table"], "record_key": w["record_key"]})
    return approval_ids


def _build_artifact(db, state: SchedulerState) -> list:
    """产物默认临时产物（15 天有效期）；读分析报告/写产出均可落库，独立于任务行.

    产物来源：若生成方未提供 sources，则把触发该产物的查询标题写入，避免「产物来源」为空。
    """
    from datetime import timedelta as _td
    art = state.get("artifact")
    if not art:
        return []
    art_id = ids.artifact_id()
    ttl = _DEFAULT_TEMP_TTL_DAYS
    intent = state["intent"]
    srcs = art.get("sources") or []
    if not srcs:
        q = (state.get("message") or "").strip()
        if q:
            srcs = [q[:200]]
    db.add(bm.Artifact(
        id=art_id, title=art["title"], art_type=art.get("type", "report"),
        scope=art.get("scope", "operations"),
        agent_code=art.get("agent_code", intent.get("agent_code", "")),
        session_id=state.get("session_id", ""),
        task_id=state["task_id"], content=art.get("content", ""),
        data=art.get("data"), sources=srcs,
        is_temp=True, ttl_days=ttl,
        expires_at=datetime.utcnow() + _td(days=ttl)))
    return [art_id]


def _apply_approval_policy(approval_ids: list) -> None:
    """按审批策略对命中白名单的审批自动通过（策略未启用则跳过，保持人工审批）."""
    from ..approval import service as ap_service
    from ..approval import policy as ap_policy
    try:
        p = ap_policy.get_policy()
    except Exception:  # noqa: BLE001
        return
    auto_tables = (p.get("auto_approve_tables") or []) if p.get("enabled") else []
    if not auto_tables:
        return
    reviewer = ap_policy.default_reviewer()
    for ap in approval_ids:
        if ap.get("table") not in auto_tables:
            continue
        try:
            ap_service.decide(ap["approval_id"], "approved", reviewer=reviewer,
                              note="审批策略·自动通过")
        except Exception:  # noqa: BLE001  单条策略失败不影响其余审批
            continue


def _trace(state: SchedulerState, approval_ids: list) -> list:
    return [
        {"ts": datetime.utcnow().isoformat(), "event": "planned",
         "intent": state["intent"]},
        {"ts": datetime.utcnow().isoformat(), "event": "executed",
         "agent": state["intent"].get("agent_code")},
        {"ts": datetime.utcnow().isoformat(), "event": "finalized",
         "status": task_status(state), "approvals": approval_ids},
    ]


def task_status(state: SchedulerState) -> str:
    if state.get("proposed_writes"):
        return "awaiting_approval"
    if state.get("error"):
        return "failed"
    return "completed"


def build_graph():
    g = StateGraph(SchedulerState)
    g.add_node("plan", _plan)
    g.add_node("execute", _execute)
    g.add_node("finalize", _finalize)
    g.add_edge(START, "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "finalize")
    g.add_edge("finalize", END)
    return g.compile()