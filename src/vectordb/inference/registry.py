"""推理 Provider 工厂与生命周期。"""

from __future__ import annotations

import logging
import time

from src.config import config
from src.vectordb.inference.base import EmbeddingProvider, InferenceError, RerankerProvider

logger = logging.getLogger(__name__)

_emb: EmbeddingProvider | None = None
_rer: RerankerProvider | None = None


def _build_embedding() -> EmbeddingProvider:
    backend = config.inference.embedding_backend.lower().strip()
    if backend == "http":
        from src.vectordb.inference.http_backend import HttpEmbeddingProvider
        return HttpEmbeddingProvider()
    if backend == "local":
        from src.vectordb.inference.local_backend import LocalEmbeddingProvider
        return LocalEmbeddingProvider()
    if backend == "algo":
        from src.vectordb.inference.algo_backend import AlgoEmbeddingProvider
        return AlgoEmbeddingProvider()
    raise InferenceError(f"未知 EMBEDDING_BACKEND: {backend}")


def _build_reranker() -> RerankerProvider:
    backend = config.inference.reranker_backend.lower().strip()
    if backend == "http":
        from src.vectordb.inference.http_backend import HttpRerankerProvider
        return HttpRerankerProvider()
    if backend == "local":
        from src.vectordb.inference.local_backend import LocalRerankerProvider
        return LocalRerankerProvider()
    if backend == "off":
        from src.vectordb.inference.local_backend import OffRerankerProvider
        return OffRerankerProvider()
    raise InferenceError(f"未知 RERANKER_BACKEND: {backend}")


def get_embedding_provider() -> EmbeddingProvider:
    """获取 Embedding Provider 单例。"""
    global _emb
    if _emb is None:
        _emb = _build_embedding()
        logger.info("EmbeddingProvider=%s", _emb.name)
    return _emb


def get_reranker_provider() -> RerankerProvider:
    """获取 Reranker Provider 单例。"""
    global _rer
    if _rer is None:
        _rer = _build_reranker()
        logger.info("RerankerProvider=%s", _rer.name)
    return _rer


def reset_providers() -> None:
    """测试用：清空单例。"""
    global _emb, _rer
    _emb = None
    _rer = None


def check_inference_ready() -> tuple[bool, str]:
    """探测当前配置的两个 Provider 是否就绪。"""
    emb = get_embedding_provider()
    rer = get_reranker_provider()
    e_ok, e_msg = emb.ready()
    r_ok, r_msg = rer.ready()
    ok = e_ok and r_ok
    return ok, f"{e_msg}; {r_msg}"


def warmup_inference() -> None:
    """按 backend warmup（local 加载 GPU 权重；http 探测健康）。"""
    emb = get_embedding_provider()
    rer = get_reranker_provider()
    logger.info(
        "warmup inference: embed=%s rerank=%s",
        config.inference.embedding_backend,
        config.inference.reranker_backend,
    )
    emb.warmup()
    rer.warmup()


def wait_inference_ready(max_wait_s: float = 180.0, interval_s: float = 2.0) -> None:
    """
    等待推理就绪。

    - http：轮询 TEI health
    - local / algo：直接 warmup（加载模型）
    """
    backend_e = config.inference.embedding_backend.lower()
    backend_r = config.inference.reranker_backend.lower()

    # local/algo：一次 warmup 即可；http：轮询
    needs_poll = backend_e == "http" or backend_r == "http"
    if not needs_poll:
        from src.perf import timed
        with timed("inference.warmup_all", backend_e=backend_e, backend_r=backend_r):
            warmup_inference()
        ok, msg = check_inference_ready()
        if not ok:
            raise InferenceError(msg)
        logger.info("推理就绪: %s", msg)
        return

    deadline = time.time() + max_wait_s
    last_msg = ""
    while time.time() < deadline:
        try:
            # http 侧先 ping；local 侧若已建则检查
            emb = get_embedding_provider()
            rer = get_reranker_provider()
            if backend_e != "http" and emb.ready()[0] is False:
                emb.warmup()
            if backend_r not in {"http", "off"} and rer.ready()[0] is False:
                rer.warmup()
            if backend_e == "http":
                emb.warmup()
            if backend_r == "http":
                rer.warmup()
            ok, msg = check_inference_ready()
            last_msg = msg
            if ok:
                logger.info("推理就绪: %s", msg)
                return
        except InferenceError as e:
            last_msg = str(e)
        logger.info("等待推理… %s", last_msg)
        time.sleep(interval_s)
    raise InferenceError(f"等待推理超时（{max_wait_s}s）: {last_msg}")
