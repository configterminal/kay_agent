# retriever.py — RAG 检索器（流水线主控）

```
┌─────────────────────────────────────────────────────────────┐
│                     retriever.py                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  retrieve(query, chat_history=None) → list[dict]             │
│       │                                                     │
│       │  QAAgent 的 search_course_content 工具内部调这个      │
│       │                                                     │
│       ├── ① 查询重写                                         │
│       │     query_rewriter.rewrite_query(query, history)     │
│       │     → 1~3 条优化查询                                  │
│       │                                                     │
│       ├── ② 混合检索                                         │
│       │     hybrid_search.hybrid_search(queries, top_k=50)   │
│       │     → Top 20 候选文档                                │
│       │                                                     │
│       ├── ③ 重排序                                           │
│       │     reranker.rerank(query, candidates, top_k=5)      │
│       │     → Top 5 精排文档                                  │
│       │                                                     │
│       ├── ④ 结果处理                                         │
│       │     ┌──────────────────────────────────────────┐    │
│       │     │ 对每条 Top 5 文档：                        │    │
│       │     │   parent_id → 查 Milvus 取父文档完整内容   │    │
│       │     │                                            │    │
│       │     │ 得分 ≥ 阈值：                               │    │
│       │     │   → 返回 content/source/score + 跳转字段   │    │
│       │     │   source 可带 @M:SS（有 start_sec 时）       │    │
│       │     │   start_sec / end_sec / media_path 透传     │    │
│       │     │                                            │    │
│       │     │ 得分 < 阈值 或无结果：                       │    │
│       │     │   → WebSearch 兜底                          │    │
│       │     │   source = "网络搜索（非课程内容）"          │    │
│       │     └──────────────────────────────────────────┘    │
│       │                                                     │
│       └── 返回：[{content, source, score, start_sec, ...}] │
│                                                             │
│  # 精排：RerankerProvider（http / local / off）                  │
│  # Probe 轻量探路不走本流水线（无 rewrite / 无 rerank）         │
│  # WebSearch 兜底后续实现，当前降级到"无相关内容"              │
└─────────────────────────────────────────────────────────────┘
```

## 与推理抽象层边界

| 步骤 | 执行位置 |
|------|----------|
| 查询重写 | 业务进程 + DeepSeek |
| 向量化 query | **EmbeddingProvider**（http / local / algo） |
| Milvus / BM25 / RRF | 业务进程 |
| 精排 | **RerankerProvider**（http / local / off） |
| 父文档回查 | 业务进程 + Milvus |

## 流水线串联

```python
# ① 查询重写
queries = rewrite_query(raw_query, chat_history)

# ② 混合检索
candidates = hybrid_search(queries, top_k=50)

# ③ 重排序
top5 = reranker.rerank(raw_query, candidates, top_k=5)

# ④ 结果处理
for doc in top5:
    parent = get_parent_document(doc["parent_id"])
    yield {"content": parent, "source": format_source(doc), "score": doc["rerank_score"]}
```

## Fallback 策略

| 环节 | 失败处理 |
|------|------|
| 查询重写 | LLM 失败 → 用原始 query |
| 混合检索 | 全部无结果 → 返回空列表 |
| 重排序 | 模型失败 → 按原始分数排 |
| 全部无结果 | → WebSearch 兜底（后续实现） |

## 返回值

```python
[{
    "content": "完整父文档内容（整节去时间戳纯文本）",
    "source": "课程《RAG全栈技术从基础到精通》第02章 第02-03节《解锁RAG三大核心》 @1:05",
    "score": 0.94,
    "section": "02-03",
    "title": "解锁RAG三大核心",
    "start_sec": 65,          # 知识点起点（有 knowledge.json）或窗口起点（fallback）
    "end_sec": 110,
    "media_path": "courses/RAG101 RAG全栈技术从基础到精通/02 .../02-03 解锁RAG三大核心.mp4",
    "is_web_search": False,
    "kp_title": "RAG三大核心的组成与作用",       # 知识点标题；规则窗口为 ""
    "kp_summary": "讲解知识库、检索、大语言模型三部分如何协作",  # 知识点摘要
    "kp_index": 0,                              # 节内序号；规则窗口为 -1
    "key_points": "知识库存储企业数据, 检索找到相关信息, 大模型生成答案",  # 逗号分隔
}, ...]
```

> 跳转字段已由检索透传；编排出口 → API → 前端 seek 见 [ui/video-jump.md](../ui/video-jump.md)。
> 知识点字段来自 [知识切分 Skill](../../../skills/knowledge-split/SKILL.md)；无 `.knowledge.json` 的节这些字段留空/置 -1。
