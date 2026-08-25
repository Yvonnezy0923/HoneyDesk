"""调度中心服务：提交任务 → LangGraph 编排 → 入库."""
from __future__ import annotations

from datetime import datetime

from .. import ids
from ..database import session
from ..models import business as bm
from .graph import build_graph


def run_task(message: str, agent_override: str | None = None,
             session_id: str = "") -> dict:
    """提交任务并编排。

    P1 决策：读操作（query/analysis）不建任务记录——只出结果，不落 tasks 表；
    仅写/预警/失败才持久化任务行（供调度中心与审批追踪）。结果始终以执行迹为准。
    """
    task_id = ids.task_id()
    graph = build_graph()
    initial = {"task_id": task_id, "message": message,
               "agent_override": agent_override or "", "session_id": session_id}
    try:
        result = graph.invoke(initial)
    except Exception as e:  # noqa: BLE001
        _mark_failed(task_id, str(e))
        return {"task_id": task_id, "status": "failed", "error": str(e)}

    with session() as db:
        task = db.get(bm.Task, task_id)
        saved = task.result if task else {}
    r = result if isinstance(result, dict) else {}
    status = (task.status if task
              else ("failed" if r.get("error") else "completed"))
    return {
        "task_id": task_id,
        "status": status,
        "answer": saved.get("answer") or r.get("answer") or "",
        "intent": saved.get("intent") or r.get("intent") or {},
        "analyses": saved.get("analyses") or r.get("analyses") or [],
        "insight": saved.get("insight") or r.get("insight") or {},
        "follow_ups": saved.get("follow_ups") or r.get("follow_ups") or [],
    }


def _mark_failed(task_id: str, error: str) -> None:
    with session() as db:
        t = db.get(bm.Task, task_id)
        if t is None:  # 图级崩溃时任务行未被持久化，补建失败记录
            t = bm.Task(id=task_id, user_message="", status="failed")
            db.add(t)
        t.status = "failed"
        t.error = error
        t.finished_at = datetime.utcnow()