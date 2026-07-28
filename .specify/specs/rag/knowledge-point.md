# 知识点切分 — LLM 驱动的结构化知识单元

> 状态：已实现 | 最后更新：2026-07-16
> 关联：[indexer.md](indexer.md) / [schema.md](schema.md) / [retriever.md](retriever.md) / [video-jump.md](../ui/video-jump.md) / [知识切分 Skill](../../skills/knowledge-split/SKILL.md)

## 1. 动机

### 1.1 当前问题

现有索引按**字数窗口（~400 字 / ~45 秒）**切块。检索命中子块后，`start_sec` 是该窗口第一条 cue 的时间戳——可能是中间某句碎片，而不是该知识讲解的起点。

用户点击跳转后，只能看到从该秒开始的部分内容，无法获得完整的知识讲解。

```
现状：
  "RAG和Graph RAG有什么区别？"
    → 检索命中子块 chunk #2，start_sec = [1:17]
    → 跳转到 1:17，看到的是"第二个是检索的机制…"
    → 用户错过开头的"第一个是知识的表达"和整体引入

期望：
  "RAG和Graph RAG有什么区别？"
    → 检索命中知识点 "普通RAG与Graph RAG的四个维度对比"
    → 跳转到 0:28，看到完整引入 "我们接下来从几个维度来对比…"
```

### 1.2 长期价值

"知识点"作为一等实体，不只服务于视频跳转：

| 消费方 | 用途 |
|--------|------|
| QA Agent | 检索命中完整知识点，`start_sec` 精准跳转 |
| 面试 Agent | 基于知识点 title/key_points 生成面试题 |
| 进度 Agent | 以知识点为颗粒度追踪学员掌握程度 |
| 推荐 Agent | 根据薄弱知识点推荐相关学习内容 |

---

## 2. 数据现状

### 2.1 规模

| 指标 | 数值 |
|------|------|
| 课程数 | 2 门（RAG101 / CAREER201） |
| 总节数 | 126 节 |
| 转写总行数 | ~26,875 行 |
| 平均行数/节 | ~213 行 |
| 最小文件 | 8 行（本章介绍） |
| 最大文件 | 1,344 行（深度讲解） |
| 转写格式 | `[M:SS]` 或 `[H:MM:SS]` cue 行 + 少量无时间戳标注行 |

### 2.2 两门课的转写风格差异

**RAG101（RAG 技术课）**：讲师表达结构化，有明显序数词和过渡语——

```
[0:28] 我们接下来从几个维度来对比一下普通的RAG跟基于知识图谱的Graph RAG
[0:37] 第一个是知识的表达
[1:17] 第二个是检索的机制
[2:53] 接下来一个是从推理能力角度来看
[3:20] 接下来我们来看一下Graph RAG 它适合的查询的场景是什么样子的
[6:46] 下面我们来举几个更加直观的例子
[10:59] 上面我们了解了GraphRAG的一些测点
[11:02] 接下来我们来详细看一下 如何构建 GraphRAG的一个过程
```

**CAREER201（职场课）**：讲师口语化，部分章节有**单行标题性 cue**（字幕中的 PPT 页切换标记）——

```
[0:31] 职场本质
[3:11] 职场模型
[4:03] 接下来聊一聊菜市场理论
[6:22] 职场真相
```

**结论**：两门课风格差异大，纯规则方案覆盖率不可靠；但转写中保留了足够的语义线索（过渡语 / 标题 cue / 序数词），适合作为 LLM 判断边界的输入。

---

## 3. 方案设计

### 3.1 核心思路

**分两步走，LLM 切分与索引解耦：**

```
① 离线切分（Skill 层，Agent 执行）：
   .md 转写 → Agent 调 LLM 识别知识边界 → .knowledge.json

② 索引（build_index）：
   扫描 .md → 检查同目录 .knowledge.json
     → 存在：读 JSON，每个 knowledge_point 作为一个子文档
     → 不存在：fallback 到 split_cues_into_chunks（规则窗口）
   → embedding → Milvus
```

**为什么分开**：
- LLM 切分可能失败（JSON 解析错误、超时），不应阻塞整个索引
- 新增课程时，Agent 可以在别的视口先切分好，`build_index` 直接消费
- `.knowledge.json` 是幂等的中间产物——切分一次，多次重建索引无需重新调 LLM

### 3.2 知识点数据模型

**中间文件**（`.knowledge.json`，与 `.md` 同目录）：

```json
{
  "section": "10-06",
  "title": "RAG和Graph RAG有什么区别：如何构建Graph RAG",
  "course_id": "RAG101",
  "total_cues": 348,
  "knowledge_points": [
    {
      "kp_index": 0,
      "kp_title": "普通RAG与Graph RAG的四个维度对比",
      "kp_summary": "从知识表达、检索机制、上下文理解能力、推理能力四个维度对比RAG和Graph RAG",
      "key_points": ["知识表达：平面文档 vs 图结构", "检索机制：语义相似度搜索 vs 图遍历算法", "上下文理解：多步骤关系局限 vs 天然关系捕捉", "推理能力：有限 vs 深度复杂推理"],
      "cue_start_idx": 7,
      "cue_end_idx": 45,
      "start_sec": 28,
      "end_sec": 199
    }
  ]
}
```

**Milvus 子文档**（每个知识点一个）：

```text
KnowledgePoint（Milvus 子文档，chunk_index >= 0）:
  id: str                  # "RAG101_10-06_kp1"
  content: str             # 知识点全文（cue_start_idx..cue_end_idx 的 text 拼接）
  embedding: float[]       # 对 (kp_title + kp_summary + key_points) 拼接文本向量化
  parent_id: str           # → 父文档（整节全文）

  # 知识点元信息（从 .knowledge.json 读取）
  kp_title: str            # "普通RAG与Graph RAG的四个维度对比"
  kp_summary: str          # 1-2 句摘要
  kp_index: int            # 节内序号，从 0 起
  key_points: str          # 要点列表，逗号分隔

  # 视频跳转
  start_sec: int           # 知识点开始秒数
  end_sec: int             # 知识点结束秒数

  # 来源信息（继承现有字段）
  course_id / chapter / section / title / tags / media_path / file_type
```

> `search_text` 不存入 Milvus——只是 embedding 前的运行时拼接（`kp_title + "\n" + kp_summary + "\n" + key_points`），在 indexer 代码中完成。

### 3.3 Schema 变更

在现有 13 个字段基础上，新增 4 个知识点专用字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `kp_title` | VARCHAR(256) | 知识点标题 |
| `kp_summary` | VARCHAR(1024) | 知识点摘要 |
| `kp_index` | INT16 | 节内序号，从 0 起 |
| `key_points` | VARCHAR(2048) | 要点列表（逗号分隔） |

**不受影响的现有字段**：`id`, `content`, `embedding`, `parent_id`, `course_id`, `chapter`, `section`, `title`, `file_type`, `chunk_index`, `tags`, `start_sec`, `end_sec`, `media_path`。

**embedding 策略变更**：不对 `content` 全文做向量化，而是对 `kp_title + kp_summary + key_points` 拼接后的 `search_text` 做向量化。这样检索时语义匹配的是**精炼过的知识点摘要**，而不是冗长的口语转写。

### 3.4 索引流程

```
build_index(force=True) 对每节 .md：

1. parse_timestamped_md() → cues 列表（现有逻辑不变）

2. 检查同目录 .knowledge.json：
   → 存在且解析成功：读取 knowledge_points 列表
   → 不存在或解析失败：fallback 到 split_cues_into_chunks(cues)

3. 对每个知识块组装 Milvus 文档：
   - content = cues[cue_start_idx..cue_end_idx] 的 text 拼接
   - search_text = kp_title + "\n" + kp_summary + "\n" + ",".join(key_points)
   - embedding = embed(search_text)
   - Milvus 字段：kp_title / kp_summary / kp_index / key_points
   - start_sec / end_sec 直接取自 JSON

4. 写入 Milvus（父文档 + N 个知识点子文档）
```

> **关键**：`build_index` **不调 LLM**——只消费已有的 `.knowledge.json`。LLM 切分由 Agent 通过 [知识切分 Skill](../../skills/knowledge-split/SKILL.md) 离线完成。

### 3.5 LLM 切分

LLM Prompt 与调用逻辑全部在 Skill 层，详见：
- SKILL 流程：[skills/knowledge-split/SKILL.md](../../skills/knowledge-split/SKILL.md)
- Prompt 模板：[skills/knowledge-split/prompts/split_prompt.py](../../skills/knowledge-split/prompts/split_prompt.py)

核心约定：
- 每节调用一次 LLM（输入 ~3K tokens，输出 ~1K tokens）
- 输入：课程元信息 + 完整 cue 列表（带 `[idx]` 行号）
- 输出：JSON 数组 `[{kp_index, kp_title, kp_summary, key_points, cue_start_idx, cue_end_idx}]`
- `start_sec` / `end_sec` 由 Agent 在写入 JSON 前根据 `cue_start_idx` / `cue_end_idx` 计算

### 3.6 检索适配

检索命中文档后，返回字段新增：

```diff
  {
-   "content": "原始 400 字窗口文本",
+   "content": "知识点全文转写",
+   "kp_title": "普通RAG与Graph RAG的四个维度对比",
+   "kp_summary": "从知识表达、检索机制、上下文理解、推理能力四个维度...",
+   "key_points": ["...", "..."],
-   "start_sec": 77,   ← 原窗口第一条 cue
+   "start_sec": 28,   ← 知识点真正的起点
    ...
  }
```

`_format_source()` 中 `@M:SS` 自动用新的 `start_sec`，无需改动。

Citation 展示时的 `source` 文案可以获得知识点语义增强：

```
现有：课程 …《RAG和Graph RAG有什么区别：如何构建Graph RAG》 @3:10
增强：课程 …《RAG和Graph RAG有什么区别：如何构建Graph RAG》
      【普通RAG与Graph RAG的四个维度对比】 @0:28
```

（是否在 citation 中展示 `kp_title`，由前端决定；数据层保持灵活。）

---

## 4. 异常处理与边界情况

| 场景 | 处理方式 |
|------|---------|
| 节很短（< 20 行 cue） | LLM 返回 1 个知识点，包含全部内容 |
| 节很长（> 80 行 cue） | LLM 自然切分为 5-15 个知识点 |
| LLM 切分失败 / 超时 | Fallback 到现有 `split_cues_into_chunks`（规则切块），标注 `kp_title=""` |
| LLM 返回的边界越界 | 校验 cue_start_idx / cue_end_idx 范围，越界则裁剪或 fallback |
| cue 数量与 LLM 返回不一致 | 以 LLM 的 cue_end_idx 为准，不依赖 cue 文本匹配 |
| LLM 返回的 JSON 解析失败 | 重试一次；仍失败则 fallback |
| 不在索引时而在查询时用到知识点 | 检索返回的 `kp_title` / `kp_summary` 可能为空（来自规则 chunk），前端降级为普通展示 |

---

## 5. 对现有代码的影响范围

| 文件 | 变更 |
|------|------|
| `skills/knowledge-split/` | **新增** Skill：SKILL.md / COPY_PROMPTS.md / prompts/split_prompt.py / scripts/scan_cues.py |
| `src/vectordb/schema.py` | 新增 4 个 FieldSchema：`kp_title`, `kp_summary`, `kp_index`, `key_points` |
| `src/vectordb/indexer.py` | `build_index()` 扫描时检查 `.knowledge.json`：存在则读 JSON 知识点，不存在则 fallback 规则窗口；embedding 改用 `search_text` |
| `src/vectordb/retriever.py` | `_format_source()` 可选增强；透传新增字段 |
| `src/agents/citations.py` | 整份工具文档 → `doc_to_citation_raw`（保留 `kp_*`）；去重键含 `kp_index` |
| `src/api/schemas.py` | `Citation` 含 `kp_title` / `kp_summary` / `kp_index` |
| `src/ui/src/components/MessageItem.vue` | `citationLabel()` 可选展示 `kp_title` |
| `src/ui/src/components/VideoDock.vue` | seek 用更准的 `start_sec`；播放器设置本地记忆（与 kp 无关） |

### 不影响的范围

- 父文档逻辑：保持不变
- 查询重写 / 混合检索 / 重排序：保持不变
- Supervisor / QA Agent / Prompt：保持不变
- `/media` 静态资源路由：保持不变
- 前端 VideoDock 播放逻辑：保持不变

---

## 6. 成本估算

### LLM 调用量

| 项目 | 估算 |
|------|------|
| 总节数 | 126 节 |
| 每节平均 token（输入） | ~3K tokens（~200 行转写 + prompt） |
| 每节平均 token（输出） | ~1K tokens（5-10 个知识点 JSON） |
| 全量索引总输入 | ~378K tokens |
| 全量索引总输出 | ~126K tokens |

按 deepseek-chat 价格（¥1/1M 输入，¥2/1M 输出），全量索引成本约 **¥0.63**。

### 增量索引

新增课程时只对新节调用 LLM。按每节 ¥0.005 计算，一门 50 节的课约 ¥0.25。

### 索引时间

| 阶段 | 全量（126 节） |
|------|-------------|
| LLM 切分 | ~126 次 API 调用，可并发；串行约 2-4 分钟 |
| Embedding | ~126 × N 个知识点的向量化，约 1-3 分钟 |
| 写入 Milvus | 秒级 |

---

## 7. 实现计划

### Phase 0：知识切分 Skill（已完成）

0. 创建 `skills/knowledge-split/`：SKILL.md + COPY_PROMPTS.md + prompts + scan_cues.py

### Phase 1：知识切分执行（Agent + LLM）

1. 用 COPY_PROMPTS.md 在 Agent 视口对现有 126 节执行 LLM 切分
2. 产出 `.knowledge.json`，抽查质量

### Phase 2：索引适配

3. 修改 `src/vectordb/schema.py`：新增 4 个字段
4. 修改 `src/vectordb/indexer.py`：`build_index()` 读 `.knowledge.json`，fallback 规则窗口
5. `build_index(force=True)` 全量重建

### Phase 3：检索 + API 适配

6. 修改 `src/vectordb/retriever.py`：返回新增字段
7. 修改 `src/agents/citations.py`：透传 `kp_*`；去重含 `kp_index`
8. `Citation` 模型新增 `kp_title` / `kp_summary` / `kp_index`

### Phase 4：前端 + 验证

9. 前端 citation 展示增强（可选——不影响现有功能）
10. 验收：提问 → 命中知识点 → 视频跳转到知识点起点

---

## 8. 相关文档

- [RAG 索引器](indexer.md) — 现有索引逻辑
- [Milvus Schema](schema.md) — 字段定义
- [RAG 检索器](retriever.md) — 检索流水线
- [视频跳转](../ui/video-jump.md) — 端到端数据流
- [QA 工具](../tools/qa.md) — `search_course_content`
- [知识切分 Skill](../../skills/knowledge-split/SKILL.md) — Agent 执行切分的操作流程
