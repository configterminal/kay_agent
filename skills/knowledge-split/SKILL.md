---
name: knowledge-split
description: >-
  用 LLM 将课程转写 .md 按知识点切分，生成 .knowledge.json。
  build_index 发现 JSON 后自动使用知识点模式替代规则窗口切块。
  当用户要求切分知识点、重建索引、或新增课程需要结构化知识单元时使用。
---

# 课程知识点切分

**项目内权威路径**：`skills/knowledge-split/`。

将 `resources/courses/` 下已有转写 `.md` 送给 LLM，识别知识边界，产出 `.knowledge.json`。
**切分完不是终点，必须 `build_index(force=True)` 重建索引才会生效。**

| 文件 | 用途 |
|------|------|
| [SKILL.md](SKILL.md) | 本文件 |
| [COPY_PROMPTS.md](COPY_PROMPTS.md) | 复制到其他 Agent 视口并行切分 |
| [prompts/split_prompt.py](prompts/split_prompt.py) | LLM System / User Prompt 模板 |
| [scripts/scan_cues.py](scripts/scan_cues.py) | 扫描转写 .md 打印 cue 摘要（预览用） |

## 与转写/改名的强制顺序

```
① course-resource-rename → 合规路径
② course-transcribe → .md 带时间戳
③ knowledge-split（本 Skill） → .knowledge.json
④ build_index(force=True) → Milvus 知识点索引
```

**禁止**：未完成 ① ② 就切分；未切分就 build_index 会 fallback 到规则窗口。

## 何时用

- 新增课程转写完成后，需要知识点结构化
- 用户说：切分知识点、生成 knowledge.json、结构化课程内容
- 存量课程：初次全量切分

## 并行规则

1. **互斥范围**：一个 Agent 只负责一门课 / 一章。禁止两 Agent 同改一课。
2. **每节独立**：`10-06.knowledge.json` 只依赖 `10-06.md`，各节互不影响。
3. **失败隔离**：某节 LLM 切分失败 → 不写 JSON（build_index 对该节自动 fallback 规则切块）。

## 工作流

```
- [ ] 1. 锁定范围（一门课或一章）
- [ ] 2. --dry-run 预览 cue 数量与时长
- [ ] 3. 逐节调用 LLM 切分 → 写入 .knowledge.json
- [ ] 4. 抽查 JSON 质量
- [ ] 5. build_index(force=True)
```

### 预览

```powershell
# 看一门课所有节的基本信息
& f:\agent\.venv\Scripts\python.exe skills/knowledge-split/scripts/scan_cues.py --course RAG101

# 只看一章
& f:\agent\.venv\Scripts\python.exe skills/knowledge-split/scripts/scan_cues.py --chapter "resources/courses/RAG101 RAG全栈技术从基础到精通/10 基于知识图谱【金融智库】：从RAG到Graph RAG"
```

## 输出格式

每节 `.md` 旁生成同 stem `.knowledge.json`：

```
10 基于知识图谱【金融智库】：从RAG到Graph RAG/
├── 10-06 RAG和Graph RAG有什么区别：如何构建Graph RAG.md
├── 10-06 RAG和Graph RAG有什么区别：如何构建Graph RAG.mp4
└── 10-06 RAG和Graph RAG有什么区别：如何构建Graph RAG.knowledge.json  ← 生成
```

```json
{
  "section": "10-06",
  "title": "RAG和Graph RAG有什么区别：如何构建Graph RAG",
  "course_id": "RAG101",
  "total_cues": 350,
  "knowledge_points": [
    {
      "kp_index": 0,
      "kp_title": "普通RAG与Graph RAG的四个维度对比",
      "kp_summary": "从知识表达、检索机制、上下文理解能力、推理能力四个维度对比RAG和Graph RAG",
      "key_points": [
        "知识表达：平面文档 vs 图结构",
        "检索机制：语义相似度搜索 vs 图遍历算法",
        "上下文理解：多步骤关系局限 vs 天然关系捕捉",
        "推理能力：有限 vs 深度复杂推理"
      ],
      "cue_start_idx": 7,
      "cue_end_idx": 45,
      "start_sec": 28,
      "end_sec": 199
    },
    {
      "kp_index": 1,
      "kp_title": "Graph RAG适合的查询场景",
      "kp_summary": "多跳关系、语义关联、聚合统计、时序关联四类适合Graph RAG的查询类型",
      "key_points": ["多跳关系查询", "语义关联查询", "聚合统计查询", "时序关联查询"],
      "cue_start_idx": 46,
      "cue_end_idx": 74,
      "start_sec": 200,
      "end_sec": 410
    }
  ]
}
```

**关键字段说明**：

| 字段 | 说明 |
|------|------|
| `kp_title` | LLM 生成的知识点标题，用于检索锚点和前端展示 |
| `kp_summary` | 1-2 句摘要，参与向量化 |
| `key_points` | 3-6 个要点，参与向量化 |
| `cue_start_idx` | 从 0 起的 cue 行号（不含标题和空行），指向本节 cues 列表 |
| `cue_end_idx` | 闭区间，此 cue 也属于本知识点 |
| `start_sec` | 知识点开始秒数 = cues[cue_start_idx].start_sec |
| `end_sec` | 知识点结束秒数 = cues[cue_end_idx].start_sec |

### 与 build_index 的协定

`build_index` 扫描时检查 `.knowledge.json` 是否存在：
- **存在** → 读取 `knowledge_points`，每个知识点作为一个子文档（替代规则切块）；embedding 对 `kp_title + kp_summary + key_points` 向量化
- **不存在** → fallback 到现有 `split_cues_into_chunks`（400 字/45s 窗口），`kp_title` / `kp_summary` 等字段留空

## LLM 调用要求

- 每节调用一次 LLM（输入 ~3K tokens，输出 ~1K tokens）
- 输入：课程元信息 + 完整 cue 列表（带 `[idx]` 编号和时间戳）
- 输出：JSON 数组 `[{kp_index, kp_title, kp_summary, key_points, cue_start_idx, cue_end_idx}]`
- 短节（< 15 行 cue）：1 个知识点
- 长节（> 80 行 cue）：自然切分为 5-15 个知识点
- 降级：LLM 返回 JSON 解析失败 → 重试一次；仍失败 → 不写 JSON，该节 fallback

## 技术细节

| 项目 | 配置 |
|------|------|
| LLM | deepseek-chat（同项目默认 Provider） |
| 每节平均 token 输入 | ~3K |
| 每节平均 token 输出 | ~1K |
| 126 节全量成本 | < ¥1 |
| 单节耗时 | ~2-5 秒（API 往返） |
| 并发 | 各 Agent 视口独立，无冲突 |

## 禁止

- 不在转写未完成前切分
- 不跨 Agent 切分同一门课（避免重复写入 JSON）
- 不修改原 .md 文件
- 不擅自 git commit
