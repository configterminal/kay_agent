"""
MemoryStore — Redis Stack 长期记忆封装。

基于 RedisJSON + RediSearch 实现结构化知识的存储、检索和全文搜索。

使用方式：
    from src.memory.store import MemoryStore
    store = MemoryStore()
    store.put(["students", "123", "weak_areas"], {"hash_table": 3})
    data = store.get(["students", "123", "preferences"])
    results = store.search("hash_table", "weak_areas")
"""

from typing import Any

import redis
from redis.commands.json.path import Path
from redis.commands.search.field import TextField, NumericField

from src.config import config

# 索引名前缀
INDEX_PREFIX = "idx:students"

# 全局单例
_store: "MemoryStore | None" = None


def set_store(store: "MemoryStore") -> None:
    """注入全局 MemoryStore 单例（lifespan 调用）"""
    global _store
    _store = store


def get_store() -> "MemoryStore":
    """获取全局 MemoryStore 单例。未注入时自动创建。"""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


class MemoryStore:
    """长期记忆 — 基于 RedisJSON + RediSearch"""

    def __init__(self):
        self._client = redis.Redis(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            decode_responses=True,
        )

    # ── Key 构造 ─────────────────────────────────────

    def _make_key(self, keys: list[str]) -> str:
        """将命名空间列表拼成 Redis key，如 ["students","123","weak_areas"] → "students:123:weak_areas" """
        return ":".join(str(k) for k in keys)

    def _index_name(self, namespace: str) -> str:
        """索引名，如 "weak_areas" → "idx:students:weak_areas" """
        return f"{INDEX_PREFIX}:{namespace}"

    # ── 基础读写（RedisJSON）─────────────────────────

    def get(self, keys: list[str]) -> dict[str, Any] | None:
        """读取数据。无数据返回 None"""
        key = self._make_key(keys)
        try:
            return self._client.json().get(key)
        except Exception:
            return None

    def put(self, keys: list[str], data: dict[str, Any]) -> None:
        """写入数据，使用 RedisJSON 存储"""
        key = self._make_key(keys)
        # 提取 namespace 用于索引匹配
        # key 格式: students:{id}:{namespace} → namespace = keys[-1]
        namespace = keys[-1] if len(keys) >= 3 else keys[0]
        self._ensure_index(namespace)
        self._client.json().set(key, Path.root_path(), data)

    def delete(self, keys: list[str]) -> None:
        """删除指定 key"""
        self._client.delete(self._make_key(keys))

    def exists(self, keys: list[str]) -> bool:
        """检查 key 是否存在"""
        return bool(self._client.exists(self._make_key(keys)))

    # ── 搜索 ────────────────────────────────────────

    def search(
        self,
        query: str,
        namespace: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        全文搜索指定 namespace 下的数据。

        参数：
            query: 搜索关键词
            namespace: 命名空间，如 "weak_areas"、"preferences"
            limit: 返回数量上限

        返回：
            匹配的数据列表
        """
        self._ensure_index(namespace)
        index_name = self._index_name(namespace)

        try:
            result = self._client.ft(index_name).search(query)
        except Exception:
            return []

        docs = []
        for doc in result.docs:
            # doc.id 是 key，如 "students:123:weak_areas"
            # doc.json 在 decode_responses=True 时是字符串
            if hasattr(doc, "json") and doc.json:
                import json
                docs.append(json.loads(doc.json))
        return docs[:limit]

    # ── 索引管理 ─────────────────────────────────────

    def _ensure_index(self, namespace: str) -> None:
        """
        确保命名空间对应的 RediSearch 索引存在（幂等）。

        索引名: idx:students:{namespace}
        索引范围: students:* key 前缀
        索引字段: 对所有 JSON 字段创建 TEXT 索引，数值字段创建 NUMERIC 索引
        """
        index_name = self._index_name(namespace)
        try:
            self._client.execute_command("FT.INFO", index_name)
        except Exception:
            # 索引不存在，创建
            # 查看已有数据的 schema 来决定字段类型
            self._client.execute_command(
                "FT.CREATE", index_name,
                "ON", "JSON",
                "PREFIX", "1", "students:",
                "SCHEMA",
                "$.name", "AS", "name", "TEXT",
                "$.value", "AS", "value", "TEXT",
                "$.score", "AS", "score", "NUMERIC",
                "$.count", "AS", "count", "NUMERIC",
            )

    def _drop_index(self, namespace: str) -> None:
        """删除索引（仅测试用）"""
        index_name = self._index_name(namespace)
        try:
            self._client.execute_command("FT.DROPINDEX", index_name, "DD")
        except Exception:
            pass

    # ── 批量操作 ─────────────────────────────────────

    def get_all(self, pattern: str) -> list[dict[str, Any]]:
        """按模式查询所有匹配的 key，返回数据列表。如 pattern="students:123:*" """
        results = []
        for key in self._client.scan_iter(match=pattern):
            try:
                data = self._client.json().get(key)
                if data:
                    results.append(data)
            except Exception:
                pass
        return results

    def delete_all(self, pattern: str) -> int:
        """按模式批量删除。返回删除数量"""
        keys = list(self._client.scan_iter(match=pattern))
        if not keys:
            return 0
        return self._client.delete(*keys)

    # ── 连接检查 ─────────────────────────────────────

    def ping(self) -> bool:
        """检查 Redis 连接是否正常"""
        try:
            return self._client.ping()
        except redis.ConnectionError:
            return False
