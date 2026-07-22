# 服务生命周期 (src/main.py)

> 状态：已落地 | 最后更新：2026-07-16  
> 总体拓扑见 [总体架构](overview.md)；推理层见 [推理抽象层](inference-services.md)。

## 设计原则

1. **编排与推理实现分离** — 业务只调 Embedding / Rerank Provider；后端由配置选择。
2. **业务侧轻资源加载一次，请求复用** — Graph、Milvus、BM25、MemoryStore；（`local` 时含模型 warmup）。
3. **Fail-fast** — 当前 Provider `ready()` 失败则 `/readyz` 失败，不接流量。

## 开发进程管理（防僵尸进程）

### 背景

本地开发默认命令含 `uvicorn --reload`，进程模型为：

```
Reloader 父进程（WatchFiles）
└── Worker 子进程（FastAPI + Milvus Lite + GPU 模型）
```

在 **Windows** 上若热重载时旧 Worker 未释放 **Milvus Lite 单实例锁**，会出现：

| 现象 | 原因 |
|------|------|
| 新 Worker `Open local milvus failed` | 旧 Worker 仍持有 `db/milvus_lite.db` |
| 父进程已退出、8000 仍被占用 | 子进程变孤儿，继续监听端口 |
| `/readyz` 超时、`CLOSE_WAIT` 堆积 | 半僵死 Worker 不响应 HTTP |

这不是业务代码的进程管理器问题，而是 **开发模式热重载 + 嵌入式 Milvus** 的组合风险。

### 统一脚本 `scripts/dev-services.ps1`

| 命令 | 作用 |
|------|------|
| `.\scripts\dev-services.ps1 status` | 查看 8000 / 5173 / 6380 端口 PID 与 HTTP 探活 |
| `.\scripts\dev-services.ps1 stop` | 按端口 + 进程特征停止后端/前端 |
| `.\scripts\dev-services.ps1 start` | 停占用 → 起 Redis（若未运行）→ 新窗口起 uvicorn + Vite |
| `.\scripts\dev-services.ps1 restart` | `stop` + `start`（**改后端代码后推荐**） |
| `.\scripts\dev-services.ps1 kill-zombies` | 强化清理孤儿 `python.exe`（`spawn_main` worker） |
| `start -Reload` | 显式启用 `--reload`（需热重载时用；出问题就 `restart`） |
| `restart -Redis` | 同时 `docker restart redis-stack` |

**默认 `start` 不带 `--reload`**，避免 Milvus 锁冲突；日常改 Python 后执行 `restart` 即可。

```powershell
cd f:\agent

# 日常
.\scripts\dev-services.ps1 restart

# 怀疑僵尸进程
.\scripts\dev-services.ps1 kill-zombies
.\scripts\dev-services.ps1 start

# 仅查看
.\scripts\dev-services.ps1 status
```

清理逻辑：① `Get-NetTCPConnection` 按端口找 PID → ② 枚举 `python.exe` 命令行含 `src.main:app` / `spawn_main` → ③ 枚举 `node.exe` 命令行含 `vite` 或 `src\ui`。

## 进程外依赖

| 依赖 | 何时需要 |
|------|----------|
| Redis Stack（宿主 **6380**） | 始终（Checkpointer + Store） |
| TEI :8090 / :8091 | 仅 `*_BACKEND=http` |

```powershell
# Redis（示例，与 memory.md 一致）
docker run -d --name redis-stack -p 6380:6379 -p 8002:8001 redis/redis-stack:latest

# 可选 TEI（仅 http 后端）
# docker compose -f docker-compose.inference.yml up -d
```

## 业务 FastAPI 启动清单

```
┌─ lifespan（一次性）──────────────────────────────────────────┐
│                                                              │
│  ① wait_inference_ready()                                    │
│       local → warmup 加载 SentenceTransformer / FlagReranker │
│       http  → 轮询 TEI /health                               │
│       algo  → 初始化哈希向量器                                 │
│  ② MemoryStore → set_store() 全局单例                         │
│  ②.5 sync_course_catalog() → course_modules                  │
│  ②.6 sync_job_catalog() → job_roles + skill_mapping          │
│  ③ Milvus Lite：get_client() + ensure_collection()            │
│  ④ BM25：warmup_bm25()                                       │
│  ⑤ 编译 Supervisor Graph → app.state.graph                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

| 组件 | 模块 | 方式 |
|------|------|------|
| Embedding / Rerank | `vectordb/inference/` | Provider 工厂 |
| MemoryStore | `memory/store.py` | `set_store` / `get_store` |
| 课程目录 | `db/catalog_sync.py` | lifespan `sync_course_catalog` |
| 岗位模板 | `db/job_catalog_sync.py` | lifespan `sync_job_catalog` |
| Milvus | `vectordb/schema.py` | lifespan 触发 |
| BM25 | `vectordb/hybrid_search.py` | `warmup_bm25()` |
| Graph | `agents/supervisor.py` | `build_supervisor_graph()` → `app.state.graph` |

## 请求处理阶段

```
POST /api/chat/
  │
  ├─① SQLite 查学员（存在性校验）
  └─② graph.invoke（复用 app.state.graph）
        │
        ├─ probe：轻量 embed → Milvus Top3；EmotionDetector（唯一）；Store 读上下文
        ├─ decide：业务规则 → 纯闲聊 → LLM
        ├─ dispatch：闲聊短回复 / 子 Agent（QA 完整 retrieve）
        └─ Checkpointer 写回；返回 {content, emotion} 填 ChatResponse
```

| 阶段 | embed() | rerank() |
|------|:-------:|:--------:|
| Probe | 是 | 否 |
| QA `retrieve()` | 是 | 是（除非 `off`） |

## 健康检查

| 端点 | 含义 |
|------|------|
| `GET /` | 进程存活 |
| `GET /readyz` | Graph 已编译 + 当前 Embedding/Rerank Provider ready |

## 耗时日志（排查卡顿）

统一写入 **`logs/perf.log`**（同时打控制台），模块：`src/perf.py`。

| 前缀 | 含义 |
|------|------|
| `startup.*` | 启动各阶段（推理加载、Milvus、BM25、Graph） |
| `api.chat.total` / `api.*` | 单次聊天 API |
| `supervisor.*` | Probe / Decide / Dispatch / invoke |
| `rag.*` | 查询重写、混合检索、重排序、父文档展开 |
| `inference.*` | Embedding/Rerank 加载与推理 |
| `qa.ensure_citations` | QA 强制检索 citations |

查看：`Get-Content f:\agent\logs\perf.log -Tail 80`

## 实现示意（与 `src/main.py` 对齐）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.vectordb.inference import wait_inference_ready
    from src.memory.store import MemoryStore, set_store
    from src.vectordb.schema import get_client, ensure_collection
    from src.vectordb.hybrid_search import warmup_bm25
    from src.agents.supervisor import build_supervisor_graph

    wait_inference_ready(max_wait_s=180.0)  # 同步；按 backend 分支

    set_store(MemoryStore())
    get_client()
    ensure_collection()
    warmup_bm25()
    app.state.graph = build_supervisor_graph()
    yield

app = FastAPI(lifespan=lifespan)
```

## 相关文件

| 文件 | 职责 |
|------|------|
| `src/vectordb/inference/` | Provider 抽象与实现 |
| `src/vectordb/inference_client.py` | 旧 API 兼容转发 |
| `src/main.py` | lifespan + `/readyz` |
| `src/llm/base.py` | `embed()` → EmbeddingProvider |
| `src/vectordb/reranker.py` | → RerankerProvider |
| `docker-compose.inference.yml` | 可选 TEI（http） |
| `src/api/routes.py` | 复用 `app.state.graph` |
| `scripts/dev-services.ps1` | 开发环境启停、僵尸进程清理 |
