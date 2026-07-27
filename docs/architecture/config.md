# 配置中心 (config.py)

```
                    .env 文件
                       │
                       ▼
                  config.py
                  ┌─────────────────────────────────┐
                  │  load_dotenv()                   │
                  │  Settings（全局单例）             │
                  │  ├─ llm_provider                 │
                  │  ├─ deepseek / openai / …        │
                  │  ├─ redis / sqlite / milvus      │
                  │  ├─ neo4j                        │  ← 图数据库配置
                  │  ├─ embedding                    │  ← model / dimension
                  │  ├─ inference                    │  ← backend + URL 等
                  │  ├─ context_budget               │  ← summaries / 近窗 token 预算
                  │  └─ speech                       │  ← ASR / TTS 配置
                  │       embedding_backend          │
                  │       reranker_backend           │
                  │       embedding_base_url         │
                  │       reranker_base_url          │
                  │       timeout / algo_*           │
                  │  get_llm_config()                │
                  └─────────────────────────────────┘
                       │
                       ▼
              from src.config import config
```

## 推理相关环境变量

| 变量 | 说明 |
|------|------|
| `EMBEDDING_BACKEND` | `local` \| `http` \| `algo`（**默认 `local`**） |
| `RERANKER_BACKEND` | `local` \| `http` \| `off`（**默认 `local`**） |
| `EMBEDDING_BASE_URL` | 仅 http：如 `http://localhost:8090` |
| `RERANKER_BASE_URL` | 仅 http：如 `http://localhost:8091` |
| `RERANKER_MODEL` | local 精排模型，默认 `BAAI/bge-reranker-v2-m3` |
| `INFERENCE_TIMEOUT_S` | HTTP 超时秒数 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | 稠密模型标识与索引维 |
| `ALGO_EMBEDDING_METHOD` / `ALGO_EMBEDDING_DIM` | 仅 algo |
| `REDIS_PORT` | 宿主端口，本机为 **6380** |

Web UI 为 Vue 3（`src/ui`），不再使用 Gradio 配置项作为主路径。

详见 [推理抽象层](inference-services.md)、[总体架构](overview.md)。
