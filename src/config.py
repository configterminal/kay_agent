"""
配置中心 — 从 .env 文件和环境变量加载所有配置。

读取链：.env 文件 → pydantic-settings → 全局 config 对象
所有模块通过 `from src.config import config` 获取配置，不直接读环境变量。
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env（显式指定路径，不依赖工作目录）
load_dotenv(PROJECT_ROOT / ".env")


class DeepSeekSettings(BaseSettings):
    """DeepSeek Chat 配置"""
    api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    base_url: str = Field(default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL")
    chat_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_CHAT_MODEL")
    temperature: float = Field(default=0.3)


class OpenAISettings(BaseSettings):
    """OpenAI 配置（预留）"""
    api_key: str = Field(default="", alias="OPENAI_API_KEY")
    base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    chat_model: str = Field(default="gpt-4o", alias="OPENAI_CHAT_MODEL")
    temperature: float = Field(default=0.3)


class AnthropicSettings(BaseSettings):
    """Anthropic 配置（预留）"""
    api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    chat_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_CHAT_MODEL")
    temperature: float = Field(default=0.3)


class RedisSettings(BaseSettings):
    """Redis Stack 连接配置"""
    host: str = Field(default="localhost", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    db: int = Field(default=0, alias="REDIS_DB")


class SQLiteSettings(BaseSettings):
    """SQLite 数据库路径"""
    path: str = Field(default="db/ai_ta.db", alias="SQLITE_PATH")

    @property
    def url(self) -> str:
        """返回 SQLAlchemy 连接 URL"""
        absolute_path = (PROJECT_ROOT / self.path).resolve()
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{absolute_path}"


class VectorDBSettings(BaseSettings):
    """Milvus 向量数据库配置"""
    host: str = Field(default="localhost", alias="MILVUS_HOST")
    port: int = Field(default=19530, alias="MILVUS_PORT")
    collection_name: str = Field(default="course_content", alias="MILVUS_COLLECTION")


class EmbeddingSettings(BaseSettings):
    """Embedding 模型配置（与 TEI 启动模型、索引维度对齐）"""
    model: str = Field(
        default="BAAI/bge-large-zh-v1.5",
        alias="EMBEDDING_MODEL",
    )
    dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")


class InferenceSettings(BaseSettings):
    """Embedding / Rerank 推理后端配置（可插拔）"""
    embedding_backend: str = Field(default="local", alias="EMBEDDING_BACKEND")
    reranker_backend: str = Field(default="local", alias="RERANKER_BACKEND")
    embedding_base_url: str = Field(
        default="http://localhost:8090",
        alias="EMBEDDING_BASE_URL",
    )
    reranker_base_url: str = Field(
        default="http://localhost:8091",
        alias="RERANKER_BASE_URL",
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        alias="RERANKER_MODEL",
    )
    timeout_s: float = Field(default=30.0, alias="INFERENCE_TIMEOUT_S")
    algo_embedding_method: str = Field(default="hashing", alias="ALGO_EMBEDDING_METHOD")
    algo_embedding_dim: int = Field(default=1024, alias="ALGO_EMBEDDING_DIM")


class GradioSettings(BaseSettings):
    """Gradio Web UI 配置（遗留，主 UI 为 Vue）"""
    host: str = Field(default="127.0.0.1", alias="GRADIO_HOST")
    port: int = Field(default=7860, alias="GRADIO_PORT")


class ContextBudgetSettings(BaseSettings):
    """进 LLM / 子 Agent 的上下文预算（对齐 memory.md）"""
    recent_turns: int = Field(default=5, alias="CONTEXT_RECENT_TURNS")
    summary_trigger_messages: int = Field(
        default=12, alias="CONTEXT_SUMMARY_TRIGGER_MESSAGES",
    )
    summary_max_chars: int = Field(default=800, alias="CONTEXT_SUMMARY_MAX_CHARS")
    tool_result_max_chars: int = Field(
        default=2000, alias="CONTEXT_TOOL_RESULT_MAX_CHARS",
    )


class SpeechSettings(BaseSettings):
    """面试语音 ASR / TTS（可插拔；引擎可发现，面向分布式）"""
    asr_backend: str = Field(default="local", alias="ASR_BACKEND")
    tts_backend: str = Field(default="local", alias="TTS_BACKEND")
    asr_model: str = Field(default="sensevoice", alias="ASR_MODEL")
    tts_model: str = Field(default="edge", alias="TTS_MODEL")
    tts_voice: str = Field(default="zh-CN-YunxiNeural", alias="TTS_VOICE")
    asr_base_url: str = Field(default="", alias="ASR_BASE_URL")
    tts_base_url: str = Field(
        default="http://127.0.0.1:8092", alias="TTS_BASE_URL",
    )
    # 引擎目录：edge 始终可用；cosy_local 指向 tts_base_url
    tts_engines: str = Field(default="edge", alias="TTS_ENGINES")
    cosyvoice_model: str = Field(
        default="300m-instruct", alias="COSYVOICE_MODEL",
    )
    cosyvoice_min_free_vram_mb: int = Field(
        default=4200, alias="COSYVOICE_MIN_FREE_VRAM_MB",
    )
    # 本机 sidecar 启动命令（空=不自动拉起，仅探测已运行实例）
    cosyvoice_start_cmd: str = Field(default="", alias="COSYVOICE_START_CMD")
    interview_tts_prefer: str = Field(
        default="edge", alias="INTERVIEW_TTS_PREFER",
    )


class Neo4jSettings(BaseSettings):
    """Neo4j 图数据库配置（Graph RAG）"""
    uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="password", alias="NEO4J_PASSWORD")
    database: str = Field(default="neo4j", alias="NEO4J_DATABASE")


class Settings(BaseSettings):
    """全局配置聚合器 — 所有模块通过它获取配置"""
    model_config = {"populate_by_name": True}

    # ── 当前使用的 LLM Provider ──
    llm_provider: str = Field(default="deepseek", alias="LLM_PROVIDER")

    # ── 路径 ──
    project_root: Path = PROJECT_ROOT
    resources_dir: Path = PROJECT_ROOT / "resources"

    # ── 子配置 ──
    deepseek: DeepSeekSettings = DeepSeekSettings()
    openai: OpenAISettings = OpenAISettings()
    anthropic: AnthropicSettings = AnthropicSettings()
    redis: RedisSettings = RedisSettings()
    sqlite: SQLiteSettings = SQLiteSettings()
    milvus: VectorDBSettings = VectorDBSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    inference: InferenceSettings = InferenceSettings()
    speech: SpeechSettings = SpeechSettings()
    gradio: GradioSettings = GradioSettings()
    context: ContextBudgetSettings = ContextBudgetSettings()
    neo4j: Neo4jSettings = Neo4jSettings()

    def get_llm_config(self, provider: str | None = None) -> dict:
        """根据 provider 名返回对应的 LLM 配置字典，供 LLMProvider 使用"""
        provider = provider or self.llm_provider
        provider_map = {
            "deepseek": self.deepseek,
            "openai": self.openai,
            "anthropic": self.anthropic,
        }
        if provider not in provider_map:
            raise ValueError(f"不支持的 LLM Provider: {provider}，可选: {list(provider_map.keys())}")
        return provider_map[provider]


# 全局单例 — 整个项目只 import 这一个 config 对象
config = Settings()
