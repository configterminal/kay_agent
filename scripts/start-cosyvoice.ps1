# 启动 CosyVoice-300M-Instruct sidecar（关 MOCK；仅 conda cosyvoice）
# 用法: .\scripts\start-cosyvoice.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "services\cosyvoice_tts\vendor\CosyVoice"
$Server = Join-Path $Root "services\cosyvoice_tts\server.py"
$ModelDir = Join-Path $Root "models\cosyvoice\300M-Instruct"
$Py = "F:\miniconda3\envs\cosyvoice\python.exe"

if (-not (Test-Path $Py)) { throw "conda env cosyvoice missing: $Py" }
if (-not (Test-Path $Vendor)) { throw "CosyVoice vendor missing: $Vendor" }
if (-not (Test-Path $ModelDir)) { throw "model missing: $ModelDir" }

$env:COSYVOICE_MOCK = "0"
$env:COSYVOICE_MODEL_DIR = $ModelDir
$env:COSYVOICE_HOST = "127.0.0.1"
$env:COSYVOICE_PORT = "8092"
# CosyVoice 包 + Matcha-TTS
$env:PYTHONPATH = "$Vendor;$Vendor\third_party\Matcha-TTS"

Write-Host "CosyVoice sidecar → http://127.0.0.1:8092  model=$ModelDir"
& $Py $Server
