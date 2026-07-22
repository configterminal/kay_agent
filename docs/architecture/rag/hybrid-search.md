# hybrid_search.py — 混合检索

```
┌─────────────────────────────────────────────────────────────┐
│                   hybrid_search.py                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  hybrid_search(queries, top_k=50, course_id=None,           │
│                course_ids=None) → list[dict]                │
│       │                                                     │
│       │  queries: 查询重写输出的 1~3 条查询                   │
│       │  course_id / course_ids: 可选课程作用域过滤           │
│       │                                                     │
│       ├── 对每条查询：                                        │
│       │   ├── 向量检索（Milvus HNSW + filter）→ Top 50       │
│       │   └── BM25 关键词检索（内存倒排 + jieba）→ Top 50    │
│       │                                                     │
│       ├── 所有结果汇总到 RRF 融合                              │
│       │     RRF = Σ 1/(k + rank)    # k=60                   │
│       │     → 合并去重 → 按 RRF 分数排序 → Top 20             │
│       │                                                     │
│       └── 返回 Top 20（带上 _original_score 给 Reranker 用）  │
│                                                             │
│  # Fallback：任一检索失败 → 用另一种的结果                     │
└─────────────────────────────────────────────────────────────┘
```

## BM25 实现（内存自包含）

课程文档量级（千级子块）下，采用 **倒排索引自带完整 payload**，命中后不再回查 Milvus。

```
┌─ warmup / 懒加载 ──────────────────────────────────────────┐
│  Milvus query（chunk_index >= 0）分页拉取子文档              │
│       │                                                    │
│       ▼                                                    │
│  BM25Index._payloads[i] = {                                 │
│    id, content, parent_id, course_id, chapter, section,    │
│    title, chunk_index, tags, start_sec, end_sec, media_path│
│    kp_title, kp_summary, kp_index, key_points              │
│  }                                                         │
│  BM25Index._tokens[i]   = jieba.cut(content)  # 口语 cue   │
│  （预计算 IDF）                                             │
└────────────────────────────────────────────────────────────┘

┌─ search(course_id / course_ids 可选) ──────────────────────┐
│  仅在匹配 course 的 payload 上打分 → [(index, score), ...] │
│       │                                                    │
│       ▼                                                    │
│  copy(_payloads[index]) + score                            │
│  （0 次 Milvus 往返）                                       │
└────────────────────────────────────────────────────────────┘
```

说明：向量侧 embedding 常按知识点 `search_text`（title+summary+要点）；BM25 仍分词 `content`（转写口语）——双路语义略有分工，属有意设计。

### 设计原则

| 原则 | 做法 |
|------|------|
| 索引自包含 | build 时写入下游 RRF / citation 所需全部字段（含 kp_*） |
| 按索引取文档 | search 返回下标后 `dict(_payloads[i])`，禁止按 content 字符串匹配 |
| 禁止全表 hydrate | 不得对每个 hit 执行 `query(id like "%%")` |
| 课程作用域 | `course_id` / `course_ids` 在向量 filter 与 BM25 内存过滤两侧同时生效 |
| 内存可接受 | 课程量级千级子块；payload 远小于 Embedding/Reranker 模型 |

### 参数

- k1 = 1.5（词频饱和度）
- b = 0.75（文档长度归一化）

业务 FastAPI **lifespan 中 `warmup_bm25()`** 预构建，避免首请求冷启动。  
`build_index` 结束后会 `reset_bm25()`；进程内已 warmup 过则仍需**重启**或再次 warmup 才能看到新节。  

索引增量策略：默认只补**尚未入库的 (course_id, section)**；改旧节内容需 `force=True` 或按课重建（业务上以加新课为主）。

向量检索的 query 向量由 **`provider.embed()` → EmbeddingProvider** 生成。详见 [推理抽象层](../inference-services.md)。

## RRF 融合

Reciprocal Rank Fusion，k=60。每个文档的 RRF 分数 = 在两种检索结果中的排名倒数之和。两边都出现的文档分数更高。按 `parent_id` 去重后取 Top 20。

Fallback：任一检索完全失败时，直接用另一种的结果，不报错。

## 耗时埋点

| 指标 | 含义 |
|------|------|
| `rag.hybrid.vector.embed` | query 向量化 |
| `rag.hybrid.vector.hnsw` | Milvus HNSW search |
| `rag.hybrid.vector` | 向量路径合计 |
| `rag.hybrid.bm25.score` | 纯 BM25 打分 |
| `rag.hybrid.bm25` | BM25 路径合计（含从 payload 拼装） |

## 性能基线（修复前后）

查询「什么是RAG？」、`top_k=50`（2026-07-16 实测）：

| 段 | 修复前 | 修复后 |
|----|--------|--------|
| `vector.hnsw` | ~0.7s | ~0.65s |
| `bm25.score` | ~0.03s | ~0.02s |
| 元数据获取 | **~64s**（全表 ×50） | **~0**（内存 copy） |
| `rag.hybrid` 合计 | ~65s | **~0.69s** |

## 待办（已暂停）

> **2026-07-16**：完整 Milvus Standalone / GPU ANN 方向先暂停。  
> 现状为 Milvus Lite（`db/milvus_lite.db`）；`.env` 的 `MILVUS_HOST/PORT` 未接入 `get_client()`。  
> 当前优先修 BM25 内存自包含；完整 Milvus 另开讨论。
