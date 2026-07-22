"""
关键路径耗时日志 — 同时写控制台与 logs/perf.log。

使用方式：
    from src.perf import setup_perf_logging, timed, log_timing

    setup_perf_logging()  # 应用启动时调用一次

    with timed("rag.retrieve"):
        ...

    log_timing("startup.milvus", 1.23, extra="ok")
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.config import PROJECT_ROOT

PERF_LOGGER_NAME = "ai_ta.perf"
_LOG_DIR = PROJECT_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "perf.log"

_configured = False


def setup_perf_logging(level: int = logging.INFO) -> Path:
    """
    初始化耗时日志：logs/perf.log + 控制台。
    幂等；返回日志文件路径。
    """
    global _configured
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(PERF_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if not _configured:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(level)
        logger.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.setLevel(level)
        logger.addHandler(sh)
        _configured = True

    logger.info("==== perf log ready: %s ====", _LOG_FILE)
    return _LOG_FILE


def get_perf_logger() -> logging.Logger:
    """获取耗时专用 logger（未 setup 时也会打到 root）。"""
    return logging.getLogger(PERF_LOGGER_NAME)


def log_timing(label: str, seconds: float, **extra) -> None:
    """写一条耗时记录。"""
    parts = [f"[耗时] {label}: {seconds:.3f}s"]
    if extra:
        detail = " ".join(f"{k}={v}" for k, v in extra.items())
        parts.append(detail)
    get_perf_logger().info(" | ".join(parts))


@contextmanager
def timed(label: str, **extra) -> Iterator[None]:
    """上下文管理器：退出时写耗时。"""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log_timing(label, time.perf_counter() - t0, **extra)


class Span:
    """可手动 start/stop 的计时片段（适合跨函数）。"""

    def __init__(self, label: str, **extra):
        self.label = label
        self.extra = extra
        self._t0 = time.perf_counter()

    def stop(self, **more) -> float:
        elapsed = time.perf_counter() - self._t0
        merged = {**self.extra, **more}
        log_timing(self.label, elapsed, **merged)
        return elapsed
