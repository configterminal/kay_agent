# Graph RAG — 双索引知识图谱检索

> 状态：Phase 1 建图（进行中）| 最后更新：2026-07-21  
> 关联：[RAG 总览](index.md) · [增强技术分类](enhancement-taxonomy.md) · [混合检索](hybrid-search.md) · [知识点切分](knowledge-point.md) · [记忆系统](../memory.md)

## 1. 定位

在现有 **Milvus 向量 + BM25 混合检索**旁新增一条 **Neo4j 图检索通路**，形成双索引架构：

```
学员问题
    │
    ├── 现有通路 ──→ 查询重写 → 混合检索(Milvus) → 精排 → Top5
    │
    └── 新增通路 ──→ 实体抽取 → 图查询(Neo4j) → 子图上下文 → Top3
                              │
                              ▼
                        RRF 融合 → 最终结果
```

不替代 Milvus，不在 Neo4j 做向量检索。两路并行，各做各擅长的事：

| 通路 | 适合的查询类型 | 不适合 |
|------|--------------|--------|
| **Milvus** | 语义匹配、关键词搜索、口语化提问 | 多跳关系、前置依赖、结构化推理 |
| **Neo4j** | 关系遍历、前置/后续知识链、"X 和 Y 有什么关系" | 语义模糊的开放式问题 |

## 2. 数据来源

所有节点和关系均可从现有数据自动构建，无需人工标注：

| 来源 | 提供什么 | 量 |
|------|---------|-----|
| `index.json`（课程级） | Course 节点、tags | 2 课 |
| 章/节目录名 | Chapter / Section 节点、层级关系 | ~20 章, 126 节 |
| `.knowledge.json`（每节） | KnowledgePoint 节点（kp_title / kp_summary / key_points / start_sec） | ~500-800 个 |
| `module.json` | 章节难度、tags（后续填充后可用） | — |
| `roles.json` | Skill / Role 节点、技能映射 | 15 技能, 2 岗位 |

## 3. 图数据模型

### 3.1 节点定义

#### Course（课程）

```
(:Course {
    id: "RAG101",                  -- 课程 ID（与 index.json 一致）
    title: "RAG全栈技术从基础到精通",  -- 课程名称
    tags: ["RAG","AI","大模型",...], -- 课程级标签（来自 index.json）
    industry: "IT"                   -- 行业
})
```

#### Chapter（章）

```
(:Chapter {
    id: "RAG101_10",               -- {course_id}_{cc}
    course_id: "RAG101",
    cc: "10",                        -- 章序号（两位数字）
    title: "基于知识图谱【金融智库】：从RAG到Graph RAG，让企业知识图谱更智能"
    -- 后续 module.json tags 填充后可用: tags, difficulty
})
```

#### Section（节）

```
(:Section {
    id: "RAG101_10-06",             -- {course_id}_{section}
    course_id: "RAG101",
    section: "10-06",
    title: "RAG和Graph RAG有什么区别：如何构建Graph RAG",
    media_path: "courses/RAG101 .../10-06 ...mp4"
    -- start_sec 由命中的 KnowledgePoint 提供，Section 不冗余
})
```

#### KnowledgePoint（知识点）

```
(:KnowledgePoint {
    id: "RAG101_10-06_kp1",         -- {course_id}_{section}_kp{kp_index}
    kp_index: 1,                     -- 节内序号（从 0 起）
    kp_title: "构建Graph RAG的三个步骤",
    kp_summary: "介绍了构建Graph RAG的三个核心步骤：提取关键词、图检索、整合上下文。",
    key_points: "第一步...; 第二步...; 第三步...",  -- 逗号分隔
    start_sec: 662,                  -- 视频跳转起始秒
    end_sec: 918,
    course_id: "RAG101",
    section: "10-06"
})
```

#### Skill（技能）

```
(:Skill {
    name: "Graph RAG",               -- 技能名（来自 roles.json skill_mappings）
    is_required: true                 -- true=必修, false=选修
})
```

#### Role（岗位）

```
(:Role {
    id: "rag_ai_engineer",           -- 岗位 ID
    title: "RAG / AI 应用工程师",
    industry: "IT"
})
```

### 3.2 关系定义

**Phase 1 必建（确定性，零 LLM）：**

```
(Course)-[:HAS_CHAPTER {order: 10}]->(Chapter)
(Chapter)-[:HAS_SECTION {order: 6}]->(Section)
(Section)-[:HAS_KNOWLEDGE_POINT {order: 1}]->(KnowledgePoint)

(Section)-[:TEACHES]->(Skill)
    -- 来源：module.json 的 tags 字段（每章标注所教技能）
    -- 只对 tags 非空的章建此关系，非整课全挂

(Role)-[:REQUIRES {importance: "required|preferred"}]->(Skill)
    -- 来源：roles.json

(KnowledgePoint)-[:BELONGS_TO]->(Skill)
    -- 反向推导：Section 教某 Skill → 其下所有 KP 都属于该 Skill
```

**后续评估（LLM 推断，Phase 1 不做，性价比低）：**

```
(KnowledgePoint)-[:PREREQUISITE_OF]->(KnowledgePoint)
    -- "必须先掌握 A 才能理解 B"
    -- 600 个 KP，可能边 18 万条，LLM 筛出几百条，有用的 ~50 条
    -- 后续可根据学员查询日志精补，比盲目 LLM 准

(KnowledgePoint)-[:RELATES_TO {type: "extends|contrasts|example_of"}]->(KnowledgePoint)
    -- 知识点间语义关联
    -- 同上，投入产出比不高
    -- 来源：LLM 从 key_points 交叉推断

(Section)-[:TEACHES]->(Skill)
    -- 来源：roles.json skill_mappings（module_id → Skill，再按课程+章节匹配到 Section）

(Role)-[:REQUIRES {importance: "required|preferred"}]->(Skill)
    -- 来源：roles.json

(KnowledgePoint)-[:BELONGS_TO]->(Skill)
    -- 反向推导：Section 教某 Skill → 其下所有 KnowledgePoint 都属于该 Skill
```

> **不在 Phase 1 建的关系**：`PREREQUISITE_OF` 和 `RELATES_TO`。
> 600 个 KP 之间可能的边达 18 万条，LLM 推断能筛出几百条，但真正对检索有用的估计 30-50 条。
> 投入产出比低，且一次推断不可增量修正。后续如有需要，根据学员实际查询日志（两个 KP 被一起搜的频率）精补，比盲目 LLM 推断准得多。

### 3.3 示例：Graph RAG 相关知识子图

```cypher
// 课程 → 章 → 节 → 知识点
(course:Course {id: "RAG101", title: "RAG全栈技术从基础到精通"})
    -[:HAS_CHAPTER]->(ch10:Chapter {id: "RAG101_10", title: "...Graph RAG..."})
    -[:HAS_SECTION]->(s06:Section {id: "RAG101_10-06", title: "RAG和Graph RAG有什么区别..."})
    -[:HAS_KNOWLEDGE_POINT]->(kp0:KnowledgePoint {kp_title: "普通RAG与Graph RAG对比"})

(s06)-[:HAS_KNOWLEDGE_POINT]->(kp1:KnowledgePoint {kp_title: "Graph RAG适用场景举例"})
(s06)-[:HAS_KNOWLEDGE_POINT]->(kp2:KnowledgePoint {kp_title: "构建Graph RAG的三个步骤"})
(s06)-[:HAS_KNOWLEDGE_POINT]->(kp3:KnowledgePoint {kp_title: "从文本提取三元组构建图数据"})

// 技能映射
(graphRag:Skill {name: "Graph RAG", is_required: false})
(s06)-[:TEACHES]->(graphRag)
(kp0)-[:BELONGS_TO]->(graphRag)
(kp1)-[:BELONGS_TO]->(graphRag)
(kp2)-[:BELONGS_TO]->(graphRag)
(kp3)-[:BELONGS_TO]->(graphRag)

// 岗位要求
(role:Role {id: "rag_ai_engineer", title: "RAG / AI 应用工程师"})
    -[:REQUIRES {importance: "preferred"}]->(graphRag)
```

## 4. 图检索通路（Phase 2）

> 状态：已落地 | 最后更新：2026-07-21

### 4.1 路由策略：按问题类型分发

不是三路并行融合——图检索和向量检索各有所长。根据问题类型**路由**到不同的检索通路：

```
学员问题
    │
    ▼
LLM 判断问题类型（工具选择，非代码硬路由）
    │
    ├── 关系型 ──→ search_course_graph (Neo4j)
    │   例: "Graph RAG 和 RAG 有什么区别"
    │       "学 Embedding 之前要掌握什么"
    │       "哪些章节讲了向量数据库"
    │
    └── 语义/事实型 ──→ search_course_content (Milvus，现有不变)
        例: "什么是 RAG 三大核心"
            "BM25 参数怎么调"
```

**为什么不是 RRF 融合**：
- 向量/BM25 擅长语义匹配和关键词搜索
- 图检索擅长关系遍历和结构化查询
- 强行融合会引入噪音——不相关的结果参与排序
- 按问题类型分流，各自发挥长处

### 4.2 工具选择

新增 `search_course_graph` 工具，与 `search_course_content` 并列。LLM 根据 QA_ROLE_PROMPT 中的指引自行选择：

```
工具选择指引：
- 关系类问题（对比、依赖、关联、哪些章节教XX）→ search_course_graph
- 事实类问题（定义、原理、参数、步骤）→ search_course_content
```

### 4.3 图检索实现

`src/graph/retriever.py` — `graph_search()`：

1. jieba 分词提取关键词
2. 并行 Cypher 查询：
   - kp_title / kp_summary / key_points CONTAINS 匹配
   - Skill name 匹配 → BELONGS_TO → 展开 KP
3. 结果包装为与 `retrieve()` 一致的 14 字段格式
4. `content` = kp_title + kp_summary + key_points 组合
5. Neo4j 不可达 → 返回 []，静默降级

### 4.4 结果格式

与 `retrieve()` 返回格式完全一致，直接兼容 citations 和前端：

```python
{
    "content": "【构建Graph RAG的三个步骤】\n介绍了构建Graph RAG的三个核心步骤...",
    "source": "[RAG101] 课程 第10章 第10-06节《RAG和Graph RAG...》 @11:02",
    "score": 0.85,
    "section": "10-06",
    "title": "RAG和Graph RAG有什么区别",
    "course_id": "RAG101",
    "start_sec": 662, "end_sec": 918,
    "media_path": "courses/RAG101 .../10-06 ...mp4",
    "is_web_search": False,
    "kp_title": "构建Graph RAG的三个步骤",
    "kp_summary": "...", "kp_index": 2, "key_points": "...",
}
```

## 5. 两期路线

### Phase 1：建图（当前）

**目标**：Neo4j 中构建完整课程知识图谱，可 Cypher 手动验证，不接入检索通路。

| 步骤 | 内容 | 产出 |
|------|------|------|
| 1.1 | 从课程目录 + index.json + module.json 建 Course/Chapter/Section 节点 + `HAS_CHAPTER`/`HAS_SECTION` | 树形结构 |
| 1.2 | 从 122 个 `.knowledge.json` 建 KnowledgePoint 节点 + `HAS_KNOWLEDGE_POINT` | KP 节点 |
| 1.3 | 导入 `roles.json` Skill/Role 节点 + `REQUIRES`；从 module.json tags 建 `TEACHES` + 反向推导 `BELONGS_TO` | 技能映射 |
| 1.4 | LLM 推断 `EXPANDS` 关系（节内 KP 层级：概述→展开，122 次调用 ≈¥0.50） | KP 层级边 |
| 1.5 | Browser 验证 → `MATCH (n) RETURN n LIMIT 25` | 可视化确认 |

**不做的**：不接检索通路、不调 Cypher 生成 LLM。

### Phase 2：接通检索（✅ 已完成）

| 步骤 | 内容 | 产出 |
|------|------|------|
| 2.1 | `src/graph/retriever.py` — graph_search() + jieba 关键词 + Cypher 双路径 | ✅ |
| 2.2 | `src/tools/graph_tools.py` — search_course_graph 工具 | ✅ |
| 2.3 | QA_ROLE_PROMPT — 工具选择指引 | ✅ |
| 2.4 | build_qa_agent() — tools 列表注册 | ✅ |
| 2.5 | 端到端测试 — 关系型查询触发图检索 | ✅ |

## 6. 异常处理

| 场景 | 处理 |
|------|------|
| Neo4j 不可达 | 图通路静默跳过，仅 Milvus 路返回（非阻断） |
| 实体抽取失败 | 跳过图通路 |
| Cypher 执行超时 | 配置 5s 超时 → 跳过图通路 |
| 图路结果为空 | 不参与 RRF，Milvus 独占 |
| 建图索引缺失 | Phase 1 建 `PREREQUISITE_OF` 和 `RELATES_TO` 时可增量运行，新节导入时自动补 |

## 7. 对现有代码的影响

| 文件 | 变更 |
|------|------|
| `src/graph/schema.cypher` | **新增** — 建图 Cypher 脚本 |
| `src/graph/importer.py` | **新增** — Python 导入器（读 .knowledge.json / roles.json → 调 neo4j driver 写） |
| `src/graph/entity_extractor.py` | **新增**（Phase 2）— 实体抽取 |
| `src/graph/cypher_generator.py` | **新增**（Phase 2）— intent→Cypher |
| `src/graph/retriever.py` | **新增**（Phase 2）— 图检索入口 |
| `src/vectordb/retriever.py` | 修改（Phase 2）— `retrieve()` 增加 `graph_results` 通路 |
| `src/vectordb/hybrid_search.py` | 不修改 — 图路结果复用现有 RRF |
| `src/vectordb/query_rewriter.py` | 不修改 |
| `src/vectordb/reranker.py` | 不修改 |

### 不影响的范围

- Milvus 索引 / 检索流水线
- BM25 索引 / 内存 payload
- 查询重写 / 精排 / 结果处理
- 课程作用域 / 类比检索
- 前端 / API 层
- 记忆系统 / 情感系统

## 11. 相关文档

- [Graph Importer 导入器](graph-importer.md) — 模块结构、数据流、线程模型、增量检测
- [Graph RAG 双索引架构](graph-rag.md) — 图数据模型定义
- [RAG 总览](index.md)
- [增强技术分类](enhancement-taxonomy.md)
- [RAG 索引器](indexer.md) — 向量索引构建（姐妹模块）
- [服务生命周期](../service-lifecycle.md)
