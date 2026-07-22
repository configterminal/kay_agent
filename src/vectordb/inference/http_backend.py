"""HTTP 后端 — TEI Embedding / Reranker。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from src.config import config
from src.vectordb.inference.base import InferenceError

logger = logging.getLogger(__name__)


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    """POST JSON，失败重试 1 次。"""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_err: Exception | None = None

    for attempt in range(2):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning("TEI 请求失败 (%s) attempt=%d: %s", url, attempt + 1, e)
            if attempt == 0:
                time.sleep(0.2)

    raise InferenceError(f"TEI 请求失败: {url} — {last_err}") from last_err


def _get_ok(url: str, timeout: float = 5.0) -> bool:
    """GET 探测是否可达。"""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


class HttpEmbeddingProvider:
    """TEI /embed"""

    name = "http"

    def __init__(self) -> None:
        self.dimension = config.embedding.dimension
        self._base = config.inference.embedding_base_url.rstrip("/")
        self._timeout = config.inference.timeout_s

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, Any] = {
            "inputs": texts if len(texts) > 1 else texts[0],
            "normalize": True,
        }
        result = _post_json(f"{self._base}/embed", payload, self._timeout)
        if not result:
            raise InferenceError("TEI /embed 返回空结果")
        if isinstance(result, list) and result and isinstance(result[0], (int, float)):
            return [list(map(float, result))]
        if isinstance(result, list):
            return [list(map(float, row)) for row in result]
        raise InferenceError(f"TEI /embed 返回格式异常: {type(result)}")

    def ready(self) -> tuple[bool, str]:
        ok = _get_ok(f"{self._base}/health", timeout=3.0)
        return (True, f"TEI embed ready ({self._base})") if ok else (False, f"embed不可达({self._base})")

    def warmup(self) -> None:
        ok, msg = self.ready()
        if not ok:
            raise InferenceError(msg)


class HttpRerankerProvider:
    """TEI /rerank"""

    name = "http"

    def __init__(self) -> None:
        self._base = config.inference.reranker_base_url.rstrip("/")
        self._timeout = config.inference.timeout_s

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        payload = {"query": query, "texts": documents, "raw_scores": False}
        result = _post_json(f"{self._base}/rerank", payload, self._timeout)
        if result is None:
            return []
        if not isinstance(result, list):
            raise InferenceError(f"TEI /rerank 返回格式异常: {type(result)}")
        pairs: list[tuple[int, float]] = []
        for item in result:
            idx = int(item.get("index", -1))
            score = float(item.get("score", 0.0))
            if 0 <= idx < len(documents):
                pairs.append((idx, score))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:top_k]

    def ready(self) -> tuple[bool, str]:
        ok = _get_ok(f"{self._base}/health", timeout=3.0)
        return (True, f"TEI rerank ready ({self._base})") if ok else (False, f"rerank不可达({self._base})")

    def warmup(self) -> None:
        ok, msg = self.ready()
        if not ok:
            raise InferenceError(msg)
