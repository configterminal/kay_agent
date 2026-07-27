# AI 助教系统 — 技术面试讲稿

> 准备时间 30 分钟 | 讲稿结构：总 → 分 → 深挖备答

---

## 一、30 秒电梯演讲

我做的是一个 **AI 教学助教系统**，基于 LangGraph 多 Agent 架构，辅助学员从零基础学习到找到心仪工作。核心技术栈是 **DeepSeek LLM + Milvus 向量检索 + Neo4j 知识图谱 + Redis 长期记忆**。

最大亮点是 RAG 检索增强——从基础语义搜索一路做到双索引路由检索（向量 + 图），并建立了完整的增强技术分类框架，40+ 技术点的状态一目了然。

---

## 二、整体架构（面试官必问）

```
学员 → Vue 3 前端 (SSE流式)
          │
          ▼
   FastAPI (lifespan 启动: GPU warmup + Redis + Neo4j)
          │
          ▼
   Supervisor (LangGraph StateGraph)
   ├── probe (向量探路 + 情绪检测 + Store读上下文)
   ├── decide (关键词规则 → LLM路由 两级决策)
   ├── dispatch → 6个子Agent
   │   ├── QAAgent     ← RAG检索 (Milvus+Neo4j双索引)
   │   ├── ProgressAgent   ← 学习报告
   │   ├── RecommendAgent  ← 课程推荐
   │   ├── JobMatchAgent   ← 岗位匹配
   │   ├── ResumeAgent     ← 简历优化 (双模式)
   │   └── InterviewAgent  ← 模拟面试 (Audio + TTS + Game UI)
   ├── aggregate → 结果汇总 + citations
   └── recovery → 异常兜底
```

**存储层**:

- **SQLite**: 学员画像、课程目录、学习进度
- **Milvus**: 课程知识向量 (1024维 BGE-large-zh, HNSW索引)
- **Neo4j**: 课程知识图谱 (700节点, 1991关系)
- **Redis Stack**: 对话检查点 + 长期记忆 (Store)

**推理层 (可插拔 Provider)**:

- Embedding: BAAI/bge-large-zh-v1.5, 本地GPU (SentenceTransformer)
- Reranker: BAAI/bge-reranker-v2-m3, 本地GPU
- LLM: DeepSeek Chat (OpenAI兼容), 预留 OpenAI/Anthropic

### 面试官可能追问的点和备用回答

#### Q: "为什么用 LangGraph 而不是直接调 OpenAI API？"

**备答**：三个原因。

1. **有状态多轮对话**：教学场景不是单轮问答。学员会追问"那个是什么意思""再讲一遍"，需要维持对话上下文。LangGraph 的 Checkpointer（RedisSaver）自动管理全量对话历史，再通过 Store.summaries（滚动摘要）控制每个子 Agent 的上下文预算——全量存储但裁剪入模，防止多轮后 token 爆炸。
2. **层级路由**：Supervisor 的两级决策——先关键词规则（高置信度场景秒级命中），再 LLM 结构化路由（处理模糊意图）。6 个子 Agent 各司其职，QAAgent 负责答疑、InterviewAgent 负责模拟面试。路由不是单一 LLM Function Call，而是有确定性 fallback 的混合架构。
3. **上下文预算管理**：Checkpointer 全量存 + Store.summaries 滚动摘要 + 近窗原文。子 Agent 只看到摘要+最近N轮原文，不塞全量历史。这个设计是我们在多轮对话测试中发现 token 爆涨后特意加的。

---

#### Q: "RAG 检索增强具体做了什么？"

**备答**：这是我在这个项目中最花精力的部分。我们做了四层增强，建立了完整的分类框架。

**检索前增强（Query-side）**：

- 条件路由查询重写：classify query → 四选一（AMBIGUOUS指代消解 / FUZZY→HyDE假答案 / VERBOSE→MultiQuery×3 / DIRECT透传）
- 关键决策：没有全部串行（那样延迟太高），一次 LLM 调用判断类型后走对应策略

**检索中增强（Index & Retrieval）**：

- 混合检索：向量 HNSW (Milvus) + BM25 (内存自包含, jieba分词) → RRF k=60 融合
- BM25 为什么自己做？因为主流的 rank-bm25 库每次请求要重建索引，我们用内存 payload 自包含方案，warmup 一次 ~0.69s，之后每次查询 ~0.01s
- **Neo4j 图检索**（最具差异化）：按问题类型路由——关系型走 search_course_graph，语义型走 search_course_content。不是三路 RRF 融合，而是各自发挥长处

**检索后增强（Post-Retrieval）**：

- Cross-Encoder 精排 (bge-reranker-v2-m3): Top20→5
- 父子文档：父=整节全文，子=知识点块。命中子→回查父
- 知识点优先切分：LLM 离线拆知识点 (kp_title/summary/key_points)，embedding 锚定在精炼文本上而非原始转写

**系统级**：可插拔 Provider（local/http/algo）、四级课程作用域（Hard/Soft/Profile/Open）、全链路耗时埋点。

**📎 如果面试官继续深挖："你为什么没有做子问题查询和 Step-Back 这些热门技术？"**
说出你的决策逻辑——这两个我都评估过但没做。子问题查询会增加 LLM 调用和延迟，教学场景极少遇到需要逻辑拆分的复杂问题。Step-Back 跟已有的 HyDE 假答案效果重叠——假答案模拟讲师口吻桥接口语和术语，比抽象检索更合适。所有决策都基于实际数据，不是拍脑袋。

---

#### Q: "Milvus 为什么从 Lite 版本开始？以后怎么升级？"

**备答**：Lite 是嵌入式版本，零配置、和 Python 进程同生命周期，开发阶段不需要单独维护一个 Docker 容器。代价是每次 query 有 ~1s 的固定延迟（单次查询的 load_collection 开销）。后续生产化可以平滑切换到 Milvus Standalone（Docker 部署），我们做了 Provider 抽象层，代码几乎不用改——换一个连接地址即可。

---

#### Q: "BM25 你是用的 Elasticsearch 还是什么？"

**备答**：自己实现的 Python 内存版本，没有外挂 ES。原因是课程知识库量级不大（2门课、126节），不需要分布式检索引擎。实现了一个 BM25Index 类——jieba 分词 + 内存倒排索引 + BM25 打分 (k1=1.5, b=0.75)。关键优化是 **payload 自包含**——所有文档字段存在内存 dict 里，命中后不需要回查数据库，一次查询 ~0.01s。启动时 warmup_bm25 预热，避免首请求冷启动（否则 ~65s）。

---

## 三、Neo4j 知识图谱（高亮亮点）

### 一句话概括

在课程知识库上构建了有向知识图谱，实现**按问题类型的双索引路由检索**。

### 图数据模型（6节点7关系）

```
Course → HAS_CHAPTER → Chapter → HAS_SECTION → Section
    → HAS_KNOWLEDGE_POINT → KnowledgePoint (531个)
  
Skill ← TEACHES — Section
Role ← REQUIRES — Skill
KnowledgePoint ← BELONGS_TO — Skill
KnowledgePoint ← EXPANDS — KnowledgePoint (387条, LLM推断)
```

### 关键设计决策

1. **不是三路融合，是按需路由**：图检索擅长关系遍历（"Graph RAG 和 RAG 有什么区别"），向量检索擅长语义匹配（"什么是RAG三大核心"）。强行 RRF 融合会引入噪音。我们让 LLM 根据问题类型选择工具——关系型→search_course_graph，事实型→search_course_content。
2. **全自动建图**：从 122 个 .knowledge.json + roles.json + module.json 自动构建，零人工标注。Phase 1 建图（700节点,1991关系），Phase 2 接通检索通路。
3. **增量同步**：lifespan 后台线程检测 new/changed sections → 自动更新 Neo4j。不影响服务启动。

### 面试官可能追问

**Q: "为什么不用 Neo4j 的向量索引代替 Milvus？"**
Neo4j 向量索引不如 Milvus 专业。Milvus 的 HNSW 索引调优、混合检索 RRF 融合、精排链路都是现成的，Neo4j 做图遍历最适合。两个系统各做各擅长的事。

**Q: "EXPANDS 关系是怎么来的？"**
LLM 推断。不是手工标注——122 节 × ~4 个知识点/节，每节一次 LLM 调用（不到一块钱），判断节内哪些 KP 是概述、哪些是展开。我们评估过要不要推断跨节的 PREREQUISITE_OF（前置依赖），但发现 600 个 KP 之间 18 万个可能边，LLM 筛出几百条有用的大概 50 条，性价比不高就暂时没做。

---

## 四、记忆系统

### 两层架构

```
Checkpointer (RedisSaver)     Store (RedisJSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
全量对话原文 → 框架自动管理    结构化知识 → 业务代码显式读写
按 thread_id 隔离             按 student_id 跨会话
断点恢复、前端回放              summaries/weak_areas/preferences
```

- **上下文预算**：Checkpointer 全量存（做回放），但进 LLM 用预算裁剪（Store.summaries 滚动摘要 + 近窗原文）。子 Agent 看不到全量历史，防止 token 爆炸
- **断点恢复**：每轮 graph.invoke 后自动持久化。即使前端 crash，同一 thread_id 回来能看到上次对话

---

## 五、工程细节（加分项）

### 1. 可插拔推理层

Embedding/Reranker 通过 Provider 注册表（local/http/algo）切换。当前默认 local GPU，生产可切 http TEI。通过环境变量 `EMBEDDING_BACKEND` 一行切换，代码零改动。

### 2. 增量索引

`build_index()` 按 (course_id, section) 扫描。已有内容跳过，新增内容自动追加。知识切分由离线 Skill 完成（.knowledge.json），索引器只消费。

### 3. BM25 自包含 Payload

传统 rank-bm25 每次查询要重建索引。我们的 BM25Index 把文档字段存在内存 dict 里，warmup 一次 ~0.69s，之后每次查询 ~0.01s，彻底解决冷启动问题。

### 4. 流式 SSE

`/api/chat/stream` 状态字 + token 流式输出。前端通过 EventSource 逐字渲染，降低心理等待感。

### 5. 全链路耗时埋点

从 API 入口 → Supervisor → RAG 子链路 → LLM 调用，每个阶段都有 log_timing。通过分析发现 parent_expand 占 RAG 内部 43%、Redis 超时导致 ~16s 卡顿等瓶颈。

---

## 六、面试结尾 — 你可以主动总结的重点

### 你在这个项目中的角色和技术深度

- 整套架构从零搭建（FastAPI + LangGraph + Milvus + Neo4j + Redis）
- RAG 检索增强是你最深入的部分——从基础方案做到双索引路由，建立了完整的增强技术分类框架
- 每个技术选型都有明确的"为什么"和"为什么不做"（子问题查询、Step-Back、PREREQUISITE_OF）
- 你能讲清楚每个瓶颈的定位方法和优化手段（perf log 分析、批量查询、重复检索消除）
- 面试官如果问到 Neo4j 图数据库，你能从建模到增量同步到路由策略完整讲述

### 如果面试官问"你遇到的最大挑战是什么"

说 RAG 检索增强的迭代过程最合适——

1. 一开始做了传统的混合检索
2. 发现有些关系型问题回答不好（"X 和 Y 的区别"）
3. 决定引入 Neo4j 知识图
4. 但面临一个选择：是做成三路 RRF 融合还是按问题类型路由？
5. 分析后发现融合会引入噪音，最终选了路由方案
6. 这个过程体现了"不是加功能，而是选合适的方案"

---

## 七、自我介绍模板（可选）

```
面试官你好，我是 XXX。我最近在做一个 AI 教学助教项目。

技术栈是 Python + LangGraph + DeepSeek + Milvus + Neo4j + Redis，
全套从零搭建。

RAG 检索增强是我最花精力的部分——从传统的混合检索一路做到
双索引路由检索（向量 + 知识图谱），并且把 40 多个增强技术点
整理成了一个完整的分类框架。

还做了多 Agent 架构、长期记忆系统、流式 SSE 等。

整个项目已经可以跑通——学员可以从提问到面试到岗位匹配一条龙使用。

接下来可以从架构图开始详细聊。
```
