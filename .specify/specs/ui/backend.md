# FastAPI 后端架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI 后端                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  uvicorn (main.py)                                                │
│       │                                                          │
│       ▼                                                          │
│  FastAPI App                                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  POST /api/chat/  ──→  chat(message, student_id)            │  │
│  │       │                                                     │  │
│  │       ├── ① 查学员信息                                       │  │
│  │       │     SQLite students 表（存在性校验）                  │  │
│  │       │                                                     │  │
│  │       ├── ② 调 Supervisor                                     │  │
│  │       │     run_supervisor(...) → content / emotion / …      │  │
│  │       │     + citations（本轮 search_course_content 结果）    │  │
│  │       │                                                     │  │
│  │       └── ③ 返回 ChatResponse（补 media_url）                 │  │
│  │                                                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  GET /media/{path}       ──→ resources/ 下只读 mp4（防穿越）      │
│  GET /api/student/{id}   ──→ 查 SQLite students 表               │
│  PUT /api/student/{id}   ──→ 更新 students 表                     │
│  GET /api/conversations  ──→ 查 Redis Checkpointer thread 列表    │
│  GET /api/conversation/{thread_id} ──→ 加载 thread 对话历史       │
│                                                                  │
│  跳转设计见 ui/video-jump.md                                      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 依赖关系

```
main.py
  ├── src.agents.supervisor     → run_supervisor()  # 内含 probe 情绪检测
  ├── src.db.init_db            → get_session()
  └── src.config                → config
```

> 情绪检测实现仍在 `src.emotion.detector`，由 Supervisor `probe_node` 调用，**不由 routes 直接依赖**。

## 文件结构

```
src/
├── main.py                    # FastAPI 入口 + lifespan
├── api/
│   ├── __init__.py
│   ├── routes.py              # 路由处理函数
│   └── schemas.py             # Pydantic 请求/响应模型
├── agents/...
├── ...
```

## 数据流（一次完整请求）

```
Vue 前端
  │  POST {message: "什么是RAG？", student_id: 1}
  ▼
FastAPI routes.py
  │  chat(request)
  ▼
① SQLite: SELECT * FROM students WHERE id=1
  → 学员存在
  ▼
② run_supervisor(graph, student_id=1, message="什么是RAG？")
      └─ probe_node: EmotionDetector.detect(...)  ← 唯一检测
      └─ … decide / dispatch …
  → {"content": "RAG是...", "emotion": "neutral", "emotion_confidence": 0.9}
  ▼
③ return ChatResponse(content=..., emotion=...)
  ▼
Vue 前端渲染回复
```
