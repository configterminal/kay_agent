# 课程作用域与类比课程

> 状态：**已按 dialogues 落地 TurnHint / 代称近窗**（单元测试 `tests/test_course_scope_turn.py` 通过） | 最后更新：2026-07-21  
> 关联：[hybrid-search](hybrid-search.md) · [retriever](retriever.md) · [video-jump](../ui/video-jump.md) · [catalog](../course-catalog-recommend.md)  
> **对话样例（验收）**：[course-scope-dialogues.md](course-scope-dialogues.md)  
> **RAGAS 方案（后续）**：[../eval/ragas-plan.md](../eval/ragas-plan.md)

## 1. 产品原则（已确认）

临时答疑里，学员可以：

- **随便聊**：跳槽 → RAG → 又问别的，不该被「锁死」在某一门课；
- **自由代指**：用「详细点 / 那个 / 继续」时，指的是**近窗上下文里的主题**，不一定是「上一门 Soft 锁住的课」；
- 例：刚聊完跳槽，再说「那个 RAG…」或回指更早的 RAG 讨论 → 应按上下文落到 RAG，而不是继续锁 CAREER。

因此：**Soft 不得做成跨轮永久锁课。** 作用域必须**按本轮 + 近窗上下文解析**，而不是「一旦 Soft=X 就一直只查 X」。

---

## 2. 四级作用域（修订）

| 级别 | 状态字段 | 何时用 | 主路检索 | 写 enrolled |
|------|----------|--------|----------|-------------|
| **Hard** | `active_course_id` | 用户**确认报名/正式学这门** | **仅该课**（学习态） | 是 |
| **TurnHint**（本轮提示） | 不持久锁死；可写 `focus_course_id` 仅作「最近话题缓存」 | 本轮从上下文解析出明确课/主题 | **本轮**优先该课；**下一轮重新解析** | 否 |
| **Open** | 无 Hard | 临时聊默认；新主题不清晰 | **全库** | 否 |
| ~~Profile 锁课~~ | — | **临时答疑不用** enrolled 首课挡自由聊 | — | — |

解析顺序（临时答疑）：

```
有 Hard？ → 仅 Hard 课
否则 → 本轮上下文解析 turn_course（可空）
         ├─ 有明确课/主题 → 本轮带 course_id 检索（TurnHint）
         └─ 无 → Open 全库
```

`focus_course_id` 若仍保留在 checkpoint：只表示「最近一次解析到的话题课」，**可供下一轮代指参考**，但：

- 本轮若出现**新主题 / 新课名** → 以新解析为准（可换课或 Open）；
- **禁止**「无新词就永远强制只查 focus」；
- **禁止**单凭向量探路 dominant 自动改写并锁死 Soft。

---

## 3. 本轮上下文怎么定课（核心）

输入：本轮用户话 + 近窗消息（及可选上轮 citations）。

```
1. 本轮显式点名课 / 主题词
   （RAG、Graph RAG、职业跃迁、课 id、课标题…）
   → turn_course = 该课

2. 本轮是代指/追问（详细、继续、那个、为什么…）且未点名新课
   → 在近窗里解析「当前指代对象」的主题课
   → 近窗可以跨多轮：刚聊跳槽，但代指的是更早的 RAG → RAG
   → 解析不到 → Open（宁可全库，也不锁错课）

3. 本轮是独立新问题、无点名
   → Open 全库（探路只辅助路由 Agent，不写死 focus）

4. 「两门课对比 / 不限定 / 换一门」等
   → 清 Hard 以外的话题缓存 → Open
```

**代指 ≠ 粘上一门 Soft。**  
代指 = **在对话历史上找指称对象**，对象可能换课。

### 近窗解析示意

```
[用户] 跳槽最佳时机？     → 话题 CAREER（TurnHint 本轮）
[助教] …CAREER…
[用户] rag和graph rag区别？ → 显式 RAG → TurnHint=RAG101（换话题）
[助教] …RAG…
[用户] 详细点               → 代指近窗「RAG 区别」→ 仍 RAG101
[用户] 那跳槽呢？           → 显式/主题回到 CAREER → 换 CAREER
[用户] 那个检索怎么做？     → 代指近窗偏 RAG → RAG101
```

---

## 4. 类比课程（不变）

主路按**本轮** `turn_course`；若有 TurnHint，类比路仍可为 enrolled\{focus}（未报名则类比区空）。

| 通道 | API 字段 | UI |
|------|----------|-----|
| 主来源 | `citations` | 消息下主 📎 |
| 类比 | `analogy_citations` | 「类比课程」弱样式区 |

Open 本轮不做类比分区（避免乱挂课）。

---

## 5. 明确不做 / 废止

| 废止 | 原因 |
|------|------|
| Soft 跨轮强制只查一课 | 临时聊被锁死，无法自由换话题/代指跨课 |
| 探路 dominant 自动写入 Soft 锁 | 「详细点」易漂到无关课（如 CAREER201） |
| 临时答疑用 Profile 锁 enrolled 首课 | 未报名/逛课时不该绑死主课 |
| 主题词一出现就永久 Soft | 与「聊完跳槽再聊 RAG」冲突 |

Hard（确认报名）逻辑保留，与临时聊分离。

---

## 6. 实现要点（已落地）

| 模块 | 状态 |
|------|------|
| `course_scope.resolve_turn_course` | ✅ 显式 → 线索 → 代称激活主题 → Open |
| `probe_node` | ✅ 已去掉探路 dominant 写 Soft；只更新话题缓存 |
| `resolve_course_scope` | ✅ Hard 优先；否则本轮 TurnHint/Open；**不再 Profile 锁课** |
| 单测 | ✅ `tests/test_course_scope_turn.py`（样例 1/2/3/9/10） |

### 验收用例

1. 只问「RAG 和 Graph RAG 区别」再「详细点」→ 仍 RAG，不漂 CAREER。  
2. 先问跳槽，再问 RAG 区别 → 能答 RAG，不被 CAREER 锁死。  
3. 先 RAG 再跳槽再「详细点讲刚才那个检索」→ 应回到 RAG 语境（近窗代指）。  
4. 无课名的全新问题 → Open，可命中任课。  
5. 确认「就学这门 RAG」→ Hard，之后严格 RAG（正式学）。

---

## 7. 数据流（修订后）

```
resolve_course_scope / resolve_turn_course(state, message)
    → mode: hard | turn_hint | open
    → course_id: str | None   # None = 全库
主路 retrieve(query, course_id?) → citations
类比路（仅 turn_hint/hard 且有 enrolled 其它课）→ analogy_citations
```

---

## 8. 代码入口（改后仍主要在此）

| 模块 | 路径 |
|------|------|
| 作用域解析 | `src/agents/course_scope.py` |
| 焦点/本轮解析 | `supervisor.probe_node` |
| 主/类比 citations | `citations.ensure_qa_citations` / `fetch_analogy_citations` |
| 检索过滤 | `retriever.retrieve(course_id=...)` |
