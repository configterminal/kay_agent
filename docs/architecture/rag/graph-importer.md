# Graph Importer — 图数据库导入器

> 状态：已落地 | 最后更新：2026-07-21  
> 关联：[Graph RAG 双索引架构](graph-rag.md) · [增强技术分类](enhancement-taxonomy.md) · [索引器](../rag/indexer.md) · [服务生命周期](../service-lifecycle.md) · [图检索器](graph-rag.md#4-图检索通路phase-2)

## 1. 定位

在服务启动时（lifespan）**增量同步**课程知识图谱到 Neo4j。

与 `build_index()`（建 Milvus 向量索引）并行运行，互不干扰，各自消费同一批数据源。

## 2. 模块结构

```
src/graph/
├── __init__.py              # 模块入口
├── client.py                # Neo4j 驱动单例（已有）
├── importer.py              # 导入器入口 — sync_graph()
├── node_builder.py          # 节点构建 — Course/Chapter/Section/KnowledgePoint/Skill/Role
├── relation_builder.py      # 关系构建 — HAS_*/TEACHES/REQUIRES/BELONGS_TO/EXPANDS
└── expan_infer.py           # LLM 推断 EXPANDS 关系（节内 KP 层级）
```

**设计原则**：
- 每个 builder 模块**幂等**——重复调用不产生重复数据（使用 Cypher MERGE）
- `importer.py` 只负责编排，不写 Cypher
- `node_builder.py` / `relation_builder.py` 是纯 Cypher 执行器
- `expan_infer.py` 调 LLM，可独立运行（也可作为 Skill 手动触发）

## 3. 数据流

```
                    ┌─────────────────────────────┐
                    │      sync_graph()            │
                    │      (importer.py)           │
                    └─────────────┬───────────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            │                     │                     │
            ▼                     ▼                     ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │  node_builder   │  │ relation_builder│  │  expan_infer   │
   │                 │  │                 │  │                 │
   │ Course          │  │ HAS_CHAPTER     │  │ EXPANDS        │
   │ Chapter         │  │ HAS_SECTION     │  │ (LLM 推断)     │
   │ Section         │  │ HAS_KNOWLEDGE_  │  │                 │
   │ KnowledgePoint  │  │   POINT          │  │                 │
   │ Skill           │  │ TEACHES         │  │                 │
   │ Role            │  │ REQUIRES        │  │                 │
   │                 │  │ BELONGS_TO      │  │                 │
   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │       Neo4j             │
                    │  bolt://localhost:7687  │
                    └─────────────────────────┘


数据源:

  resources/courses/**/index.json        ──→  Course 节点
  resources/courses/**/module.json       ──→  Chapter/Section 节点 + skills 字段
  resources/courses/**/*.knowledge.json  ──→  KnowledgePoint 节点
  resources/job_roles/IT/roles.json      ──→  Skill/Role 节点

关系推导:

  index.json + 目录层级 → HAS_CHAPTER, HAS_SECTION
  knowledge.json 遍历   → HAS_KNOWLEDGE_POINT
  module.json skills    → TEACHES (Section → Skill)
  TEACHES 反向          → BELONGS_TO (KnowledgePoint → Skill)
  roles.json            → REQUIRES (Role → Skill)
  LLM 推断              → EXPANDS (KnowledgePoint → KnowledgePoint)
```

## 4. 线程模型

`sync_graph()` 和 `build_index()` **互不依赖**，资源独立（Neo4j vs Milvus），可以并行启动。

```
lifespan 启动
    │
    ├── 推理就绪后
    │
    ├── async: sync_graph()        ← 图数据库导入（新增）
    │     ├── node_builder
    │     ├── relation_builder
    │     └── expan_infer (LLM)
    │
    └── sync:  build_index()?      ← 向量索引（通常手动触发）
         warmup_bm25()             ← BM25 预热（已有）
```

但实际上 `build_index()` 目前是**手动调用**的（不在 lifespan 里自动跑），只有 `warmup_bm25()` 在 lifespan 中。

所以导入器的线程模型很简单：

```
lifespan:
  ① ② ②.5 ... ──→ 主线程
                    │
                    └── Thread(target=sync_graph) ──→ 后台线程
                           │
                           ├── build_nodes()
                           ├── build_relations()
                           └── infer_expands()
```

- 后台线程，不阻塞服务启动
- 异常静默捕获，写日志，不 crash 服务
- Neo4j 不可达 → 跳过，下次启动重试

## 5. 增量检测

每个节点有唯一标识，导入前用 MERGE 保证幂等，同时检查是否已存在以跳过不必要的工作：

| 节点类型 | 唯一键 | 检测方式 |
|---------|--------|---------|
| Course | `id` (RAG101/CAREER201) | `MERGE (c:Course {id: ...})` |
| Chapter | `id` (RAG101_10) | `MERGE (ch:Chapter {id: ...})` |
| Section | `id` (RAG101_10-06) | `MERGE (s:Section {id: ...})` |
| KnowledgePoint | `kp_id` (RAG101_10-06_kp1) | `MERGE (kp:KnowledgePoint {kp_id: ...})` |
| Skill | `name` (Graph RAG) | `MERGE (sk:Skill {name: ...})` |
| Role | `id` (rag_ai_engineer) | `MERGE (r:Role {id: ...})` |

**节级批量策略**：不是逐 KP 检查，而是按 `section` 批量——查询该 Section 下已有多少 KP，对比 `.knowledge.json` 中的数量。一致则整节跳过，不一致则删除该 Section 下所有 KP 并重建该节的 KP 和关系。

这样 122 节只需要 122 次快速查询（而非 531 次），新课程新增的节自然通过"0 KP → 不一致 → 导入"的路径处理。

## 6. 各模块输入输出

### 6.1 node_builder.py

```python
def build_course_nodes(courses: list[dict]) -> int
    # 输入：_scan_course_files() 返回的课程列表（复用 indexer.py）
    # 输出：创建的 Course 节点数
    # 幂等：MERGE ON id

def build_chapter_section_nodes(courses: list[dict]) -> tuple[int, int]
    # 输入：同上，遍历章节目录
    # 输出：(Chapter 数, Section 数)
    # 幂等：MERGE ON id

def build_knowledge_point_nodes(sections: list[dict], force_sections: set[str] | None) -> int
    # 输入：Section 列表 + 需要强制重建的 section 集合
    # 增量：查询每节已有 KP 数，一致则跳过
    # force_sections：指定节强制重建（知识切分更新后）
    # 输出：新导入的 KP 数

def build_skill_role_nodes(roles_data: dict) -> tuple[int, int]
    # 输入：roles.json 解析结果
    # 输出：(Skill 数, Role 数)
    # 幂等：MERGE ON name/id
```

### 6.2 relation_builder.py

```python
def build_tree_relations(courses: list[dict]) -> int
    # Course -[:HAS_CHAPTER]-> Chapter -[:HAS_SECTION]-> Section
    # 幂等：MERGE 关系

def build_knowledge_point_relations(sections: list[dict]) -> int
    # Section -[:HAS_KNOWLEDGE_POINT]-> KnowledgePoint
    # 幂等：MERGE 关系

def build_skill_relations(sections: list[dict], roles_data: dict) -> int
    # Section -[:TEACHES]-> Skill（读 module.json skills 字段）
    # Role -[:REQUIRES]-> Skill（读 roles.json）
    # KnowledgePoint -[:BELONGS_TO]-> Skill（从 TEACHES 反向推导）
    # 幂等：MERGE 关系

def build_expan_relations(section_id: str, kp_pairs: list[tuple[str, str]]) -> int
    # (kp_概述) -[:EXPANDS]-> (kp_详细)
    # 输入：expan_infer 的输出
```

### 6.3 expan_infer.py

```python
def infer_expands_for_section(section_id: str, kps: list[dict]) -> list[dict]
    # 输入：某节的所有 KP（[{kp_id, kp_title, kp_summary, key_points}, ...]）
    # 输出：[{source_kp_id, target_kp_id}, ...]
    # LLM: 1 次调用，判断哪些 KP 是概述，哪些是展开

def infer_expands_all(sections: list[dict], force: bool = False) -> dict
    # 遍历所有 section，检查已有 EXPANDS 关系
    # 已有则跳过（除非 force=True）
    # 返回：{section_id: [EXPANDS 边列表], ...}
```

## 7. 与 indexer.py 的数据源复用

两个模块消费同一批数据源，但读取方式不同：

| 数据 | indexer.py | importer |
|------|-----------|----------|
| 课程列表 | `_scan_course_files()` | **复用同一个函数** |
| 章节结构 | 遍历目录 | 复用 |
| 知识点 | 读 `.knowledge.json` + embedding | 读 `.knowledge.json`（不 embedding） |
| 技能映射 | 不处理 | 读 module.json `skills` + roles.json |

**复用方案**：import `_scan_course_files` 和 `parse_timestamped_md` 等工具函数，不做重复扫描。importer 拿到课程列表后走自己的 Neo4j Cypher 逻辑。

## 8. 异常处理

| 场景 | 处理 |
|------|------|
| Neo4j 不可达 | 静默跳过，日志 warning，不阻塞服务 |
| .knowledge.json 缺失 | 该 Section 无 KP 节点（合法——有些章可能未做知识切分） |
| module.json skills 为空 | 该 Section 不建 TEACHES（合法——课程介绍/模型选型章无对应技能） |
| LLM 推断失败 | 该节不建 EXPANDS，日志 warning，不阻断其余导入 |
| 目录扫描失败 | 日志 warning，返回空 |
| 中途 crash | 下次启动增量检测自动补齐 |

## 9. lifespan 接入

在 `src/main.py` 的 lifespan 中添加：

```python
# ⑤.5 图数据库导入（后台线程，不阻塞启动）
import threading
from src.graph.importer import sync_graph

def _sync_graph_async():
    try:
        sync_graph()
    except Exception as e:
        logging.getLogger(__name__).warning("图数据库同步失败: %s", e)

threading.Thread(target=_sync_graph_async, daemon=True).start()
```

放在 `④ BM25 warmup` 之后——此时 inference 已就绪（EXPANDS 推断需要 LLM），但不需要等它完成再对外服务。

## 10. 日志与观测

复用现有 `src/perf.py` 的 `log_timing`：

| 指标 | 含义 |
|------|------|
| `graph.sync.total` | 全流程耗时 |
| `graph.nodes.courses` | Course 节点数 |
| `graph.nodes.kp` | KnowledgePoint 节点数（新导入） |
| `graph.relations.tree` | 树形关系数 |
| `graph.relations.skills` | 技能关系数 |
| `graph.expands.inferred` | EXPANDS 推断节数 |
| `graph.expands.llm_time` | LLM 推断总耗时 |

## 11. 相关文档

- [Graph RAG 双索引架构](graph-rag.md) — 图数据模型定义
- [增强技术分类](enhancement-taxonomy.md) — B2 多索引检索
- [RAG 索引器](indexer.md) — 向量索引构建（姐妹模块）
- [服务生命周期](../service-lifecycle.md) — lifespan 启动流程
