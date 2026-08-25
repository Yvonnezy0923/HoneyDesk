"""对话信息服务：会话窗口 + 消息持久化（系统库）."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, desc

from .. import ids
from ..database import session
from ..models import business as bm

_UTC8 = timedelta(hours=8)   # 东八区：存储为 naïve UTC，展示统一加 8 小时


def _utc8(v) -> str:
    """naïve UTC datetime → 东八区字符串."""
    if v is None:
        return ""
    return (v + _UTC8).strftime("%Y-%m-%d %H:%M:%S")


def add_message(role: str, content: str, agent_code: str = "ops_query",
                session_id: str = "", task_id: str = "",
                data: dict | None = None) -> dict:
    with session() as db:
        m = bm.ChatMessage(role=role, agent_code=agent_code, session_id=session_id,
                           content=content, task_id=task_id, data=data)
        db.add(m)
        db.flush()
        if session_id:
            s = db.get(bm.ChatSession, session_id)
            if s:
                s.last_message_at = datetime.utcnow()
        return {"id": m.id, "role": role, "agent_code": agent_code,
                "session_id": session_id, "content": content, "task_id": task_id,
                "data": data,
                "created_at": _utc8(m.created_at)}


def list_messages(session_id: str | None = None,
                  agent_code: str | None = None, limit: int = 500) -> list[dict]:
    with session() as db:
        # 先只按 id/时间排序取出有序 id，再按 id 取完整行，避免把超大 data 列卷入 filesort
        # → 避免 MySQL 1038 Out of sort memory（会话内一条消息 data 可达 ~1MB）
        stmt = select(bm.ChatMessage.id)
        if session_id:
            stmt = stmt.where(bm.ChatMessage.session_id == session_id)
            stmt = stmt.order_by(bm.ChatMessage.created_at)
        elif agent_code:
            stmt = stmt.where(bm.ChatMessage.agent_code == agent_code)
            stmt = stmt.order_by(bm.ChatMessage.created_at)
        else:
            stmt = stmt.order_by(bm.ChatMessage.created_at.desc()).limit(limit)
        ids = db.execute(stmt).scalars().all()
        if not ids:
            return []
        rows = db.execute(
            select(bm.ChatMessage).where(bm.ChatMessage.id.in_(ids))).scalars().all()
        by_id = {m.id: m for m in rows}
        return [_to_dict(by_id[i]) for i in ids]


def recent_context(session_id: str, rounds: int = 5, max_user: int = 300,
                   max_assistant: int = 220) -> str:
    """返回该会话最近 N 轮紧凑对话历史（剔除当前用户轮），供 LLM 作为多轮上下文."""
    if not session_id:
        return ""
    with session() as db:
        # 只取 role/content/时间，不载入超大 data 列，避免会话级 filesort 触发 1038
        rows = db.execute(
            select(bm.ChatMessage.role, bm.ChatMessage.content,
                   bm.ChatMessage.created_at)
            .where(bm.ChatMessage.session_id == session_id)
            .order_by(bm.ChatMessage.created_at)).all()
    if not rows:
        return ""
    # 当前用户消息已在任务提交前写入；从历史中剔除它，避免把本轮当背景
    if rows[-1][0] == "user":
        rows = rows[:-1]
    rows = rows[-(rounds * 2):]
    lines = []
    for i, (role, content, _created) in enumerate(rows, 1):
        c = (content or "").replace("\n", " ")
        cap = max_assistant if role == "assistant" else max_user
        lines.append(f"[{i}] {role}: {c[:cap]}")
    return "\n".join(lines)


# ────────────────────────── 会话窗口 ──────────────────────────
def create_session(agent_code: str = "ops_query", title: str = "新会话") -> dict:
    sid = ids.session_id()
    with session() as db:
        db.add(bm.ChatSession(id=sid, agent_code=agent_code, title=title or "新会话",
                              last_message_at=datetime.utcnow()))
        db.flush()
        return _session_to_dict(sid, db)


def list_sessions(agent_code: str | None = None) -> list[dict]:
    with session() as db:
        stmt = select(bm.ChatSession).order_by(desc(bm.ChatSession.updated_at))
        if agent_code:
            stmt = stmt.where(bm.ChatSession.agent_code == agent_code)
        return [_session_to_dict(m.id, db) for m in db.execute(stmt).scalars().all()]


def get_session(session_id: str) -> dict | None:
    with session() as db:
        s = db.get(bm.ChatSession, session_id)
        return _session_to_dict(s.id, db) if s else None


def rename_session(session_id: str, title: str) -> dict:
    with session() as db:
        s = db.get(bm.ChatSession, session_id)
        if not s:
            return {"ok": False, "message": "会话不存在"}
        s.title = title.strip() or s.title
        db.flush()
        return _session_to_dict(s.id, db)


def delete_session(session_id: str) -> dict:
    with session() as db:
        s = db.get(bm.ChatSession, session_id)
        if not s:
            return {"ok": False, "message": "会话不存在"}
        # 级联删除该会话消息
        msgs = db.execute(select(bm.ChatMessage).where(
            bm.ChatMessage.session_id == session_id)).scalars().all()
        for m in msgs:
            db.delete(m)
        db.delete(s)
        return {"ok": True}


def _session_to_dict(sid: str, db=None) -> dict:
    if db is None:
        from ..database import session as _session
        with _session() as db:
            return _session_to_dict(sid, db)
    s = db.get(bm.ChatSession, sid)
    if not s:
        return {}
    return {
        "id": s.id, "agent_code": s.agent_code, "title": s.title,
        "created_at": _utc8(s.created_at),
        "last_message_at": _utc8(s.last_message_at or s.created_at),
    }


def _to_dict(m: bm.ChatMessage) -> dict:
    d = {c.name: getattr(m, c.name) for c in m.__table__.columns}
    if d.get("created_at"):
        d["created_at"] = _utc8(d["created_at"])
    return d