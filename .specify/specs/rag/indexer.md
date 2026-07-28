# indexer.py — 索引器

> 唯一文本源：**带时间戳的转写 `.md`**（`[M:SS]` / `[H:MM:SS]`）+ 同 stem `.mp4`。  
> 资源命名见项目 Skill [`skills/course-resource-rename/naming.md`](../../../skills/course-resource-rename/naming.md)。  
> 改字段后须 `build_index(force=True)` 重建 Collection。  
> 知识切分见 [知识切分 Skill](../../../skills/knowledge-split/SKILL.md) 及 [知识点设计文档](knowledge-point.md)。

```
┌─────────────────────────────────────────────────────────────┐
│                      indexer.py                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  build_index(resources_dir=None, force=False) → int          │
│       │                                                     │
│       │  返回：索引的子文档块总数                              │
│       │                                                     │
│       ├── ① 扫描课程目录                                      │
│       │     resources/courses/{course_id} {course_title}/    │
│       │     → 读 index.json（course_id / title 必填）         │
│       │     → 遍历章目录 `{CC} {chapter_title}/`              │
│       │        → 读 module.json（tags / difficulty）         │
│       │        → 仅索引合规 stem 的 `.md`                     │
│       │           `^(?P<section>\d{2}-\d{2}) (?P<title>.+)$` │
│       │     .mp4 → 不读内容；同 stem 则写入 media_path         │
│       │     .docx / .pdf → 不再索引（遗留）                   │
│       │                                                     │
│       ├── ② 解析 cue                                          │
│       │     行：`[M:SS]` 或 `[H:MM:SS]` + 文本                │
│       │     → list[{start_sec, text}]                       │
│       │     Embedding / 父文档正文 = 去时间戳纯文本            │
│       │                                                     │
│       ├── ③ 父文档                                            │
│       │     整节纯文本 → Milvus（chunk_index = -1）           │
│       │     start_sec/end_sec = -1；可填 media_path          │
│       │     embedding = 全零占位（不参与向量搜索）             │
│       │                                                     │
│       ├── ④ 子文档（二选一）                                   │
│       │                                                     │
│       │     ┌─ 优先：知识点模式 ────────────────────────┐   │
│       │     │  检查 .knowledge.json 存在                  │   │
│       │     │  ├─ 读取 knowledge_points 列表              │   │
│       │     │  │  每项含：kp_title / kp_summary /         │   │
│       │     │  │  key_points / cue_start_idx /            │   │
│       │     │  │  cue_end_idx / start_sec / end_sec       │   │
│       │     │  ├─ content = cue[始..终] 的 text 拼接      │   │
│       │     │  ├─ search_text = kp_title + kp_summary      │   │
│       │     │  │              + ", ".join(key_points)      │   │
│       │     │  └─ embedding = EmbeddingProvider(search)    │   │
│       │     └────────────────────────────────────────┘   │   │
│       │                                                     │
│       │     └─ Fallback：规则窗口（无 .knowledge.json）       │
│       │        按 cue 累积；纯文本 ≥≈400 字 或 跨度 ≥≈45 秒   │
│       │        → kp_title / kp_summary / key_points = ""    │
│       │                                                     │
│       └── ⑤ BM25 随子文档内容重建（force 时全量）              │
│                                                             │
│  # id：                                                      │
│  #   知识点模式：`{course_id}_{section}_kp{kp_index}`         │
│  #   规则窗口：  `{course_id}_{section}_{chunk_index}`        │
│  # parent_id：`{course_id}_{section}_full`                   │
│  # force=True：drop Collection → 全量重建                    │
└─────────────────────────────────────────────────────────────┘
```

## 分块策略

```
带时间戳 md
    │
    ▼
解析 cue 列表 [{t, text}, ...]
    │
    ▼
检查同目录 .knowledge.json
    │
    ├── 存在 ──→ 知识点模式
    │   · 一个 knowledge_point → 一个子文档
    │   · content = 知识点覆盖的全部 cue 文本
    │   · start_sec / end_sec = LLM 确定的边界秒数
    │   · embedding = 对 (kp_title + kp_summary + key_points) 向量化
    │
    └── 不存在 ──→ Fallback 规则窗口
        · 按序累积，先到先切
        · 纯文本长度 ≥ ≈400 字 或 时间跨度 ≥ ≈45 秒
        · 与下一块重叠末 2～3 条 cue
        · 知识点字段留空
```

## 元数据来源

| 字段 | 来源 |
|------|------|
| course_id | `index.json` / 课目录名前缀 |
| chapter | 章目录名 |
| section | 文件名 `CC-LL` |
| title | 文件名标题段 |
| file_type | `md` |
| tags | `module.json` |
| media_path | 相对 `resources/` 的同 stem `.mp4`（无则 `""`） |
| start_sec / end_sec | 知识点：`.knowledge.json`；规则窗口：cue 首/末 |
| kp_title / kp_summary / kp_index / key_points | `.knowledge.json`；无则 `""` / `-1` |
| parent_id | `{course_id}_{section}_full` |
| id | 知识点：`{course_id}_{section}_kp{kp_index}`；规则：`{course_id}_{section}_{i}` |

## 文件处理

| 文件类型 | 处理 | 是否索引 |
|------|------|:--:|
| `.md`（合规 stem + 含 cue） | 解析时间戳行 | ✅ |
| `.knowledge.json`（同 stem） | 优先用于知识点切分 | ✅ |
| `.mp4` | 仅关联路径 | ❌ 不读内容 |
| `.docx` / `.pdf` | 忽略 | ❌ |
