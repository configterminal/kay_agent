"""
转写 / docx 共用的 ASR 修正规则。

- AUTO_FIX：高置信，直接替换
- FLAG_ONLY：低置信，仅 convert_docx 插入 <!--⚠️ --> 供人工审核
"""

from __future__ import annotations

import re

# 高置信 → 自动替换（两边脚本共用）
# 注意：复合误听必须写在「独立 rig」之前，否则 GraphRIG 等不会被修到
AUTO_FIX: list[tuple[str, str]] = [
    # RAG 复合误听（Whisper 常把 RAG 听成 RIG，并粘在前后词上）
    # 更长的模式必须在前
    (r"Advanced\s*RIG", "Advanced RAG"),
    (r"Graph\s*RIG", "Graph RAG"),
    (r"Safe\s*RIG", "Self-RAG"),
    (r"Self\s*RIG", "Self-RAG"),
    (r"Light\s*RIG", "LightRAG"),
    (r"Table\s*RIG", "TableRAG"),
    (r"Open\s*RIG", "OpenRAG"),
    (r"Visual\s*RIG", "Visual-RAG"),
    (r"Rig\s*Pub\s*Line", "RAG Pipeline"),
    (r"Rig\s*Pub\s*Lang", "RAG Pipeline"),
    (r"Rig\s*Pub\s*Lender", "RAG Pipeline"),
    (r"Rig\s*Pyper\s*Line", "RAG Pipeline"),
    (r"Rig\s*Pipeline", "RAG Pipeline"),
    (r"rigpublender", "RAG Pipeline"),
    (r"Rig\s*Rooter", "RAG Router"),
    (r"rig\s*root", "RAG Router"),
    (r"Rig\s*Flow", "RAGFlow"),
    (r"rigflow", "RAGFlow"),
    (r"Rig\s*Chain", "LangChain"),  # 课程语境下常见
    (r"RAG\s*Looter", "RAG Router"),  # Router 误听
    (r"Looter", "Router"),  # 路由场景常见误听；若误伤极少专有名词可再收紧
    (r"CF\s*RIG", "Self-RAG"),
    (r"(?<![a-zA-Z])FRIG(?![a-zA-Z])", "Self-RAG"),
    (r"RIGAS", "Ragas"),
    (r"(?<![a-zA-Z])riga(?![a-zA-Z])", "RAG"),
    (r"(?<![a-zA-Z])rigdb(?![a-zA-Z])", "ragdb"),
    # 英文术语（CJK 友好边界，避免误伤单词内部）
    (r"(?<![a-zA-Z])rig(?![a-zA-Z])", "RAG"),
    (r"(?<![a-zA-Z])reg(?![a-zA-Z])", "RAG"),
    (r"OPenAi", "OpenAI"),
    (r"deep\s*seek", "DeepSeek"),
    (r"\blamer\b", "LLaMA"),
    (r"LA\s*mer", "LLaMA"),
    (r"line\s*chain", "LangChain"),
    (r"p\s*touch", "PyTorch"),
    (r"g\s*radio", "Gradio"),
    (r"near\s*for\s*z", "Neo4j"),
    (r"jupiter\s*note", "Jupyter Notebook"),
    (r"(?<![a-zA-Z])jupiter(?![a-zA-Z])", "Jupyter"),
    (r"ra'g", "RAG"),
    # 中文常见误听
    (r"待遇模型", "大语言模型"),
    (r"大圆模型", "大语言模型"),
    (r"大元模型", "大语言模型"),
    (r"大于模型", "大语言模型"),
    (r"单元模型", "大语言模型"),
    (r"代元模型", "大语言模型"),
    (r"大圆模", "大语言模"),
    (r"支持库", "知识库"),
    (r"上下网", "上下文"),
    (r"掐gpt", "ChatGPT"),
    (r"掐\s*gpt", "ChatGPT"),
]

# 低置信 → 仅 flag（视频转写不插入注释，避免污染逐字稿）
FLAG_ONLY: list[tuple[str, str]] = [
    (r"dream\s*nine", "dream nine → Gemini?"),
    (r"dream\s*1\s*[.]?\s*5", "dream 1.5 → Gemini 1.5?"),
    (r"dream\s*2\s*[.]?\s*0", "dream 2.0 → Gemini 2.0?"),
    (r"km\s*it", "km it → Kimi?"),
    (r"\bg\s*bd\b", "g bd → GPT?"),
    (r"\bg\s*b[dt]\b", "gbt/gbd → GPT?"),
    (r"gha\s*PC", "gha PC → ChatGPT?"),
    (r"opal\s*on", "opal on → OpenAI?"),
    (r"(?<![a-zA-Z])cord\s*3(?![a-zA-Z])", "cord 3 → Cohere / Claude 3?"),
]


def apply_auto_fix(text: str) -> str:
    """应用高置信替换。"""
    for pattern, replacement in AUTO_FIX:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def apply_fix_and_flag(text: str) -> str:
    """高置信替换 + 低置信 HTML 注释（供 docx 遗留路径）。"""
    text = apply_auto_fix(text)
    for pattern, note in FLAG_ONLY:
        def _repl(m: re.Match, _note: str = note) -> str:
            return f"{m.group()}<!--⚠️ {_note}-->"

        text = re.sub(pattern, _repl, text, flags=re.IGNORECASE)
    return text
