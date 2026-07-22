"""推理抽象层 — Embedding / Reranker 统一接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class InferenceError(RuntimeError):
    """推理后端失败"""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """文本向量化 Provider"""

    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与 texts 等长的向量列表"""
        ...

    def ready(self) -> tuple[bool, str]:
        """是否可服务"""
        ...

    def warmup(self) -> None:
        """预热（加载权重 / 探测健康）"""
        ...


@runtime_checkable
class RerankerProvider(Protocol):
    """精排 Provider"""

    name: str

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        """返回 (原下标, score) 列表，按 score 降序，最多 top_k 条"""
        ...

    def ready(self) -> tuple[bool, str]:
        ...

    def warmup(self) -> None:
        ...
