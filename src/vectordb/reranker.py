"""
重排序器 — 委托 RerankerProvider（http / local / off）。

调用面保持不变：
    from src.vectordb.reranker import get_reranker
    top5 = get_reranker().rerank(query, candidates)
"""

import logging
from typing import Any

from src.vectordb.inference import InferenceError, get_reranker_provider

logger = logging.getLogger(__name__)

_reranker: "Reranker | None" = None


def set_reranker(reranker: "Reranker") -> None:
    """注入全局 Reranker 单例（可选）"""
    global _reranker
    _reranker = reranker


def get_reranker() -> "Reranker":
    """获取全局 Reranker 单例。"""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


class Reranker:
    """文档列表精排外壳 — 内部转 RerankerProvider"""

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        对候选文档重排序。

        参数：
            query: 原始学员问题
            candidates: 混合检索返回的候选，每条需含 content
            top_k: 返回条数

        返回：
            精排后的 top_k（带 rerank_score）
        """
        if not candidates:
            return []

        texts = [doc.get("content", "") or "" for doc in candidates]

        try:
            ranked = get_reranker_provider().rerank(query, texts, top_k=len(texts))
            score_map = {idx: score for idx, score in ranked}
            for i, doc in enumerate(candidates):
                doc["rerank_score"] = float(score_map.get(i, 0.0))
        except (InferenceError, Exception) as e:
            logger.warning("Reranker 失败，使用原始分数: %s", e)
            for doc in candidates:
                doc["rerank_score"] = doc.get("_original_score", doc.get("score", 0.0))

        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return candidates[:top_k]
