"""
Checkpointer — LangGraph 短期记忆。

使用方式：
    from src.memory.checkpointer import get_checkpointer
    checkpointer = get_checkpointer()
    graph = graph.compile(checkpointer=checkpointer)

使用 RedisSaver 实现对话历史的持久化存储和断点恢复。
如果 Redis 不可用，回退到无 Checkpointer 的内存模式。
"""

import logging

from langgraph.checkpoint.redis import RedisSaver

from src.config import config

logger = logging.getLogger(__name__)

_checkpointer: RedisSaver | None = None


def get_checkpointer() -> RedisSaver | None:
    """
    返回 RedisSaver 实例（单例），持久化对话历史到 Redis。

    如果 Redis 连接失败，返回 None，调用方应退化为无 Checkpointer 模式。
    """
    global _checkpointer
    if _checkpointer is None:
        try:
            redis_url = f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}"
            _checkpointer = RedisSaver(redis_url=redis_url)
            _checkpointer.setup()
            logger.info("RedisSaver 初始化成功 (host=%s:%d db=%d)",
                        config.redis.host, config.redis.port, config.redis.db)
        except Exception as e:
            logger.warning("RedisSaver 连接失败，Checkpointer 不可用: %s", e)
            return None
    return _checkpointer
