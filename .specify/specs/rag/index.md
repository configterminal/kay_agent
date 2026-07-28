# RAG 系统 (src/vectordb/)

> 传统 RAG 完整流水线：查询重写、混合检索、重排序、父子文档。
> **Embedding / Rerank 经可插拔 Provider**（见 [推理抽象层](../inference-services.md)）；本目录负责编排与向量库。

## 完整架构图

```
                          ┌─────────────────────────┐
                          │    resources/courses/     │
                          │    {id} {课名}/           │  见 naming.md
                          │    ├── index.json          │
                          │    ├── 02 章标题/          │
                          │    │   ├── module.json    │
                          │    │   ├── 02-03 标题.md  │  带时间戳转写
                          │    │   └── 02-03 标题.mp4 │
                          └───────────┬───────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ① 索引器 (indexer.py)                        │
│                                                                     │
│  启动时执行一次 / 课程内容更新时手动触发                               │
│                                                                     │
│  合规 .md → 解析 [M:SS] cue → 去时间戳纯文本                         │
│       │                                                             │
│       ▼                                                             │
│  父文档：整节纯文本（chunk_index=-1，start_sec=-1）                   │
│       │                                                             │
│       ▼                                                             │
│  子文档（二选一）：                                                   │
│  优先：读 .knowledge.json → LLM 知识点块（kp_title/kp_summary...）    │
│  Fallback：≈400字或≈45秒窗口 + cue 重叠；带 start_sec/media_path     │
│       │                                                             │
│       ▼                                                             │
│  EmbeddingProvider → Milvus（父占位向量；子按知识点 search_text 向量化）│
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Milvus Collection                            │
│                                                                     │
│  id │ content │ embedding(1024) │ parent_id │ course_id │ chapter...│
│  ───┼─────────┼─────────────────┼───────────┼───────────┼──────────│
│  ch02_2-3_0  │ 检索模块负责...   │ [0.12, -0.34, ...] │ ch02_2-3_full │ ... │
│  ch02_2-3_1  │ 生成模块接收...   │ [0.08, 0.21, ...] │ ch02_2-3_full │ ... │
│  ch02_2-3_full│ 整节 3000 字全文 │ NULL               │ NULL        │ ... │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ② 检索器 (retriever.py)                         │
│                                                                     │
│  学员原始问题                                                        │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────┐                      │
│  │ ②-1 查询重写 (query_rewriter.py)          │                      │
│  │                                          │                      │
│  │ 条件路由：classify → 四选一                │                      │
│  │   AMBIGUOUS→指代消解 / FUZZY→HyDE        │                      │
│  │   VERBOSE→MultiQuery / DIRECT→透传        │                      │
│  │   → 生成 1~3 条优化查询                    │                      │
│  └──────────────────┬───────────────────────┘                      │
│                     │                                               │
│                     ▼                                               │
│  ┌──────────────────────────────────────────┐                      │
│  │ ②-2 混合检索 (hybrid_search.py)           │                      │
│  │                                          │                      │
│  │  向量检索（HNSW）────┬── 各返回 Top 50     │                      │
│  │  BM25 关键词 ────────┘                    │                      │
│  │        │                                 │                      │
│  │        ▼                                 │                      │
│  │  RRF 融合 → Top 20                        │                      │
│  └──────────────────┬───────────────────────┘                      │
│                     │                                               │
│                     ▼                                               │
│  ┌──────────────────────────────────────────┐                      │
│  │ ②-3 重排序 (reranker.py → Provider)       │                      │
│  │                                          │                      │
│  │  精排 Top 20 → Top 5（http / local / off）│                      │
│  └──────────────────┬───────────────────────┘                      │
│                     │                                               │
│                     ▼                                               │
│  ┌──────────────────────────────────────────┐                      │
│  │ ②-4 结果处理                              │                      │
│  │                                          │                      │
│  │  有结果 → parent_id 取父文档 → 返回       │                      │
│  │          标注"来自课程第X章第Y节"          │                      │
│  │                                          │                      │
│  │  无结果 → WebSearch 兜底（后续接入；当前降级提示）│                      │
│  └──────────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ③ QAAgent 调用                               │
│                                                                     │
│  search_course_content(query) →                                     │
│      检索器执行完整流水线 →                                          │
│      返回 [{content, source, score}, ...]                            │
│                                                                     │
│  Agent 拿到这些内容 + 学员问题 → LLM 生成最终回答                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 索引器

### 扫描逻辑

```
扫描 resources/courses/{course_id}/ 目录
  → 读取 index.json 获取课程信息
  → 遍历每个章节目录
    → 读取 module.json 获取章节元数据
    → 遍历 .doc / .pdf 文件
      → 从文件名解析节号（如 "2-3"）和标题
      → 提取文本 → 父文档
      → 分块 → 子文档 → Embedding → 写入 Milvus
    → .mp4 跳过
```

### 分块策略

- **父文档**：整节全文（.md 全部 cue 去时间戳），chunk_index = -1，无向量
- **子文档（知识点优先）**：
  - `.knowledge.json` 存在 → 每个 `knowledge_point` 一个子文档
    - embedding 对 `kp_title + kp_summary + key_points` 向量化（精炼语义锚点）
    - `start_sec` = 知识点真正的讲解起点
  - 不存在 → fallback 规则窗口（≈400 字 / ≈45 秒 + cue 重叠）
    - 知识点字段留空，`kp_index = -1`
- 不在句子中间切断；识别标题/段落边界（仅 fallback 窗口时）

> 知识切分由 [知识切分 Skill](../../skills/knowledge-split/SKILL.md) 离线完成；索引器只消费 `.knowledge.json`。

## 检索器

### ②-1 查询重写 (query_rewriter.py)

```
学员原始问题 + 对话历史
    │
    ▼
① classify_query：1 次轻量 LLM 判断问题类型 → AMBIGUOUS / FUZZY / VERBOSE / DIRECT
    │
    ├── AMBIGUOUS → history_rewrite（指代消解、补全上下文）
    ├── FUZZY     → hyde（生成假答案，用假答案搜索）
    ├── VERBOSE   → multiquery（3 个不同角度重写）
    └── DIRECT    → 透传 [raw_query]
    │
    → 输出 1~3 条优化查询
```

### ②-2 混合检索 (hybrid_search.py)

```
每条优化查询
    │
    ├── 向量检索（Milvus HNSW）→ Top 50
    └── BM25 关键词检索 → Top 50
    │
    ▼
RRF 融合（k=60）：合并去重，按排名融合得分 → Top 20
```

### ②-3 重排序 (reranker.py)

```
RerankerProvider：Top 20 → 精排 → Top 5（默认模型 bge-reranker-v2-m3）
见 inference-services.md
```

**调用约定**：完整 `retrieve()`（QA）走精排；Supervisor Probe 轻量探路**不**走本步。

### ②-4 结果处理

```
得分 ≥ 阈值 → parent_id 取父文档完整内容 → 标注来源
得分 < 阈值 → WebSearch 网络搜索（后续接入；当前降级提示）→ 标注"网络搜索，非课程内容"
```

### Fallback 策略

| 环节          | 失败处理                  |
| ------------- | ------------------------- |
| HyDE 生成失败 | 跳过，用原始查询继续      |
| BM25 无结果   | 只用向量结果              |
| 向量无结果    | 只用 BM25 结果            |
| Reranker 报错 | 跳过，用 RRF 结果直接返回 |
| 全部无结果    | WebSearch 兜底（后续接入） |

## Milvus Schema

```
Collection: course_content

字段:
  id              VARCHAR      主键    "ch02_2-3_0"
  content         VARCHAR      文本    子文档500字 / 父文档全文
  embedding       FLOAT_VECTOR(1024)  BGE-large-zh 向量
  parent_id       VARCHAR      父文档ID "ch02_2-3_full"
  course_id       VARCHAR      课程    "RAG101"
  chapter         VARCHAR      章节    "第2章..."
  section         VARCHAR      节号    "2-3"
  title           VARCHAR      标题    "解锁RAG三大核心"
  file_type       VARCHAR      类型    md
  chunk_index     INT          序号    子文档:0/1/2, 父文档:-1
  tags            VARCHAR      标签    "RAG,检索,生成"
  start_sec       INT          起始秒；父=-1
  end_sec         INT          结束秒；父=-1
  media_path      VARCHAR      相对 resources/ 的 mp4
  kp_title        VARCHAR      知识点标题（知识切分后可用）
  kp_summary      VARCHAR      知识点摘要
  kp_index        INT          节内序号；无则-1
  key_points      VARCHAR      要点列表（逗号分隔）

索引:
  embedding   → HNSW（M=16, efConstruction=200, COSINE）
  其余字段   → 检索时用 filter 表达式（如 course_id == "RAG101"）；
               当前 Lite 路径未单独建标量索引
```

## 代码模块设计

- [增强技术分类框架](enhancement-taxonomy.md) — 检索前/中/后 + 系统级四维分类，技术点状态地图
- [Graph RAG（双索引知识图谱）](graph-rag.md) — Neo4j 图检索 + Milvus 向量检索并行；图数据模型与两期路线
- [Graph Importer（导入器）](graph-importer.md) — 模块结构、数据流、线程模型、增量检测、LLM 推断 EXPANDS
- [Schema 定义](schema.md) — Milvus Collection 与索引配置
- [查询重写](query-rewriter.md) — 历史感知 + MultiQuery + HyDE
- [混合检索](hybrid-search.md) — 向量 + BM25 + RRF 融合 + course 过滤
- [课程作用域与类比](course-scope.md) — Soft/Hard 焦点、主 citations / 类比区
- [知识点切分](knowledge-point.md) — `.knowledge.json` → 索引 kp_* 字段
- [推理抽象层](../inference-services.md) — http / local / algo

## 代码结构

```
src/vectordb/
├── __init__.py
├── indexer.py           # ① 索引器：分块 → EmbeddingProvider → Milvus
├── retriever.py         # ② 检索器：流水线主控（QA 用）
├── query_rewriter.py    # ②-1 查询重写
├── hybrid_search.py     # ②-2 混合检索（embed → Provider）
├── reranker.py          # ②-3 → RerankerProvider
├── inference/           # 可插拔 Provider（已落地）
│   ├── base.py
│   ├── registry.py
│   ├── http_backend.py
│   ├── local_backend.py
│   └── algo_backend.py
├── inference_client.py  # 兼容旧 embed_texts / rerank_texts
└── schema.py            # Milvus Collection 定义

src/graph/
├── __init__.py
├── client.py            # Neo4j 驱动单例
├── importer.py          # sync_graph() — 增量知识图谱导入
├── node_builder.py      # 6 种节点 MERGE
├── relation_builder.py  # 7 种关系 MERGE
├── expan_infer.py       # LLM 推断 EXPANDS 关系
└── retriever.py         # graph_search() — 图检索（Phase 2）

src/tools/
├── graph_tools.py       # search_course_graph 工具（Phase 2）
└── ...
```
