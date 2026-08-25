"""Qdrant 向量存储封装（Docker 单机，混合检索 + payload 过滤）."""
from __future__ import annotations

import threading
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, PointStruct, VectorParams, FieldCondition, Filter,
    MatchValue, PayloadSchemaType,
)

from ..config import get_settings
from ..ml.embedder import get_embedder

_lock = threading.Lock()

_UUID_NS = uuid.UUID("00000000-0000-4000-8000-000000000000")


def _point_id(chunk_id: str) -> str:
    """Qdrant 点 ID 必须是无符号整数或 UUID；把可读 chunk_id 稳定映射为 UUID."""
    return str(uuid.uuid5(_UUID_NS, chunk_id))


class VectorStore:
    def __init__(self):
        s = get_settings()
        self._client = QdrantClient(host=s.qdrant_host, port=s.qdrant_port)
        self._collection = s.qdrant_collection
        self._payload_cache: dict[str, dict] = {}
        self._ensure()

    def _ensure(self) -> None:
        with _lock:
            dim = get_embedder().dim
            collections = {c.name for c in self._client.get_collections().collections}
            if self._collection not in collections:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
                self._client.create_payload_index(
                    self._collection, "scope", PayloadSchemaType.KEYWORD
                )
                self._client.create_payload_index(
                    self._collection, "doc_id", PayloadSchemaType.KEYWORD
                )

    def upsert(self, points: list[tuple[str, list[float]]], payloads: list[dict]) -> None:
        ids = [_point_id(pid) for pid, _ in points]
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(id=pid, vector=vec, payload=payload)
                for pid, (_, vec), payload in zip(ids, points, payloads)
            ],
        )
        for pid, payload in zip(ids, payloads):
            self._payload_cache[pid] = payload

    def search(self, vector: list[float], scope: str | None = None,
               limit: int = 20) -> list[tuple[str, float]]:
        filt = None
        if scope:
            filt = Filter(must=[
                FieldCondition(key="scope", match=MatchValue(value=scope))
            ])
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            query_filter=filt,
            limit=limit,
            with_payload=True,
        )
        hits = hits or []
        out = []
        for h in hits:
            self._payload_cache[h.id] = h.payload
            out.append((h.id, float(h.score)))
        return out

    def payload(self, chunk_id: str) -> dict:
        cached = self._payload_cache.get(chunk_id)
        if cached is not None:
            return cached
        pts = self._client.retrieve(self._collection, ids=[chunk_id], with_payload=True)
        if pts:
            return pts[0].payload or {}
        return {}

    def delete_by_source(self, source: str) -> None:
        if not source:
            return
        self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(must=[
                FieldCondition(key="doc_id", match=MatchValue(value=source))
            ]),
        )
        self._payload_cache = {k: v for k, v in self._payload_cache.items()
                               if v.get("doc_id") != source}

    def count(self) -> int:
        try:
            return self._client.count(self._collection).count
        except Exception:  # noqa: BLE001
            return 0