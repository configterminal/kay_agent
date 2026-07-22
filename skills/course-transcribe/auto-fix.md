# Auto-Fix 规则表

权威实现：[`scripts/auto_fix_rules.py`](scripts/auto_fix_rules.py)  
`transcribe_video.py` 与 `convert_docx.py` **共用**该文件，勿在两边各写一份。

## 两档规则

| 档位 | 行为 | 谁用 |
|------|------|------|
| `AUTO_FIX` | 高置信，直接替换 | 视频转写 + docx |
| `FLAG_ONLY` | 低置信，保留原文并加 `<!--⚠️ …-->` | **仅** docx 遗留路径（避免污染逐字稿） |

## 已收录（摘要）

**英文 / RAG 误听**：
- 复合（须优先于独立词）：`GraphRIG` → `Graph RAG`；`AdvancedRIG` → `Advanced RAG`；`SafeRIG`/`SelfRIG`/`FRIG` → `Self-RAG`；`RIGAS` → `Ragas`；`RigPubLine`/`RigPyperLine` → `RAG Pipeline`；`RigRooter` → `RAG Router`；`RigFlow` → `RAGFlow`；`LightRIG` → `LightRAG` 等
- 独立：`rig`/`reg`/`riga` → `RAG`；`Looter` → `Router`（路由误听）
- 其它：`lamer`/`LA mer` → LLaMA；`line chain` → LangChain；`p touch` → PyTorch；`g radio` → Gradio；`near for z` → Neo4j；`jupiter` → Jupyter；`deep seek` → DeepSeek；`OPenAi` → OpenAI 等

**中文**：`大圆/大元/大于/单元/代元/待遇模型` → 大语言模型；`支持库` → 知识库；`上下网` → 上下文；`掐gpt` → ChatGPT。

**已移除**：裸 `ig` → RAG（误伤风险）；noop `检索犯绝`。

**根因说明**：Whisper 常把「RAG」听成「RIG」。旧规则只替换独立 `rig`，`GraphRIG` / `RIGAS` 因字母粘连匹配不到——属**脚本规则覆盖不全**，不是没跑修正。

## 如何新增

只改 `scripts/auto_fix_rules.py`：

```python
AUTO_FIX: list[tuple[str, str]] = [
    # ...
    (r"错误写法", "正确写法"),
]
```

不确定的写进 `FLAG_ONLY`，不要放进 `AUTO_FIX`。
