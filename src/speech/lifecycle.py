"""面试 TTS 引擎发现与生命周期 — 禁止迁 Embedding 到 CPU。"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config import config

logger = logging.getLogger(__name__)

# 本场选定的引擎（进程内）；prepare 写入
_selected_engine_id: str = "edge"
_started_local_pid: int | None = None


@dataclass
class TtsEngineInfo:
    """一条可注册的 TTS 引擎。"""

    id: str
    kind: str  # edge | cosyvoice
    base_url: str = ""
    model: str = ""
    priority: int = 0
    min_free_vram_mb: int = 0
    available: bool = False
    reason: str = ""
    latency_ms: int = 0


@dataclass
class PrepareResult:
    """prepare 结果。"""

    selected: str
    engines: list[TtsEngineInfo] = field(default_factory=list)
    detail: str = ""


def gpu_free_mb() -> int | None:
    """本机 GPU 空闲显存 MB（公开给 API）。"""
    return _gpu_free_mb()


def get_selected_engine_id() -> str:
    return _selected_engine_id


def demote_to_edge(reason: str = "") -> None:
    """Cosy 推理失败（如 OOM）后降级到 Edge，本场不再硬打 Cosy。"""
    global _selected_engine_id
    if _selected_engine_id != "edge":
        logger.warning("TTS demote → edge (%s)", reason[:160])
    _selected_engine_id = "edge"


def _gpu_free_mb() -> int | None:
    """本机 GPU 空闲显存 MB（优先 nvidia-smi，跨进程准确）；不可用则 None。"""
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        line = (out or "").strip().splitlines()[0].strip()
        return int(float(line))
    except Exception as e:
        logger.debug("nvidia-smi gpu_free failed: %s", e)
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info(0)
        return int(free / (1024 * 1024))
    except Exception as e:
        logger.debug("torch gpu_free_mb failed: %s", e)
        return None


def _probe_http_ready(base_url: str, timeout: float = 1.5) -> tuple[bool, str, int]:
    """探测 sidecar /ready。返回 (ok, reason, latency_ms)。"""
    url = base_url.rstrip("/") + "/ready"
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return False, f"http {r.status_code}", ms
            data = r.json() if r.content else {}
            if isinstance(data, dict) and data.get("ready") is False:
                return False, str(data.get("detail") or "not ready"), ms
            return True, "ready ok", ms
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return False, f"unreachable: {e}", ms


def _catalog() -> list[TtsEngineInfo]:
    """从配置构建引擎目录（本期 edge + cosy_local）。"""
    speech = config.speech
    ids = [x.strip() for x in (speech.tts_engines or "edge").split(",") if x.strip()]
    prefer = (speech.interview_tts_prefer or "edge").lower()
    out: list[TtsEngineInfo] = []
    for eid in ids:
        if eid == "edge":
            out.append(
                TtsEngineInfo(
                    id="edge",
                    kind="edge",
                    priority=10 if prefer == "edge" else 1,
                )
            )
        elif eid.startswith("cosy"):
            # cosy_local 用 TTS_BASE_URL；其它 id 可读 TTS_ENGINE_{ID}_URL（预留）
            url = speech.tts_base_url or "http://127.0.0.1:8092"
            env_key = f"TTS_ENGINE_{eid.upper()}_URL"
            import os

            url = os.environ.get(env_key, url)
            prio = 50 if prefer.startswith("cosy") else 20
            out.append(
                TtsEngineInfo(
                    id=eid,
                    kind="cosyvoice",
                    base_url=url,
                    model=speech.cosyvoice_model,
                    priority=prio,
                    min_free_vram_mb=speech.cosyvoice_min_free_vram_mb,
                )
            )
    return out


def discover_tts_engines() -> list[TtsEngineInfo]:
    """探测目录内引擎是否可用（不启进程、不迁 Embedding）。"""
    free_mb = _gpu_free_mb()
    engines = _catalog()
    for eng in engines:
        if eng.kind == "edge":
            eng.available = True
            eng.reason = "always"
            continue
        # cosyvoice：先探 ready；未运行则看本机显存是否「理论上够启」
        ok, reason, ms = _probe_http_ready(eng.base_url)
        eng.latency_ms = ms
        if ok:
            # 模型已加载仍可能推理 OOM：空闲显存过低则本场不用 Cosy
            if free_mb is not None and free_mb < max(800, eng.min_free_vram_mb // 4):
                eng.available = False
                eng.reason = (
                    f"ready but vram_free_mb={free_mb} too low for infer "
                    f"(need≥{max(800, eng.min_free_vram_mb // 4)}; use edge)"
                )
            else:
                eng.available = True
                eng.reason = reason
            continue
        # 未 ready：标记为「可尝试启动」仅当显存够且配置了 start_cmd
        if free_mb is not None and free_mb >= eng.min_free_vram_mb:
            if config.speech.cosyvoice_start_cmd.strip():
                eng.available = False
                eng.reason = (
                    f"sidecar_down; vram_free_mb={free_mb}>=min; start_cmd_configured"
                )
            else:
                eng.available = False
                eng.reason = (
                    f"sidecar_down; vram_free_mb={free_mb} "
                    f"(no COSYVOICE_START_CMD; will not auto-start)"
                )
        elif free_mb is None:
            eng.available = False
            eng.reason = f"sidecar_down; {reason}; gpu_unknown"
        else:
            eng.available = False
            eng.reason = (
                f"sidecar_down; vram_free_mb={free_mb}<{eng.min_free_vram_mb}; "
                "will not start (no embedding eviction)"
            )
    return engines


def _try_start_local_cosy(eng: TtsEngineInfo) -> bool:
    """仅当配置了 COSYVOICE_START_CMD 且显存够时拉起本机 sidecar。"""
    global _started_local_pid
    cmd = (config.speech.cosyvoice_start_cmd or "").strip()
    if not cmd:
        return False
    free_mb = _gpu_free_mb()
    if free_mb is not None and free_mb < eng.min_free_vram_mb:
        logger.info(
            "skip start cosy: free_mb=%s < min=%s", free_mb, eng.min_free_vram_mb,
        )
        return False
    try:
        # Windows：用 shell 启动；不阻塞主进程
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(config.project_root),
        )
        _started_local_pid = proc.pid
        logger.info("started cosy sidecar pid=%s cmd=%s", proc.pid, cmd)
        # 等待 ready
        for _ in range(60):
            time.sleep(1.0)
            ok, _, _ = _probe_http_ready(eng.base_url, timeout=2.0)
            if ok:
                return True
        logger.warning("cosy sidecar start timeout")
        return False
    except Exception as e:
        logger.warning("start cosy failed: %s", e)
        return False


def prepare_interview_speech() -> PrepareResult:
    """发现 → 可选启本机 Cosy → 选定引擎。禁止迁 Embedding。"""
    global _selected_engine_id
    engines = discover_tts_engines()

    # 若偏好 Cosy 且本机未 ready 但显存够且有 start_cmd → 尝试启动
    prefer = (config.speech.interview_tts_prefer or "edge").lower()
    if prefer.startswith("cosy"):
        for eng in engines:
            if eng.kind != "cosyvoice":
                continue
            ok, _, _ = _probe_http_ready(eng.base_url)
            if ok:
                eng.available = True
                eng.reason = "ready ok"
                break
            if "start_cmd_configured" in eng.reason:
                if _try_start_local_cosy(eng):
                    eng.available = True
                    eng.reason = "started and ready"
                break

    # 再发现一次刷新状态
    engines = discover_tts_engines()
    available = [e for e in engines if e.available]
    if not available:
        _selected_engine_id = "edge"
        return PrepareResult(
            selected="edge",
            engines=engines,
            detail="no engine available; force edge",
        )

    available.sort(key=lambda e: e.priority, reverse=True)
    chosen = available[0]
    _selected_engine_id = chosen.id
    detail = f"selected={chosen.id} ({chosen.reason})"
    logger.info("prepare_interview_speech %s", detail)
    return PrepareResult(selected=chosen.id, engines=engines, detail=detail)


def release_interview_speech() -> dict[str, Any]:
    """停本场拉起的本机 Cosy；不碰 Embedding。"""
    global _started_local_pid, _selected_engine_id
    killed = False
    if _started_local_pid:
        try:
            import os
            import signal

            os.kill(_started_local_pid, signal.SIGTERM)
            killed = True
        except Exception as e:
            logger.warning("release cosy pid=%s: %s", _started_local_pid, e)
        _started_local_pid = None
    _selected_engine_id = "edge"
    return {"released": killed, "selected": _selected_engine_id}


def resolve_tts_target() -> TtsEngineInfo:
    """合成时解析当前引擎（无 prepare 则默认 edge）。"""
    eid = _selected_engine_id or "edge"
    for eng in _catalog():
        if eng.id == eid:
            return eng
    return TtsEngineInfo(id="edge", kind="edge", available=True, reason="fallback")


def engines_to_dict(engines: list[TtsEngineInfo]) -> list[dict[str, Any]]:
    return [
        {
            "id": e.id,
            "kind": e.kind,
            "base_url": e.base_url,
            "model": e.model,
            "priority": e.priority,
            "min_free_vram_mb": e.min_free_vram_mb,
            "available": e.available,
            "reason": e.reason,
            "latency_ms": e.latency_ms,
        }
        for e in engines
    ]
