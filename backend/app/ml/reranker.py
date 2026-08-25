"""文本重排：BGE-reranker（本地，可选）或内置词法相似度（降级）."""
from __future__ import annotations

import re
from typing import Protocol

from ..config import get_settings


class Reranker(Protocol):
    def score(self, query: str, docs: list[str]) -> list[float]: ...


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    text = text.lower()
    parts: set[str] = set()
    for p in _TOKEN_RE.findall(text):
        parts.add(p)
        if "\u4e00" <= p[0] <= "\u9fff" and len(p) > 1:
            parts.update(p[i:i + 2] for i in range(len(p) - 1))
    return parts


class FallbackReranker:
    """词法 + 长度归一化的交叉相似度，作为无模型时的兜底重排."""

    def score(self, query: str, docs: list[str]) -> list[float]:
        qt = _tokens(query)
        scores = []
        for d in docs:
            dt = _tokens(d)
            if not qt:
                scores.append(0.0)
                continue
            inter = len(qt & dt)
            union = len(qt | dt) or 1
            jac = inter / union
            scores.append(round(jac * 100.0, 2))
        return scores


class BgeReranker:
    def __init__(self, model_path: str):
        from FlagEmbedding import FlagReranker
        self._model = FlagReranker(model_path, use_fp16=False, device="cpu")

    def score(self, query: str, docs: list[str]) -> list[float]:
        pairs = [[query, d] for d in docs]
        scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        return [float(s) for s in scores]


class CrossEncoderReranker:
    def __init__(self, model_path: str):
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model_path, device="cpu")

    def score(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self._model.predict([[query, d] for d in docs])]


_singleton: Reranker | None = None


def get_reranker() -> Reranker:
    global _singleton
    if _singleton is not None:
        return _singleton
    s = get_settings()
    prefer = s.embedding_backend == "bge" or s.embedding_backend == "auto"
    try:
        if prefer:
            from FlagEmbedding import FlagReranker  # noqa: F401
            _singleton = BgeReranker(s.rerank_model_path)
        else:
            raise ImportError
    except Exception:  # noqa: BLE001
        try:
            if prefer:
                from sentence_transformers import CrossEncoder  # noqa: F401
                _singleton = CrossEncoderReranker(s.rerank_model_path)
            else:
                raise ImportError
        except Exception:  # noqa: BLE001
            _singleton = FallbackReranker()
    return _singleton