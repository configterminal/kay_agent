# AI 助教系统 — 总体架构

> 状态：设计定稿（目标架构） | 最后更新：2026-07-17  
> 本文描述**最新目标架构**。Embedding / Rerank 为**可插拔推理抽象**（http / local / algo），详见 [推理抽象层](inference-services.md)。语音 ASR/TTS 见 [模拟面试多模态](ui/interview-multimodal.md)。

---

## 1. 系统定位

辅助与监测学习状态，个性化调整课程内容，帮助学员从零基础到求职。

| 维度 | 说明 |
|------|------|
| 学员 | 在校生 / 在职人员 |
| 试点领域 | 计算机 / IT |
| 交互 | Vue Web 端 ↔ FastAPI |
| 协作模式 | Supervisor 层级调度 → 6 子 Agent |

---

## 2. 逻辑分层

```
┌─────────────────────────────────────────────────────────────────┐
│  表现层          Vue 3（src/ui）ChatGPT 风格对话界面              │
├─────────────────────────────────────────────────────────────────┤
│  接入层          FastAPI（src/main.py + src/api）                  │
│                  CORS /chat /student /readyz                      │
├─────────────────────────────────────────────────────────────────┤
│  编排层          Supervisor StateGraph（probe→decide→dispatch…） │
│                  QA / Progress / Recommend / JobMatch / …*        │
├─────────────────────────────────────────────────────────────────┤
│  能力层          Tools + Prompt 组装 + Emotion + Schemas          │
├─────────────────────────────────────────────────────────────────┤
│  检索编排        RAG：重写 → 混合检索 → 精排 → 父子文档            │
│                  （业务进程内编排；向量/精排经 Provider）            │
├───────────────┬─────────────────────────┬───────────────────────┤
│  推理抽象层    │  数据与记忆层            │  外部 LLM             │
│  Embedding     │  SQLite / Milvus Lite   │  DeepSeek Chat        │
│  Reranker      │  Redis Stack            │  （OpenAI 兼容）       │
│  Provider      │  （Checkpointer+Store）  │                       │
│  http|local|   │                         │                       │
│  algo          │                         │                       │
└───────────────┴─────────────────────────┴───────────────────────┘

* Interview：文字 + ASR/TTS + **全屏面试场 P0**；**CosyVoice-300M 本机试用通过**。JobMatch / Resume 已接通。
```

**分层原则**：

- **编排与实现分离** — RAG / Agent 只调 `embed()` / `rerank()`；后端由 `EMBEDDING_BACKEND` / `RERANKER_BACKEND` 选择。语音同理：`transcribe()` / `synthesize()`，由 `ASR_BACKEND` / `TTS_BACKEND` 选择。
- **当前默认 `local`（本机 GPU）** — 开发与联调无需 TEI；`http` 为可选外置（TEI），便于日后生产拆分；`algo` 为非神经网络向量化（**不可与 BGE 索引混用**）。
- **数据面就近** — SQLite、Milvus Lite、BM25 索引仍由业务侧管理（MVP 阶段不拆）。

---

## 3. 部署拓扑（当前默认 local；下图为 http 可选形态）

```
                    ┌──────────────┐
  浏览器 ──────────►│ Vue :5173    │
                    └──────┬───────┘
                           │ /api
                    ┌──────▼───────┐
                    │ FastAPI :8000│  业务编排 + Provider 门面
                    │  Graph+RAG   │
                    └──┬───┬───┬───┘
           ┌───────────┘   │   └───────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌──────────────┐
    │ TEI Embed  │  │ TEI Rerank │  │ DeepSeek API  │
    │ :8090      │  │ :8091      │  │（云端 Chat）  │
    │（backend=  │  │（backend=  │  └──────────────┘
    │  http）    │  │  http）    │
    └────────────┘  └────────────┘
           ▲               ▲
           │        ┌──────┴──────┐
           └────────┤ Redis       │  Checkpointer + Store
                    │ Milvus Lite │  向量库
                    │ SQLite      │  学员与进度
                    └─────────────┘
```

`backend=local` 时无 TEI 框，权重在 FastAPI 进程内。`backend=algo` 时无神经网络推理服务。

| 服务 | 端口 | 职责 |
|------|------|------|
| Vue UI | 5173 | 前端 |
| FastAPI | 8000 | 业务 API + Supervisor + Provider |
| TEI Embedding | 8090 | 仅 `EMBEDDING_BACKEND=http` |
| TEI Reranker | 8091 | 仅 `RERANKER_BACKEND=http` |
| Redis Stack | **6380** / **8002** | 记忆 + Insight（宿主映射；容器内仍为 6379/8001） |
| Milvus Lite | 文件库 | 课程向量（BGE 空间） |

启动顺序：**先 Redis** → 再 FastAPI（`local` 时 lifespan 加载 GPU 权重）。仅当 backend=`http` 时需先起 TEI。`/readyz` 按当前 Provider `ready()` 判定。

---

## 4. 请求主链路

```
学员消息
    │
    ▼
POST /api/chat/ 或 /api/chat/stream  { thread_id, message, selected_option_id? }
    │
    ├─① SQLite 查学员（存在性校验）
    │
    └─② Supervisor.graph.invoke（启动时编译，请求复用）
            │     Checkpointer key = 请求中的 thread_id（每会话独立状态）
            │     stream 时：probe/decide/dispatch → status；Agent LLM → token；结束 → done
            │
            ├─ probe
            │     · 轻量向量探路 Top3（不 rewrite、不 rerank）
            │     · embed() → 当前 EmbeddingProvider
            │     · EmotionDetector.detect（全链路唯一一次）
            │     · Store 读 coach_style / weak_areas / thread 摘要
            │
            ├─ decide
            │     · ⓪ 本线程 pending_options 选号（点击/手输）→ 粘性路由
            │     · ① 业务确定性规则 → ② 纯闲聊收窄 → ③ LLM 路由
            │     · 单意图必须带 task_queue.input（学员原话或改写后的选项）
            │
            ├─ dispatch
            │     · 闲聊 → Supervisor 短回复
            │     · 否则 → 子 Agent（QA 走完整 RAG，消费 state.emotion）
            │     · 回复含编号列表 → 写入本线程 pending_options，经 options 回传前端
            │
            ├─ aggregate / recovery
            │
            └─ final_response
                    │
                    ▼
            run_supervisor → {content, emotion, options} → ChatResponse / SSE done
```

> 会话隔离详见 [Supervisor § 会话隔离与结构化选项](agents/supervisor.md)。

**检索两次成本的约定**：

| 阶段 | 检索深度 | 是否 Rerank |
|------|----------|-------------|
| Probe | 单 query 向量 Top3 | 否 |
| QA `retrieve()` | 重写 + 混合 + 精排 + 父文档 | 是（除非 `RERANKER_BACKEND=off`） |

---

## 5. Agent 与路由

### 5.1 层级关系

```
                    Supervisor
         ┌─────┬─────┼─────┬──────┬──────┐
         ▼     ▼     ▼     ▼      ▼      ▼
        QA  Progress Rec  JobMatch  Resume  Interview*
```

已实现：QA、Progress、Recommend、JobMatch、Resume、Interview（文字 + 全屏语音面试场 P0）。

### 5.2 Decide 优先级（业务优先闲聊分流）

1. 业务确定性规则 + QA 疑问模式  
2. 纯闲聊（整句 / 去问候壳后无实质内容）  
3. LLM 结构化多意图路由  
4. 禁止：子串命中「你好」就短路整句  

详见 [Supervisor](agents/supervisor.md)。

---

## 6. RAG 与推理边界

```
业务进程内编排                      Embedding / Rerank Provider
─────────────────                   ──────────────────────────
query_rewriter (LLM)
hybrid_search ──embed()──────────►  http | local | algo
retriever ──────rerank()─────────►  http | local | off
父子文档回查
```

- **索引**：`indexer` 经同一 EmbeddingProvider；**写入 BGE collection 时只能用与建索引时相同空间的后端**（通常 `http`/`local` + 同模型）。  
- **algo**：禁止混入现网 BGE collection。详见 [推理抽象层](inference-services.md)。  
- 专题：[RAG 总览](rag/index.md)。

---

## 7. 记忆与状态

| 层 | 实现 | 用途 |
|----|------|------|
| 短期 | LangGraph `RedisSaver` | 对话与图状态，按请求 `thread_id`（每会话独立） |
| 长期 | MemoryStore（RedisJSON + RediSearch） | weak_areas、preferences、**summaries（按 thread 滚动摘要）** 等 |
| 结构化 | SQLite ORM（9 表） | 学员、进度、测验、问答历史、情绪记录等 |

**上下文预算**：Checkpointer 可存全量原文；进子 Agent / LLM 须为「Store.summaries + 近窗」，禁止全量 `messages`。详见 [记忆系统 · 上下文预算](memory.md)。

Checkpointer 要求 `dispatch` 写回 `AIMessage`，否则近窗与断点恢复不完整。

---

## 8. 服务生命周期（目标）

**业务 FastAPI 启动（一次性）**

1. 按 backend：`http` 则等 TEI；`local`/`algo` 则 `warmup()`  
2. 初始化 MemoryStore 单例、Milvus Collection、BM25 warmup  
3. 编译 Supervisor Graph → `app.state.graph`  
4. `/readyz` 就绪  

**请求期**：Graph 复用；每次检索付 Provider 推理成本（http 不付加载；local 加载在启动期）。

**关闭**：释放 Redis 等；TEI（若使用）由 Docker 独立生命周期管理。

详见 [服务生命周期](service-lifecycle.md)。

---

## 9. 技术栈一览

| 类别 | 选型 |
|------|------|
| 语言 / 包管理 | Python 3.13、Poetry |
| Agent | LangGraph StateGraph + ReAct 子 Agent |
| Chat LLM | DeepSeek Chat（OpenAI 兼容） |
| Embedding / Rerank | **可插拔 Provider**：http(TEI) / local / algo |
| ASR / TTS | **可插拔** `src/speech/`：SenseVoice + Edge；可选 **CosyVoice-300M sidecar**（已本机试用） |
| 向量库 | Milvus Lite（生产可迁 Docker Milvus） |
| 记忆 | Redis Stack |
| 业务 DB | SQLite + SQLAlchemy |
| API / UI | FastAPI、Vue 3 |
| 部署 | Docker Compose（Redis；TEI 可选） |

---

## 10. 实现状态（相对本架构）

| 能力 | 状态 |
|------|------|
| Supervisor + 闲聊分流 + task_queue.input | 已实现 |
| QA / Progress / Recommend | 已实现 |
| RAG 编排流水线 | 已实现 |
| Graph 启动编译复用 | 已实现 |
| MemoryStore / BM25 / Milvus 预热 | 已实现 |
| **可插拔 Provider（http / local / algo）** | **已落地**；`.env` 默认 **local** |
| Probe 轻量化（无 rewrite / 无 rerank） | 已落地 |
| `/readyz` 按 backend 分支 | 已落地 |
| 会话隔离 thread_id + pending_options（可点/手输） | 已落地 |
| 上下文预算（summaries + 近窗，禁全量进 Agent） | 已落地 |
| InterviewAgent（文字）+ speech API + 全屏面试场 P0 | **已落地并联调**；DEBUG 仅开发态；**Cosy 300M 本机试用通过** |
| HTTP TEI 生产化（Windows CPU） | 实验中，暂不作为默认 |

---

## 11. 文档索引

| 文档 | 内容 |
|------|------|
| [本页 overview](overview.md) | 总体架构 |
| [推理抽象层](inference-services.md) | Provider、http/local/algo、配置 |
| [服务生命周期](service-lifecycle.md) | 启动 / 请求 / 关闭 |
| [Supervisor](agents/supervisor.md) | 路由、闲聊分流、多意图 |
| [RAG](rag/index.md) | 检索流水线 |
| [记忆](memory.md) | Checkpointer + Store |
| [需求](../requirements.md) | 产品与功能需求 |

---

## 12. 演进路线（刻意不做）

当前 **不做**：Triton/K8s、独立 Retrieval 微服务、查询语义缓存、把 Milvus/BM25 再拆服务、BGE 与 algo 混索引。  
等 QPS / 多卡调度成为瓶颈后再进入更重的推理调度档。
