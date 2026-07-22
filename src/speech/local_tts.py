"""本地 TTS 编排 — 按 prepare 选定的引擎走 Edge 或 Cosy sidecar。"""

from __future__ import annotations

import asyncio
import io
import logging

from src.config import config
from src.speech.base import SpeechError, TtsResult

logger = logging.getLogger(__name__)

DEFAULT_INTERVIEW_INSTRUCT = (
    "用自然的中文口语说话，语速正常，吐字清楚，语气平和专业，"
    "像真的技术面试官在交流，不要朗读腔、不要夸张表情。"
)


class LocalTtsProvider:
    """本机 TTS 门面：根据 lifecycle 选定引擎路由。"""

    name = "local"

    def __init__(self) -> None:
        self._voice = config.speech.tts_voice or "zh-CN-YunxiNeural"

    def ready(self) -> tuple[bool, str]:
        # Edge 始终可作为兜底 → TTS 整体 ready
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "edge-tts 未安装：pip install edge-tts --target f:\\jupyter"
        from src.speech.lifecycle import get_selected_engine_id

        return True, f"local tts ready (selected={get_selected_engine_id()}, edge fallback ok)"

    def warmup(self) -> None:
        ok, msg = self.ready()
        if not ok:
            raise SpeechError(msg)
        logger.info("LocalTtsProvider warmup: %s", msg)

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        instruct: str | None = None,
    ) -> TtsResult:
        text = (text or "").strip()
        if not text:
            raise SpeechError("TTS 文本为空")

        from src.speech.lifecycle import resolve_tts_target

        target = resolve_tts_target()
        if target.kind == "cosyvoice" and target.base_url:
            try:
                from src.speech.http_backend import HttpTtsProvider

                return HttpTtsProvider(base_url=target.base_url).synthesize(
                    text, voice=voice, instruct=instruct or DEFAULT_INTERVIEW_INSTRUCT,
                )
            except Exception as e:
                logger.warning("cosy TTS failed, fallback edge: %s", e)
                from src.speech.lifecycle import demote_to_edge

                demote_to_edge(str(e))

        return self._edge_synthesize(text, voice=voice or self._voice)

    def _edge_synthesize(self, text: str, *, voice: str) -> TtsResult:
        try:
            import edge_tts
        except ImportError as e:
            raise SpeechError(
                "edge-tts 未安装：pip install edge-tts --target f:\\jupyter"
            ) from e

        async def _run() -> bytes:
            # Clash 等本地代理常导致 Edge 无音频；合成时临时直连
            import os

            saved = {
                k: os.environ.pop(k)
                for k in list(os.environ)
                if k.upper() in {
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                    "http_proxy", "https_proxy", "all_proxy",
                }
            }
            try:
                communicate = edge_tts.Communicate(text, voice)
                buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                return buf.getvalue()
            finally:
                os.environ.update(saved)

        try:
            audio = asyncio.run(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                audio = loop.run_until_complete(_run())
            finally:
                loop.close()

        if not audio:
            raise SpeechError("Edge-TTS 未返回音频")
        return TtsResult(
            audio=audio,
            mime="audio/mpeg",
            raw={"voice": voice, "engine": "edge"},
        )
