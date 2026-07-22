# RAGAS 自动评测方案（后续启用）

> 状态：**方案就绪，待准备数据集后接入** | 最后更新：2026-07-21  
> 关联：[course-scope-dialogues.md](../rag/course-scope-dialogues.md) · [performance.md](../performance.md) · 课程作用域 [course-scope.md](../rag/course-scope.md)

## 1. 目标

用 [RAGAS](https://docs.ragas.io/) 对 **QA / 检索答疑** 做可重复的自动回归，覆盖：

1. **忠实度 / 相关性**：回答是否基于检索上下文、是否答到问题  
2. **课程作用域**：多轮代称、换题不串课（与 dialogues 样例对齐）  
3. **检索质量**：context precision / recall（有金标段落时）

不在首期用 RAGAS 评：面试 TTS、简历长链路、闲聊寒暄。

---

## 2. 评测分层

| 层 | 测什么 | 工具 | 频率 |
|----|--------|------|------|
| L0 单元 | `resolve_turn_course` / 代称落点 | `tests/test_course_scope_turn.py` | 每次改 scope 必跑 |
| L1 检索 | 单问 top_k 是否含金标 `section`/`media_path` | 自研 script + 可选 RAGAS Context* | 索引变更后 |
| L2 生成 | 单轮 QA：faithfulness / answer_relevancy | RAGAS | 日/周或发版前 |
| L3 多轮作用域 | dialogues 对话：每轮期望 `course_id` + 回答不否认「课内无此内容」误伤 | 编排脚本 + 轻量规则/RAGAS | 发版前 |

L0 已落地。L1–L3 按下面目录准备后启用。

---

## 3. 目录约定（建议）

```
f:/agent/
├── eval/
│   ├── README.md                 # 如何跑
│   ├── datasets/
│   │   ├── qa_single.jsonl       # 单轮：question / reference / course_id?
│   │   ├── qa_multiturn.jsonl    # 多轮：messages[] / expect_course_id[]
│   │   └── retrieval_gold.jsonl  # query / gold_sections[]
│   ├── runs/                     # 输出报告（gitignore）
│   └── scripts/
│       ├── run_ragas_single.py   # L2
│       ├── run_scope_multiturn.py# L3（可先规则，再挂 RAGAS）
│       └── run_retrieval_eval.py # L1
└── docs/architecture/eval/ragas-plan.md  # 本文件
```

`.gitignore` 增加：`eval/runs/`。

---

## 4. 数据集格式

### 4.1 单轮 `qa_single.jsonl`

```json
{
  "id": "rag-diff-01",
  "question": "RAG 和 Graph RAG 的区别是什么？",
  "reference": "……金标要点（可短）……",
  "expect_course_id": "RAG101",
  "gold_sections": ["10-06"],
  "tags": ["rag", "graph"]
}
```

### 4.2 多轮 `qa_multiturn.jsonl`（对齐 dialogues）

```json
{
  "id": "dlg-sample-9",
  "turns": [
    {"role": "user", "content": "三年程序员，什么时候跳比较合适？", "expect_course_id": "CAREER201"},
    {"role": "user", "content": "详细点", "expect_course_id": "CAREER201"},
    {"role": "user", "content": "对了我想问检索增强生成是啥", "expect_course_id": "RAG101"},
    {"role": "user", "content": "那个再展开说说", "expect_course_id": "RAG101"}
  ],
  "tags": ["anaphora", "cross-course"]
}
```

助手轮由系统实际生成；评测时只断言：

- 内部 `resolve_turn_course` / 日志中的 `course_id`（L3 主断言，便宜）  
- 可选：回答不得出现「本课是职业课、没有 RAG」类串课话术（正则黑名单）  
- 可选：RAGAS faithfulness（贵，抽样）

### 4.3 金标来源

- 优先：课程 `knowledge` / 转写 md 中人工摘录  
- 次选：现有 QAHistory 里人工标「好答」  
- 首批建议 **30～50 单轮 + 10 条多轮**（覆盖 sample 1/2/9/10/11）

---

## 5. RAGAS 指标（L2 建议）

| 指标 | 含义 | 备注 |
|------|------|------|
| `faithfulness` | 答案是否忠于 contexts | 需 LLM-as-judge（可用 DeepSeek） |
| `answer_relevancy` | 答案是否相关问题 | 同上 |
| `context_precision` | 检索上下文是否精准 | 有金标更好 |
| `context_recall` | 金标是否被召回 | 需 reference |

Judge 模型：与线上一致可用 `deepseek-chat`（OpenAI 兼容），在脚本里配 `ChatOpenAI(base_url=...)`，**勿把 key 写入仓库**。

阈值（首期建议，可调）：

- faithfulness ≥ 0.7  
- answer_relevancy ≥ 0.7  
- 多轮 expect_course_id **准确率 = 100%**（硬门槛）

---

## 6. 运行方式（规划）

```powershell
# L0（现已可跑）
& f:\agent\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,r'f:\agent'); ..."
# 或安装 pytest 后：
# pip install pytest --target f:\jupyter
# pytest tests/test_course_scope_turn.py -v

# L3 多轮作用域（待脚本）
# python eval/scripts/run_scope_multiturn.py --dataset eval/datasets/qa_multiturn.jsonl

# L2 RAGAS（待脚本 + 数据集）
# python eval/scripts/run_ragas_single.py --dataset eval/datasets/qa_single.jsonl --out eval/runs/
```

依赖（届时装到 `f:\jupyter`）：

```
pip install ragas datasets --target f:\jupyter
```

注意：RAGAS 会额外消耗 DeepSeek token；CI 可改为「仅 L0+L3 规则」，L2 夜间跑。

---

## 7. 与课程作用域的衔接

多轮评测 **必须** 调用与线上一致的路径：

- 优先：`resolve_turn_course(state, message)`（便宜、稳定）  
- 完整：`POST /api/chat/` 或 stream，再读日志 / 在 state 打点 `turn_course`

禁止只测「最终答案字符串像不像」，否则串课 bug 会漏（旧 bug 答案通顺但课错了）。

---

## 8. 启用清单（后续你准备测试时勾）

- [ ] 建 `eval/datasets/` 首批 jsonl（从 dialogues 抄多轮）  
- [ ] 实现 `run_scope_multiturn.py`（硬断言 course_id）  
- [ ] 实现 `run_ragas_single.py`（faithfulness 等）  
- [ ] `.gitignore` → `eval/runs/`  
- [ ] 文档：`eval/README.md` 一条龙命令  
- [ ] （可选）周报：指标掉点自动 diff 上次 `eval/runs/`

---

## 9. 非目标

- 不把 RAGAS 接到每次 `npm run dev`  
- 不做简历/面试全链路 RAGAS  
- 不在评测里启 Cosy TTS
