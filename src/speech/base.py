"""语音抽象层 — ASR / TTS 统一接口（对齐 Embedding Provider 模式）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class SpeechError(RuntimeError):
    """语音后端失败"""


@dataclass
class AsrResult:
    """语音识别结果"""
    text: str
    duration_ms: int = 0
    language: str = "zh"
    raw: dict = field(default_factory=dict)


@dataclass
class TtsResult:
    """语音合成结果"""
    audio: bytes
    mime: str = "audio/mpeg"
    sample_rate: int | None = None
    raw: dict = field(default_factory=dict)


@runtime_checkable
class AsrProvider(Protocol):
    """语音识别 Provider"""

    name: str

    def transcribe(self, audio: bytes, *, mime: str = "audio/webm") -> AsrResult:
        """音频字节 → 文本"""
        ...

    def ready(self) -> tuple[bool, str]:
        ...

    def warmup(self) -> None:
        ...


@runtime_checkable
class TtsProvider(Protocol):
    """语音合成 Provider（面试官播报）"""

    name: str

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        instruct: str | None = None,
    ) -> TtsResult:
        """文本 → 音频字节"""
        ...

    def ready(self) -> tuple[bool, str]:
        ...

    def warmup(self) -> None:
        ...
