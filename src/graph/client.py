"""
Neo4j 图数据库连接管理 — 单例驱动，供 Graph RAG 使用。

使用方式：
    from src.graph.client import get_driver, check_connection
    driver = get_driver()
    ok, msg = check_connection()
"""

from __future__ import annotations

import logging

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from src.config import config

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    """获取 Neo4j 驱动单例（不验证连接，惰性创建）。"""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.neo4j.uri,
            auth=(config.neo4j.user, config.neo4j.password),
            max_connection_lifetime=3600,
            keep_alive=True,
        )
        logger.info("Neo4j driver created: %s", config.neo4j.uri)
    return _driver


def check_connection() -> tuple[bool, str]:
    """探测 Neo4j 连接是否就绪。"""
    try:
        driver = get_driver()
        with driver.session(database=config.neo4j.database) as session:
            result = session.run("RETURN 1 AS n")
            result.single()
        return True, f"Neo4j connected ({config.neo4j.uri})"
    except ServiceUnavailable:
        return False, "Neo4j 不可达 — 确认 Docker 容器是否运行"
    except Neo4jError as e:
        return False, f"Neo4j 错误: {e}"
    except Exception as e:
        return False, f"Neo4j 连接失败: {e}"


def close_driver() -> None:
    """关闭驱动（服务停服时调用）。"""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")
