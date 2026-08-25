"""文本向量化：BGE-M3（本地，可选）或内置轻量 Embedding（降级）."""
from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Protocol

from ..config import get_settings

_lock = threading.Lock()


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ────────────────────────── 内置轻量 Embedding（降级） ──────────────────────────
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


class FallbackEmbedder:
    """关键词哈希嵌入：对中文按字符、英文按词切分，哈希投影到固定维度后归一化。

    无外部模型依赖，保证 RAG 闭环在离线/无 GPU 环境可运行。
    """
    def __init__(self, dim: int = 1024):
        self.dim = dim
        self._k1 = 1.2
        self._b = 0.75

    @staticmethod
    def _tokens(text: str) -> list[str]:
        text = text.lower()
        parts = _TOKEN_RE.findall(text)
        toks: list[str] = []
        for p in parts:
            toks.append(p)
            if _is_cjk(p) and len(p) > 1:
                toks.extend(p[i:i + 2] for i in range(len(p) - 1))  # 字 bigram
        return toks

    def _hash(self, tok: str) -> int:
        return int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % self.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for t in texts:
            vec = [0.0] * self.dim
            tf: dict[str, int] = {}
            for tok in self._tokens(t):
                tf[tok] = tf.get(tok, 0) + 1
            for tok, f in tf.items():
                vec[self._hash(tok)] += 1.0 + math.log1p(f)
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vecs.append([v / norm for v in vec])
        return vecs


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


# ────────────────────────── BGE-M3（本地，可选） ──────────────────────────
class BgeM3Embedder:
    """FlagEmbedding BGEM3FlagModel，1024 维密集向量."""
    def __init__(self, model_path: str):
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(model_path, use_fp16=False, device="cpu")
        self.dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self._model.encode(texts, return_dense=True, max_length=512)
        return [row.tolist() for row in out["dense_vecs"]]


class BgeSentenceEmbedder:
    """sentence-transformers 变体（部分环境无 FlagEmbedding）。"""
    def __init__(self, model_path: str):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_path)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


_singleton: Embedder | None = None


def get_embedder() -> Embedder:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        s = get_settings()
        backend = s.embedding_backend
        prefer_bge = backend == "bge" or (backend == "auto")
        chosen: str
        try:
            if prefer_bge:
                from FlagEmbedding import BGEM3FlagModel  # noqa: F401
                _singleton = BgeM3Embedder(s.embedding_model_path)
                chosen = "bge-m3"
            else:
                raise ImportError
        except Exception:  # noqa: BLE001
            try:
                if prefer_bge:
                    from sentence_transformers import SentenceTransformer  # noqa: F401
                    _singleton = BgeSentenceEmbedder(s.embedding_model_path)
                    chosen = "bge-sentence-transformers"
                else:
                    raise ImportError
            except Exception:  # noqa: BLE001
                _singleton = FallbackEmbedder(dim=s.embedding_dim)
                chosen = "fallback"
        # 记录实际后端到设置，方便前端展示
        _record_backend(chosen)
        return _singleton


def _record_backend(chosen: str) -> None:
    try:
        from .database import business_session
        from .models.business import Setting
        with business_session() as db:
            row = db.get(Setting, "embedding_backend_actual")
            if row:
                row.value = chosen
            else:
                db.add(Setting(key="embedding_backend_actual", value=chosen))
    except Exception:  # noqa: BLE001
        pass