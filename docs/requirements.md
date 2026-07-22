# AI 助教系统 — 需求与架构文档

> 状态：与代码同步修订中 | 最后更新：2026-07-15

---

## 1. 项目背景

**目标**：做一个 AI 助教，辅助和监测学生的学习状态，个性化调整课程内容，帮助学员从零基础学习到找到心仪的工作。

**学员画像**：
- 在校大学生 — 夯实基础，面向校招
- 在职人员 — 实用技能，跳槽/涨薪

**行业方向**：
- 最终目标：全行业覆盖
- 试点阶段：计算机/IT 类

**交互方式**：Web 学习平台

---

## 2. 核心功能（四大模块）

| 模块 | 功能 | 说明 |
|------|------|------|
| **智能答疑** | 基于课程内容的问答 | 向量检索 + LLM 生成，带来源引用 |
| **进度追踪** | 学习路径记录与分析 | 课时完成度、测验成绩、薄弱点识别、学习报告 |
| **个性化推荐** | 自适应学习路径 | 根据学员画像（在校/在职）、进度、水平差异推荐内容 |
| **就业辅导** | 岗位匹配 + 模拟面试 + 简历优化 | 技能差距分析、面试题练习、简历 ATS 建议 |

---

## 3. Agent 架构设计

### 3.1 协作模式：Hierarchical（层级调度）

采用 **Supervisor + 子 Agent** 的层级调度模式。学员统一与 Supervisor 对话，Supervisor 自动分析意图并路由到对应子 Agent，子 Agent 之间共享上下文。

```
                        学员
                         │
                    Supervisor Agent
                    （意图分析 + 任务分解 + 结果汇总）
                         │
        ┌────────┬───────┼───────┬──────────┬──────────┐
        │        │       │       │          │          │
        ▼        ▼       ▼       ▼          ▼          ▼
   QAAgent   Progress  Recommend  JobMatch  Resume   Interview
   (答疑)    Agent     Agent      Agent     Agent    Agent
            (进度)    (推荐)     (岗位匹配) (简历)   (模拟面试)
```

### 3.2 六个子 Agent 职责

| Agent | 职责 | 典型场景 |
|------|------|------|
| **QAAgent** | 课程检索 + 知识解答 + 来源引用 + 追问理解 | "什么是哈希表？" |
| **ProgressAgent** | 进度查询 + 测验批改 + 学习报告 + 懈怠预警 | "我这周学了多少？" |
| **RecommendAgent** | 下一课推荐 + 薄弱点补充 + 难度调整 + 人群差异化 | "学完 Python 基础后该学什么？" |
| **JobMatchAgent** | 岗位匹配 + 技能差距分析 + 补课路线图 | "我离后端开发还差什么？" |
| **ResumeAgent** | ATS 扫描 + 结构建议 + 内容优化 + 岗位定制 | "帮我看看这份简历" |
| **InterviewAgent** | 出题 + 追问 + 逐题评分 + 复盘报告 | "来一场后端面试" |

### 3.3 就业辅导细分逻辑

```
准备期 ────────→ 投递期 ────────→ 面试期
  │                 │                 │
JobMatchAgent   ResumeAgent     InterviewAgent
"我还差什么？"   "简历怎么改？"    "来模拟面试/复盘"
```

### 3.4 记忆策略（LangGraph 标准两层模型）

| 层 | 技术 | 后端 | 记什么 | 生命周期 |
|------|------|------|------|------|
| **短期（Checkpointer）** | `RedisSaver`（LangGraph 原生） | Redis Stack | 当前会话完整对话 + Agent 执行状态 + 中间推理步骤 | 会话结束可清除，支持断点恢复 |
| **长期（Store）** | LangGraph Store API + Redis Stack | Redis Stack | 薄弱点、知识状态、学习偏好、职业线路、跨会话摘要 | 永久累积 |

**Store 命名空间设计**：
```
["students", {id}, "weak_areas"]    → 薄弱知识点及频次
["students", {id}, "preferences"]   → 学习偏好（节奏、风格）
["students", {id}, "knowledge"]     → 已掌握知识点图谱
["students", {id}, "summaries"]     → 历次会话摘要
```

### 3.5 Supervisor 实现策略

**正式方案**：手写 LangGraph `StateGraph`（probe → decide → dispatch → aggregate → recovery），证据驱动路由 + 业务优先闲聊分流。不使用 `create_supervisor()` 黑盒。

详见 [Supervisor 设计](architecture/agents/supervisor.md)、[总体架构](architecture/overview.md)。

### 3.6 工具清单

#### QAAgent（智能答疑）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `search_course_content` | `query: str, top_k: int = 5` | `list[{content, module_id, lesson_id, title, score}]` | 从向量库检索课程内容 |
| `get_lesson_content` | `module_id: str, lesson_id: str` | `str` | 获取指定课程完整原文 |
| `get_qa_history` | `student_id: int, limit: int = 10` | `list[{question, answer}]` | 查历史问答记录，用于追问理解 |

#### ProgressAgent（进度追踪）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_student_progress` | `student_id: int` | `{total_lessons, completed, completion_pct}` | 整体学习进度 |
| `get_quiz_history` | `student_id: int` | `list[{module_id, score, weak_areas}]` | 测验记录+薄弱点 |
| `get_weak_areas` | `student_id: int` | `list[{topic, error_count}]` | 聚合薄弱点，按频次排序 |
| `get_strong_areas` | `student_id: int` | `list[{topic, score_avg}]` | 掌握较好的模块 |
| `get_study_streak` | `student_id: int` | `{current_streak, days_since_last}` | 学习连续天数+懈怠检测 |
| `generate_progress_report` | `student_id: int` | `ProgressReport (Pydantic)` | 结构化学习报告 |

#### RecommendAgent（个性化推荐）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_available_modules` | `industry, skill_level, type=None` | `list[{module_id, title, difficulty, type}]` | 可选模块列表 |
| `get_next_recommendations` | `student_id, count=5` | `list[{module_id, title, reason, priority, source}]` | 综合推荐，source 标注推荐来源 |
| `get_prerequisite_modules` | `module_id, student_id` | `list[{module_id, title, completed}]` | 前置模块及完成状态 |

#### JobMatchAgent（岗位匹配）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_job_roles` | `industry: str` | `list[{role_id, title, required_skills, salary_range}]` | 目标岗位列表 |
| `analyze_skill_gap` | `student_id, role_id` | `{match_pct, mastered, gaps: [{skill, module}]}` | 匹配度+补课路线图 |
| `get_industry_trends` | `industry: str` | `str` | 行业趋势（后期接招聘数据源） |

#### ResumeAgent（简历优化）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `parse_resume` | `text: str` | `{sections, skills_found, years, education, projects}` | 解析简历结构（支持 Word/PDF/粘贴文本，文件格式由 UI 层预处理） |
| `get_resume_feedback` | `text: str, role_id: str` | `{ats_score, missing_keywords, structural_suggestions, content_suggestions}` | ATS 检查+改进建议 |

#### InterviewAgent（模拟面试）

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_interview_questions` | `role_id, difficulty, count=5` | `list[{question_id, text, type, expected_topics}]` | 面试题库出题 |
| `evaluate_answer` | `question, answer, role_id` | `{score, strengths, weaknesses, model_answer}` | 逐题评分（后台进行，不打断对话） |
| `generate_interview_report` | `session_id` | `{total_score, by_question, overall_feedback, improvement_plan, offer}` | 复盘报告（含模拟 Offer） |
| `save_interview_session` | `student_id, role_id, questions, answers` | `session_id` | 保存面试记录 |

**面试流程**：自然对话式，不分"第N题"。三个阶段：面试官提问→学员反问→模拟Offer。支持多模态输入（代码块/图片/语音，UI层预处理）。

#### 共享工具（Supervisor级，所有Agent可用）

| 工具 | 说明 |
|------|------|
| `get_student_profile` | 学员完整画像 |
| `get_student_progress` | 学习进度统计（同 ProgressAgent 调用的工具） |
| `get_career_paths` | 查看所有职业线路 |
| `switch_career_path` | 切换主方向 |
| `follow_career_path` | 关注新线路（先概述，确认后加） |
| `archive_career_path` | 放弃线路，保留已学记录 |
| `add_self_pick_module` | 添加零散课程 |
| `get_self_pick_modules` | 查看零散课程 |
| `get_long_term_memory` | Redis 读历史 |
| `set_long_term_memory` | Redis 写入 |

### 3.7 情感系统

**6 种核心情感状态**，由 Supervisor 在分析用户意图时同步判断：

| 情绪 | 触发条件 | Agent 响应策略 |
|------|------|------|
| `frustrated` | 连续答错、长时间卡壳 | 降难度、给提示、先鼓励 |
| `bored` | 回复敷衍、频繁跳过、节奏慢 | 换讲法、加入互动或小测验 |
| `anxious` | "我学不会""太难了"等措辞 | 安抚情绪 + 给简单任务重建信心 |
| `confident` | 连续正确、答题快 | 适当加难度、给挑战 |
| `disengaged` | 一周未登录、消息间隔长 | 提醒鼓励、给低门槛小目标 |
| `accomplished` | 完成里程碑、项目交付 | 正向强化、推荐类似挑战 |

**实现方式**：
- 情感判断由 DeepSeek 在 Supervisor 层完成（零额外模型成本）
- 情感状态写入 Store：`["students", {id}, "emotion"]` → `{state, trigger, trend, updated_at}`
- 子 Agent 收到路由指令时附带情感标签，调整回复风格
- 情感趋势用于长期学习画像（如"该学员在算法模块频繁焦虑，建议调整课程顺序"）

### 3.8 LLM 抽象层

在 Agent 与具体模型之间加一层适配层，支持后续接入多个大模型：

```
Agent ─→ LLMProvider (抽象接口)
              │
     ┌────────┼────────┐
     │        │        │
  DeepSeek  OpenAI  Anthropic  ...
```

| 方法 | 说明 |
|------|------|
| `get_model(temperature)` | 返回 LangChain BaseChatModel |
| `embed(texts)` | 文本向量化 |
| `analyze_emotion(text)` | 情感分析 |
| `get_coach_prompt(style)` | 导师人格 Prompt 片段 |

MVP 阶段只实现 DeepSeek Provider，但接口预留扩展点。

### 3.9 导师人格

4 种导师人格，学员通过"切换人格"关键词进入选择流程（不通过随口评价触发切换）。

| 人格 | 风格 | 适合学员 |
|------|------|------|
| `encouraging` | 温柔鼓励型 | 初学者、容易焦虑 |
| `pushing` | 严厉驱动型 | 自觉性差、需要鞭策 |
| `humorous` | 幽默风趣型 | 轻松学习、不喜欢说教 |
| `professional` | 专业简洁型 | 在职人员、时间紧 |

**切换流程**：学员说"切换人格"→ Agent 展示 4 种人格简介 → 学员选择 → 更新 `students.coach_style`。

**后期规划**：通过真人导师对话数据，Fine-tune 出项目专属人格（非 Prompt 工程方式）。

同一情绪 + 不同人格 = 不同回应策略。实现位置：`src/llm/base.py` — `CoachStyle` 枚举 + `COACH_STYLE_PROMPTS`。

### 3.9 UI 交互

- **学员侧**：统一聊天界面（Vue 3 + FastAPI），与 Supervisor 对话，背后自动调度子 Agent
- **不设独立 Tab 入口**：Agent 切换对学员透明

### 3.9 MCP 策略

| 阶段 | 方案 |
|------|------|
| **MVP** | 工具通过 LangChain `@tool` 装饰器注册，直接函数调用 |
| **正式** | 每个 Agent 的工具集封装为独立 MCP Server，支持独立部署、灰度发布、故障隔离 |

MVP 阶段每个工具集设计为独立类，预留 MCP 接口，后续切换不动内部逻辑。

### 3.10 招聘数据

---

## 4. 技术栈

| 层面 | 选型 | 说明 |
|------|------|------|
| LLM | DeepSeek Chat | OpenAI 兼容接口 |
| Agent 框架 | LangChain + LangGraph | 手写 StateGraph Supervisor + ReAct 子 Agent |
| 向量存储 | Milvus Lite（MVP）/ Docker Milvus（生产） | |
| Embedding | BAAI/bge-large-zh-v1.5 | 1024 维；经 **EmbeddingProvider**（**默认 local GPU**；可选 http→TEI） |
| Reranker | BAAI/bge-reranker-v2-m3 | 经 **RerankerProvider**（**默认 local**；可选 http→TEI） |
| 图数据库（Graph RAG） | Neo4j | 待实现 |
| 长期记忆 | Redis Stack | Checkpointer + RedisJSON Store；宿主端口 **6380** |
| Web UI | Vue 3 + Vite + FastAPI | ChatGPT 风格 |
| ORM | SQLAlchemy | SQLite |
| 推理部署 | 可插拔：local（默认）/ TEI(http) / algo | 见 docs/architecture/inference-services.md |

---

## 5. 现有环境

| 组件 | 位置 | 版本 |
|------|------|------|
| Python venv | `f:\agent\.venv\` | 3.13.12 |
| 包管理 | Poetry | 2.4.1 |
| DeepSeek Key | `f:\agent\.env` | 已配置 |
| Redis Stack | Docker (`redis-stack`) | 7.4.2 |
| Docker | 全局 | 29.6.1 |
| LangChain 全家桶 | Poetry 管理 | 1.x 系列 |

---

## 6. 依赖清单

所有依赖由 Poetry 统一管理，见 `pyproject.toml` 和 `poetry.lock`。

---

## 7. 课程内容格式

### 核心原则：零硬编码

课程内容全部由资源目录下的文件驱动，系统不内置任何课程数据。课程模块、技能映射、测验题目、面试题库均从文件读取。

### 7.1 资源目录结构

采用扁平化结构，文件按 `章节号 + 标题` 命名。索引器从文件名自动解析章节信息，无需手动维护单节元数据。

```
resources/
├── courses/
│   └── {course_id}/
│       ├── index.json                  # 课程级别：课程名、行业、难度
│       ├── 第1章 xxx/
│       │   ├── module.json             # 章节级别：本章难度、标签、前置依赖
│       │   ├── 1-1 课程标题.doc        # 讲义 → 提取文本 → 索引
│       │   ├── 1-1 课程标题.mp4        # 视频 → 不索引，文件名关联
│       │   └── ...
│       └── 第2章 xxx/
│           ├── module.json
│           ├── 2-1 课程标题.doc
│           ├── 2-1 课程标题.mp4
│           ├── ...
│           └── 2-7 补充文档.pdf        # PDF → 提取文本 → 索引
│
├── job_roles/
│   └── {industry}/
│       └── roles.json                  # 岗位定义 + 技能要求
│
└── interviews/
    └── {role_id}/
        └── questions.json              # 面试题库
```

**索引规则**：

| 文件类型 | 是否索引 | 说明 |
|------|:--:|------|
| `.doc` 讲义 | ✅ | 提取文本 → 分块 → Embedding → Milvus |
| `.pdf` 补充文档 | ✅ | 同上 |
| `.mp4` 视频 | ❌ | 不索引，通过文件名与对应讲义关联，UI 层播放 |

**元数据来源**：文件名解析（章节号、标题）+ 章节 `module.json`（难度、标签、前置、适合人群）+ LLM 自动补全标签。

### 7.2 自动发现机制

系统启动时扫描 `resources/courses/` 目录，自动：
1. 读取各课程 `index.json` → 注册课程
2. 读取各章节 `module.json` → 注册章节元数据
3. 读取 `roles.json` → 注册岗位定义
4. 将所有 `.doc` 和 `.pdf` 文件提取文本、分块、Embedding、写入 Milvus

新增课程只需在 `resources/courses/` 下放入对应文件，无需修改任何代码。

### 7.3 index.json 格式

```json
{
  "course_id": "RAG101",
  "title": "RAG全栈技术从基础到精通，打造高精准AI应用",
  "industry": "computer_it"
}
```

### 7.4 module.json 格式

每章一个，字段精简，覆盖整章所有节：

```json
{
  "difficulty": "beginner",
  "tags": ["RAG", "检索", "生成", "Embedding"],
  "prerequisites": [],
  "persona_target": "all",
  "estimated_hours": 4
}
```

### 7.5 首期课程

**RAG101 — RAG 全栈技术从基础到精通，打造高精准 AI 应用**。课程资源已部分就位（第 1-2 章），后续章节持续追加。

**quiz.json**：选择题 + 填空题，每题标注 `topic` 和 `difficulty`。

**roles.json**：岗位列表，每个岗位含 `required_skills` 和 `preferred_skills`，与课程模块通过 `skill_mapping` 表关联。

---

## 8. 数据模型概览（7 张表）

| 表 | 用途 |
|------|------|
| students | 学员档案（在校/在职区分） |
| learning_progress | 逐课进度 |
| quiz_attempts | 测验记录 + 薄弱点 |
| qa_history | 问答日志 |
| course_modules | 课程模块元数据 |
| job_roles | 目标岗位定义 |
| interview_sessions | 模拟面试记录 |

---

## 9. UI 布局

ChatGPT 风格深色主题，Vue 3 + Vite 构建，FastAPI 后端。

- 左侧栏：功能入口 + 历史对话 + 学员信息
- 主区域：统一聊天界面，Markdown 渲染，来源标注
- 后端通过 POST /api/chat/ 调用 Supervisor 路由到子 Agent

详见 [Web UI 设计文档](architecture/ui/index.md)

---

## 11. 实施阶段（TBD）

大致顺序：基础设施 → 课程内容+向量库 → 智能答疑 → 进度追踪 → 个性化推荐 → 就业辅导（三个子 Agent）→ Supervisor 集成联调

---

## 12. 待处理项目

- [x] JobMatchAgent — 站内课程覆盖匹配 MVP（见 architecture/agents/jobmatch.md）
- [x] ResumeAgent — fact/target + 定向呈现（见 architecture/agents/resume.md）
- [x] InterviewAgent — 文字 + ASR/TTS + 全屏面试场 P0 已联调（见 architecture/ui/interview-multimodal.md；开发态 DEBUG 文字入口）
- [ ] 真人导师数据 Fine-tune 专属人格（后期，非 MVP）
- [ ] Graph RAG（Neo4j 知识图谱）
- [ ] WebSearch 兜底接入
- [x] SSE 流式输出（聊天主路径 `/api/chat/stream`；见 `docs/architecture/ui/chat-stream.md`）
- [ ] 前端后端联调
- [ ] 课程资源准备（后续章节内容）
