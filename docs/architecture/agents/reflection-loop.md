# Agent 反思循环 (Reflection Loop)

> 设计文档 · 2026-07-27 · 状态：方案设计

## 1. 问题

当前子 Agent（以 ResumeAgent 为代表）产出依赖一次 ReAct 调用：LLM 边想边调工具，
最终一把输出。对于简历这种**一句话就影响约面率**的高风险产出，不够可靠。

已有 `optimize_resume_document` 内置了规则门禁（密度检查 + 审核关），
但这些是**工具层面**的硬规则，缺少**LLM 自我评价驱动**的质量闭环。

## 2. 方案：Reflection 模式接入子 Agent

### 2.1 核心理念

```
一次产出 ──→ LLM 自评 ──→ 不合格 → 修改 → 再评 → 合格 → 返回
```

不是规则告诉 LLM "你不对"，而是 **LLM 自己看自己的产出，自己找问题，自己改**。

### 2.2 图拓扑

```
                    [dispatch → build_resume_agent]
                              │
                              ▼
                    ┌──────────────────┐
                    │   GENERATE       │
                    │   ReAct 生成初稿  │
                    │   (现有逻辑)      │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   REFLECT        │
                    │   LLM 自我审查    │
                    │   打分 + 找问题   │
                    └────────┬─────────┘
                             │
                    ┌────────┴────────┐
                    │ score ≥ 8       │ score < 8
                    │ or rounds ≥ 3   │ AND rounds < 3
                    ▼                 ▼
              ┌──────────┐    ┌──────────────┐
              │ 返回结果  │    │   REVISE     │
              │ → dispatch│    │   基于反思修改│
              └──────────┘    └──────┬───────┘
                                     │
                                     └──→ 回到 REFLECT
```

### 2.3 三个子阶段

#### GENERATE（现有逻辑复用）

就是现在的 ReAct Agent 调用。`build_resume_agent()` → `agent.invoke(messages)`。
产出结构化 `ResumeDocument`（通过 `optimize_resume_document` 生成的 artifact）。

#### REFLECT（新增 — 自我审查）

**不是调工具，而是 LLM 纯推理**。

```
Prompt:

  你是简历质量审核专家。请审查以下简历终稿，从以下维度评分（1-10）：

  1. 角色匹配度：内容是否贴合目标岗位要求
  2. 量化成果：bullet 是否包含具体数字/方法/工具/结果
  3. 技能分层：是否按目标方向排序，写透了关键技能
  4. 格式规范：无畸形占位、无辅导内容、句子通顺
  5. 完整性：一页内容是否充实（≥10 bullet）

  简历终稿：
  {final_response text + artifact summary}

  输出 JSON：
  {
    "total_score": 8,
    "dimensions": {
      "role_match": 8,
      "quantified_impact": 7,
      "skill_layering": 9,
      "format_compliance": 10,
      "completeness": 6
    },
    "top_issues": [
      "项目经历第 3 条缺少量化结果",
      "技能列表中 '办公软件' 优先级过高"
    ],
    "pass": true/false
  }

  pass=true 当且仅当 total_score ≥ 8 且所有维度 ≥ 5。
```

**为什么不用工具？**
- 反思是纯判断，不需要查数据库
- 工具调用会增加延迟和复杂度
- 结构化 JSON 输出即可驱动下一阶段

#### REVISE（新增 — 基于反思修改）

```
Prompt:

  你的上一版简历终稿有以下问题（自我审查发现）：

  {reflect_result.top_issues}

  请重新调用 optimize_resume_document，这次重点修复上述问题。

  注意：
  - 不改真实经历，只改进写法
  - 量化不足的 bullet 请补充 [量化待补：方向] 标记
  - 技能按目标方向重新排序
```

REVISE 节点**再次调用 ReAct Agent**（同一套 tools），
但这次 prompt 里带了上一轮的反思反馈。

### 2.4 循环控制

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `max_rounds` | 3 | 最多反思 3 轮 |
| `pass_threshold` | 8 | 总分 ≥8 即放行 |
| `min_dimension` | 5 | 任一维度 <5 不通过 |
| `early_exit` | score ≥ 8 | 一旦合格马上返回 |

### 2.5 与现有门禁的关系

```
REFLECTION 循环（新增）          现有门禁（保留）
─────────────────────          ───────────────
GENERATE → REFLECT → REVISE    optimize_resume_document 内部：
   ↑_______________│             ① 密度门禁（density_report）
                                ② 审核关（review_and_gate_document）

两层互补：
  - 现有门禁 = 硬规则（畸形占位、bullet 数量、辅导内容过滤）
  - 反思循环 = 软评价（整体质量、角色匹配、量化深度）

反思循环给出"还可以更好"的方向，门禁确保"至少不出错"。
```

## 3. 实现方案

### 3.1 不创建新 Agent 类型

反思循环在 **Agent 内部** 完成，对 Supervisor 透明。

```
_dispatch_to_agent("resume_agent", ...)
  │
  ├─ build_resume_agent()
  │
  └─ _invoke_with_reflection(agent, messages)   ← 新增包装
       │
       ├─ round 1: agent.invoke() → GENERATE
       ├─ reflect() → REFLECT
       ├─ if pass: return result
       ├─ revise_prompt = 注入反思
       ├─ round 2: agent.invoke(revise_prompt) → REVISE
       ├─ reflect()
       └─ ...
```

### 3.2 新增文件

```
src/agents/reflection.py     ← 反思循环核心逻辑
```

### 3.3 核心函数签名

```python
# src/agents/reflection.py

from typing import TypedDict

class ReflectionResult(TypedDict):
    total_score: int
    dimensions: dict[str, int]
    top_issues: list[str]
    passed: bool

class ReflectionConfig:
    max_rounds: int = 3
    pass_threshold: int = 8
    min_dimension: int = 5

def reflect_on_output(
    output: str,
    task_context: str,        # "简历优化 fact 模式，目标方向 RAG AI 工程师"
    dimensions: list[str],    # 评价维度
) -> ReflectionResult:
    """LLM 自我审查：评价产出质量，返回评分与问题列表。"""

def build_reflection_cycle(
    agent,                    # 现有 ReAct Agent
    task_context: str,
    config: ReflectionConfig | None = None,
):
    """
    包装 Agent，在 agent.invoke() 后自动反思改进。

    返回与 agent.invoke() 相同结构 {"messages": [...]}，
    但内部经过了 GENERATE → REFLECT → (REVISE → REFLECT)* 循环。
    """
```

### 3.4 流式集成

反思过程中向 SSE 发送进度事件：

```
emit_status("generate", "正在生成简历…")
  → GENERATE (现有流式 token)

emit_status("reflect", "AI 正在自我审查…")

if not passed:
    emit_status("revise", "正在基于审查意见修改…")
    → REVISE (流式 token)

emit_status("generate", "简历优化完成")
```

### 3.5 改造点

| 文件 | 改动 |
|------|------|
| `src/agents/reflection.py` | **新建**：`reflect_on_output()` + `build_reflection_cycle()` |
| `src/agents/resume.py` | `build_resume_agent()` 返回时包装 `reflection_cycle` |
| `src/agents/supervisor.py` | `_dispatch_to_agent()` 中 `resume_agent` 路径使用 `_invoke_with_reflection()` |
| `src/agents/stream_events.py` | 新增 `emit_reflection_progress()` 或在现有 `emit_status` 上用新 phase |

### 3.6 反思维度配置（按 Agent 类型）

| Agent | 反思维度 | pass_threshold |
|-------|---------|---------------|
| ResumeAgent | 角色匹配度、量化成果、技能分层、格式规范、完整性 | 8 |
| QAAgent | 准确性（引文支撑）、完整性（是否覆盖问题）、可读性 | 7 |
| JobMatchAgent | 差距分析准确度、推荐课匹配度、行业侧重 | 7 |

### 3.7 回退策略

- `reflect_on_output()` 调用失败 → 直接通过（不阻塞用户）
- 反思 JSON 解析失败 → 默认 pass=false，允许一轮 REVISE 兜底
- REFLECT 超 3 轮仍不合格 → **不强求，当前最优版返回**。同时可记录原因到 Store
- 记录失败经验到 Store（后续 Reflexion 记忆接入）

## 4. 落地路线

### Phase 1 — ResumeAgent 接入（本次）

- [ ] 新建 `src/agents/reflection.py`
- [ ] `reflect_on_output()` — 单一 LLM 调用，结构化 JSON 输出
- [ ] `_dispatch_to_agent()` 中 ResumeAgent 路径接入反思循环
- [ ] 流式 status 事件：reflect / revise
- [ ] 配置项 `RESUME_REFLECTION_MAX_ROUNDS` / `RESUME_REFLECTION_PASS_THRESHOLD`

### Phase 2 — QA / JobMatch 接入

- [ ] QA 反思维度：引文准确性 + 回答完整性
- [ ] JobMatch 反思维度：差距准确度 + 推荐匹配度

### Phase 3 — Reflexion 长记忆

- [ ] 反思失败 case 写入 Store（`reflection_notes`）
- [ ] 下次类似任务时注入历史反思经验

## 5. 不做的

- ❌ 不引入 Mem0 / Letta 等外部框架（过度依赖）
- ❌ 不做 LATS 树搜索（调用成本太高，简历不需要）
- ❌ 不在所有 Agent 上一把推开（先 Resume 验证效果）
