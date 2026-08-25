"""产物中心：跨 Agent 产物自动沉淀、查询、删除；临时产物有效期管理与引用顺延."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select, desc, or_

from .. import ids
from ..database import session
from ..models import business as bm
from ..audit import service as audit_service

DEFAULT_TTL_DAYS = 15
_MAX_CONTENT_BYTES = 60_000   # 产物正文写入上限（content 为 Text，65535 字节，留余量）


def _fit_content(s: str) -> str:
    """把产物正文按 UTF-8 字节安全截断，避免 1406 Data too long."""
    if not s:
        return s or ""
    if len(s.encode("utf-8")) <= _MAX_CONTENT_BYTES:
        return s
    b = s.encode("utf-8")[:_MAX_CONTENT_BYTES]
    while b and (b[-1] & 0xC0) == 0x80:     # 剥掉被切断的多字节字符续字节
        b = b[:-1]
    return b.decode("utf-8", "replace") + "\n…[产物过长，已截断]"


def _first_str(sources) -> str:
    """取出 sources 中第一个可展示的字符串（读产物的查询标题）."""
    if not sources:
        return ""
    for s in sources:
        if isinstance(s, str) and s.strip():
            return s.strip()
    return ""


def _chat_query_by_task(db, task_ids) -> dict:
    """读操作不再留任务行时，从对话回退产物来源：
    取该 task_id 对应的助手消息所在会话，取其紧邻上一条用户消息作为查询标题."""
    out: dict[str, str] = {}
    ids = [t for t in task_ids if t]
    if not ids:
        return out
    rows = db.execute(
        select(bm.ChatMessage.task_id, bm.ChatMessage.session_id,
               bm.ChatMessage.created_at)
        .where(bm.ChatMessage.task_id.in_(ids),
               bm.ChatMessage.role == "assistant")).all()
    for tid, sess, ts in rows:
        if not sess:
            continue
        prev = db.execute(
            select(bm.ChatMessage.content)
            .where(bm.ChatMessage.session_id == sess,
                   bm.ChatMessage.role == "user",
                   bm.ChatMessage.created_at <= ts)
            .order_by(bm.ChatMessage.created_at.desc()).limit(1)).scalar()
        if prev:
            out[tid] = prev.strip()[:200]
    return out


def create(task_id: str, title: str, art_type: str, scope: str, agent_code: str,
           content: str, data: dict | None = None, sources: list | None = None,
           is_temp: bool = True, ttl_days: int | None = None) -> dict:
    art_id = ids.artifact_id()
    ttl = ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS
    expires_at = datetime.utcnow() + timedelta(days=ttl) if is_temp else None
    with session() as db:
        db.add(bm.Artifact(
            id=art_id, title=title, art_type=art_type, scope=scope,
            agent_code=agent_code, task_id=task_id, content=_fit_content(content),
            data=data, sources=sources or [],
            is_temp=is_temp, ttl_days=ttl if is_temp else None,
            expires_at=expires_at))
    return {"id": art_id, "title": title}


def list_artifacts(scope: str | None = None, agent_code: str | None = None,
                   session_id: str | None = None, art_type: str | None = None,
                   is_temp: bool | None = None, include_expired: bool = False,
                   limit: int = 200) -> list[dict]:
    now = datetime.utcnow()
    with session() as db:
        # 联查 Task 取用户原始输入，作为「产物来源」展示
        stmt = (select(bm.Artifact, bm.Task.user_message)
                .join(bm.Task, bm.Task.id == bm.Artifact.task_id, isouter=True)
                .order_by(desc(bm.Artifact.created_at)).limit(limit))
        if scope:
            stmt = stmt.where(bm.Artifact.scope == scope)
        if agent_code:
            stmt = stmt.where(bm.Artifact.agent_code == agent_code)
        if session_id is not None and session_id != "":
            stmt = stmt.where(bm.Artifact.session_id == session_id)
        if art_type:
            stmt = stmt.where(bm.Artifact.art_type == art_type)
        if is_temp is not None:
            stmt = stmt.where(bm.Artifact.is_temp == is_temp)
        if not include_expired:
            stmt = stmt.where(or_(bm.Artifact.expires_at.is_(None),
                                  bm.Artifact.expires_at > now))
        rows = db.execute(stmt).all()
        result = []
        # 读操作不再留任务行：缺失任务时，从对话消息回退该产物对应的用户查询标题
        missing = {art.task_id for art, um in rows if not um and art.task_id}
        query_by_task = _chat_query_by_task(db, missing)
        for art, user_message in rows:
            d = _to_dict(art, now)
            d["source"] = user_message or _first_str(art.sources) \
                or query_by_task.get(art.task_id) or (d.get("title") or "")
            result.append(d)
        return result


def get(artifact_id: str) -> dict | None:
    with session() as db:
        a = db.get(bm.Artifact, artifact_id)
        return _to_dict(a, datetime.utcnow()) if a else None


def delete(artifact_id: str, operator: str = "user") -> dict:
    with session() as db:
        a = db.get(bm.Artifact, artifact_id)
        if not a:
            return {"ok": False, "message": "产物不存在"}
        info = _to_dict(a, datetime.utcnow())
        db.delete(a)
    audit_service.record(ids.op_id(), action="delete_artifact", op_type="artifact",
                         operator=operator, params={"artifact_id": artifact_id},
                         before=info)
    return {"ok": True}


def set_ttl(artifact_id: str, days: int, is_temp: bool = True,
            operator: str = "user") -> dict:
    """手动设置产物有效期：临时产物按 days 天倒计时，转为正式产物则取消过期."""
    days = max(int(days or 0), 1) if is_temp else days
    with session() as db:
        a = db.get(bm.Artifact, artifact_id)
        if not a:
            return {"ok": False, "message": "产物不存在"}
        before = _to_dict(a, datetime.utcnow())
        a.is_temp = is_temp
        a.ttl_days = days if is_temp else None
        a.expires_at = datetime.utcnow() + timedelta(days=days) if is_temp else None
        db.flush()
        after = _to_dict(a, datetime.utcnow())
    audit_service.record(ids.op_id(), action="artifact_set_ttl", op_type="artifact",
                         operator=operator, params={"artifact_id": artifact_id,
                                                    "days": days, "is_temp": is_temp},
                         before=before, after=after)
    return {"ok": True, "artifact": after}


def inject_ref(artifact_id: str, target_agent: str, operator: str = "user",
               task_id: str = "", session_id: str = "") -> dict:
    """跨 Agent 注入：记录引用留痕；注入后临时产物有效期顺延 DEFAULT_TTL_DAYS."""
    a = get(artifact_id)
    if not a:
        return {"ok": False, "message": "产物不存在"}
    now = datetime.utcnow()
    new_expires = None
    if a.get("is_temp"):
        with session() as db:
            obj = db.get(bm.Artifact, artifact_id)
            ttl = obj.ttl_days or DEFAULT_TTL_DAYS
            base = obj.expires_at or now
            obj.expires_at = (base if base > now else now) + timedelta(days=ttl)
            new_expires = obj.expires_at.strftime("%Y-%m-%d %H:%M:%S")
    audit_service.record(ids.op_id(), action="artifact_inject", op_type="artifact",
                         operator=operator, agent_code=target_agent, task_id=task_id,
                         params={"artifact_id": artifact_id, "source_agent": a["agent_code"],
                                 "target_agent": target_agent})
    return {"ok": True, "content": a.get("content"), "data": a.get("data"),
            "expires_at": new_expires or a.get("expires_at") or ""}


def _to_dict(a: bm.Artifact, now: datetime | None = None) -> dict:
    if now is None:
        now = datetime.utcnow()
    d = {c.name: getattr(a, c.name) for c in a.__table__.columns}
    exp = d.get("expires_at")
    if isinstance(exp, datetime):
        d["expired"] = exp <= now
        d["expires_at"] = exp.strftime("%Y-%m-%d %H:%M:%S")
    else:
        d["expired"] = False
        d["expires_at"] = ""
    # 统一把 datetime/date 序列化为字符串（避免审计 JSON 落库失败）
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            d[k] = v.isoformat()
    return d