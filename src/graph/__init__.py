"""src/graph/ — 图数据库模块（Neo4j + Graph RAG）

导入器 (importer):
    sync_graph() — 增量同步课程知识图谱到 Neo4j
    sync_graph(force=True) — 全量重建

连接管理 (client):
    get_driver() — Neo4j 驱动单例
    check_connection() — 连接探测
"""

from src.graph.importer import sync_graph

__all__ = ["sync_graph"]
