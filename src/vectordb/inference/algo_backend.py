"""算法向量化 — 非神经网络兜底（不可写入 BGE Milvus collection）。"""

from __future__ import annotations

import hashlib
import math
import re

from src.config import config
from src.vectordb.inference.base import InferenceError


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


class AlgoEmbeddingProvider:
    """特征哈希向量化（固定维、可复现；与 BGE 空间不同）。"""

    name = "algo"

    def __init__(self) -> None:
        self.dimension = config.inference.algo_embedding_dim
        self._method = config.inference.algo_embedding_method
        if self._method not in {"hashing"}:
            raise InferenceError(f"不支持的 ALGO_EMBEDDING_METHOD: {self._method}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        dim = self.dimension
        vec = [0.0] * dim
        tokens = _TOKEN_RE.findall(text.lower()) or ["_empty_"]
        for tok in tokens:
            digest = hashlib.md5(tok.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            sign = 1.0 if (int(digest[8:10], 16) % 2 == 0) else -1.0
            vec[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def ready(self) -> tuple[bool, str]:
        return True, f"algo embed ready (hashing dim={self.dimension})"

    def warmup(self) -> None:
        _ = self.embed(["warmup"])
