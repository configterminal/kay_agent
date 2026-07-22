# QAAgent 工具 (src/tools/qa_tools.py)

```
┌─────────────────────────────────────────────────────────────┐
│                   tools/qa_tools.py                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  search_course_content(query: str, top_k: int = 5)          │
│       → list[{content, source, score, section, title,       │
│               start_sec, end_sec, media_path, ...}]         │
│       │                                                     │
│       └── 调用 retriever.retrieve(query, chat_history)       │
│           完整 RAG：查询重写→混合检索→RerankerProvider→父子文档 │
│           跳转字段供编排层抽成 citations（见 ui/video-jump）   │
│                                                             │
│  get_lesson_content(module_id: str, lesson_id: str) → str   │
│       │                                                     │
│       └── 从 Milvus 按 parent_id 查询父文档完整内容          │
│           用于学员追问时加载整节课原文                         │
│                                                             │
│  get_qa_history(student_id: int, limit: int = 10)            │
│       → list[{question, answer, created_at}]                 │
│       │                                                     │
│       └── 从 SQLite qa_history 表查询                         │
│           用于追问理解：Agent 知道学员刚才问了什么             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 三个工具的依赖

| 工具 | 依赖 | 状态 |
|------|------|:--:|
| `search_course_content` | `src.vectordb.retriever.retrieve` | ✅ |
| `get_lesson_content` | Milvus 按 parent_id 查询 | ✅ |
| `get_qa_history` | SQLite `qa_history` 表 | ✅ |

全部依赖已有模块，工具层是薄封装。

## 与 QAAgent 的配合

```python
# Agent 调用流程：
tools = [search_course_content, get_lesson_content, get_qa_history]

# 学员问"RAG是什么"
# Agent 调 search_course_content("RAG是什么") → 拿到 Top 5 文档
# Agent 用返回内容 + 问题 → LLM 生成回答
# 学员追问 → Agent 调 get_qa_history 查历史 → 知道"RAG"是刚才的话题
# 学员要看整节内容 → Agent 调 get_lesson_content("RAG101", "2-3") → 返回全文
```
