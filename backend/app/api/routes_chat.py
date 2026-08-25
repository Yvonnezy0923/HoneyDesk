"""对话入口 API."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..chat import service as chat_service
from ..scheduler import service as scheduler_service
from ..approval import service as approval_service
from ..artifacts import service as artifact_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SendBody(BaseModel):
    message: str
    agent_code: str = "ops_query"
    session_id: str = ""


@router.post("/send")
def send(body: SendBody) -> dict:
    user_msg = chat_service.add_message("user", body.message, body.agent_code,
                                        session_id=body.session_id)
    result = scheduler_service.run_task(body.message, agent_override=body.agent_code,
                                        session_id=body.session_id)

    data: dict = {"task_id": result.get("task_id"), "status": result.get("status")}
    if result.get("status") == "awaiting_approval":
        approvals = approval_service.list_pending()
        task_aps = [a for a in approvals if a.get("task_id") == result.get("task_id")]
        data["approvals"] = [
            {"id": a["id"], "table_name": a["table_name"],
             "record_key": a["record_key"], "reason": a["reason"],
             "changes": a["changes"], "evidence": a["evidence"]}
            for a in task_aps]
        data["approval_pending"] = len(task_aps)

    answer = result.get("answer") or f"任务 {result.get('task_id')} 已结束（{result.get('status')}）"
    if result.get("error"):
        answer = f"⚠️ {answer or '执行失败'}"
    data["analyses"] = result.get("analyses")
    data["insight"] = result.get("insight")
    data["follow_ups"] = result.get("follow_ups") or []
    assistant = chat_service.add_message(
        "assistant", answer, body.agent_code,
        session_id=body.session_id, task_id=result.get("task_id", ""), data=data)
    return {"user": user_msg, "assistant": assistant, "task": result}


@router.get("/messages")
def messages(session_id: str | None = None, agent_code: str | None = None,
             limit: int = 500) -> dict:
    rows = chat_service.list_messages(session_id=session_id, agent_code=agent_code,
                                      limit=limit)
    return {"messages": rows}


# ────────────────────────── 会话窗口 ──────────────────────────
class CreateSessionBody(BaseModel):
    agent_code: str = "ops_query"
    title: str = "新会话"


class RenameSessionBody(BaseModel):
    title: str


@router.get("/sessions")
def sessions(agent_code: str | None = None) -> dict:
    return {"sessions": chat_service.list_sessions(agent_code)}


@router.post("/sessions")
def create_session(body: CreateSessionBody) -> dict:
    s = chat_service.create_session(body.agent_code, body.title)
    return {"session": s}


@router.post("/sessions/{session_id}/rename")
def rename_session(session_id: str, body: RenameSessionBody) -> dict:
    return chat_service.rename_session(session_id, body.title)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    return chat_service.delete_session(session_id)


@router.post("/inject-artifact")
def inject(body: dict):
    """跨 Agent 注入产物为上下文，返回产物内容；引用后产物有效期顺延."""
    art_id = body.get("artifact_id")
    target = body.get("agent_code", "ops_query")
    task_id = body.get("task_id", "")
    session_id = body.get("session_id", "")
    res = artifact_service.inject_ref(art_id, target, task_id=task_id,
                                      session_id=session_id)
    if not res.get("ok"):
        return {"ok": False, "message": res.get("message")}
    # 注入后作为一条系统提示注入到对话
    chat_service.add_message("assistant",
                             f"📎 已注入产物 #{art_id} 作为上下文，可基于其继续分析。\n\n"
                             + (res.get("content") or "")[:800],
                             target, session_id=session_id, task_id=task_id)
    return res