# Auto-Fix 规则表

转写时自动修正以下已知语音识别错误。可自行扩充此表。

## 英文术语

| 错误写法 | 正确写法 | 错误来源 |
|---|---|---|
| `rig`, `reg`, `ig` | `RAG` | 语音识别 |
| `lamer` | `LLaMA` | 同音 |
| `LA mer` | `LLaMA` | 同音拆分 |
| `line chain` | `LangChain` | 音译 |
| `p touch` | `PyTorch` | 音译 |
| `g radio` | `Gradio` | 音译 |
| `near for z` | `Neo4j` | 音译 |
| `jupiter` | `Jupyter` | 音译 |
| `OPenAi` | `OpenAI` | 大小写 |
| `deep seek` | `DeepSeek` | 拆分 |
| `ra'g` | `RAG` | 标点插入 |

## 中文术语

| 错误写法 | 正确写法 | 错误来源 |
|---|---|---|
| `大圆模型`, `大元模型`, `大于模型` | `大语言模型` | 音似 |
| `单元模型`, `代元模型` | `大语言模型` | 音似 |
| `支持库` | `知识库` | 音似 |
| `上下网` | `上下文` | 音似 |
| `掐gpt` | `ChatGPT` | 音译 |

## 如何新增规则

编辑 `skills/course-transcribe/scripts/transcribe_video.py` 中的 `AUTO_FIX` 列表：

```python
AUTO_FIX: list[tuple[str, str]] = [
    # ... 现有规则 ...
    (r'新错误写法', '正确写法'),
]
```

同样，`convert_docx.py` 中有对应的 `AUTO_FIX` 和 `FLAG_ONLY` 列表。
`FLAG_ONLY` 用于不确定项——保留原文并插入 `<!--⚠️ -->` HTML 注释供人工审核。
