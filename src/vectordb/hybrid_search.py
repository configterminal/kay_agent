"""
混合检索 — 向量检索 + BM25 关键词检索 + RRF 融合。

每条查询同时跑两种检索，用 RRF 合并去重，返回 Top 20 候选。

使用方式：
    from src.vectordb.hybrid_search import hybrid_search
    candidates = hybrid_search(["RAG检索模块工作原理"], top_k=50)
"""

import math
import time
from typing import Any

from src.llm.base import LLMProvider
from src.perf import log_timing
from src.vectordb.schema import COLLECTION_NAME, ensure_collection, get_client

# ── BM25 配置 ──────────────────────────────────────

# BM25 标准参数
_BM25_k1 = 1.5   # 词频饱和度控制
_BM25_b = 0.75   # 文档长度归一化

# RRF 平滑参数
_RRF_K = 60

# 建索引时一并载入内存的字段（命中后不再回查 Milvus）
_BM25_PAYLOAD_FIELDS = [
    "id",
    "content",
    "parent_id",
    "course_id",
    "chapter",
    "section",
    "title",
    "chunk_index",
    "tags",
    "start_sec",
    "end_sec",
    "media_path",
    "kp_title",
    "kp_summary",
    "kp_index",
    "key_points",
]


# ── BM25 倒排索引 ──────────────────────────────────

class BM25Index:
    """
    纯 Python BM25 实现，基于倒排索引。

    为什么不用 Milvus 内置的 BM25：
      Milvus 3.x 的 BM25 需要 Sparse Vector（SPARSE_FLOAT_VECTOR），
      跟我们现有的 Dense Vector Collection 不兼容。
      自建倒排索引更灵活，且课程文档量级（几千份）完全够用。

    索引自包含：_payloads 持有 RRF/citation 所需字段，search 后内存取文档。
    """

    def __init__(self):
        self._payloads: list[dict[str, Any]] = []      # 完整子文档（含 id/元数据）
        self._tokens: list[list[str]] = []            # 分词后的文档
        self._doc_freq: dict[str, int] = {}            # 每个词出现在多少篇文档里
        self._avg_doc_len: float = 0                   # 平均文档长度（词数）
        self._idf_cache: dict[str, float] = {}         # 预计算的 IDF 值

    def build(self, documents: list[dict[str, Any]]) -> None:
        """
        从子文档列表构建 BM25 索引（内存自包含）。

        参数：
            documents: [{id, content, parent_id, ...}] — 所有子文档
        """
        if not documents:
            return

        # 浅拷贝字段，避免后续误改污染索引
        self._payloads = [
            {k: doc.get(k) for k in _BM25_PAYLOAD_FIELDS}
            for doc in documents
        ]
        # 分词：jieba（中文友好）
        import jieba
        self._tokens = [
            list(jieba.cut(doc.get("content") or "")) for doc in self._payloads
        ]

        # 总文档数
        N = len(self._tokens)

        # 平均文档长度
        total_len = sum(len(t) for t in self._tokens)
        self._avg_doc_len = total_len / N if N > 0 else 1.0

        # 文档频率（DF）
        for tokens in self._tokens:
            for term in set(tokens):
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

        # 预计算 IDF
        for term, df in self._doc_freq.items():
            self._idf_cache[term] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

    def search(
        self,
        query: str,
        top_k: int = 50,
        course_id: str | None = None,
        course_ids: list[str] | None = None,
    ) -> list[tuple[int, float]]:
        """
        BM25 搜索，返回 [(doc_index, score), ...]。

        course_id / course_ids：仅在匹配的 payload 上打分（内存过滤）。
        """
        if not self._tokens:
            return []

        allow: set[str] | None = None
        if course_ids:
            allow = {str(c).strip() for c in course_ids if str(c).strip()}
        elif course_id:
            allow = {str(course_id).strip()}

        import jieba
        query_tokens = list(jieba.cut(query))

        scores = []
        for i, doc_tokens in enumerate(self._tokens):
            if allow is not None:
                cid = str((self._payloads[i] or {}).get("course_id") or "").strip()
                if cid not in allow:
                    continue
            score = 0.0
            doc_len = len(doc_tokens)

            # 统计查询词在该文档中的词频
            tf_map: dict[str, int] = {}
            for t in doc_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            for term in set(query_tokens):
                if term not in self._idf_cache:
                    continue
                tf = tf_map.get(term, 0)
                idf = self._idf_cache[term]
                # BM25 公式
                numerator = tf * (_BM25_k1 + 1)
                denominator = tf + _BM25_k1 * (1 - _BM25_b + _BM25_b * doc_len / self._avg_doc_len)
                score += idf * numerator / denominator

            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ── 全局 BM25 索引（懒加载） ────────────────────────

_bm25_index: BM25Index | None = None


def _get_bm25_index() -> BM25Index:
    """获取或构建 BM25 索引（完整 payload 驻留内存）"""
    global _bm25_index
    if _bm25_index is None:
        _bm25_index = BM25Index()

        client = get_client()
        ensure_collection()

        # 分页拉取子文档的完整字段，供命中后零回查
        all_docs: list[dict[str, Any]] = []
        offset = 0
        limit = 1000
        while True:
            results = client.query(
                collection_name=COLLECTION_NAME,
                filter="chunk_index >= 0",
                output_fields=list(_BM25_PAYLOAD_FIELDS),
                offset=offset,
                limit=limit,
            )
            if not results:
                break
            all_docs.extend(results)
            offset += limit
            if len(results) < limit:
                break

        _bm25_index.build(all_docs)
    return _bm25_index


def warmup_bm25() -> None:
    """预加载 BM25 索引（供 lifespan 调用，避免首次请求冷启动）"""
    _get_bm25_index()


def reset_bm25() -> None:
    """清空内存 BM25（重建索引后调用，下次 search 会重新加载）"""
    global _bm25_index
    _bm25_index = None


# ── 向量检索 ──────────────────────────────────────

def _milvus_course_filter(
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> str | None:
    """构造 Milvus filter 表达式。"""
    if course_ids:
        ids = [str(c).strip() for c in course_ids if str(c).strip()]
        if not ids:
            return None
        if len(ids) == 1:
            return f'course_id == "{ids[0]}"'
        inner = ", ".join(f'"{c}"' for c in ids)
        return f"course_id in [{inner}]"
    if course_id:
        return f'course_id == "{str(course_id).strip()}"'
    return None


def _vector_search(
    query: str,
    top_k: int = 50,
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Milvus HNSW 向量检索。

    返回：[{id, content, parent_id, ..., score}, ...]
    """
    # 向量化查询（经 EmbeddingProvider / local GPU）
    t0 = time.perf_counter()
    provider = LLMProvider.create()
    query_vec = provider.embed([query])[0]
    log_timing("rag.hybrid.vector.embed", time.perf_counter() - t0)

    client = get_client()
    ensure_collection()

    filter_expr = _milvus_course_filter(course_id=course_id, course_ids=course_ids)
    t0 = time.perf_counter()
    search_kwargs: dict[str, Any] = {
        "collection_name": COLLECTION_NAME,
        "data": [query_vec],
        "limit": top_k,
        "output_fields": [
            "id", "content", "parent_id", "course_id", "chapter", "section",
            "title", "chunk_index", "tags", "start_sec", "end_sec", "media_path",
            "kp_title", "kp_summary", "kp_index", "key_points",
        ],
    }
    if filter_expr:
        search_kwargs["filter"] = filter_expr
    results = client.search(**search_kwargs)
    log_timing(
        "rag.hybrid.vector.hnsw",
        time.perf_counter() - t0,
        top_k=top_k,
        course_id=course_id or "",
    )

    # 展平返回结果
    docs = []
    if results and len(results) > 0:
        for hit in results[0]:
            doc = hit.get("entity", {})
            doc["score"] = hit.get("distance", 0)
            docs.append(doc)

    return docs


def quick_vector_search(
    query: str,
    top_k: int = 3,
    course_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    轻量向量检索 — 供 Supervisor Probe 使用。

    仅 TEI embed + Milvus TopK，不做 query rewrite / BM25 / rerank。
    """
    return _vector_search(query, top_k=top_k, course_id=course_id)


# ── BM25 检索 ─────────────────────────────────────

def _bm25_search(
    query: str,
    top_k: int = 50,
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    BM25 关键词检索 — 命中后从内存 payload 取文档，不回查 Milvus。

    返回：[{id, content, parent_id, ..., score}, ...]
    """
    t0 = time.perf_counter()
    bm25 = _get_bm25_index()
    hits = bm25.search(
        query,
        top_k=top_k,
        course_id=course_id,
        course_ids=course_ids,
    )
    log_timing("rag.hybrid.bm25.score", time.perf_counter() - t0, n_hit=len(hits or []))

    if not hits:
        return []

    docs: list[dict[str, Any]] = []
    for idx, score in hits:
        if idx < 0 or idx >= len(bm25._payloads):
            continue
        doc = dict(bm25._payloads[idx])
        doc["score"] = score
        docs.append(doc)
    return docs[:top_k]


# ── RRF 融合 ──────────────────────────────────────

def _rrf_fuse(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    top_k: int = 20,
    rrf_k: int = _RRF_K,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion — 合并去重，按排名得分排序。

    原理：1/(k + rank) 累加，两边都提到的文档得分更高。
    去重：按 parent_id 去重（同一父文档的不同子文档只保留最高分那条）。
    """
    # 第一步：RRF 融合（按子文档 id 累加排名分）
    doc_map: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(vector_results):
        doc_id = doc.get("id", "")
        if not doc_id:
            continue
        if doc_id not in doc_map:
            doc_map[doc_id] = doc
        doc_map[doc_id]["_rrf_score"] = doc_map[doc_id].get("_rrf_score", 0) + 1.0 / (rrf_k + rank + 1)

    for rank, doc in enumerate(bm25_results):
        doc_id = doc.get("id", "")
        if not doc_id:
            continue
        if doc_id not in doc_map:
            doc_map[doc_id] = doc
        doc_map[doc_id]["_rrf_score"] = doc_map[doc_id].get("_rrf_score", 0) + 1.0 / (rrf_k + rank + 1)

    # 第二步：按 parent_id 去重 — 每个父文档只保留 RRF 分数最高的那个子文档
    parent_best: dict[str, dict[str, Any]] = {}
    for doc in doc_map.values():
        pid = doc.get("parent_id", "")
        if not pid:
            pid = doc.get("id", "")  # 父文档本身没有 parent_id，用自身 id
        if pid not in parent_best or doc.get("_rrf_score", 0) > parent_best[pid].get("_rrf_score", 0):
            parent_best[pid] = doc

    # 按 RRF 分数降序
    merged = list(parent_best.values())
    merged.sort(key=lambda x: x.get("_rrf_score", 0), reverse=True)

    # 保存原始分数（给 Reranker fallback 用）
    for doc in merged:
        doc["_original_score"] = doc.get("_rrf_score", 0)

    return merged[:top_k]


# ── 主入口 ────────────────────────────────────────

def hybrid_search(
    queries: list[str],
    top_k: int = 50,
    rrf_top_k: int = 20,
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    混合检索主入口。

    参数：
        queries: 查询重写输出的 1~3 条优化查询
        top_k: 每种检索返回的候选数
        rrf_top_k: RRF 融合后的返回数（给 Reranker）
        course_id / course_ids: 课程作用域过滤（主路单课 / 类比多课）

    返回：
        Top 20 候选文档列表
    """
    all_vector_docs: list[dict[str, Any]] = []
    all_bm25_docs: list[dict[str, Any]] = []
    t_vec = 0.0
    t_bm25 = 0.0

    for query in queries:
        # 向量检索（embed + Milvus HNSW）
        try:
            t0 = time.perf_counter()
            vec_docs = _vector_search(
                query,
                top_k=top_k,
                course_id=course_id,
                course_ids=course_ids,
            )
            t_vec += time.perf_counter() - t0
            all_vector_docs.extend(vec_docs)
        except Exception:
            pass

        # BM25 关键词检索（内存 payload）
        try:
            t0 = time.perf_counter()
            bm25_docs = _bm25_search(
                query,
                top_k=top_k,
                course_id=course_id,
                course_ids=course_ids,
            )
            t_bm25 += time.perf_counter() - t0
            all_bm25_docs.extend(bm25_docs)
        except Exception:
            pass

    log_timing(
        "rag.hybrid.vector",
        t_vec,
        n_q=len(queries),
        n_hit=len(all_vector_docs),
        course_id=course_id or "",
    )
    log_timing(
        "rag.hybrid.bm25",
        t_bm25,
        n_q=len(queries),
        n_hit=len(all_bm25_docs),
        course_id=course_id or "",
    )

    # 任一检索完全失败 → 用另一种的结果
    if not all_vector_docs and not all_bm25_docs:
        return []
    if not all_vector_docs:
        all_bm25_docs.sort(key=lambda x: x.get("score", 0), reverse=True)
        for doc in all_bm25_docs:
            doc["_original_score"] = doc.get("score", 0)
        return all_bm25_docs[:rrf_top_k]
    if not all_bm25_docs:
        all_vector_docs.sort(key=lambda x: x.get("score", 0), reverse=True)
        for doc in all_vector_docs:
            doc["_original_score"] = doc.get("score", 0)
        return all_vector_docs[:rrf_top_k]

    # RRF 融合
    return _rrf_fuse(all_vector_docs, all_bm25_docs, top_k=rrf_top_k)
