# reranker.py — 重排序

> 目标架构：薄封装 → **RerankerProvider**（`http` / `local` / `off`）。详见 [推理抽象层](../inference-services.md)。

```
┌─────────────────────────────────────────────────────────────┐
│                     reranker.py                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  get_reranker().rerank(query, candidates) → list[dict]       │
│     │                                                       │
│     └── RerankerProvider.rerank(...)                        │
│           ├── http  → TEI :8091                             │
│           ├── local → 进程内 CrossEncoder / FlagReranker    │
│           └── off   → 跳过，按混合检索分截断 Top K            │
│                                                             │
│  Fallback：Provider 失败 → 按 _original_score 返回 Top 5     │
└─────────────────────────────────────────────────────────────┘
```

## 位置（RAG 流水线）

```
① 查询重写 → ② 混合检索 Top 20 → ③ Provider 精排 Top 5 → ④ 父文档 / WebSearch
```

仅 **正式答疑** `retrieve()` 走本模块。Supervisor **Probe 轻量探路不调用 Reranker**。

## 为什么需要

混合检索粗排不够准；Cross-Encoder 对 `(问题, 文档)` 精排可提升 Top5 质量。`http` 便于 GPU 常驻与 batching；`local` 便于无 Docker 开发。

## 模型选型（http / local）

| 模型 | 中文效果 | 说明 |
|------|:--:|------|
| BGE-Reranker-v2-m3 | 优 | **选用**，与 BGE-large-zh Embedding 同系 |
| BGE-Reranker-v2-minicpm | 良 | 更快，质量略降 |

## 相关

- [推理抽象层](../inference-services.md)
- [retriever.md](retriever.md)
- [服务生命周期](../service-lifecycle.md)
