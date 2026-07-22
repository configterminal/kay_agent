"""
CosyVoice TTS sidecar — Python 3.10 conda 环境运行。

模式：
- MOCK=1：不加载 Cosy，返回短静音 wav（联调主应用发现/路由）
- 默认：加载 CosyVoice-300M-Instruct（需按 README 安装）
"""

from __future__ import annotations

import io
import os
import wave
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

HOST = os.environ.get("COSYVOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("COSYVOICE_PORT", "8092"))
MOCK = os.environ.get("COSYVOICE_MOCK", "").strip() in {"1", "true", "yes"}
MODEL_DIR = os.environ.get(
    "COSYVOICE_MODEL_DIR",
    "",
)

_model: Any = None
_load_error: str = ""


def _silent_wav(duration_sec: float = 0.4, rate: int = 22050) -> bytes:
    """生成短静音 wav（mock）。"""
    n = int(rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def _load_cosy() -> None:
    global _model, _load_error
    if MOCK:
        _load_error = ""
        return
    if _model is not None:
        return
    try:
        # CosyVoice 官方包路径需加入 PYTHONPATH（见 README）
        from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore

        model_dir = MODEL_DIR or "pretrained_models/CosyVoice-300M-Instruct"
        _model = AutoModel(model_dir=model_dir)
        _load_error = ""
    except Exception as e:
        _load_error = str(e)
        _model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MOCK:
        try:
            _load_cosy()
        except Exception:
            pass
    yield


app = FastAPI(title="CosyVoice TTS Sidecar", lifespan=lifespan)


class TtsIn(BaseModel):
    text: str
    instruct: str | None = None
    voice: str | None = None
    model: str | None = None


@app.get("/ready")
def ready():
    if MOCK:
        return {"ready": True, "detail": "mock mode", "mock": True}
    if _model is not None:
        return {"ready": True, "detail": "cosyvoice loaded", "mock": False}
    _load_cosy()
    if _model is not None:
        return {"ready": True, "detail": "cosyvoice loaded", "mock": False}
    return {
        "ready": False,
        "detail": _load_error or "model not loaded",
        "mock": False,
    }


@app.post("/tts")
def tts(body: TtsIn):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text empty")
    if MOCK:
        return Response(content=_silent_wav(), media_type="audio/wav")

    _load_cosy()
    if _model is None:
        raise HTTPException(503, _load_error or "cosyvoice not ready")

    instruct = body.instruct or (
        "用自然的中文口语说话，语速正常，吐字清楚，语气平和专业。"
    )
    try:
        # 300M-Instruct: inference_instruct；具体 API 以安装的 CosyVoice 版为准
        chunks = []
        if hasattr(_model, "inference_instruct"):
            for _, out in enumerate(
                _model.inference_instruct(text, "中文女", instruct, stream=False)
            ):
                chunks.append(out["tts_speech"])
        elif hasattr(_model, "inference_sft"):
            for _, out in enumerate(_model.inference_sft(text, "中文女", stream=False)):
                chunks.append(out["tts_speech"])
        else:
            raise RuntimeError("unsupported cosyvoice API")

        import torch
        import numpy as np
        import soundfile as sf

        wav = torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]
        # torchaudio.save 在新 torch 依赖 torchcodec；改用 soundfile 写 wav
        audio = wav.detach().cpu().numpy()
        if audio.ndim == 2:
            audio = audio[0] if audio.shape[0] <= 2 else audio.T
        bio = io.BytesIO()
        sf.write(bio, audio.astype(np.float32), int(_model.sample_rate), format="WAV")
        return Response(content=bio.getvalue(), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(500, f"tts failed: {e}") from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
