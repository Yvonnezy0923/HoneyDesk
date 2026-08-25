"""RRF 融合（Reciprocal Rank Fusion）."""
from __future__ import annotations


def rrf_fuse(rank_lists: list[list[tuple[str, float]]], k: int = 60,
             limit: int | None = None) -> list[str]:
    """融合多个检索器的打分列表（每项为 (id, score)）。

    向量召回的 score 与 BM25 的 score 量纲不同，直接用分数相加不可比，
    因此采用 RRF：score_rrf = Σ_k 1/(k + rank_i)。
    """
    acc: dict[str, float] = {}
    for lst in rank_lists:
        for rank, (cid, _score) in enumerate(lst):
            acc[cid] = acc.get(cid, 0.0) + 1.0 / (k + rank + 1)
    ranked = sorted(acc.items(), key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in ranked][: limit or len(ranked)]