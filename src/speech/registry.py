"""语音 Provider 工厂与单例。"""

from __future__ import annotations

import logging

from src.config import config
from src.speech.base import AsrProvider, SpeechError, TtsProvider

logger = logging.getLogger(__name__)

_asr: AsrProvider | None = None
_tts: TtsProvider | None = None


def _build_asr() -> AsrProvider:
    backend = config.speech.asr_backend.lower().strip()
    if backend == "local":
        from src.speech.local_asr import LocalAsrProvider
        return LocalAsrProvider()
    if backend == "http":
        from src.speech.http_backend import HttpAsrProvider
        return HttpAsrProvider()
    raise SpeechError(f"未知 ASR_BACKEND: {backend}")


def _build_tts() -> TtsProvider:
    backend = config.speech.tts_backend.lower().strip()
    if backend == "local":
        from src.speech.local_tts import LocalTtsProvider
        return LocalTtsProvider()
    if backend == "http":
        from src.speech.http_backend import HttpTtsProvider
        return HttpTtsProvider()
    raise SpeechError(f"未知 TTS_BACKEND: {backend}")


def get_asr_provider() -> AsrProvider:
    """获取 ASR Provider 单例。"""
    global _asr
    if _asr is None:
        _asr = _build_asr()
        logger.info("AsrProvider=%s", _asr.name)
    return _asr


def get_tts_provider() -> TtsProvider:
    """获取 TTS Provider 单例。"""
    global _tts
    if _tts is None:
        _tts = _build_tts()
        logger.info("TtsProvider=%s", _tts.name)
    return _tts


def reset_speech_providers() -> None:
    """测试用：清空单例。"""
    global _asr, _tts
    _asr = None
    _tts = None


def check_speech_ready() -> tuple[bool, str]:
    """探测 ASR/TTS 是否就绪（面试语音模式用；不影响主 chat）。"""
    asr = get_asr_provider()
    tts = get_tts_provider()
    a_ok, a_msg = asr.ready()
    t_ok, t_msg = tts.ready()
    return a_ok and t_ok, f"asr: {a_msg}; tts: {t_msg}"
