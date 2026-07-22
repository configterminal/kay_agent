"""
Milvus Schema 定义 — Collection 创建、索引、连接管理。

Collection: course_content
  - 子文档（chunk_index >= 0）：知识点块（优先 .knowledge.json）或时间窗片段，有向量，含 start_sec/media_path
  - 父文档（chunk_index = -1）：整节去时间戳全文，占位向量，命中后经 parent_id 取回

使用方式：
    from src.vectordb.schema import get_client, ensure_collection
    client = get_client()
    ensure_collection()
"""

import logging
import shutil
from pathlib import Path

from pymilvus import (
    MilvusClient,
    DataType,
    CollectionSchema,
    FieldSchema,
    IndexType,
)
from pymilvus.milvus_client import IndexParams

from src.config import config

logger = logging.getLogger(__name__)


# ── 集合名称与向量维度 ──────────────────────────────

COLLECTION_NAME = config.milvus.collection_name
VECTOR_DIM = config.embedding.dimension
MAX_CONTENT_LENGTH = 65535  # VARCHAR 最大长度


def milvus_db_path() -> Path:
    """Milvus Lite 本地数据目录。"""
    return config.project_root / "db" / "milvus_lite.db"


# ── Field Schema ────────────────────────────────────

def _build_fields() -> list[FieldSchema]:
    """构建 Collection 的字段定义"""
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=128, is_primary=True, auto_id=False),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=MAX_CONTENT_LENGTH),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
        FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="course_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="chapter", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="section", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="file_type", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="chunk_index", dtype=DataType.INT16),
        FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="start_sec", dtype=DataType.INT32),
        FieldSchema(name="end_sec", dtype=DataType.INT32),
        FieldSchema(name="media_path", dtype=DataType.VARCHAR, max_length=1024),
        # 知识点字段（优先从 .knowledge.json 读取；无则留空）
        FieldSchema(name="kp_title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="kp_summary", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="kp_index", dtype=DataType.INT16),
        FieldSchema(name="key_points", dtype=DataType.VARCHAR, max_length=2048),
    ]


# ── 索引配置 ────────────────────────────────────────

def _build_index_params() -> IndexParams:
    """HNSW 向量索引参数"""
    params = IndexParams()
    params.add_index(
        field_name="embedding",
        index_type=IndexType.HNSW,
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    return params


# ── 连接管理 ────────────────────────────────────────

_client: MilvusClient | None = None


def get_client() -> MilvusClient:
    """获取 Milvus 客户端（单例，Milvus Lite 文件模式 — MVP）"""
    global _client
    if _client is None:
        # Milvus Lite：内嵌模式，数据存本地文件，无需 Docker
        _client = MilvusClient(uri=str(milvus_db_path()))
    return _client


def reset_client() -> None:
    """关闭并清空客户端单例（删库文件前必须调用）。"""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


# ── Collection 管理 ────────────────────────────────

def ensure_collection() -> bool:
    """
    确保 Collection 存在，不存在则创建。
    返回 True 表示新建，False 表示已存在。
    """
    client = get_client()

    if client.has_collection(COLLECTION_NAME):
        # 加载到内存（Milvus 需要显式加载才能搜索）
        client.load_collection(COLLECTION_NAME)
        return False

    schema = CollectionSchema(
        fields=_build_fields(),
        description="课程内容向量存储 — 父子文档模式",
        enable_dynamic_field=False,
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=_build_index_params(),
    )

    client.load_collection(COLLECTION_NAME)
    return True


def wipe_milvus_db() -> None:
    """
    关闭连接并删除整个 Milvus Lite 数据目录。

    Windows 上 drop_collection API 常因 os.rename 失败且易留下旧 schema，
    全量重建时用整库擦除最可靠；LOCK 占用时短暂重试。
    """
    import time

    path = milvus_db_path()
    last_err: Exception | None = None
    for attempt in range(5):
        reset_client()
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            logger.info("已擦除 Milvus Lite 数据目录: %s", path)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"无法擦除 Milvus 数据目录（可能仍被占用）: {path}") from last_err


def drop_collection() -> None:
    """
    删除 Collection（重建索引时使用）。

    优先整库擦除，避免 Windows 上 API drop / 旧 schema 残留。
    """
    wipe_milvus_db()
