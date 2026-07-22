"""语音模块 — 可插拔 ASR / TTS（默认 local，http Cosy sidecar）。"""

from src.speech.base import AsrResult, SpeechError, TtsResult
from src.speech.lifecycle import (
    discover_tts_engines,
    prepare_interview_speech,
    release_interview_speech,
)
from src.speech.registry import (
    check_speech_ready,
    get_asr_provider,
    get_tts_provider,
    reset_speech_providers,
)

__all__ = [
    "AsrResult",
    "TtsResult",
    "SpeechError",
    "get_asr_provider",
    "get_tts_provider",
    "check_speech_ready",
    "reset_speech_providers",
    "discover_tts_engines",
    "prepare_interview_speech",
    "release_interview_speech",
]
