# 答案跳转课程视频

> 状态：已实现（首版） | 最后更新：2026-07-16  
> 关联：RAG 已入库字段见 [schema.md](../rag/schema.md) / [retriever.md](../rag/retriever.md)；本文件覆盖编排出口 → API → 静态资源 → UI。

## 1. 目标与边界

**目标**：学员在答疑回复下点击来源，同页打开课程 `.mp4` 并 seek 到命中子块的 `start_sec`（秒级）。

| 在范围内 | 不在范围内（首版） |
|----------|-------------------|
| 展示 citations + 类比 analogy_citations（分区） | SSE 流式中途推 citation |
| 底部停靠播放器 + seek；倍速/音量/字幕本地记忆 | 多清晰度 |
| `/media` 只读播 mp4 + `/captions` WebVTT | SQLite 外的跨设备历史同步 |
| 路径防穿越 | 非 QA Agent 伪造跳转 |

数据唯一来源：索引阶段写入的 `media_path` + `start_sec`（同 stem 转写 md / mp4）。**禁止 LLM 编造路径或秒数。**

## 2. 已就绪 vs 待做

| 层 | 状态 | 说明 |
|----|:----:|------|
| indexer / schema | 已实现 | 子块含 `start_sec` / `end_sec` / `media_path`；知识切分后 `start_sec` 精准指向知识点起点 |
| retrieve | 已实现 | 工具返回已透传跳转字段 + `kp_title` / `kp_summary` / `kp_index` |
| 知识切分 Skill | 已实现 | `skills/knowledge-split/` — LLM 离线切分 → `.knowledge.json` |
| Supervisor / QA 出口 | 已实现 | ToolMessage → `citations`；`ensure_qa_citations` 强制主路检索 |
| ChatResponse / routes | 已实现 | 下发 `citations` + `analogy_citations`；`source`/`score`=Top1 |
| `/media` / `/captions` | 已实现 | 限定 `resources/`；mp4 / vtt |
| 前端 MessageItem | 已实现 | citation 按钮；`kp_title` 作副标题 |
| 前端 VideoDock | 已实现 | seek + 进度/倍速/音量/字幕 localStorage 记忆 |

## 3. 端到端数据流

```
┌──────────────┐   search_course_content   ┌─────────────────────┐
│ retrieve()   │ ─────────────────────────►│ Tool 返回 list[dict] │
│ start_sec    │                           │ 含 media_path 等     │
│ media_path   │                           └──────────┬──────────┘
└──────────────┘                                      │
                                                      ▼
                                         ┌────────────────────────┐
                                         │ QAAgent 自然语言作答    │
                                         │ （不输出路径；口述章节） │
                                         └──────────┬─────────────┘
                                                    │
         ┌──────────────────────────────────────────┘
         ▼
┌─────────────────────────────────────────────────────────────┐
│ run_supervisor 出口（职责归属）                               │
│  扫描本轮 QA 调用产生的 ToolMessage / 工具 JSON               │
│  → 规范化为 citations[]（去重、丢弃空 media_path 亦可保留文案） │
│  → 与 final_response 一并返回                                │
│  API 层只做字段映射，不解析 LangGraph 内部消息                │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ POST /api/chat/ → ChatResponse                              │
│  content / emotion / agent / options                        │
│  source, score = citations[0] 兼容字段                       │
│  citations[] + 每条拼好的 media_url                          │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────┐
│ MessageItem：citation 按钮 │   │ GET /media/{relative_path}  │
│ 可点项：media_url 非空且   │──►│ 根 = resources/；禁 ..      │
│ start_sec >= 0             │   │ 仅 .mp4 → FileResponse      │
└─────────────┬─────────────┘   └─────────────────────────────┘
              ▼
┌───────────────────────────┐
│ VideoDock（聊天区底部）    │
│ <video controls>           │
│ loadedmetadata → seek      │
└───────────────────────────┘
```

## 4. Citation 模型

```text
Citation:
  source: str          # 展示文案（可含 @M:SS）
  score: float
  section: str
  title: str
  start_sec: int       # < 0 → 不可 seek，仅展示文案
  end_sec: int
  media_path: str      # 相对 resources/；空 → 无播放
  media_url: str       # 后端拼好，如 /media/courses/RAG101%20.../xx.mp4
  captions_url: str    # /captions/...vtt；无字幕则为空
  kp_title: str        # 知识点标题；规则窗为空
  kp_summary: str      # 知识点摘要
  kp_index: int        # 节内序号；无则 -1
```

规范化规则（`src/agents/citations.py`）：

- 主路：`ensure_qa_citations` = dispatch 强制 retrieve + 本轮 `search_course_content` 工具结果合并。
- 工具侧抽取时**整份文档**交给 `doc_to_citation_raw`，保留全部 `kp_*`（勿只抄 path/sec）。
- 按 `score` 降序；去重键为 `(media_path, start_sec, kp_index)`——同秒不同知识点不合并。
- `media_path` 非空时生成 `media_url` / `captions_url`；文件不存在仍可下发 URL，播放时 404 由前端降级。
- Progress / Recommend / 闲聊：`citations = []`；类比见 [course-scope](../rag/course-scope.md)。

## 5. 后端设计

### 5.1 ChatResponse（扩展）

```json
{
  "content": "RAG 是检索增强生成……",
  "source": "课程 …… @3:10",
  "score": 0.99,
  "emotion": "neutral",
  "agent": "qa_agent",
  "thread_id": "stu_1_…",
  "options": [],
  "citations": [
    {
      "source": "课程 ……《RAG和Graph RAG有什么区别》 @0:28",
      "score": 0.9959,
      "section": "10-06",
      "title": "RAG和Graph RAG有什么区别：如何构建Graph RAG",
      "start_sec": 28,
      "end_sec": 95,
      "media_path": "courses/RAG101 RAG全栈技术从基础到精通/10 …/10-06 ….mp4",
      "media_url": "/media/courses/RAG101%20RAG…/10-06%20….mp4",
      "captions_url": "/captions/courses/RAG101%20RAG…/10-06%20….vtt",
      "kp_title": "普通RAG与Graph RAG的四个维度对比",
      "kp_summary": "…",
      "kp_index": 0
    }
  ],
  "analogy_citations": []
}
```

- `source` / `score`：取 `citations[0]`，无则空 / 0（兼容旧前端）。
- Prompt / QA 产出仍为纯文本；跳转字段与回答正文解耦。

### 5.2 提取职责

| 位置 | 做什么 |
|------|--------|
| `run_supervisor`（或 QA dispatch 紧邻处） | 收集本轮工具检索结果 → `citations` 原始列表（尚无 `media_url`） |
| `routes.chat` | 补 `media_url`；填 `ChatResponse` |
| QA Prompt | 不要求模型输出路径；可继续口述章节名 |

### 5.3 静态资源 `/media`

```
GET /media/{path:path}
  1. 规范化 path，拒绝绝对路径与 ".."
  2. full = resources_dir / path；须 full.is_relative_to(resources_dir)
  3. 后缀必须为 .mp4（大小写不敏感）
  4. 存在 → FileResponse；否则 404
```

挂载方式：受控路由优于裸 `StaticFiles` 全盘开放（便于后缀与穿越校验）。开发期 Vite 可将 `/media` 代理到 `:8000`，保证 `<video src>` 同源。

## 6. 前端设计

### 6.1 布局

```
┌────────────────────────────────────────────┐
│ Sidebar │  消息列表（Markdown + citations） │
│         │                                  │
│         │  [📎 10-06 @3:10] [📎 10-08 …]   │
│         ├──────────────────────────────────┤
│         │  VideoDock（可关闭）              │
│         │  ┌────────────────────────────┐  │
│         │  │ <video>  标题 / 关闭        │  │
│         │  └────────────────────────────┘  │
│         │  ChatInput                       │
└────────────────────────────────────────────┘
```

单栏聊天不变；大屏也不强制左右分栏。

### 6.2 组件职责

| 组件 | 职责 |
|------|------|
| `App.vue` | 收 `citations` / `analogy_citations`；处理 `playCitation` |
| `MessageItem.vue` | 主区 + 类比区按钮；可点：`media_url` 且 `start_sec >= 0`；可选展示 `kp_title` |
| `VideoDock.vue` | seek；进度键 `video_playback_progress`；设置键 `video_player_settings`（倍速/音量/静音/字幕） |

播放逻辑：

1. 同 `media_url`：只改 `currentTime = start_sec` 并 `play()`。
2. 不同文件：换 `src`，在 `ready` / `loadeddata` 后恢复设置再 seek。
3. 加载/404 失败：dock 内提示「视频暂不可用」，citation 文案仍保留。

### 6.3 持久化与每轮附带

- 每轮 QA：`dispatch` 层 `ensure_qa_citations()` **强制 retrieve**（不依赖 LLM 是否调工具），与工具结果合并 → 每答必有可跳转来源（有 mp4 时）。
- 选项续聊：用选项正文作检索词（非「学员选择了选项…」整句）。
- 写入 `QAHistory.retrieved_docs`；`GET .../messages` 带回 `citations`；前端 localStorage 同步。

## 7. 安全与失败

| 场景 | 行为 |
|------|------|
| `media_path` 含 `..` / 越出 resources | 不下发 `media_url` 或 `/media` 返回 404 |
| 非 `.mp4` | 拒绝 |
| 文件缺失 | 404；UI 降级为不可点或提示 |
| `start_sec < 0` 或无 path | 只展示 `source` 文案 |
| 非 QA 轮次 | `citations=[]` |

## 8. 实现顺序（文档确认后编码）

1. `Citation` 模型 + `ChatResponse.citations`；`run_supervisor` 抽出工具结果。
2. `/media` 受控路由 +（可选）Vite proxy。
3. `MessageItem` citations UI + `VideoDock` seek。
4. 联调：问 Graph RAG 相关题 → 点 `@3:10` → 视频落在约 190s。

## 9. 相关文档

- [RAG retriever](../rag/retriever.md) — 检索返回字段
- [RAG indexer](../rag/indexer.md) — cue 分块与 media_path
- [知识点切分](../rag/knowledge-point.md) — LLM 知识边界检测
- [课程作用域](../rag/course-scope.md) — Soft/Hard 与 analogy_citations
- [知识切分 Skill](../../skills/knowledge-split/SKILL.md) — Agent 执行切分
- [QA 工具](../tools/qa.md) — `search_course_content`
- [API](api.md) — 响应契约
- [UI 总览](index.md) — 布局与交互
