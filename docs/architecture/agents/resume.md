# ResumeAgent — 双模式简历 + 学习闭环（设计方案）

> 状态：**证据驱动加强版已落地** | 最后更新：2026-07-17  
> 关联：[tools/resume.md](../tools/resume.md) · [jobmatch.md](jobmatch.md) · [recommend.md](recommend.md) · **[简历 PDF 展示](../ui/resume-pdf.md)** · Interview（占位）  
> 本阶段：站内岗位模板 +（有目标岗时）公开网络侧重点；真实招聘 JD 下阶段。  
> 代码：`src/agents/resume.py` · `prompts/resume.py` · `tools/resume_tools.py`  
> 上游定位：终稿驱动 **画像 / 训练题 / 面试重点**；方法论借鉴 resume-optimizer、resume-jd-optimizer-cn（内化，非运行时依赖）。

## 1. 产品一句话

简历不是终点：**两种写法模式** → 对照站内目标方向 → **自动串起课程 / 题目练习 / 模拟面试**，把「想成为的人」落成可验证的能力与可投递材料。

## 2. 两种模式（核心）

| 模式 | 标识 | 是否可「编」 | 用途 |
|------|------|:------------:|------|
| **真实经历** | `fact` | ❌ 不改任职事实；✅ 可定向裁剪叙事 | 真实公司/年限/title；正文按目标岗主写相关、弱相关压缩 |
| **目标职业蓝图** | `target` | ✅ 允许生成目标态表述 | 按「希望成为的方向」生成**成长后可写进简历**的项目/技能叙事，并标成蓝图 |

### 2.1 真实经历模式（`fact`）+ 定向呈现

简历不是「把会的都写上」，而是让 HR **一眼看到他要的**。在事实成立的前提下，**选择性强调**目标方向——产品一等能力，不是造假。

#### 典型场景（必须支持）

> 在 A 公司做**渲染** 3 年（任职真实），同时做成了 **Agent**。投 Agent 方向时：  
> - 工作经历仍写：**A 公司 · 真实 title（如渲染工程师）· 3 年**  
> - 正文**主写 Agent**；渲染经历压缩为一行可迁移点或略写  
> - **不把** title 改成「Agent 工程师 · 3 年」（编制上不是该岗则不改）

| 允许（定向呈现） | 不允许 |
|------------------|--------|
| 真实公司 + 真实在职年限 | 伪造公司、拉长在职时间 |
| 真实岗位 title | 用从未担任的 title 充「对口年限」 |
| 篇幅倾斜：目标方向详写，弱相关略写/删细节 | 把非主业改写成「公司主职负责 Agent 业务线」（若不符） |
| 「个人项目 / 技术探索」块写 Agent 实战 | 把个人项目写成任职主责（若不符） |
| 技能区按目标岗排序，删掉无关技能 | 编造未掌握的技能词 |

原则：**雇主与任职事实不变；叙事焦点按目标岗裁剪。**

#### 其它规则

- 输入：简历正文 + 目标方向。  
- 审计：STAR、主栈清晰、约一页。  
- 缺量化 → 追问，不代填假数。  
- 输出：改前→改后 + **删减/弱化建议** + 关键词对照 + 缺口闭环。

### 2.2 目标职业蓝图模式（`target`）——允许「编」的边界

这里的「编」= **尚未兑现的课内项目话术蓝图**（规划学习用）；**不改任职事实、不伪造雇主**。

允许生成：

- 目标岗位下的**技能清单与模块结构**（求职意向、技能分层、项目标题骨架）  
- 基于**站内课程真实项目**（RAG101/CAREER201 等课内实战）的「完成后可这样写」的 STAR 示例  
- 与方向对齐的量化**占位符**（如「检索延迟从 __ ms 降到 __ ms」），标明待学员实战后填数  

必须同时做到：

1. **显式标注**：「以下为【目标蓝图】，完成对应学习与项目前请勿当作已有经历投递。」  
2. **每条蓝图项目 ↔ 可执行学习动作**：推荐课程模块 / 练习题 / 模拟面试主题。  
3. **禁止**编造不存在的公司名、虚假在职时间、无法溯源的「大厂实习」。蓝图项目应挂在「课程实战 / 个人项目 / 学习项目」名下。  

```
fact：  真实材料 ──优化──► 可投递简历片段
target：目标方向 ──生成──► 蓝图简历 + 学习闭环（课 / 题 / 面）
              └──► 学员完成学习后，把蓝图条目「兑现」进 fact 模式再精修
```

### 2.3 模式如何选定

优先级：

1. 学员明示：「按真实经历改」/「按我想做的 XX 方向编一版目标简历」  
2. 有长文本简历且未提目标蓝图 → 默认 `fact`  
3. 只说「我想做 RAG 工程师，简历该长什么样」且无真实项目 → `target`  
4. 含糊 → 追问一句二选一（编号选项）

画像：`target` 模式下应用 `update_student_profile(target_role=...)`。

---

## 3. 学习闭环（课 / 题 / 面）

两种模式在发现缺口后，都要给出**可执行闭环**；`target` 模式为强约束（无闭环不算完成）。

```
ResumeAgent（本 Agent）
  │  产出：简历建议 / 蓝图条目 + gap 列表
  │
  ├─► 课程推荐
  │     工具：get_next_recommendations / get_available_modules
  │     或缺口 skill → skill_mapping.module_id（同 JobMatch）
  │     也可 secondary 派 RecommendAgent（多意图）
  │
  ├─► 题目练习
  │     本阶段：按弱项知识点给出「练习主题清单」+ 若有题库则挂 quiz
  │     （resources 题库 / quiz_attempts；无题则给可自练题干模板）
  │
  └─► 模拟面试
        本阶段：给出「建议开练的面试主题 / role_id」
        InterviewAgent 接通后：可 secondary 派发或引导「回复：开始模拟面试」
```

| 闭环项 | 本阶段（Resume 内可做） | 依赖其他 Agent |
|--------|-------------------------|----------------|
| 课程 | 列出 module_id + 一句话理由（读 recommend 工具或 skill_mapping） | 复杂路径可派 `recommend_agent` |
| 练习 | 按缺失技能出 3～5 道练习题干或知识点清单 | 有 quiz 数据时再挂工具 |
| 面试 | 建议 `role_id` + 3～5 个必问主题 | `interview_agent` 接通后一键开练 |

Supervisor 多意图（编码阶段）：

- `target` 且缺口大 → primary=`resume_agent`，secondary 可选 `recommend_agent`  
- 学员说「按蓝图开始面试」→ `interview_agent`（占位期给明确「开发中 + 题单自练」）

---

## 4. 端到端流程（证据驱动）

```
学员消息 + 简历正文
  → parse_resume（事实底稿）
  → sync_resume_profile（画像）
  → build_resume_direct_brief（JobMatch：role + skill_gap + keep/compress）
  → research_target_role_signals（有目标岗：公开网络侧重点；失败降级站内）
  → get_resume_feedback（覆盖矩阵 + 价值提炼；点评用）
  → optimize_resume_document（整页终稿 + 密度门禁 + artifact）
       → practice_topics / interview_focus / open_questions
  → 聊天：结论 + 改前改后样例 + 练题/面试点 + 追问（不贴终稿全文）
```

**定向优化**：有 `target_role` / `role_id` 时，JobMatch 层必用；网络层指导「写透/压缩」主题，**禁止**把网文写成学员事实。

## 5. 架构与工具

```
┌──────────────────────────────────────────────────────────────┐
│ ResumeAgent                                                   │
│ Prompt：质量优先 + 证据态 + 定向 + 课练面上游                  │
│                                                              │
│ parse / sync_profile / build_direct_brief / research_signals │
│ get_resume_feedback / optimize_resume_document（主路径）       │
│ compose（仅合格完整 JSON）+ JobMatch/Recommend 工具           │
└──────────────────────────────────────────────────────────────┘
```

## 6. 输出骨架

### 6.1 `fact` 模式

```markdown
## 模式：真实经历优化（定向呈现）
## 30 秒结论
## 定向说明（站内 + 公开侧重点：写透/压缩）
## 覆盖与致命问题
## 重点改写（改前 → 改后）
## 建议训练题（practice_topics）
## 建议面试深挖（interview_focus）
## 还需你补充 / 学习闭环
> 终稿见「查看优化简历」；非实时 ATS；未改任职事实。
```

### 6.2 `target` 模式

```markdown
## 模式：目标职业蓝图（非已有经历）
⚠️ 完成对应学习前勿当已有任职投递
## 目标方向说明 + 训练题/面试深挖/兑现表
## 建议学习顺序：课 → 练 → 面 → 回 fact 精修
> 蓝图终稿见「查看蓝图简历」
```

## 7. 路由

| 说法 | 模式 / Agent |
|------|----------------|
| 帮我改这份简历 + 正文 | `fact` / resume |
| 我想做 RAG，简历应该长什么样 | `target` / resume |
| 按目标方向编一版简历 + 学什么 | `target` / resume（含闭环） |
| 简历要注意什么（课知识） | qa |
| 还差什么课（只问差距） | jobmatch |
| 开始模拟面试 | interview（接通后） |

- 移出 `UNIMPLEMENTED_AGENTS`；去掉单字「简历」宽松命中。  
- 强信号增加：`目标简历`、`蓝图简历`、`编一版简历`、`理想简历`（进 `target`）。

## 8. 中文技术岗写法（两模式共用）

仍采用国内习惯：求职意向、主栈分层、产物导向 STAR、约一页、单栏 ATS 友好。  
方法论借鉴：resume-optimizer、resume-jd-optimizer-cn（证据态/覆盖矩阵/面试自洽）— **内化进 Prompt/工具，非运行时依赖**。  
`target` 的「可编」**不解除**对虚假公司/虚假在职的禁令。

## 9. 与 JobMatch / Recommend / Interview

| Agent | 分工 |
|-------|------|
| Resume | 材料形态（事实优化 or 蓝图）+ 发起闭环 |
| JobMatch | 进度 vs 技能覆盖的匹配度深挖 |
| Recommend | 复杂选课路径、人群差异化推荐 |
| Interview | 按 role 开练；蓝图里的 interview_topics 作为出题种子 |

避免重复：Resume 给「闭环清单」；学员要详细选课理由时可转 Recommend。

## 10. 已定决策

| 项 | 决定 |
|----|------|
| 双模式 | `fact` + `target` |
| `fact` 定向呈现 | **支持**：真实任职年限保留，正文主写目标方向（如 Agent）；弱相关经历压缩 |
| 底线 | 不改假公司/假在职/假 title；`target` 只编课内可兑现蓝图并标注 |
| 闭环 | 课 + 练习 + 面试；`target` 必选，`fact` 有缺口时也给 |
| 真实 JD | 下阶段 |
| 无方向 | 追问，不默认 |

## 11. 实现清单（确认后）

1. 定稿本文；更新 tools/resume.md  
2. Prompt 双模式 + 蓝图免责 + 闭环强制结构  
3. `build_resume_agent`：挂 profile、job_roles、parse、feedback、recommend 工具（+ 可选 skill_gap）  
4. Supervisor：双模式关键词；dispatch；多意图 secondary recommend  
5. Interview 占位期：输出「主题清单 + 开通后面试用」  
6. 验收：  
   - fact 定向：渲染 3 年 + Agent 项目 → 保留公司年限与真实 title，正文主写 Agent、渲染压缩  
   - fact：弱项目 → 改前改后  
   - target：蓝图带 ⚠️ + 课/练/面  
   - 「简历怎么写」→ qa  

## 12. 明确不做（本阶段）

- 协助生成用于欺骗 HR 的虚假在职履历  
- 真实招聘平台 JD  
- 文件上传导出（可后做）  
