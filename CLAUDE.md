# CLAUDE.md

## 项目简介

AI 助教系统 — 辅助和监测学生学习状态，个性化调整课程内容，帮助学员从零基础到找到心仪工作。

## 环境要求

| 组件 | 最低版本 | 当前版本 | 位置 |
|------|---------|---------|------|
| Python | 3.13 | 3.13.12 | `f:\agent\.venv\` |
| LangChain | ≥0.3 | 1.3.13 | `f:\jupyter\` |
| LangGraph | ≥0.3 | 1.2.9 | `f:\jupyter\` |
| Poetry | ≥2.1 | 2.4.1 | 全局 |
| Docker | ≥27.5.1 | 4.81.0 | 全局 |
| docker-compose | ≥2.32 | Docker Desktop 自带 | 全局 |
| Pydantic | ≥2.10.6 | 2.13.4 | `f:\jupyter\` |
| qdrant-client | ≥1.12 | 1.12.0 | `f:\jupyter\` |
| Redis | ≥7.4.2 | 7.4.2 (Redis Stack) | Docker |
| dingtalk-stream | ≥0.22 | 暂缓安装 | — |

## 环境配置详解

### 虚拟环境

```
位置:   f:\agent\.venv\
Python: 3.13.12
来源:   F:\miniconda3\python.exe -m venv
激活:   & f:\agent\.venv\Scripts\Activate.ps1
```

### 共享包目录

```
位置:   f:\jupyter\
说明:   所有第三方包通过 pip install --target f:\jupyter 安装到此目录
链接:   f:\agent\.venv\Lib\site-packages\jupyter-pkgs.pth 中写入 f:\jupyter
        使得 venv 中的 Python 可以直接 import f:\jupyter 下的所有包
```

### 环境变量

```
文件:   f:\agent\.env
内容:   DEEPSEEK_API_KEY=sk-xxx；HF_HOME / PIP_CACHE_DIR 等指向 F:\agent\.cache
加载:   load_dotenv(Path(__file__).parent / ".env")
安全:   .gitignore 已排除 .env、.cache/、tmp/、tei-data/、models/
```

### 大文件缓存（勿放 C:）

```
HF 模型缓存:   f:\agent\.cache\huggingface  （C: 用户目录 junction → 此处）
pip 缓存:      f:\agent\.cache\pip
临时目录:      f:\agent\tmp
TEI 本地 ONNX: f:\agent\models\
TEI 运行数据:  f:\agent\tei-data\
```

### LLM 配置

```
Provider: DeepSeek Chat
接口:    OpenAI 兼容 (langchain_openai.ChatOpenAI)
Base URL: https://api.deepseek.com/v1
Model:   deepseek-chat
API Key: 从 .env 读取 DEEPSEEK_API_KEY
```

### Redis

```
版本:   7.4.2 (Redis Stack)
方式:   Docker 容器 (redis-stack)
端口:   宿主 6380→6379 (Redis), 8002→8001 (RedisInsight)
启动:   docker run -d --name redis-stack -p 6380:6379 -p 8002:8001 redis/redis-stack:latest
客户端: redis-py（f:\jupyter\）；.env 中 REDIS_PORT=6380
```

### Docker

```
版本:   4.81.0 (Docker Desktop)
安装:   winget install Docker.DockerDesktop
前提:   需安装 WSL 2 (wsl --install)
注意:   安装后需重启电脑才能使用
数据盘: F:\Docker\wsl （C: AppData\Local\Docker\wsl 为 junction → 此处，避免占满 C:）
崩溃转储: F:\WSL\wsl-crashes（见 %USERPROFILE%\.wslconfig 的 crashDumpFolder；C: Temp\wsl-crashes 为 junction）
用户 TEMP/TMP: F:\agent\tmp
```

### Poetry

```
版本:   2.4.1
安装:   pip install poetry (全局)
使用:   cd f:\agent && poetry init / poetry add <pkg>
```

### LangChain 全家桶

```
位置:   f:\jupyter\
langchain:           1.3.13
langchain-core:      1.4.9
langchain-classic:   1.0.8
langchain-community: 0.4.2
langchain-openai:    1.3.5
langchain-text-splitters: 1.1.2
langgraph:           1.2.9
langgraph-checkpoint: 4.1.1
langgraph-prebuilt:  1.1.0
```

### Milvus

```
位置:   f:\jupyter\
版本:   pymilvus（Milvus Lite）
模式:   本地文件持久化（milvus_lite），生产可切换 Milvus Server
```

### Pydantic

```
版本:   2.13.4 (f:\jupyter\)
注意:   qdrant-client 依赖 pydantic>=1.10.8，兼容
关键模块: pydantic-core 2.27.2 (cp313-win_amd64)
```

### 钉钉

```
目标:   dingtalk-stream >=0.22
状态:   暂缓安装
```

## 常用命令

### 激活虚拟环境
```powershell
& f:\agent\.venv\Scripts\Activate.ps1
```

### 运行当前项目
```powershell
# 推荐：统一脚本（防僵尸进程）
cd f:\agent
.\scripts\dev-services.ps1 restart

# 手动（等价于 start，默认无 --reload）
& f:\agent\.venv\Scripts\Activate.ps1
& f:\agent\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
# 另开终端：cd f:\agent\src\ui && npm run dev

# 需要热重载时（出问题请 restart）
.\scripts\dev-services.ps1 start -Reload
```

### 安装新包
```powershell
pip install <package> --target f:\jupyter
```

### Docker Redis Stack
```powershell
docker run -d --name redis-stack -p 6380:6379 -p 8002:8001 redis/redis-stack:latest
```

### Poetry 使用
```powershell
# 在项目目录初始化
cd f:\agent
poetry init
poetry add <package>
```

## 项目文件结构

```
f:/agent/
├── .env                    # DeepSeek API Key（不提交）
├── .gitignore
├── CLAUDE.md               # 本文件
├── README.md
├── docs/
│   ├── requirements.md     # 需求与架构文档
│   └── architecture/       # 架构设计图
│       ├── index.md        # 目录索引
│       ├── overview.md     # 总体架构（入口必读）
│       ├── inference-services.md  # Embedding/Rerank 可插拔（http/local/algo）
│       ├── service-lifecycle.md   # 服务生命周期
│       ├── config.md       # 配置中心设计图
│       ├── llm.md          # LLM 抽象层设计图
│       ├── database.md     # 数据库设计图
│       ├── memory.md       # 记忆系统设计图
│       ├── emotion.md      # 情感系统设计图
│       ├── rag/            # RAG 系统设计图
│       │   ├── index.md    # 传统 RAG 完整架构
│       │   ├── schema.md   # Milvus Schema
│       │   ├── query-rewriter.md  # 查询重写
│       │   ├── hybrid-search.md   # 混合检索
│       │   ├── reranker.md        # 重排序
│       │   ├── indexer.md         # 索引器
│       │   └── retriever.md       # 检索器
│       ├── tools/          # 工具层设计图
│       │   ├── qa.md
│       │   ├── progress.md
│       │   ├── recommend.md
│       │   ├── jobmatch.md
│       │   ├── resume.md
│       │   ├── interview.md
│       │   └── shared.md
│       └── agents/         # Agent 层设计图
│           ├── supervisor.md  # Supervisor 层级调度
│           ├── qa.md          # QAAgent
│           ├── progress.md    # ProgressAgent
│           ├── schedules.md   # 输出 Schema
│           └── prompts.md     # Prompt 多层组装
├── resources/              # 课程资源（视频、文档、题库）
│   └── courses/
│       └── RAG101-RAG全栈技术从基础到精通，打造高精准AI应用/
│           ├── index.json
│           ├── 第1章/（module.json + docx + mp4）
│           └── 第2章/（module.json + docx + pdf + mp4）
├── src/                    # 源代码
│   ├── config.py           # 配置中心
│   ├── llm/                # LLM 抽象层
│   ├── db/                 # 数据库（SQLAlchemy ORM）
│   ├── memory/             # 记忆系统（RedisSaver + Store + context 预算）
│   ├── emotion/            # 情感系统
│   ├── schemas/            # Agent 输出 Schema
│   ├── vectordb/           # RAG 向量存储（Milvus Lite）
│   ├── speech/             # 可插拔 ASR/TTS（SenseVoice / Edge）
│   ├── tools/              # Agent 工具函数（34个）
│   ├── agents/             # Agent 层（含 interview / resume / jobmatch）
│   │   ├── prompts/        # Prompt 多层组装模块
│   │   ├── supervisor.py   # Supervisor 层级调度
│   │   └── …               # qa / progress / recommend / …
│   └── ui/                 # Vue 3 Web UI
├── skills/                 # 项目 Agent Skill（可复制到其他视口）
│   ├── course-resource-rename/  # 课程资源按规范改名
│   ├── course-transcribe/       # 视频转写带时间戳 md（docx 遗留）
│   └── interview-speech-lifecycle/  # 面试 TTS 发现/启停
├── pyproject.toml          # Poetry 项目配置
├── poetry.lock             # 依赖锁定文件
└── .venv/                  # Python 虚拟环境
```

### 项目 Skill（多视口）

| Skill | 路径 | 用法 |
|------|------|------|
| 课程资源改名 | [`skills/course-resource-rename/`](skills/course-resource-rename/SKILL.md) | 并行改 `resources/courses/` 不合规目录/文件名；复制 [`COPY_PROMPTS.md`](skills/course-resource-rename/COPY_PROMPTS.md) 到其他 Agent 视口 |
| 课程视频转写 | [`skills/course-transcribe/`](skills/course-transcribe/SKILL.md) | mp4→带时间戳 md（主路径）；docx→md 为遗留；[`COPY_PROMPTS.md`](skills/course-transcribe/COPY_PROMPTS.md) |
| 面试语音生命周期 | [`skills/interview-speech-lifecycle/`](skills/interview-speech-lifecycle/SKILL.md) | 进面试 discover/prepare TTS（Edge/Cosy）；禁止迁 Embedding；[`COPY_PROMPTS.md`](skills/interview-speech-lifecycle/COPY_PROMPTS.md) |

## 开发进度

### 已完成（代码）
- [x] 配置中心 (`src/config.py`) — 多 LLM Provider 预留
- [x] LLM 抽象层 (`src/llm/base.py`) — DeepSeek + OpenAI + Anthropic 预留
- [x] 数据库 (`src/db/`) — 9 张表 SQLAlchemy ORM + 初始化
- [x] 记忆系统 (`src/memory/`) — RedisSaver + MemoryStore
- [x] 上下文预算 — Store.summaries + 近窗组 prompt（见 `src/memory/context.py`）
- [x] 情感系统 (`src/emotion/detector.py`) — 7 种情绪实时检测；落库与预警 → P1 任务（[`docs/tasks.md`](docs/tasks.md)）
- [x] 导师人格 (`src/llm/base.py` — CoachStyle 枚举 + Prompt 注入)
- [x] 传统 RAG 编排 (`src/vectordb/`) — 重写 / 混合检索 / 精排适配 / 父子文档
- [x] 工具层 (`src/tools/`) — 多个 Agent 工具函数（`@tool` 装饰 + 内部辅助）
- [x] 输出 Schema (`src/schemas/`)
- [x] Prompt 模块 (`src/agents/prompts/`)
- [x] Supervisor — 证据驱动路由 + 业务优先闲聊分流
- [x] 会话隔离 — Checkpointer `thread_id` 与前端一致；`pending_options` 结构化选项（可点/手输 id）
- [x] QAAgent / ProgressAgent / RecommendAgent / JobMatchAgent / ResumeAgent / InterviewAgent（文字）
- [x] FastAPI 后端 + Vue 3 前端
- [x] Chat SSE 流式（`/api/chat/stream`：状态字 + token；见 `docs/architecture/ui/chat-stream.md`）
- [x] Graph 启动编译复用
- [x] 可插拔推理抽象（http / local / algo）；**当前默认 local GPU**
- [x] 可插拔语音 `src/speech/`（ASR/TTS；默认 local；http 占位）
- [x] Interview ASR/TTS API — SenseVoice + Edge-TTS（`/api/interview/speech/ready` 已通）
- [x] Probe 轻量化（`quick_vector_search`）
- [x] `/readyz` 按 Provider backend 分支
- [ ] HTTP TEI 生产化（Windows CPU 镜像兼容性待完善，暂不用）
- [x] Interview 全屏游戏态 UI（Stage / Avatar P0 / Voice VAD+barge-in；DEV 调试文字入口）
- [x] 面试 TTS 引擎发现 / prepare / release（Edge 兜底；Cosy sidecar 可选）
- [x] CosyVoice-300M-Instruct 本机试用（conda `cosyvoice` + cu128；当前默认改回 Edge，Cosy 后续再开）
- [ ] 下一阶段（见 `docs/architecture/ui/interview-multimodal.md` §9）：性能 P0 / 真麦 VAD / Avatar P1–P2

### 占位（待实现）
- [x] JobMatchAgent — 课程覆盖匹配 MVP（非实时市场）
- [x] ResumeAgent — fact/target 双模式 + 定向呈现
- [x] InterviewAgent — 文字 + 语音 API + 全屏面试场 P0（已联调）

### 待讨论/待优化
- [x] Graph RAG（Neo4j）— Phase 1 建图 + lifespan 增量同步；Phase 2 图检索通路，按问题类型路由
- [ ] WebSearch 兜底接入（部分：`resume_tools.py` 已有 DuckDuckGo 搜索，未作为通用工具开放）
- [ ] 端到端联调与 SSE（面试语音等仍可加强）
- [x] Chat SSE 流式主路径（`/api/chat/stream`）
- [ ] build_index() 接入 lifespan 自动触发（当前手动）
- [ ] 格式化输出 + 错误重传
- [ ] 课程资源后续章节补充

## 开发规范

### 代码风格
- 每个模块、类、公开方法必须有简短的中文注释说明用途
- 复杂逻辑加行内注释解释"为什么这样做"
- 函数保持单一职责，不超过 50 行为佳
- 命名：模块用 snake_case，类用 PascalCase，函数和变量用 snake_case

### 开发工作流

**每次代码改动必须遵守 [开发工作流](docs/workflow.md)**：

1. 需求讨论 → 2. 方案设计（你审核） → 3. 接口定义（你确认） → 4. 编码+评审循环（>4轮打断找你） → 5. 你最终审查 → 6. 同步文档 → 7. 提交

**核心规则**：
- 加新模块、改架构、跨 2+ 文件 → 先方案文档到 `docs/architecture/`
- 编码阶段前后端并行，各自自测
- reviewer Agent 单独审查，评审记录写入 `docs/review/`
- 阻塞问题必须修；建议问题由你最终审查时决定
- 文档同步紧跟代码合入，不拖延

### Prompt 管理规范
- Agent System Prompt 统一由 `src/agents/prompts/` 模块运行时组装
- 组装公式：shared_base(L2-L5) + coach(L6) + emotion(L7) + role(L1)
- 共享规则（安全、工具协议）只改 shared.py 一处
- 各 Agent 专属职责只改对应文件

### 禁止事项
- ❌ 硬编码任何课程数据
- ❌ 跨模块直接 import 内部实现
- ❌ 无注释的复杂逻辑
- ❌ 未经用户同意擅自降级技术方案（如 RedisSaver → MemorySaver）
- ❌ 遇到兼容性问题时绕过而非解决
- ❌ **禁止修改、覆盖、截断 `.env` 文件**——该文件包含用户私密配置，损坏不可恢复

## 后续规划

- [x] 可插拔 Embedding/Rerank Provider（默认 local；http 可选）
- [x] InterviewAgent 文字 + speech API + 全屏面试场 P0
- [x] CosyVoice 300M 本机试用
- [ ] 性能 P0（QA 双重检索）+ 面试 §9 余下（真麦 / Avatar）
- [ ] HTTP TEI 生产化（Windows 兼容）
- [ ] algo 写入 BGE collection 运行时拦截
- [ ] 安装 dingtalk-stream SDK（暂缓）
