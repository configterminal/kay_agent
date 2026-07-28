"""FastAPI 后端入口 — AI 助教系统。

启动：
    poetry run uvicorn src.main:app --reload --port 8000

Embedding / Rerank 经可插拔 Provider（默认 local GPU；可选 http TEI）。
"""

# 必须在 import transformers / sentence_transformers 之前设置，否则启动会卡 HF 网络
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from src.api.routes import router
from src.config import config, PROJECT_ROOT
from src.perf import setup_perf_logging, timed, log_timing
from pathlib import Path


# ── 环境核查 ──────────────────────────────────────────────

def _preflight_check() -> None:
    """启动前环境核查。致命项不通过 → SystemExit(1)。"""
    import logging
    import sys

    logger = logging.getLogger("preflight")
    fatal = False

    def _ok(msg: str) -> None:
        print(f"   [OK] {msg}")

    def _warn(msg: str) -> None:
        print(f"   [!!] {msg}")

    def _fail(msg: str) -> None:
        nonlocal fatal
        fatal = True
        print(f"   [XX] {msg}")

    print("+-- 环境核查 -------------------------------------------+")

    # ① .env
    env_file = config.model_config.get("env_file") or ".env"
    if Path(env_file).exists():
        _ok(f".env 存在")
    else:
        _warn(f".env 文件未找到 ({env_file})")

    # ② DeepSeek API Key
    key = config.deepseek.api_key or ""
    if key and key != "sk-xxx":
        _ok(f"DeepSeek API Key     sk-...{key[-4:]}")
    else:
        _fail("DEEPSEEK_API_KEY 未配置或为占位值，请检查 .env")

    # ③ Redis 连通性
    try:
        import redis as _redis
        r = _redis.Redis(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            socket_connect_timeout=3,
        )
        r.ping()
        _ok(f"Redis Stack         {config.redis.host}:{config.redis.port}")
    except Exception as e:
        _fail(f"Redis 不可达 ({config.redis.host}:{config.redis.port}): {e}")

    # ④ Neo4j 连通性（可选）
    try:
        from src.graph.client import check_connection
        neo_ok, neo_msg = check_connection()
        if neo_ok:
            _ok(f"Neo4j               {neo_msg}")
        else:
            _warn(f"Neo4j 不可达: {neo_msg} (图检索将不可用)")
    except Exception as e:
        _warn(f"Neo4j 连接检查失败: {e} (图检索将不可用)")

    # ⑤ Milvus 数据目录
    milvus_path = PROJECT_ROOT / "milvus_lite"
    try:
        milvus_path.mkdir(parents=True, exist_ok=True)
        _ok(f"Milvus 数据目录      {milvus_path}")
    except Exception as e:
        _fail(f"Milvus 数据目录不可写: {milvus_path} ({e})")

    # ⑥ 日志目录可写
    log_dir = PROJECT_ROOT / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _ok(f"日志目录            {log_dir}")
    except Exception as e:
        _fail(f"日志目录不可写: {log_dir} ({e})")

    # ⑦ 磁盘空间
    try:
        import shutil
        usage = shutil.disk_usage(str(PROJECT_ROOT))
        free_gb = usage.free / (2 ** 30)
        if free_gb >= 1:
            _ok(f"磁盘空间            {free_gb:.1f} GB 可用")
        else:
            _warn(f"磁盘空间不足 ({free_gb:.1f} GB)，建议清理")
    except Exception:
        pass  # 忽略磁盘检查失败

    print("+-------------------------------------------------------+")

    if fatal:
        print("+-------------------------------------------------------+")
        print("| [XX] 致命项未通过，终止启动。请修复后重试。           |")
        print("+-------------------------------------------------------+")
        logger.error("环境核查致命项未通过，终止启动")
        sys.exit(1)
    else:
        print("+-------------------------------------------------------+")
        print("| [OK] 环境核查通过，启动服务                            |")
        print("+-------------------------------------------------------+")
        logger.info("环境核查通过")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：环境核查 → 推理 warmup → 轻资源预热 → 编译 Graph；关闭时清理。"""
    log_path = setup_perf_logging()
    t_boot = __import__("time").perf_counter()
    log_timing("startup.begin", 0.0, log_file=str(log_path))

    # ── 0. 环境核查 ──
    _preflight_check()

    from src.vectordb.inference import wait_inference_ready
    from src.memory.store import MemoryStore, set_store
    from src.vectordb.schema import get_client, ensure_collection
    from src.vectordb.hybrid_search import warmup_bm25
    from src.agents.supervisor import build_supervisor_graph

    # ① 推理后端就绪（local=加载 GPU 权重；http=等 TEI）
    with timed("startup.inference_warmup"):
        wait_inference_ready(max_wait_s=180.0)

    # ② MemoryStore 单例
    with timed("startup.memory_store"):
        set_store(MemoryStore())

    # ②.5 课程目录同步（轻量，推荐依赖 course_modules）
    from src.db.catalog_sync import sync_course_catalog
    try:
        with timed("startup.catalog_sync"):
            sync_course_catalog()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("课程目录同步失败: %s", e)
        log_timing("startup.catalog_sync", 0.0, error=str(e))

    # ②.6 岗位模板同步（JobMatch 课程覆盖匹配）
    from src.db.job_catalog_sync import sync_job_catalog
    try:
        with timed("startup.job_catalog_sync"):
            sync_job_catalog()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("岗位目录同步失败: %s", e)
        log_timing("startup.job_catalog_sync", 0.0, error=str(e))

    # ③ Milvus + Collection
    with timed("startup.milvus"):
        get_client()
        ensure_collection()

    # ④ BM25
    with timed("startup.bm25"):
        warmup_bm25()

    # ④.5 知识图谱同步（后台线程，不阻塞服务启动）
    import threading
    def _sync_graph_async():
        try:
            from src.graph.importer import sync_graph
            sync_graph()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("图数据库同步失败: %s", e)

    threading.Thread(target=_sync_graph_async, daemon=True).start()

    # ⑤ Supervisor Graph
    with timed("startup.build_graph"):
        app.state.graph = build_supervisor_graph()
    app.state.ready = True
    log_timing("startup.total", __import__("time").perf_counter() - t_boot, ready=True)

    yield

    app.state.ready = False
    log_timing("shutdown", 0.0)


app = FastAPI(
    title="AI 助教教学系统",
    description="基于 LangGraph 的多 Agent 智能教学助手",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/media/{file_path:path}")
def serve_media(file_path: str):
    """
    课程 mp4 只读：根目录限定 resources/，禁止路径穿越，仅 .mp4。
    """
    rel = (file_path or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    if not rel.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="仅支持 mp4")

    root = config.resources_dir.resolve()
    full = (root / rel).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界") from None
    if not full.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(full, media_type="video/mp4", filename=full.name)


@app.get("/captions/{file_path:path}")
def serve_captions(file_path: str):
    """
    课程字幕：由同 stem 转写 .md 动态生成 WebVTT；路径规则同 /media/。
    """
    rel = (file_path or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    if not rel.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="仅支持 mp4 对应字幕")

    from src.media.captions import build_vtt_for_media

    vtt = build_vtt_for_media(rel)
    if not vtt:
        raise HTTPException(status_code=404, detail="无可用字幕")
    return Response(
        content=vtt,
        media_type="text/vtt; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/")
def root():
    """存活探针"""
    return {"message": "AI 助教系统 API 运行中", "docs": "/docs"}


@app.get("/readyz")
def readyz():
    """就绪探针：Graph 已编译 + 推理 Provider 就绪"""
    from src.vectordb.inference import check_inference_ready

    graph_ok = bool(getattr(app.state, "graph", None))
    inf_ok, inf_msg = check_inference_ready()
    ready = graph_ok and inf_ok
    payload = {
        "ready": ready,
        "graph": graph_ok,
        "inference": inf_msg,
    }
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload
