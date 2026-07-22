"""兼容旧 import — 请改用 src.vectordb.inference。"""

from src.vectordb.inference import (  # noqa: F401
    InferenceError,
    check_inference_ready,
    get_embedding_provider,
    wait_inference_ready,
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """兼容旧 API：转发 EmbeddingProvider。"""
    return get_embedding_provider().embed(texts)


def rerank_texts(query: str, texts: list[str]) -> list[dict]:
    """兼容旧 API：转发 RerankerProvider。"""
    from src.vectordb.inference import get_reranker_provider

    ranked = get_reranker_provider().rerank(query, texts, top_k=len(texts))
    return [{"index": i, "score": s} for i, s in ranked]
