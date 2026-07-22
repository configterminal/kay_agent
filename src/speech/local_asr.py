"""本地 ASR — FunASR SenseVoice（优先）；未安装时 ready=False。"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from src.config import config
from src.speech.base import AsrResult, SpeechError

logger = logging.getLogger(__name__)


class LocalAsrProvider:
    """本机 ASR Provider（SenseVoice / Fun-ASR）"""

    name = "local"

    def __init__(self) -> None:
        self._model_name = (config.speech.asr_model or "sensevoice").lower().strip()
        self._model = None
        self._device = "cuda:0"

    def ready(self) -> tuple[bool, str]:
        try:
            import funasr  # noqa: F401
        except ImportError:
            return False, (
                "funasr 未安装：pip install funasr --target f:\\jupyter "
                f"(当前 ASR_MODEL={self._model_name})"
            )
        return True, f"local asr configured (model={self._model_name})"

    def warmup(self) -> None:
        ok, msg = self.ready()
        if not ok:
            raise SpeechError(msg)
        self._ensure_model()
        logger.info("LocalAsrProvider warmup ok: %s", self._model_name)

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from funasr import AutoModel

        # 注册名 SenseVoiceSmall；下载源 iic/SenseVoiceSmall（modelscope）
        if self._model_name in {"sensevoice", "sensevoice-small", "iic/sensevoicesmall"}:
            model_id = "iic/SenseVoiceSmall"
        elif self._model_name in {"fun-asr-nano", "funasr-nano", "nano"}:
            model_id = "FunASRNano"
        else:
            model_id = self._model_name

        last_err: Exception | None = None
        for device in (self._device, "cpu"):
            try:
                self._model = AutoModel(
                    model=model_id,
                    vad_model="fsmn-vad",
                    device=device,
                    disable_update=True,
                )
                logger.info("LocalAsr loaded model=%s device=%s", model_id, device)
                return
            except Exception as e:
                last_err = e
                logger.warning("ASR load failed device=%s: %s", device, e)
        raise SpeechError(f"无法加载 ASR 模型 {model_id}: {last_err}")

    def transcribe(self, audio: bytes, *, mime: str = "audio/webm") -> AsrResult:
        """识别一句学员语音。"""
        if not audio:
            raise SpeechError("ASR 音频为空")
        ok, msg = self.ready()
        if not ok:
            raise SpeechError(msg)

        self._ensure_model()
        suffix = _suffix_for_mime(mime)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            path = tmp.name
        try:
            res = self._model.generate(
                input=path,
                language="zh",
                use_itn=True,
            )
            text = _extract_text(res)
            return AsrResult(
                text=text.strip(),
                duration_ms=0,
                language="zh",
                raw={"engine": "funasr", "model": self._model_name},
            )
        finally:
            Path(path).unlink(missing_ok=True)


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "wav" in m:
        return ".wav"
    if "mpeg" in m or "mp3" in m:
        return ".mp3"
    if "ogg" in m:
        return ".ogg"
    if "mp4" in m or "m4a" in m:
        return ".m4a"
    return ".webm"


def _extract_text(res) -> str:
    if not res:
        return ""
    if isinstance(res, list) and res:
        item = res[0]
        if isinstance(item, dict):
            raw = str(item.get("text") or item.get("preds") or "")
        else:
            raw = str(item)
    elif isinstance(res, dict):
        raw = str(res.get("text") or "")
    else:
        raw = str(res)
    return _strip_sensevoice_tags(raw)


def _strip_sensevoice_tags(text: str) -> str:
    """去掉 SenseVoice 事件标签，如 <|zh|><|NEUTRAL|><|Speech|>。"""
    import re

    cleaned = re.sub(r"<\|[^|>]+\|>", "", text or "")
    return cleaned.strip()
