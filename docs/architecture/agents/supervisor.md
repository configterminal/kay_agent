# Supervisor — 层级调度主控

> 状态：设计定稿 | 最后更新：2026-07-16  
> 子 Agent：QA / Progress / Recommend / JobMatch / Resume / **Interview（文字 + 全屏面试场 P0）** 已接通。

## 架构总览

### Agent 层级关系

```
                        学员
                         │
                    Supervisor Agent
                         │
        ┌────────┬───────┼───────┬──────────┬──────────┐
        │        │       │       │          │          │
        ▼        ▼       ▼       ▼          ▼          ▼
   QAAgent   Progress  Recommend  JobMatch  Resume   Interview
   (答疑)    Agent     Agent      Agent     Agent    Agent
            (进度)    (推荐)     (岗位匹配) (简历)   (面试)
```

### LangGraph StateGraph 节点与边

```
         ┌──────────────────────────────────────────────────┐
         │                   START                           │
         └──────────────────────┬───────────────────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────┐
         │              probe_node                           │
         │  ┌─────────────────────────────────────────┐     │
         │  │ · Milvus 快速向量搜索 Top 3               │     │
         │  │ · EmotionDetector 情绪检测（全链路唯一）   │     │
         │  │ · MemoryStore 读取 coach_style +         │     │
         │  │   weak_areas                             │     │
         │  └─────────────────────────────────────────┘     │
         └──────────────────────┬───────────────────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────┐
         │              decide_node                          │
         │  ┌─────────────────────────────────────────┐     │
         │  │ · 业务确定性规则优先（QA/进度/推荐…）       │     │
         │  │ · 再判纯闲聊 → 标记 is_chitchat            │     │
         │  │ · 低置信度 → LLM 结构化输出分类            │     │
         │  │ · 多意图 → 拆分 task_queue（含 input）     │     │
         │  └─────────────────────────────────────────┘     │
         └───────────┬──────────────────┬───────────────────┘
                     │                  │
              ┌──────┘                  └──────┐
              ▼                                ▼
    ┌─────────────────┐              ┌─────────────────┐
    │  is_chitchat?   │              │  task_queue?    │
    │     YES         │              │  has tasks      │
    └────────┬────────┘              └────────┬────────┘
             │                                │
             ▼                                ▼
    ┌─────────────────┐              ┌─────────────────┐
    │  aggregate_node  │              │  dispatch_node   │
    │  (Supervisor     │              │  ┌─────────────┐ │
    │   自己回复闲聊)   │              │  │ 并行: 同时   │ │
    └────────┬────────┘              │  │ 分派汇总    │ │
             │                       │  │ 串行: 顺序   │ │
             │                       │  │ 执行入队    │ │
             │                       │  └─────────────┘ │
             │                       └────────┬────────┘
             │                                │
             │              ┌─────────────────┘
             │              ▼
             │    ┌─────────────────┐
             │    │ 子Agent需要       │
             │    │ 退回重路由?        │
             │    └────────┬────────┘
             │             │
             │      ┌──────┘
             │      ▼
             │    ┌─────────────────┐
             │    │  recovery_node   │
             │    │ · called 列表    │
             │    │ · 换Agent重试    │
             │    │ · 超过限制→自回   │
             │    └────────┬────────┘
             │             │
             └──────┬──────┘
                    │
                    ▼
         ┌──────────────────────────────────────────────────┐
         │              aggregate_node                       │
         │  ┌─────────────────────────────────────────┐     │
         │  │ · 汇总并行结果                             │     │
         │  │ · 串行: 检查下一步，未完成→dispatch         │     │
         │  │ · 全部完成 → 生成 final_response          │     │
         │  └─────────────────────────────────────────┘     │
         └──────────────────────┬───────────────────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────┐
         │                   END                             │
         └──────────────────────────────────────────────────┘
```

### 节点间数据流

```
              probe_node
                  │
          probe_evidence
          emotion + confidence
          coach_style
                  │
                  ▼
              decide_node
                  │
        next_agent / task_queue
        is_chitchat
        routing_confidence
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
    aggregate_node      dispatch_node
    (闲聊直回)           (子Agent调用)
        │                    │
        │            task_results
        │            needs_reroute
        │                    │
        └──────────┬─────────┘
                   ▼
              aggregate_node
                   │
              final_response
                   │
                   ▼
                  END
```

## 每次收到消息的完整处理流程

```
学员消息
    │
    ▼
┌──────────────────────────────────────────────────┐
│ ① Probe（探路 + 情绪，情绪全链路唯一检测点）         │
│    - 向量快速检索 Top 3                            │
│    - EmotionDetector.detect(text) → state.emotion │
│    - 读取 Store → coach_style + weak_areas         │
│    - API 层禁止再调 detect（见 emotion.md）         │
│                                                  │
│ ② Decide（决策）                                  │
│    - 业务确定性规则优先（快速路径，含单意图 input）     │
│    - 再判纯闲聊 → is_chitchat（见「闲聊分流」）        │
│    - 证据模糊 → LLM 结构化输出 + called 去重         │
│    - 多意图 → 拆分为任务队列                         │
│                                                  │
│ ③ Execute（执行）                                  │
│    - 单一意图 → 路由到目标 Agent（必须带学员原话）     │
│    - 多意图并行 → 并行分派 → 汇总                     │
│    - 多意图串行 → 先A → 拿结果 → 再B                 │
│    - 纯闲聊 → Supervisor 自己回复                    │
│                                                  │
│ ④ Recovery（容错）                                 │
│    - 子 Agent 退回 → 附带理由 → 重新路由              │
│    - called 列表防循环（同 Agent 最多调 2 次）         │
└──────────────────────────────────────────────────┘
    │
    ▼
  run_supervisor → {content, emotion, emotion_confidence}
```

---

## 一、多意图处理（混合模式）

### 意图分类

| 意图类型 | 处理方式 | 例子 |
|------|------|------|
| 单一明确 | 直接路由，task_queue 写入学员原话 | "什么是 RAG" → QAAgent |
| 多意图并行 | 同时分派，汇总后一次返回 | "看看进度，顺便推荐下一课" → Progress \|\| Recommend |
| 多意图串行 | B 依赖 A 的结果，顺序执行 | "先分析我的薄弱点，再推荐练习" → Progress → Recommend |
| 纯闲聊 | Supervisor 自己回复 | "你好"、"谢谢"、"今天心情不太好" |
| 问候 + 业务（混合句） | **不当闲聊**，按业务意图路由 | "你好，什么是 embedding" → QAAgent |

### 任务队列

```python
# 单意图（确定性或 LLM 路由均须带 input，禁止空字符串）
task_queue = [
    {"agent": "qa_agent", "input": "什么是 RAG", "depends_on": None}
]

# 多意图串行
task_queue = [
    {"agent": "progress", "input": "分析学员123的薄弱点"},
    {"agent": "recommend", "input": "基于{上一步结果}推荐练习"}
]

# 多意图并行
task_queue = [
    {"agent": "progress", "input": "查询进度"},
    {"agent": "recommend", "input": "推荐下一课"}
]
# 两个同时执行 → 等全部完成 → 汇总返回
```

**约束**：`decide_node` 无论走确定性还是 LLM 路径，只要路由到子 Agent，就必须把学员原话写入 `task_queue[].input`。`dispatch_node` 若发现 `input` 为空，回退取对话中最后一条 `HumanMessage`，不得向子 Agent 传入空问题。

### 判断串行还是并行的规则

```
判断规则（Python 确定性逻辑，不依赖 LLM）：

1. 如果任务队列中只有 1 个 → 直接路由
2. 如果多个任务之间没有依赖 → 并行分派
3. 如果后面的任务引用了前面的结果 → 串行分派
4. 如果有一个任务需要 LLM 分析 → 它往后的任务默认串行
```

---

## 二、会话隔离与结构化选项（对话状态）

> **硬约束**：每个 `thread_id` 拥有独立的图状态（含 `messages`、`pending_options`）。  
> 不同会话互不干扰；切换侧边栏会话 = 切换 RedisSaver checkpoint 命名空间。

### 2.1 thread_id 全链路

```
前端生成/持有 thread_id（如 stu_1_20260715T183000）
        │
        ▼
POST /api/chat { thread_id, message, selected_option_id? }
        │
        ▼
run_supervisor(..., thread_id=T)
        │
        ▼
RedisSaver configurable.thread_id = T   ← 禁止再写死 stu_{student_id}
```

| 层 | key | 说明 |
|----|-----|------|
| Vue / QAHistory | `thread_id` | 会话列表与消息落库 |
| Supervisor Checkpointer | 同一 `thread_id` | 图状态、pending 选项 |
| MemoryStore（长期记忆） | `student_id` | 跨会话人格/薄弱点，**不属于单会话** |

删除会话时：删 QAHistory，并尽量删除该 `thread_id` 的 checkpoint。

### 2.2 pending_options（结构化选项）

选项由 **Agent Prompt 驱动**：仅在学员需要做选择时主动给出编号项（学员不会也不该被要求「请列个表」）。  
普通讲解默认不给列表；一旦给出，须为严格编号行，系统解析后写入**当前线程**状态：

```python
pending_options = [{"id": 1, "text": "..."}, {"id": 2, "text": "..."}]
pending_agent = "qa_agent"   # 粘性：选号后默认回到上一业务 Agent
```

同时经 `ChatResponse.options` 返回前端，在助教气泡下渲染可点按钮。

学员选择方式（等价）：

| 方式 | 请求 |
|------|------|
| 点击选项 | `selected_option_id=1`，`message` 可为选项文案 |
| 手输 id | `message="1"` / `"选项2"`（不带 selected_option_id） |

Decide **第 0 步**（先于业务规则与闲聊）：

```
本线程有 pending_options？
 且（selected_option_id 命中 或 文本解析为选项 id）？
    → 改写 input：「学员选择了选项 N：{原文}。请继续…」
    → 路由 pending_agent（缺省 qa_agent）
    → is_chitchat=false
    → 清空 pending（等本轮回复若再带列表则重写）
```

切换会话：`GET /api/conversations/{thread_id}/state` 读取该线程 checkpoint 的 `pending_options`，前端恢复选项条。

### 2.3 与 RAG 查询重写的边界

| | 选项续聊（本节） | RAG query_rewriter |
|--|------------------|---------------------|
| 层 | Supervisor Decide | QA 检索流水线内 |
| 目的 | 解释短回复 / 正确路由 | 提高检索召回 |
| 禁止 | 把选号逻辑塞进 query_rewriter | — |

---

## 三、闲聊分流（业务优先）

> 对标业界常见做法（Rasa：chitchat 与业务意图同级竞争；Agent 路由 cascade：规则 → 语义/LLM → fallback）。
> **禁止**用「全文包含问候子串」抢在业务规则之前短路整句。

### 设计原则

1. **对话状态优先**：本线程 `pending_options` 命中选号 → 绝不进闲聊（见第二节）
2. **业务优先**：再跑 QA / 进度 / 推荐等确定性规则；有可识别业务信号则不当闲聊
3. **闲聊收窄**：仅当「整句纯寒暄」或「去掉问候壳后仍无实质内容」时，才标记 `is_chitchat`
4. **固定文案只服务真闲聊**：`_handle_chitchat` 不得用「我是谁」类自我介绍顶替所有未识别消息

### Decide 内判定顺序

```
decide_node 确定性路径：

  ⓪ 本线程 pending_options 选号解析（点击 id / 手输 id）
       命中 → 粘性路由 pending_agent，改写 input，禁止闲聊
       │
  ① 业务 DETERMINISTIC_RULES + QA_PATTERNS
       命中 → 路由到对应 Agent（写入 task_queue.input）
       │
  ② 闲聊判定（仅在业务未命中后）
       │
       ├─ 整句等于问候/寒暄词（如「你好」「谢谢」「好的」）
       ├─ 或：剥离开头问候壳后，剩余为空 / 仍无业务信号
       ├─ 或：超短消息（≤3 字）且无业务关键词且无对话历史
       │      ↑ 有对话历史时不拦截——可能是追问
       │
       └─ 命中 → is_chitchat=true，Supervisor 自身用 LLM 回复
              ↑ 不再用固定文案；LLM 按 CoachStyle 礼貌回应
       │
  ③ 以上皆否 → LLM 结构化路由
       │
       └─ 仍不确定 → 澄清 / 温和兜底，不硬判闲聊
```

### 未实现 Agent 探路改派 QA

仅 **`interview_agent`** 仍占位。命中后若 Probe `top_score ≥ 0.35` 且有条目，改派 `qa_agent`。

**`jobmatch_agent` / `resume_agent` 已接通**，不在 `UNIMPLEMENTED_AGENTS`。

典型场景：
- 「面试技巧」「简历怎么写」「怎么跳槽」→ `qa_agent`
- 「我离 RAG 方向还差什么」→ `jobmatch_agent`
- 「帮我优化这份简历 / 目标蓝图简历」→ `resume_agent`

确定性规则调整：
- 职业跃迁 / 简历课知识词 → `qa_agent`
- 简历优化强信号（优化/修改/我的简历/蓝图…）；**无**单字「简历」宽松命中
- 技能差距 / 对照课程 → `jobmatch_agent`

```python
# supervisor.py
UNIMPLEMENTED_AGENTS = {interview_agent}
PROBE_COURSE_OVERRIDE_MIN_SCORE = 0.35
```

### 闲聊回复规范

**禁止 `_handle_chitchat` 用固定文案。** 闲聊命中后走 LLM 生成回复，按 CoachStyle 礼貌、简短回应。固定文案仅限于 `CHITCHAT_EXACT` 中的纯问候词（如"你好""谢谢"），其他情况必须走 LLM。
```

### 混合句处理

| 学员说 | 判定 | 路由 |
|--------|------|------|
| `你好` | 纯闲聊 | Supervisor 固定问候（按 CoachStyle） |
| `谢谢` / `知道了` | 纯闲聊 | Supervisor 简短回应 |
| `你好，什么是 embedding` | 混合句：有 QA 信号 | QAAgent（可先剥问候壳再答，或直接传原话） |
| `好的，我想学 RAG` | 混合句：有业务信号 | 对应业务 Agent，**禁止**因含「好的」判闲聊 |
| `早上学的内容讲了什么` | 业务问答 | QAAgent（禁止因含「早」子串误判） |

可选增强（非必须）：识别到「问候 + 业务」时，回复可带一句短问候再答业务；路由目标仍是业务 Agent，不是 `is_chitchat`。

### 反模式（禁止）

```
❌ if "你好" in text:  → 整句当闲聊     # 子串误伤混合句
❌ 闲聊规则排在业务规则之前短路
❌ _handle_chitchat 忽略用户原话、一律回「我是你的 AI 助教」
❌ 确定性路由到子 Agent 时 task_queue=[] 或 input=""
❌ 有对话历史时仍把 ≤3 字判为闲聊  # 可能是追问
❌ 闲聊回复用固定文案而非 LLM     # 除非纯问候词
❌ Checkpointer 使用 stu_{student_id} 导致多会话串状态
❌ 有 pending_options 时仍把 "1"/"2" 判为闲聊
❌ 把选项续聊塞进 RAG query_rewriter
```

### 与实现的对应关系

| 设计点 | 代码落点 |
|--------|----------|
| 会话隔离 | `run_supervisor(thread_id=…)` → RedisSaver `thread_id` |
| 上下文预算 | 见 [memory.md · 上下文预算](../memory.md)：摘要+近窗，禁全量进子 Agent |
| 结构化选项 | `pending_options` / `pending_agent`；回复后解析编号列表写入 |
| 选号第 0 步 | `decide_node` 先于业务/闲聊调用 `_resolve_option_selection` |
| 业务优先再闲聊 | `_deterministic_route`：先规则/QA，后 `_classify_chitchat` |
| 收窄闲聊匹配 | `_classify_chitchat`：整句/去壳，禁用松散子串 |
| 真闲聊才自回 | `dispatch_node` + `_handle_chitchat` |
| 单意图必带原话 | `decide_node` 填 `task_queue`；`dispatch` 空 input 回退 |
| 切会话恢复 | `GET /conversations/{thread_id}/state` |

---

## 四、路由容错（证据驱动 + 退回机制）

### Probe → Decide → Execute

```
① Probe（1 次极低成本操作）
  ┌─────────────────────────────────────────────┐
  │ Milvus 快速向量搜索（只取 Top 3，不要精排）    │
  │ → 返回 [{section, tags, score}]             │
  │                                             │
  │ 提取证据：                                    │
  │ - 如果 Top 3 都来自同一章节 → 置信度高              │
  │ - 如果 Top 3 分布在不同章节 → 置信度低              │
  │ - 如果 Top 1 score > 0.85 → 强信号              │
  └─────────────────────────────────────────────┘

② Decide（分类决策）
  ┌─────────────────────────────────────────────┐
  │ ① 业务确定性规则 / QA 模式（高置信 → 直接路由） │
  │ ② 纯闲聊判定（业务未命中后，见「闲聊分流」）   │
  │ ③ 低置信度 → LLM 结构化路由                   │
  │             │                                │
  │             ├── 要求 JSON 输出                   │
  │             ├── 参考 called 排除已调用           │
  │             ├── 如果判断为中间地带 → 标记风险        │
  │             └── 附带 fallback Agent             │
  └─────────────────────────────────────────────┘

③ Execute
  ┌─────────────────────────────────────────────┐
  │ 子 Agent 收到路由指令：                        │
  │   - 学员原话（task_queue.input，禁止为空）     │
  │   - 情绪标签 + CoachStyle + 学员画像            │
  │   - 附带 on_failure 指令：                     │
  │     "如果这个问题不属于你的处理范围，返回         │
  │      {'status': 'reroute', 'reason': '...'}"   │
  └─────────────────────────────────────────────┘
```

### 退回重路由

```
子 Agent 判断无法处理
    │
    ▼
返回 {"status": "reroute", "reason": "这是进度问题，不是课程答疑"}
    │
    ▼
Supervisor 收到退回：
    1. 记录原路由到 called
    2. 把 reason 作为新的意图信号
    3. 重新 Decide → 排除已调用的 Agent
    4. 如果所有 Agent 都被排除 → Supervisor 自己回复
```

### called 防循环

```python
# Supervisor State 中追踪
called: list[str] = ["qa_agent", "progress_agent"]

# 路由决策时
if agent_name in called and called.count(agent_name) >= 2:
    # 同一个 Agent 最多调 2 次
    skip this agent, try next best
```

---

## 五、Supervisor State

```python
class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]  # 完整对话历史（按 thread_id 隔离）
    student_id: int
    coach_style: str                          # 从 Store 读取
    emotion: str                              # 当前消息的情绪
    emotion_confidence: float                 # 情绪置信度
    next_agent: str                           # 路由目标
    called: list[str]                         # 已调用的 Agent 列表
    call_count: dict[str, int]                # 每个 Agent 的调用次数
    task_queue: list[dict]                    # 多意图任务队列（含 input）
    task_results: list[dict]                  # 已完成任务的结果
    final_response: str                       # 最终输出
    needs_reroute: bool                       # 是否需要重路由
    reroute_reason: str                       # 重路由原因
    is_chitchat: bool                         # 是否纯闲聊（业务优先判定后）
    routing_confidence: float                 # 路由置信度
    probe_evidence: dict                      # Probe 探路证据
    # ── 会话级对话状态（随 Checkpointer 按 thread_id 持久化）──
    pending_options: list[dict]               # [{"id": 1, "text": "..."}]
    pending_agent: str                        # 选号后粘性路由目标
    selected_option_id: int | None            # 本轮请求可选：前端点击传入
```

> `run_supervisor` 每轮 **不得** 用空列表覆盖 `pending_options` / `pending_agent`（省略字段以保留 checkpoint）；由 decide 选号清空、dispatch 解析列表后重写。

## 六、实施策略

**按正式项目标准，手写 StateGraph**。不使用 `create_supervisor()` 黑盒。

LangGraph StateGraph 节点：
- `probe_node` — 向量探路 + 情绪检测（唯一）+ Store 读取
- `decide_node` — 选项续聊 → 业务规则 → 闲聊收窄 → LLM 分类 + 任务队列
- `dispatch_node` — 分派子任务；回复含列表则写入 `pending_options`
- `aggregate_node` — 汇总并行结果 / 检查串行下一步
- `recovery_node` — 处理子 Agent 退回 + 重新路由

实施阶段：
1. State 定义 + 基础图骨架
2. probe + decide + dispatch 单意图路由（含 task_queue.input）
3. 闲聊分流：业务优先 + 收窄匹配
4. **会话隔离 thread_id + pending_options 结构化选项（UI 可点 / 手输 id）**
5. 多意图混合调度（并行 + 串行）
6. 退回重路由 + called 防循环
7. 6 个子 Agent 接入联调
