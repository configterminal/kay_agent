"""本地 GPU/CPU 后端 — SentenceTransformer + FlagReranker。"""

from __future__ import annotations

import logging
import time

import torch

from src.config import config
from src.vectordb.inference.base import InferenceError
from src.perf import log_timing

logger = logging.getLogger(__name__)


def _device() -> str:
    """优先 CUDA。"""
    return "cuda" if torch.cuda.is_available() else "cpu"


class LocalEmbeddingProvider:
    """进程内 BGE Embedding（GPU 优先）"""

    name = "local"

    def __init__(self) -> None:
        self.dimension = config.embedding.dimension
        self._model_id = config.embedding.model
        self._model = None

    def _ensure(self):
        if self._model is not None:
            return self._model
        from sentence_transformers import SentenceTransformer

        device = _device()
        logger.info("加载 Embedding %s → %s", self._model_id, device)
        t0 = time.perf_counter()
        self._model = SentenceTransformer(self._model_id, device=device)
        log_timing("inference.load_embedding", time.perf_counter() - t0, device=device)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure()
        t0 = time.perf_counter()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        log_timing("inference.embed", time.perf_counter() - t0, n=len(texts))
        return [v.tolist() for v in vectors]

    def ready(self) -> tuple[bool, str]:
        if self._model is None:
            return False, "local embed 未 warmup"
        return True, f"local embed ready ({_device()})"

    def warmup(self) -> None:
        self._ensure()
        # 跑一条空推理占住 CUDA context
        _ = self.embed(["warmup"])
        logger.info("Local Embedding warmup 完成")


class LocalRerankerProvider:
    """进程内 FlagReranker（GPU 优先）"""

    name = "local"

    def __init__(self) -> None:
        self._model_id = config.inference.reranker_model
        self._model = None

    def _ensure(self):
        if self._model is not None:
            return self._model
        from FlagEmbedding import FlagReranker

        use_fp16 = torch.cuda.is_available()
        logger.info("加载 Reranker %s fp16=%s", self._model_id, use_fp16)
        t0 = time.perf_counter()
        self._model = FlagReranker(self._model_id, use_fp16=use_fp16)
        log_timing("inference.load_reranker", time.perf_counter() - t0, fp16=use_fp16)
        return self._model

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        model = self._ensure()
        t0 = time.perf_counter()
        pairs = [[query, doc] for doc in documents]
        scores = model.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            scores = [float(scores)]
        else:
            scores = [float(s) for s in scores]
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        log_timing(
            "inference.rerank",
            time.perf_counter() - t0,
            n_docs=len(documents),
            top_k=top_k,
        )
        return ranked[:top_k]

    def ready(self) -> tuple[bool, str]:
        if self._model is None:
            return False, "local rerank 未 warmup"
        return True, f"local rerank ready ({_device()})"

    def warmup(self) -> None:
        self._ensure()
        _ = self.rerank("warmup", ["warmup doc"], top_k=1)
        logger.info("Local Reranker warmup 完成")


class OffRerankerProvider:
    """关闭精排：按输入顺序截断，分数恒为 0。"""

    name = "off"

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        return [(i, 0.0) for i in range(min(top_k, len(documents)))]

    def ready(self) -> tuple[bool, str]:
        return True, "rerank off"

    def warmup(self) -> None:
        return
