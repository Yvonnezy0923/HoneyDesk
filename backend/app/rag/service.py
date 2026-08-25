"""知识库全栈检索：BM25 + 向量召回 → RRF 融合 → BGE-rerank 重排."""
from __future__ import annotations

from sqlalchemy import select

from .bm25 import BM25Index
from .rrf import rrf_fuse
from .vector_store import VectorStore
from ..config import get_settings
from ..database import session
from ..models import business as bm
from ..ml.embedder import get_embedder
from ..ml.reranker import get_reranker
from .. import ids

_bm25 = BM25Index()
_KB_RETRIEVAL_KEY = "kb_retrieval_count"
_KB_RETRIEVAL_OK_KEY = "kb_retrieval_ok"


def _bump_setting_count(key: str) -> None:
    """看板计数落库（尽力而为，失败不影响检索本身）."""
    try:
        with session() as db:
            s = db.execute(
                select(bm.Setting).where(bm.Setting.key == key)).scalar()
            if s:
                s.value = str(int(s.value or 0) + 1)
            else:
                db.add(bm.Setting(key=key, value="1"))
    except Exception:
        pass


class RagResult:
    def __init__(self, chunk_id, content, source: dict, score: float):
        self.chunk_id = chunk_id
        self.content = content
        self.source = source
        self.score = score

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source": self.source,
            "score": round(self.score, 4),
        }


class RagService:
    def __init__(self):
        self.settings = get_settings()
        self.vs = VectorStore()

    # ---- 写入 ----
    def ingest_chunks(self, doc_id: str, title: str, source: str, scope: str,
                      chunks: list[str]) -> int:
        embedder = get_embedder()
        vectors = embedder.embed(chunks)
        points = []
        metas = []
        for i, (text, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = ids.chunk_id()
            points.append((chunk_id, vec))
            metas.append({
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "title": title,
                "source": source,
                "scope": scope,
                "content": text,
                "chunk_index": i,
                "text": text,
            })
        self.vs.upsert(points, metas)
        for meta in metas:
            _bm25.add(meta["chunk_id"], meta["content"], scope, meta["doc_id"])
        return len(chunks)

    def delete_doc_by_source(self, source: str) -> None:
        self.vs.delete_by_source(source)
        _bm25.remove_by_source_hint(source)

    # ---- 检索 ----
    def search(self, query: str, scope: str | None = None,
               top_k: int | None = None) -> list[RagResult]:
        _bump_setting_count(_KB_RETRIEVAL_KEY)
        top_k = top_k or self.settings.rag_top_k
        embedder = get_embedder()
        q_vec = embedder.embed([query])[0]
        vector_hits = self.vs.search(q_vec, scope=scope, limit=max(top_k * 4, 20))
        bm25_hits = _bm25.search(query, scope=scope, limit=max(top_k * 4, 20))
        fused = rrf_fuse(vector_hits, bm25_hits, k=60)

        # 取 top candidates 重排
        candidates = fused[: max(top_k * 6, 30)]
        docs = [self.vs.payload(c)["content"] for c in candidates]
        reranker = get_reranker()
        scores = reranker.score(query, docs) if docs else []
        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1], reverse=True,
        )[: top_k]

        results = []
        for cid, sc in ranked:
            payload = self.vs.payload(cid)
            results.append(RagResult(
                chunk_id=cid,
                content=payload["content"],
                source={
                    "doc_id": payload.get("doc_id"),
                    "title": payload.get("title", ""),
                    "source": payload.get("source", ""),
                    "scope": payload.get("scope", ""),
                    "chunk_index": payload.get("chunk_index"),
                },
                score=sc,
            ))
        if results:
            _bump_setting_count(_KB_RETRIEVAL_OK_KEY)
        return results

    def confidence_ok(self, results: list[RagResult]) -> bool:
        if not results:
            return False
        return results[0].score >= self.settings.low_confidence_threshold

    def search_sources(self, query: str, scope: str | None = None,
                       top_k: int | None = None) -> list[dict]:
        return [r.to_dict() for r in self.search(query, scope, top_k)]


_singleton: RagService | None = None


def get_rag() -> RagService:
    global _singleton
    if _singleton is None:
        _singleton = RagService()
    return _singleton