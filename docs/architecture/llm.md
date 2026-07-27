# LLM 抽象层 (src/llm/)

```
Agent / Supervisor / RAG
       │
       ▼
┌─────────────────────────────────────────────┐
│         LLMProvider（抽象基类）               │
│                                             │
│  + get_model(temperature) → BaseChatModel   │
│  + embed(texts) → list[list[float]]         │
│  + analyze_emotion(text) → EmotionResult    │
│  + get_coach_prompt(style) → str            │
│                                             │
│  工厂方法：create(provider) → LLMProvider    │
└─────────────────────────────────────────────┘
       │
       ├── DeepSeekProvider（✅ 已实现）
       │   ├── ChatDeepSeek（云端对话 / 情绪 / 路由 / 重写）
       │   └── embed() → EmbeddingProvider（见推理抽象层）
       │
       ├── OpenAIProvider（部分实现：ChatOpenAI get_model() 可用，analyze_emotion() 未实现）
       └── AnthropicProvider（预留）
```

## 边界说明

| 能力 | 实现位置 |
|------|----------|
| Chat / 结构化路由 / 查询重写 / 情绪 | DeepSeek API |
| 文本向量化 | `embed()` **委托** [EmbeddingProvider](inference-services.md)（http / local / algo） |
| 导师人格 Prompt | `CoachStyle` + `get_coach_prompt` |

精排（Rerank）不在 LLMProvider 内，见 `vectordb/reranker.py` → [RerankerProvider](inference-services.md)。
