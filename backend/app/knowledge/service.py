"""知识库管理：文档/业务表接入 → 切分 → 向量化 → 索引."""
from __future__ import annotations

import re

from .. import ids
from ..database import session
from ..models import business as bm
from ..rag.service import get_rag

_SYNC_PREFIX = "kb_sync:"


def _split(text: str, size: int = 180, overlap: int = 30) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def list_documents() -> list[dict]:
    with session() as db:
        from sqlalchemy import select, desc
        rows = db.execute(select(bm.KnowledgeDocument).order_by(
            desc(bm.KnowledgeDocument.created_at))).scalars().all()
        return [_to_dict(d) for d in rows]


def ingest_text(title: str, scope: str, content: str, source: str = "") -> dict:
    chunks = _split(content)
    doc_id = ids.doc_id()
    rag = get_rag()
    try:
        n = rag.ingest_chunks(doc_id, title, source or doc_id, scope, chunks)
        status = "ready"
    except Exception as e:  # noqa: BLE001
        n = 0
        status = f"failed:{e}"[:40]
    with session() as db:
        db.add(bm.KnowledgeDocument(
            id=doc_id, title=title, doc_type="document", scope=scope,
            source=source or doc_id, chunk_count=n, status=status, error=status))
    return {"id": doc_id, "chunks": n, "status": status}


def ingest_business_table(table: str, fields: list[str] | None = None) -> dict:
    """把业务表关键字段语义化索引进知识库，支撑跨字段语义检索."""
    from ..data import access
    if table not in access.MODEL_MAP:
        return {"id": "", "chunks": 0, "status": "failed", "error": "未公开的表"}
    rows = access.query_table(table, store_id="store_1001", limit=500)
    fields = fields or list(rows[0].keys()) if rows else []
    texts = []
    for r in rows:
        parts = [f"{k}: {r.get(k)}" for k in fields if r.get(k) not in (None, "")]
        if parts:
            texts.append(" | ".join(parts))
    # 打包成若干 chunk（每 chunk 多条记录）
    chunks = ["\n".join(texts[i:i + 4]) for i in range(0, len(texts), 4)]
    doc_id = f"table:{table}"
    rag = None
    try:
        rag = get_rag()
        n = rag.ingest_chunks(doc_id, f"业务表-{table}", f"table:{table}",
                              access.TABLE_META.get(table, {}).get("scope", "general"),
                              chunks)
        status = "ready"
    except Exception as e:  # noqa: BLE001
        n = 0
        status = f"failed:{e}"[:40]
    with session() as db:
        doc = db.get(bm.KnowledgeDocument, doc_id)
        if doc:
            doc.chunk_count = n
            doc.status = "ready" if n else doc.status
            doc.error = status
        else:
            db.add(bm.KnowledgeDocument(
                id=doc_id, title=f"业务表-{table}", doc_type="table",
                scope=access.TABLE_META.get(table, {}).get("scope", "general"),
                source=f"table:{table}", chunk_count=n,
                status="ready" if n else status))
        if n:
            _record_snapshot(db, table)
    return {"id": doc_id, "chunks": n, "status": "ready" if n else status}


def _record_snapshot(db, table: str) -> None:
    """记录索引时的业务表行数，作为后续『同步数据源』变更判定的基线."""
    from sqlalchemy import select, func
    from ..data import access
    model = access.MODEL_MAP.get(table)
    if model is None:
        return
    cnt = db.execute(select(func.count()).select_from(model)).scalar() or 0
    key = f"{_SYNC_PREFIX}{table}"
    snap = db.get(bm.Setting, key)
    if snap:
        snap.value = str(cnt)
    else:
        db.add(bm.Setting(key=key, value=str(cnt)))


def sync_sources() -> list[dict]:
    """同步业务数据源：扫描各业务表当前行数，与索引基线对比，标记新增/变更/已就绪."""
    from sqlalchemy import select, func
    from ..data import access
    out = []
    with session() as db:
        for table, model in access.MODEL_MAP.items():
            rows = db.execute(select(func.count()).select_from(model)).scalar() or 0
            key = f"{_SYNC_PREFIX}{table}"
            snap = db.get(bm.Setting, key)
            snap_rows = int(snap.value) if snap else None
            doc = db.execute(select(bm.KnowledgeDocument).where(
                bm.KnowledgeDocument.doc_type == "table",
                bm.KnowledgeDocument.source == f"table:{table}"
            )).scalars().first()
            ready = bool(doc and doc.status == "ready")
            if not ready and rows > 0:
                state = "new"
            elif ready:
                if snap_rows is None:
                    # 历史已索引但无基线：本次同步建立基线，视为已就绪
                    if snap is None:
                        db.add(bm.Setting(key=key, value=str(rows)))
                    state = "ok"
                elif snap_rows != rows:
                    state = "changed"
                else:
                    state = "ok"
            else:
                state = "empty"
            out.append({
                "table": table, "rows": rows, "ready": ready,
                "state": state, "indexed_rows": snap_rows,
            })
    return out


def delete_document(doc_id: str) -> dict:
    rag = get_rag()
    with session() as db:
        doc = db.get(bm.KnowledgeDocument, doc_id)
        if not doc:
            return {"ok": False, "message": "文档不存在"}
        source = doc.source
        db.delete(doc)
    try:
        rag.delete_doc_by_source(source)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


def stats() -> dict:
    docs = list_documents()
    return {"docs": len(docs), "ready": sum(1 for d in docs if d["status"] == "ready"),
            "chunks": sum(d["chunk_count"] for d in docs)}


def _to_dict(d: bm.KnowledgeDocument) -> dict:
    return {c.name: getattr(d, c.name) for c in d.__table__.columns}