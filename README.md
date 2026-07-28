# AI 助教教学系统

辅助和监测学生学习状态，个性化调整课程内容，帮助学员从零基础到找到心仪的工作。

## 架构概述

层级调度模式：Supervisor Agent → 6 个子 Agent

| Agent | 职责 |
|------|------|
| QAAgent | 智能答疑，RAG 检索 + 来源引用 |
| ProgressAgent | 进度追踪，薄弱点分析，学习报告 |
| RecommendAgent | 个性化推荐，在校/在职差异化 |
| JobMatchAgent | 岗位匹配，技能差距分析 |
| ResumeAgent | 简历解析，ATS 关键词检查 |
| InterviewAgent | 模拟面试，评分反馈，Offer 模拟 |

## 技术栈

- **LLM**: DeepSeek Chat（OpenAI 兼容接口，多 Provider 预留）
- **Agent 框架**: LangGraph（StateGraph + ReAct Agent）
- **RAG**: 查询重写 → 混合检索(BM25+向量+RRF) → Reranker → 父子文档
- **向量存储**: Milvus Lite（MVP）/ Milvus Docker（生产）
- **Embedding / Rerank**: BGE 系列；目标架构由 TEI Docker 提供推理（见总体架构）
- **数据库**: SQLite（结构化数据）+ Redis Stack（记忆 + 检查点）
- **图数据库**: Neo4j（Graph RAG，待实现）
- **Web UI**: Vue 3（`src/ui`）

## 快速开始

```powershell
# 安装依赖
poetry install

# 运行索引器
poetry run python -c "from src.vectordb.indexer import build_index; build_index(force=True)"

# 启动 API（需 Redis；目标架构下还需先起 TEI）
poetry run uvicorn src.main:app --reload --port 8000
```

## 项目结构

详见 [CLAUDE.md](CLAUDE.md)

## 文档

- [总体架构](.specify/specs/overview.md)（入口必读）
- [需求与架构](.specify/specs/index.md)
- [项目宪法与开发规范](.specify/constitution.md)
