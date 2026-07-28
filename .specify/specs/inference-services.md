# 推理抽象层（Embedding / Reranker）

> 状态：已落地 | 最后更新：2026-07-15  
> 总体关系见 [总体架构](overview.md)；启动顺序见 [服务生命周期](service-lifecycle.md)。

## 1. 目标

Embedding / Rerank **不再绑死某一种部署方式**。业务只依赖统一接口；具体实现由配置选择：

| 后端 | Embedding | Rerank | 典型场景 |
|------|:---------:|:------:|----------|
| `local` | ✅ SentenceTransformer（GPU 优先） | ✅ FlagReranker（GPU 优先） | **当前默认**：本机联调 |
| `http` | ✅ TEI `/embed` | ✅ TEI `/rerank` | 可选外置；生产拆分时启用 |
| `algo` | ✅ 算法向量化（非神经网络） | ❌（用 `off`） | 兜底 / 实验；不可混入 BGE 索引 |

**原则**：编排与「如何得到向量 / 分数」解耦；换后端不改 `hybrid_search` / `retriever` / Probe 调用点。

---

## 2. 模块边界

```
业务调用方
  indexer / hybrid_search / probe / DeepSeekProvider.embed() / get_reranker()
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  src/vectordb/inference/                                  │
│                                                           │
│  get_embedding_provider() / get_reranker_provider()       │
│  EmbeddingProvider.embed / ready / warmup                 │
│  RerankerProvider.rerank / ready / warmup                 │
└─────────────────────────────┬─────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   Http* (http_backend)  Local* (local_backend)  Algo (algo_backend)
   TEI HTTP               进程内 GPU/CPU          hashing
```

`inference_client.py` 仅为旧 API 兼容转发，新代码请直接 `from src.vectordb.inference import ...`。

---

## 3. 接口约定

```python
class EmbeddingProvider(Protocol):
    name: str                    # "http" | "local" | "algo"
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def ready(self) -> tuple[bool, str]: ...
    def warmup(self) -> None: ...


class RerankerProvider(Protocol):
    name: str                    # "http" | "local" | "off"

    def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]: ...
    def ready(self) -> tuple[bool, str]: ...
    def warmup(self) -> None: ...
```

```python
emb = get_embedding_provider()   # 读 EMBEDDING_BACKEND
rer = get_reranker_provider()    # 读 RERANKER_BACKEND
```

`DeepSeekProvider.embed()`、`get_reranker().rerank()` 委托上述工厂。

---

## 4. 各后端说明

### 4.1 `local`（当前默认）

- Embedding：`SentenceTransformer(config.embedding.model)`，device=`cuda`（若可用）。
- Rerank：`FlagReranker(config.inference.reranker_model)`，`use_fp16` 随 CUDA。
- lifespan 调用 `wait_inference_ready()` → 内部 `warmup()` 加载权重。
- 多 worker 时每进程一份权重。

### 4.2 `http`（TEI，可选）

| 服务 | 端口 | 模型约定 | 协议 |
|------|------|----------|------|
| TEI Embedding | 8090 | 与 `EMBEDDING_MODEL` 对齐（可用本地 ONNX 挂载） | `POST /embed` |
| TEI Reranker | 8091 | 与 `RERANKER_MODEL` 对齐；compose 实验镜像可能降级为 `bge-reranker-base` | `POST /rerank` |

- **仅此模式下**权重在容器内、业务进程不加载 BGE。
- Windows CPU TEI 兼容性仍不稳，**暂不作为默认**。
- 部署：`docker compose -f docker-compose.inference.yml up -d`，且 `.env` 改为 `http`。

### 4.3 `algo`（算法向量化）

当前实现：`hashing` 特征哈希（`ALGO_EMBEDDING_METHOD` / `ALGO_EMBEDDING_DIM`）。

**硬约束**：

1. 与 `bge-large-zh` **不同向量空间**，**不得**写入现网 BGE collection 并混搜（实现侧防护待补；运维须遵守）。
2. Rerank 无 `algo`；配合 `RERANKER_BACKEND=off` 或 http/local。

---

## 5. 配置

| 变量 | 示例 | 说明 |
|------|------|------|
| `EMBEDDING_BACKEND` | `local` \| `http` \| `algo` | **默认 `local`** |
| `RERANKER_BACKEND` | `local` \| `http` \| `off` | **默认 `local`** |
| `EMBEDDING_MODEL` | `BAAI/bge-large-zh-v1.5` | local 加载 / http 语义对齐 |
| `EMBEDDING_DIMENSION` | `1024` | 稠密索引维 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | local FlagReranker |
| `EMBEDDING_BASE_URL` | `http://localhost:8090` | 仅 `http` |
| `RERANKER_BASE_URL` | `http://localhost:8091` | 仅 `http` |
| `INFERENCE_TIMEOUT_S` | `30` | HTTP 超时 |
| `ALGO_EMBEDDING_METHOD` | `hashing` | 仅 `algo` |
| `ALGO_EMBEDDING_DIM` | `1024` | 算法输出维 |

当前 `.env`（联调）：

```env
EMBEDDING_BACKEND=local
RERANKER_BACKEND=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

可选切 HTTP：

```env
EMBEDDING_BACKEND=http
RERANKER_BACKEND=http
EMBEDDING_BASE_URL=http://localhost:8090
RERANKER_BASE_URL=http://localhost:8091
```

---

## 6. 与 RAG / 生命周期的关系

```
业务进程内编排                         Provider（可插拔）
─────────────────                      ────────────────
query_rewriter (LLM)
hybrid_search ──embed()─────────────►  local | http | algo
retriever ──────rerank()────────────►  local | http | off
indexer ────────embed()─────────────►  须与 collection 空间一致
probe ──────────embed()─────────────►  轻量；同正式检索后端
```

| 场景 | Embedding | Rerank | `/readyz` |
|------|-----------|--------|-----------|
| 当前联调 | `local` | `local` | GPU warmup 成功 |
| 外置 TEI | `http` | `http` | TEI health |
| 无精排 | `local`/`http` | `off` | embed ready |
| 算法实验 | `algo` | `off` | **勿写 BGE collection** |

---

## 7. 代码落点

| 路径 | 职责 |
|------|------|
| `src/vectordb/inference/base.py` | Protocol / `InferenceError` |
| `src/vectordb/inference/registry.py` | 工厂、单例、`wait_inference_ready` |
| `src/vectordb/inference/http_backend.py` | TEI HTTP |
| `src/vectordb/inference/local_backend.py` | local + `OffRerankerProvider` |
| `src/vectordb/inference/algo_backend.py` | hashing |
| `src/vectordb/reranker.py` | 文档列表外壳 → Provider |
| `src/vectordb/inference_client.py` | 兼容旧 `embed_texts` / `rerank_texts` |
| `src/llm/base.py` `embed()` | → `get_embedding_provider()` |
| `src/config.py` | backend 与相关环境变量 |

---

## 8. 明确不做（本阶段）

- 不上 Triton / K8s。
- 不把 Milvus / BM25 拆成独立微服务。
- 不在同一 Milvus collection 混用 BGE 与 algo。
- 不为 algo 伪造与 BGE 可互换的语义。

---

## 9. 实现状态

| 项 | 状态 |
|----|------|
| 可插拔架构 | 本文 + 代码 |
| Registry + http / local / algo | **已落地** |
| 默认 backend | **`local` / `local`** |
| `/readyz` 按 backend | **已落地** |
| HTTP TEI 生产化 | 暂缓（Windows CPU 兼容问题） |
| algo 写入拦截 | 待补代码防护 |
