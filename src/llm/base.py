"""
LLM 抽象层 — 统一多模型调用接口。

Agent 不直接依赖具体模型，通过 LLMProvider 接口调用。
切换模型只需修改 .env 中 LLM_PROVIDER 的值。

扩展新模型：
  1. 继承 LLMProvider
  2. 实现 chat() / chat_with_tools() / embed() / analyze_emotion()
  3. 在 LLMProvider.create() 中注册
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.config import config


# ── 导师人格 ──────────────────────────────────────────

class CoachStyle(str, Enum):
    """导师人格 — 同一种情绪，不同人格给出不同回应"""
    ENCOURAGING = "encouraging"       # 温柔鼓励型
    PUSHING = "pushing"               # 严厉驱动型
    HUMOROUS = "humorous"             # 幽默风趣型
    PROFESSIONAL = "professional"     # 专业简洁型


# 人格 → System Prompt 注入片段
COACH_STYLE_PROMPTS = {
    CoachStyle.ENCOURAGING: (
        "你是温柔鼓励型的导师。"
        "语气温和、耐心，多用'没关系'、'慢慢来'、'你已经很棒了'等正向语言。"
        "学员沮丧时先共情安抚，学员完成时大方夸奖。"
    ),
    CoachStyle.PUSHING: (
        "你是严厉驱动型的导师。"
        "语气直接有力，推动学员走出舒适区。"
        "学员懈怠时鞭策提醒，学员找借口时不轻易放过。"
        "同时要让学员感受到你是在帮 ta 变强，而非打击 ta。"
    ),
    CoachStyle.HUMOROUS: (
        "你是幽默风趣型的导师。"
        "语气轻松活泼，可以适当吐槽、开玩笑、用网络梗。"
        "把枯燥的内容讲得好玩，让学员笑着学会。"
        "但注意不要过度玩梗而偏离教学内容。"
    ),
    CoachStyle.PROFESSIONAL: (
        "你是专业简洁型的导师。"
        "语气精炼干练，直击要点不啰嗦。"
        "用数据和事实说话，避免情绪化表达。"
        "适合时间紧、已经有一定基础的在职学员。"
    ),
}


def get_coach_prompt(style: str) -> str:
    """根据人格标识返回对应的 System Prompt 片段"""
    try:
        coach = CoachStyle(style)
    except ValueError:
        coach = CoachStyle.ENCOURAGING  # 默认温柔型
    return COACH_STYLE_PROMPTS[coach]


# ── 数据结构 ──────────────────────────────────────────

@dataclass
class EmotionResult:
    """情感分析结果"""
    state: str          # frustrated / bored / anxious / confident / disengaged / accomplished / neutral
    confidence: float   # 置信度 0-1
    evidence: str       # 判断依据（引用的原文关键词）


# ── 抽象基类 ──────────────────────────────────────────

class LLMProvider(ABC):
    """LLM 统一接口 — 所有 Provider 必须实现这些方法"""

    @abstractmethod
    def get_model(self, temperature: float | None = None) -> BaseChatModel:
        """返回 LangChain BaseChatModel 实例，供 Agent 使用"""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化 — 返回 embedding 列表"""
        ...

    @abstractmethod
    def analyze_emotion(self, text: str) -> EmotionResult:
        """分析文本中的学员情绪"""
        ...

    # ── 工厂方法 ──────────────────────────────────────

    @staticmethod
    def create(provider: str | None = None) -> "LLMProvider":
        """工厂方法 — 根据配置创建对应的 Provider 实例"""
        provider = provider or config.llm_provider
        match provider:
            case "deepseek":
                return DeepSeekProvider()
            case "openai":
                return OpenAIProvider()
            case "anthropic":
                return AnthropicProvider()
            case _:
                raise ValueError(f"不支持的 LLM Provider: {provider}")


# ── DeepSeek 实现 ─────────────────────────────────────

class DeepSeekProvider(LLMProvider):
    """DeepSeek Chat — 基于 langchain-deepseek 原生 SDK"""

    def __init__(self):
        cfg = config.deepseek
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url
        self.chat_model = cfg.chat_model
        self.temperature = cfg.temperature

    def get_model(self, temperature: float | None = None) -> BaseChatModel:
        """返回 ChatDeepSeek 实例"""
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=self.chat_model,
            api_base=self.base_url,
            api_key=self.api_key,
            temperature=temperature if temperature is not None else self.temperature,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化 — 委托 EmbeddingProvider"""
        from src.vectordb.inference import get_embedding_provider
        return get_embedding_provider().embed(texts)

    def analyze_emotion(self, text: str) -> EmotionResult:
        """用 DeepSeek 分析学员文本情绪"""
        model = self.get_model(temperature=0)
        prompt = _build_emotion_prompt(text)
        response = model.invoke(prompt)
        return _parse_emotion_response(response.content)


# ── 预留 Provider ─────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """OpenAI — 预留实现"""

    def __init__(self):
        cfg = config.openai
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url
        self.chat_model = cfg.chat_model
        self.temperature = cfg.temperature

    def get_model(self, temperature: float | None = None) -> BaseChatModel:
        return ChatOpenAI(
            model=self.chat_model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=temperature if temperature is not None else self.temperature,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        from src.vectordb.inference import get_embedding_provider
        return get_embedding_provider().embed(texts)

    def analyze_emotion(self, text: str) -> EmotionResult:
        raise NotImplementedError("OpenAI 情感分析待实现")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude — 预留实现"""

    def __init__(self):
        cfg = config.anthropic
        self.api_key = cfg.api_key
        self.chat_model = cfg.chat_model
        self.temperature = cfg.temperature

    def get_model(self, temperature: float | None = None) -> BaseChatModel:
        raise NotImplementedError("Anthropic Provider 待实现（需 langchain-anthropic）")

    def embed(self, texts: list[str]) -> list[list[float]]:
        from src.vectordb.inference import get_embedding_provider
        return get_embedding_provider().embed(texts)

    def analyze_emotion(self, text: str) -> EmotionResult:
        raise NotImplementedError("Anthropic 情感分析待实现")


# ── 情感分析辅助 ──────────────────────────────────────

def _build_emotion_prompt(text: str) -> str:
    """构建情感分析 prompt"""
    return f"""分析以下学员消息中蕴含的情绪状态，从以下 7 种中选一个最匹配的：

- frustrated（沮丧）：对具体任务感到挫败，如代码跑不通、题目一直错
- bored（无聊）：敷衍、跳过内容、不想继续当前任务
- anxious（焦虑）：对自身能力或未来的担忧，如怕学不会、怕找不到工作
- confident（自信）：回答快速正确、主动要求挑战、拒绝提示
- disengaged（懈怠）：长时间未学、缺乏动力、随便看看
- accomplished（成就）：完成了目标或项目，主动分享成果
- neutral（中性）：普通知识问答，无明显情绪

区分要点：
- frustrated 针对具体任务，anxious 针对自身能力或未来。如"这题太难了"=frustrated，"我学不会"=anxious。
- bored 是"这太简单没意思"，disengaged 是"没动力不想学"。前者已有能力只是无趣，后者是放弃状态。
- 如果不确定，选最接近的那个，confidence 给 0.5-0.7。

返回 JSON 格式：{{"state": "情绪", "confidence": 0.0-1.0, "evidence": "判断依据"}}

学员消息：{text}"""


def _parse_emotion_response(response: str) -> EmotionResult:
    """解析 LLM 返回的情感 JSON"""
    import json
    try:
        # 提取 JSON 块（LLM 可能在前后加文字）
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(response[start:end])
            return EmotionResult(
                state=data.get("state", "neutral"),
                confidence=float(data.get("confidence", 0.5)),
                evidence=data.get("evidence", ""),
            )
    except (json.JSONDecodeError, ValueError):
        pass
    return EmotionResult(state="neutral", confidence=0.0, evidence="解析失败")
