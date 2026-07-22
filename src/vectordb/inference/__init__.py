"""推理抽象层对外出口 — 业务只应从这里取 Provider。"""

from src.vectordb.inference.base import EmbeddingProvider, InferenceError, RerankerProvider
from src.vectordb.inference.registry import (
    check_inference_ready,
    get_embedding_provider,
    get_reranker_provider,
    reset_providers,
    wait_inference_ready,
    warmup_inference,
)

__all__ = [
    "EmbeddingProvider",
    "RerankerProvider",
    "InferenceError",
    "get_embedding_provider",
    "get_reranker_provider",
    "check_inference_ready",
    "warmup_inference",
    "wait_inference_ready",
    "reset_providers",
]
