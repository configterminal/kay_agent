# AI 助教系统 — 总体架构

> 状态：设计定稿（目标架构） | 最后更新：2026-07-24  
> 本文描述**最新目标架构**。Embedding / Rerank 为**可插拔推理抽象**（http / local / algo），详见 [推理抽象层](inference-services.md)。语音 ASR/TTS 见 [模拟面试多模态](ui/interview-multimodal.md)；聊天语音 I/O 见 [Web UI](ui/index.md)。

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
│                  语音 I/O：🎤 麦克风录音 + 🔊 TTS 朗读              │
├─────────────────────────────────────────────────────────────────┤
│  接入层          FastAPI（src/main.py + src/api）                  │
│                  CORS /chat /chat/stream /student /readyz          │
│                  + 语音端点：/interview/asr /interview/tts          │
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
│  ASR/TTS       │  （Checkpointer+Store）  │                       │
│  Provider      │                         │                       │
│  http|local|   │                         │                       │
│  algo          │                         │                       │
└───────────────┴─────────────────────────┴───────────────────────┘

* Interview：文字 + ASR/TTS + **全屏面试场 P0**；**CosyVoice-300M 本机试用通过**。
  聊天语音：🎤 录音→ASR→输入框 + 回复→TTS→自动朗读（[Web UI](ui/index.md)）。
  JobMatch / Resume 已接通。
```

**分层原则**：

- **编排与实现分离** — RAG / Agent 只调 `embed()` / `rerank()`；后端由 `EMBEDDING_BACKEND` / `RERANKER_BACKEND` 选择。语音同理：`transcribe()` / `synthesize()`，由 `ASR_BACKEND` / `TTS_BACKEND` 选择。
- **语音 I/O 是适配层** — 聊天语音（`useVoiceChat`）不侵入对话逻辑：🎤 输入经 ASR 转文字送入 LLM；LLM 回复经 TTS 朗读。语音模式开关仅控制输入方式 + 输出是否自动朗读，文字通道不变。
- **当前默认 `local`（本机 GPU）** — 开发与联调无需 TEI；`http` 为可选外置（TEI），便于日后生产拆分；`algo` 为非神经网络向量化（**不可与 BGE 索引混用**）。
- **数据面就近** — SQLite、Milvus Lite、BM25 索引仍由业务侧管理（MVP 阶段不拆）。

---

## 3. 部署拓扑（当前默认 local；下图为 http 可选形态）

```
                    ┌──────────────┐
  浏览器 ──────────►│ Vue :5173    │  语音 I/O：🎤 → ASR / TTS → 🔊
                    └──────┬───────┘
                           │ /api
                    ┌──────▼───────┐
                    │ FastAPI :8000│  业务编排 + Provider 门面
                    │  Graph+RAG   │  + speech ASR/TTS 端点
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
           ┌────────┤ Milvus Lite │  向量库
           │        │ SQLite      │  学员与进度
           │        └─────────────┘
           │
    ┌──────┴──────┐
    │ CosyVoice   │  TTS sidecar（可选；conda 环境 :8092）
    │ SenseVoice  │  ASR 本地 GPU
    │ Edge TTS     │  TTS 兜底（免费在线）
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

## 4. 请求主链路（文字模式）

```
学员消息（键盘输入）
    │
    ▼
POST /api/chat/stream  { thread_id, message, voice_mode: false }
    │
    ├─① SQLite 查学员（存在性校验）
    │
    └─② Supervisor.graph.invoke（启动时编译，请求复用）
            │     Checkpointer key = 请求中的 thread_id（每会话独立状态）
            │     stream 时：probe/decide/dispatch → status；Agent LLM → token；结束 → done
            │
            ├─ probe（与语音模式相同）
            │
            ├─ decide（与语音模式相同）
            │
            ├─ dispatch
            │     · voice_mode=false → 路由到 qa_text 节点
            │     · QA 走完整 RAG，System Prompt = QA_ROLE_PROMPT（允许 Markdown / 列表 / Emoji）
            │     · 回复含编号列表 → 写入本线程 pending_options，经 options 回传前端
            │
            ├─ aggregate / recovery
            │
            └─ final_response
                    │
                    ▼
            run_supervisor → {content, emotion, options} → ChatResponse / SSE done
```

## 4a. 请求主链路（语音模式）

## 4a. 请求主链路（语音模式）

```
学员消息（🎤 录音 → ASR 转文字 / 键盘输入）
    │
    ▼
POST /api/chat/stream  { thread_id, message, voice_mode: true }
    │
    ├─① SQLite 查学员
    │
    └─② Supervisor.graph.invoke（initial_state.voice_mode = True）
            │
            ├─ probe / decide（与文字模式相同）
            │
            ├─ dispatch
            │     · voice_mode=true → 路由到 qa_voice 节点
            │     · qa_voice 与 qa_text 共用同一套工具和检索逻辑，仅 System Prompt 不同
            │       （QA_ROLE_PROMPT_VOICE = QA_ROLE_PROMPT 基础上追加语音输出规范）
            │     · LLM 直接输出口语：无 Markdown、无 Emoji、无表格、短句、数字口语化
            │     · 其他 Agent（Progress/Recommend/…）：不受影响，始终走文字 prompt
            │
            └─ final_response
                    │
                    ▼
            SSE done { voice_mode: true, content: "口语文本" }
                    │
                    ▼
            前端 ttsSpeak(content) → 直接送 /interview/tts → 浏览器 Audio 播放
            （不做 stripForSpeech 清洗——口语转换是 LLM 的职责）
```

**语音模式 vs 文字模式 — 唯一区别**：dispatch 时根据 `voice_mode` 路由到不同 QA 节点。

| 对比 | 文字模式 | 语音模式 |
|------|---------|---------|
| QA 节点 | `qa_text` | `qa_voice` |
| System Prompt | `QA_ROLE_PROMPT` | `QA_ROLE_PROMPT_VOICE` |
| 工具/检索 | 共用 | 共用 |
| LLM 输出 | Markdown / 列表 / Emoji | 自然口语 / 无标记 / 数字口语化 |
| 前端处理 | 渲染 Markdown | 直接送 TTS（不额外清洗） |
| TTS 朗读 | 手动点 🔈 | 自动朗读 |

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
         ┌─────┬─────┼─────┬──────┬──────┬──────┐
         ▼     ▼     ▼     ▼      ▼      ▼      ▼
      qa_text qa_voice Progress Rec  JobMatch Resume Interview*
         │     │
         └──┬──┘
        共用工具 + 检索逻辑；仅 System Prompt 不同
```

QA Agent 分两个编译节点（`qa_text` / `qa_voice`），dispatch 时根据 `state.voice_mode` 路由。二者共用同一套工具函数和 RAG 检索流水线，仅 System Prompt 不同——`qa_voice` 的输出规范要求 LLM 直接输出适合 TTS 朗读的自然口语。

已实现：QA（两节点）、Progress、Recommend、JobMatch、Resume、Interview（文字 + 全屏语音面试场 P0）。

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
| 聊天语音 I/O（🎤→ASR→输入框 / 回复→TTS→朗读） | **已落地**；`useVoiceChat` 全局单例；复用面试 ASR/TTS 端点；语音模式一键切换 |
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
