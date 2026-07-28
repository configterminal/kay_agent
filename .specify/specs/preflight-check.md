# 环境核查 (Preflight Check)

> 设计文档 · 2026-07-28 · 状态：方案设计

## 1. 问题

`dev-services.ps1 start` 和 `uvicorn` 启动时经常遇到依赖未就绪：
- Docker 未运行 → Redis 起不来
- Neo4j 未运行 → 图同步静默失败
- .env 缺失 → LLM API Key 为空
- 端口被占用 → 启动失败无提示

当前失败后错误信息不清晰，排查耗时。

## 2. 系统依赖全景

```
┌─────────────────────────────────────────────────────────────┐
│  AI 助教系统 依赖清单                                        │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│ Python   │ Docker   │ Neo4j    │ 本地模型  │ 外部 API       │
│ 3.13+    │ Redis    │ 图数据库  │ GPU/CUDA │ DeepSeek       │
│          │ Stack    │          │          │                │
├──────────┼──────────┼──────────┼──────────┼────────────────┤
│ 必须     │ 必须     │ 可选     │ 必须     │ 必须           │
│ 否则     │ 否则     │ 无则     │ 无则     │ 无则           │
│ 起不来   │ 记忆/    │ 图检索    │ Embed/   │ LLM 调用       │
│          │ 存储挂   │ 降级      │ Rerank挂 │ 全部挂         │
└──────────┴──────────┴──────────┴──────────┴────────────────┘
```

## 3. 核查项设计

### 3.1 PowerShell 层面 (`dev-services.ps1`)

新增 `Check-Environment` 函数，在 `Start-DevServices` 最前面调用。

```
Check-Environment:

  ① Python venv
     检查: Test-Path f:\agent\.venv\Scripts\python.exe
     失败: "❌ 虚拟环境未找到，请运行: python -m venv .venv"

  ② Python 版本
     检查: python --version ≥ 3.13
     失败: "❌ 需要 Python 3.13+，当前: {version}"

  ③ Docker 运行状态
     检查: docker info 2>$null
     失败: "❌ Docker 未运行，请启动 Docker Desktop"

  ④ Redis 容器
     检查: docker ps --filter "name=redis-stack"
     不存在: 尝试 docker run -d --name redis-stack ...
     已停止: docker start redis-stack
     失败: "❌ Redis 启动失败，请检查 Docker"

  ⑤ Neo4j 容器 (可选)
     检查: docker ps --filter "name=neo4j"
     不存在: "⚠️ Neo4j 未运行，图检索功能将不可用"
     已停止: docker start neo4j

  ⑥ 端口占用
     检查: 8000, 5173 是否被占用
     冲突: "⚠️ 端口 {port} 被占用，将先停止旧进程"

  ⑦ .env 文件
     检查: Test-Path f:\agent\.env
     失败: "⚠️ .env 文件不存在，LLM 调用将失败"

  ⑧ 磁盘空间 (建议)
     检查: 项目盘剩余 > 1GB
     失败: "⚠️ 磁盘空间不足 {free}MB"

全部通过 → "✅ 环境核查通过" → 继续启动
```

### 3.2 Python 层面 (`src/main.py`)

新增 `preflight_check()` 函数，在 lifespan 入口调用。

```
preflight_check():

  ① Redis 连通性
     检查: redis.ping()
     失败: "❌ Redis 不可达 ({host}:{port})，请确认 Docker Redis 已启动"

  ② Neo4j 连通性 (可选)
     检查: get_driver() + session.run("RETURN 1")
     失败: "⚠️ Neo4j 不可达，图检索将降级"

  ③ DeepSeek API Key
     检查: config.deepseek.api_key 非空
     失败: "❌ DEEPSEEK_API_KEY 未配置，请检查 .env"

  ④ Milvus 数据目录
     检查: config.milvus.data_path 目录存在/可创建
     失败: "⚠️ Milvus 数据目录不可写"

  ⑤ 向量模型文件 (可选，本地模式才检查)
     检查: sentence-transformers 可 import，模型路径存在
     失败: "⚠️ 本地向量模型未就绪，首次运行需下载"

  ⑥ 日志目录可写
     检查: logs/ 目录存在或可创建
     失败: "❌ 日志目录不可写"

  ⑦ 语音模型 (可选)
     检查: SenseVoice / Edge TTS ready()
     失败: "⚠️ 语音模型未就绪"

全部通过 → "✅ 预检通过" → 继续 lifespan
```

### 3.3 输出格式

```
┌─ 环境核查 ────────────────────────────────────────────┐
│ ✅ Python 3.13.12     f:\agent\.venv                  │
│ ✅ Docker 4.81.0      运行中                           │
│ ✅ Redis Stack 7.4.2  端口 6380                       │
│ ⚠️ Neo4j 未运行      图检索将不可用                     │
│ ✅ 端口 8000/5173     空闲                             │
│ ✅ .env               DEEPSEEK_API_KEY=sk-***         │
│ ✅ 磁盘               F: 剩余 85.2 GB                 │
│ ✅ 向量模型           local embed ready (cuda)        │
│ ✅ 语音模型           asr=sensevoice tts=edge          │
│ ✅ DeepSeek API       api.deepseek.com 可达            │
│ ✅ Milvus             f:\agent\milvus_lite            │
│ ✅ 日志目录           f:\agent\logs                    │
├───────────────────────────────────────────────────────┤
│ ✅ 所有关键项通过，启动服务                             │
│ ⚠️ 1 项可选未就绪 (Neo4j)                              │
└───────────────────────────────────────────────────────┘
```

## 4. 严重度分级

| 级别 | 含义 | 行为 |
|------|------|------|
| **致命** | 没有它系统起不来 | 终止启动，打印修复指引 |
| **警告** | 没有它部分功能降级 | 继续启动，打印警告 |
| **信息** | 正常状态 | 仅显示 |

| 检查项 | 级别 |
|--------|------|
| Python venv | 致命 |
| Docker + Redis | 致命 |
| .env / API Key | 致命 |
| 端口占用 | 致命 (冲突时) |
| Neo4j | 警告 |
| 向量模型 | 致命 (本地模式) / 警告 (http模式) |
| 语音模型 | 警告 |
| 磁盘空间 | 警告 (< 1GB 时) |

## 5. 实现

### 5.1 改动范围

| 文件 | 改动 |
|------|------|
| `scripts/dev-services.ps1` | 新增 `Check-Environment`，`Start-DevServices` 入口调用 |
| `src/main.py` | 新增 `preflight_check()`，`lifespan` 入口调用 |

**纯后端，无前端联动。**

### 5.2 核心函数

```python
# src/main.py

def preflight_check() -> dict[str, bool]:
    """
    启动前环境核查。
    返回 {"redis": True, "neo4j": False, "api_key": True, ...}
    
    致命项不通过 → raise SystemExit(1)
    警告项不通过 → 打印 warning，继续
    """
```

```powershell
# scripts/dev-services.ps1

function Check-Environment {
    # 逐项检查，致命项失败 → exit 1
    # 警告项失败 → 黄色警告，继续
    # 全部通过 → 绿色 "环境核查通过"
}
```

### 5.3 验证

1. 故意停掉 Docker → 启动脚本应该打印 "❌ Docker 未运行" 并退出
2. 临时设一个无效 API Key → 启动应该打印 "❌ DeepSeek API Key 不可用" 并退出（不操作 .env 文件，仅验证检测逻辑）
3. 正常环境 → 打印全绿检查清单，正常启动

**禁止**：删除、修改、覆盖 `.env` 文件进行测试。
