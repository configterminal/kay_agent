# CosyVoice TTS Sidecar

独立 **Python 3.10** conda 环境 `cosyvoice`，为 AI 助教主应用（Python 3.13）提供 CosyVoice HTTP TTS。  
**不影响**主项目 `.venv` / `f:\jupyter` / 系统 CUDA。

## 为什么单独环境？

官方 CosyVoice 依赖与主项目 3.13 不兼容；RTX 50 系列还需 **cu128** torch（含 `sm_120`），不能装进主 venv。

## 快速联调（Mock，无需装 Cosy）

```powershell
$env:COSYVOICE_MOCK="1"
& f:\agent\.venv\Scripts\python.exe f:\agent\services\cosyvoice_tts\server.py
```

## 正式试用（300M-Instruct，已装路径）

前置（本机已完成可跳过）：

1. `conda create -n cosyvoice -y python=3.10`
2. 仓库：`services/cosyvoice_tts/vendor/CosyVoice`（git clone --recursive）
3. 权重：`models/cosyvoice/300M-Instruct`（ModelScope `iic/CosyVoice-300M-Instruct`）
4. 依赖：推理最小集 + **覆盖**  
   `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128`  
   验收：`torch.cuda.get_arch_list()` 含 `sm_120`  
5. 下载建议走 Clash：`$env:HTTP_PROXY='http://127.0.0.1:7897'`（端口以本机为准）

启动：

```powershell
cd f:\agent
.\scripts\start-cosyvoice.ps1
# 监听 127.0.0.1:8092；COSYVOICE_MOCK=0
```

主应用 `.env`：

```
TTS_ENGINES=edge,cosy_local
TTS_BASE_URL=http://127.0.0.1:8092
COSYVOICE_MODEL=300m-instruct
COSYVOICE_MIN_FREE_VRAM_MB=3500
```

进面试：`POST /api/interview/speech/prepare` → 期望 `selected=cosy_local`（sidecar 已 ready 时）。

## 验收

1. `GET http://127.0.0.1:8092/ready` → `mock=false`
2. TTS 非静音、非 Edge 音色
3. 看 `nvidia-smi` 独显占用与延迟；过慢则停 sidecar，自动回落 Edge

**本机实测（2026-07-17）**：`prepare`→`cosy_local`；面试官短句经主应用 TTS ~49s / ~450KB wav；样例 `tmp/cosy_tts_demo.wav`。

## 卸载试用

停 sidecar → `conda remove -n cosyvoice --all` → 删 `models/cosyvoice`（可选删 `vendor/CosyVoice`）。

参见 Skill：`skills/interview-speech-lifecycle/`。
