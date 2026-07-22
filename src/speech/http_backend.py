"""HTTP CosyVoice sidecar 客户端（本机或远程）。"""

from __future__ import annotations

import logging

import httpx

from src.config import config
from src.speech.base import AsrResult, SpeechError, TtsResult

logger = logging.getLogger(__name__)


class HttpAsrProvider:
    """云 ASR 占位（未启用）"""

    name = "http"

    def ready(self) -> tuple[bool, str]:
        return False, "ASR http backend 未启用（本期仅 local）"

    def warmup(self) -> None:
        pass

    def transcribe(self, audio: bytes, *, mime: str = "audio/webm") -> AsrResult:
        raise SpeechError("ASR http backend 未启用；请设 ASR_BACKEND=local")


class HttpTtsProvider:
    """CosyVoice sidecar TTS（base_url 可指向本机或远程节点）。"""

    name = "http"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or config.speech.tts_base_url or "").rstrip("/")

    def ready(self) -> tuple[bool, str]:
        if not self._base_url:
            return False, "TTS_BASE_URL 未配置"
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{self._base_url}/ready")
            if r.status_code != 200:
                return False, f"sidecar http {r.status_code}"
            data = r.json() if r.content else {}
            if isinstance(data, dict) and data.get("ready") is False:
                return False, str(data.get("detail") or "not ready")
            return True, f"cosy sidecar ready ({self._base_url})"
        except Exception as e:
            return False, f"sidecar unreachable: {e}"

    def warmup(self) -> None:
        ok, msg = self.ready()
        if not ok:
            raise SpeechError(msg)

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
        if not self._base_url:
            raise SpeechError("TTS_BASE_URL 未配置")
        payload = {
            "text": text,
            "voice": voice,
            "instruct": instruct,
            "model": config.speech.cosyvoice_model,
        }
        try:
            with httpx.Client(timeout=120.0) as client:
                r = client.post(f"{self._base_url}/tts", json=payload)
            if r.status_code != 200:
                raise SpeechError(f"sidecar TTS HTTP {r.status_code}: {r.text[:200]}")
            mime = r.headers.get("content-type") or "audio/wav"
            return TtsResult(
                audio=r.content,
                mime=mime.split(";")[0].strip(),
                raw={"engine": "cosyvoice", "base_url": self._base_url},
            )
        except SpeechError:
            raise
        except Exception as e:
            raise SpeechError(f"sidecar TTS 失败: {e}") from e
