# RAG 增强技术分类框架

> 已落地 / 暂不采纳 / 后续规划的技术按四大维度归类。新增增强技术直接归入对应分类，不再零散列在对话中。

## 分类总览

```
RAG 增强技术
├── A. 检索前增强（Query-side）
│   ├── 查询改写
│   ├── 查询扩展
│   └── 查询分解
├── B. 检索中增强（Index & Retrieval）
│   ├── 索引策略
│   ├── 检索策略
│   └── 多路融合
├── C. 检索后增强（Post-Retrieval）
│   ├── 精排
│   ├── 压缩/过滤
│   └── 结果增强
└── D. 系统级增强（System-wide）
    ├── 作用域与路由
    ├── 反馈闭环
    └── 可插拔与可观测
```

---

## A. 检索前增强（Query-side）

在查询进入检索之前对查询本身做的优化。

### A1. 查询改写

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 条件路由分类 | ✅ | `query_rewriter.py` | classify → AMBIGUOUS/FUZZY/VERBOSE/DIRECT 四选一，1~2 次 LLM |
| 指代消解 | ✅ | `query_rewriter.py` `history_rewrite()` | AMBIGUOUS 时消解"那个/这个/它"为历史具体内容 |
| MultiQuery 多角度 | ✅ | `query_rewriter.py` `multiquery()` | VERBOSE 时 3 个不同措辞重写 |
| HyDE 假答案 | ✅ | `query_rewriter.py` `hyde()` | FUZZY 时生成假答案桥接口语 → 课程术语 |
| 查询路由（意图识别） | ⬜ | — | 识别问题类型（事实/操作/对比/排查），路由不同检索策略 |
| AGREE 自适应改写 | ⬜ | — | 检索后 LLM 裁判反馈 → 重写，Self-RAG 风格闭环 |

### A2. 查询扩展

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 术语同义/缩写映射 | ⬜ 规划 | `hybrid_search` 入口 | 静态词典：HyDE↔假文档嵌入、HNSW↔分层导航小世界、RRF↔倒数排名融合 等。零 LLM 零延迟 |
| LLM 关键词生成 | ⬜ | — | 用 LLM 从 query 抽取关键词做补充检索词 |
| jieba 自定义词典 | ⬜ | — | 让 BM25 正确识别 Graph RAG/HNSW/RRF 等复合术语，不切碎 |

### A3. 查询分解

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 子问题分解（Sub-Question） | ❌ 暂不采纳 | — | 教学场景极少需要"对比 A 和 B 在 X/Y/Z 三方面异同"类多跳问题；MultiQuery 已覆盖多角度；增加 LLM 调用 + 延迟 |
| Step-Back（退一步抽象） | ❌ 暂不采纳 | — | HyDE 假答案已覆盖语义桥接，且方向更贴合教学场景（口语→术语）；Step-Back 的"具体→抽象"在课程文档中容易丢精度 |
| 多步推理检索（IRCoT） | ⬜ | — | 思考链 × 检索交叉迭代；复杂推理题有用但教学答疑需求弱 |

---

## B. 检索中增强（Index & Retrieval）

影响"文档如何被索引、查询如何命中"的策略。

### B1. 索引策略

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 父子文档 | ✅ | `indexer.py` `schema.py` | 父=整节全文（占位向量）；子=知识点块/时间窗（有向量）。命中小块→回查父文档 |
| 知识点优先切分 | ✅ | `indexer.py` `_build_knowledge_point_chunks()` | `.knowledge.json` 存在时每个 KP 一个子文档，embedding 对 search_text（title+summary+要点）做 |
| Fallback 规则窗口 | ✅ | `indexer.py` `split_cues_into_chunks()` | 无 `.knowledge.json` 时 ≈400 字 / ≈45 秒 + cue 重叠 |
| BGE-large-zh 向量化 | ✅ | `local_backend.py` | SentenceTransformer, GPU, normalize |
| 多模态索引（图/表） | ⬜ | — | 课程 PPT 截图、架构图 → 多模态 embedding → 图片检索 |
| 增量索引 | ⚠️ 部分 | `indexer.py` | 按 (course_id, section) 增量；改旧节需 force=True |
| 索引标签（tags 写入） | ⬜ 规划 | `indexer.py` | module.json tags 全空，课程 index.json tags 未写入文档 |

### B2. 检索策略

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 向量检索（HNSW） | ✅ | `hybrid_search.py` `_vector_search()` | Milvus HNSW, COSINE 距离, Top 50 |
| BM25 关键词检索 | ✅ | `hybrid_search.py` `BM25Index` | 纯 Python 实现，内存倒排 + jieba 分词，payload 自包含（0 次回查），k1=1.5/b=0.75 |
| 图检索（Neo4j 知识图谱） | ✅ | `src/graph/retriever.py` → [graph-rag.md](graph-rag.md) | 按问题类型路由：关系型→search_course_graph，语义型→search_course_content。不融合，各自发挥长处 |
| course 作用域过滤 | ✅ | `hybrid_search.py` | 向量侧 Milvus filter + BM25 侧内存 allow set，两侧同时生效 |
| 查询向量批处理 | ⬜ | `hybrid_search.py` | 当前 MultiQuery 3 条查询 3 次 `embed([query])`，可改 batch 一次 |
| 多粒度检索（句子级） | ⬜ | — | 当前最小检索单元是知识点（≈段），更细粒度在课程场景价值待评估 |
| 时间戳检索（视频 seek） | ✅ | `retriever.py` / `citations.py` | 命中后透传 start_sec/media_path → 前端视频跳转 |

### B3. 多路融合

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| RRF 融合 | ✅ | `hybrid_search.py` `_rrf_fuse()` | k=60，按 parent_id 去重，两边都命中得分更高 |
| 权重可配 | ⬜ | — | 当前向量/BM25 等权；可改为业务可配 |
| 多课程类比检索 | ✅ | `hybrid_search.py` + `citations.py` | 主路 `course_id` 单课 + 类比路 `course_ids` 多课独立拉取，RRF 内自动合 |
| LLM 裁判选择 | ⬜ | — | 不使用固定融合公式，让 LLM 评判候选质量取舍 |

---

## C. 检索后增强（Post-Retrieval）

检索结果返回后，喂给 LLM 之前做的处理。

### C1. 精排

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| Cross-Encoder 精排 | ✅ | `reranker.py` → `RerankerProvider` | bge-reranker-v2-m3, Top 20 → 5, local GPU |
| 可插拔精排后端 | ✅ | `inference/registry.py` | local / http / off 三选一 |
| 精排 Fallback | ✅ | `reranker.py` | Provider 失败 → 按 `_original_score` 返回 Top 5 |
| Probe 跳过精排 | ✅ | `hybrid_search.py` `quick_vector_search()` | Supervisor 轻量探路只用向量 TopK，不走 rerank |
| 多维度精排（相关性+时效+权威） | ⬜ | — | 当前仅相关性；课程场景时效/权威需求弱 |
| LLM-as-Reranker | ⬜ | — | 让 LLM 打分而非 Cross-Encoder；质量更高但延迟大 |

### C2. 压缩/过滤

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 阈值过滤 | ✅ | `retriever.py` `_SCORE_THRESHOLD = 0.3` | 硬阈值；score < 0.3 丢弃 |
| 父文档展开 | ✅ | `retriever.py` `_get_parent_content()` | 子文档命中 → parent_id 查 Milvus 取整节全文 |
| 同节去重 | ✅ | `retriever.py` `_rrf_fuse()` + section 排序 | RRF 按 parent_id 去重 + 有作用域时 section 升序 |
| 动态阈值 | ⬜ | — | 当前 0.3 硬阈值可能过粗暴 → Top-K 保底 + 相对衰减 |
| 上下文压缩 | ⬜ | — | LLMLingua / LongLLMLingua 压缩长文档，减 token 成本 |
| 冗余过滤 | ⬜ | — | 相邻文档内容高度重复时合并或去重（Cross-Encoder 前做） |

### C3. 结果增强

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 来源标注 | ✅ | `retriever.py` `_format_source()` | "第X章 第Y节《标题》 @M:SS" + course_id 前缀 |
| 知识点头增强 | ✅ | `retriever.py` / `citations.py` | 透传 kp_title / kp_summary / kp_index / key_points |
| 视频跳转透传 | ✅ | `retriever.py` / `citations.py` | start_sec / end_sec / media_path → API → 前端 VideoDock seek |
| WebSearch 兜底 | ⚠️ 降级 | `retriever.py` `_web_search_fallback()` | 当前返回提示文本，未接入真实搜索 API |
| Citation 到原文高亮 | ⬜ | — | 回复中引用原文片段可点 → 跳到转写文字对应行 |
| 证据引用链 | ⬜ | — | 每个 citation 带命中子文档 ID，可追溯检索路径 |

---

## D. 系统级增强（System-wide）

横跨流水线各阶段的系统能力。

### D1. 作用域与路由

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 四级课程作用域 | ✅ | `course_scope.py` + `citations.py` | Hard → Soft → Profile → Open 逐级解析 |
| 类比课程独立通道 | ✅ | `citations.py` `fetch_analogy_citations()` | 主路焦点课 + 类比路 enrolled 非焦点课，独立 retrieve |
| QA dispatch 强检索 | ✅ | `citations.py` `ensure_qa_citations()` | 每轮 QA 强制检索，不依赖 LLM 是否调工具 |
| 知识点去重（kp_index） | ✅ | `citations.py` `normalize_citations()` | 去重键 (media_path, start_sec, kp_index)，区分同秒不同知识点 |
| 检索模式切换 | ⬜ | — | 按任务类型自动选则：答疑→全链路 / Probe→轻量 / 面试→仅知识点 |

### D2. 反馈闭环

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 用户行为反馈 | ⬜ | — | 学员点击 citation/看视频 → 反哺检索排序 |
| 检索质量评估 | ⬜ | — | 命中率 / MRR / NDCG 离线评测 |
| Self-RAG 反思 | ⬜ | — | LLM 裁判检索结果 → 相关性不够则触发二次检索 |

### D3. 可插拔与可观测

| 技术 | 状态 | 位置 | 说明 |
|------|:--:|------|------|
| 可插拔 Embedding | ✅ | `inference/registry.py` | local (GPU) / http (TEI) / algo (哈希占位) |
| 可插拔 Reranker | ✅ | `inference/registry.py` | local (GPU) / http (TEI) / off |
| 耗时埋点 | ✅ | `retriever.py` / `hybrid_search.py` | rag.rewrite / rag.hybrid.vector/bm25 / rag.rerank / rag.parent_expand / rag.retrieve.total |
| 推理 warmup | ✅ | `inference/registry.py` + lifespan | 启动时预加载 GPU 模型 / http health check |
| BM25 warmup | ✅ | `hybrid_search.py` `warmup_bm25()` | lifespan 中预构建，避免首请求冷启动（~0.69s vs ~65s） |
| 全链路 trace | ⬜ | — | 单次检索的完整路径追踪（rewrite→hybrid→rerank→parent→fallback） |

---

## 状态图例

| 符号 | 含义 |
|:--:|------|
| ✅ | 已落地 |
| 🚧 | 进行中 |
| ⬜ | 未实现（可规划） |
| ⚠️ | 部分/降级（已实现但未完整） |
| ❌ | 评估后暂不采纳 |

---

## 相关文档

- [RAG 总览](index.md) — 完整架构与数据流
- [查询重写](query-rewriter.md) — 条件路由 + 三种策略
- [混合检索](hybrid-search.md) — 向量 + BM25 + RRF
- [重排序](reranker.md) — 可插拔精排
- [检索器](retriever.md) — 流水线主控
- [课程作用域](course-scope.md) — 四级作用域 + 类比通道
- [知识点切分](knowledge-point.md) — `.knowledge.json` → Milvus kp_* 字段
