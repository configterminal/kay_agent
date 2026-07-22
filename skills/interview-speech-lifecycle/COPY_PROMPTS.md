# 复制到其他 Agent 视口

模拟面试语音：进场前动态发现 TTS（Edge / Cosy sidecar / 远程预留），**不要**把 Embedding 迁 CPU 腾显存。

```
请按 skills/interview-speech-lifecycle/SKILL.md：
1. 查 GET /api/interview/speech/engines
2. 需要本机 Cosy 时按 services/cosyvoice_tts/README.md 用 conda py3.10 启动
3. POST /api/interview/speech/prepare 后再进面试场
4. 显存不够就用 Edge，不要拆主服务 GPU 模型
```
