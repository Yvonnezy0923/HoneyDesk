"""进程内 BM25 关键词索引（本地全栈，单用户规模足够）."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
_lock = threading.Lock()


@dataclass
class _Doc:
    chunk_id: str
    text: str
    scope: str
    doc_id: str

    def tokens(self) -> list[str]:
        text = self.text.lower()
        parts = _TOKEN_RE.findall(text)
        toks: list[str] = []
        for p in parts:
            toks.append(p)
            if "\u4e00" <= p[0] <= "\u9fff" and len(p) > 1:
                toks.extend(p[i:i + 2] for i in range(len(p) - 1))
        return toks


class BM25Index:
    def __init__(self):
        self._docs: dict[str, _Doc] = {}
        self._index: BM25Okapi | None = None
        self._dirty = False

    def add(self, chunk_id: str, text: str, scope: str, doc_id: str) -> None:
        with _lock:
            self._docs[chunk_id] = _Doc(chunk_id, text, scope, doc_id)
            self._dirty = True

    def remove_by_source_hint(self, source: str) -> None:
        with _lock:
            keep = {k: v for k, v in self._docs.items() if v.doc_id != source}
            self._docs = keep
            self._dirty = True

    def _rebuild(self) -> None:
        docs = list(self._docs.values())
        tokenized = [d.tokens() for d in docs]
        self._index = BM25Okapi(tokenized) if docs else None
        self._dirty = False

    def search(self, query: str, scope: str | None = None,
               limit: int = 20) -> list[tuple[str, float]]:
        with _lock:
            if self._dirty or not self._index:
                self._rebuild()
            if not self._index or not self._docs:
                return []
            all_docs = list(self._docs.values())
            scores = self._index.get_scores(_tokenize(query))
            ranked = sorted(zip(all_docs, scores), key=lambda x: x[1], reverse=True)
        out = []
        for d, s in ranked:
            if s <= 0:
                continue
            if scope and d.scope != scope:
                continue
            out.append((d.chunk_id, float(s)))
            if len(out) >= limit:
                break
        return out


def _tokenize(text: str) -> list[str]:
    toks = []
    for p in _TOKEN_RE.findall(text.lower()):
        toks.append(p)
        if "\u4e00" <= p[0] <= "\u9fff" and len(p) > 1:
            toks.extend(p[i:i + 2] for i in range(len(p) - 1))
    return toks