---
name: interview-speech-lifecycle
description: >-
  模拟面试语音生命周期：进场前 discover/prepare TTS 引擎（Edge / 本机 Cosy sidecar / 预留远程），
  按健康与显存动态选择；禁止为腾显存把 Embedding 迁 CPU。
  当用户要开模拟面试、启停 CosyVoice、排查面试 TTS 时使用。
---

# 面试语音生命周期（发现式 TTS）

**项目路径**：`skills/interview-speech-lifecycle/`

进面试场时**动态发现**当前可用的 TTS，再选定引擎。面向以后分布式（多 GPU 节点注册同一目录）。

| 文件 | 用途 |
|------|------|
| [COPY_PROMPTS.md](COPY_PROMPTS.md) | 复制到其他 Agent 视口 |
| 架构 | [`.specify/specs/ui/interview-multimodal.md`](../../.specify/specs/ui/interview-multimodal.md) |
| sidecar | [`services/cosyvoice_tts/`](../../services/cosyvoice_tts/) |

## 原则

1. **主应用 Python 3.13**；CosyVoice **独立 conda 3.10** sidecar（不能进主 venv）
2. **禁止**把 Embedding/Rerank 迁到 CPU 腾显存（影响实时检索体感）
3. 空闲显存不够本机 Cosy、又无远程节点 → **诚实用 Edge**（不是故障）
4. 引擎选择走 **discover 结果**，不要让 LLM 临场拍板

## 何时用

- 用户：开模拟面试 / 起 CosyVoice / 面试没声音 / 换 TTS 引擎
- 产品进场：前端调 `POST /api/interview/speech/prepare`
- Cursor Agent：按本 Skill 启停 sidecar、查 engines

## 工作流

```
- [ ] 1. GET /api/interview/speech/engines（或 prepare）看 available
- [ ] 2. 需要本机 Cosy 且目录显示可启 → 起 services/cosyvoice_tts（conda cosyvoice）
- [ ] 3. POST /api/interview/speech/prepare → 记录 selected engine
- [ ] 4. 进 InterviewStage；TTS 走选定 endpoint
- [ ] 5. 结束面试可选 POST .../speech/release（仅停本场拉起的本机 Cosy）
```

## 决策摘要

| 条件 | 选择 |
|------|------|
| 远程 Cosy `/ready` 且 priority 高 | 远程 Cosy |
| 本机 Cosy 已 ready | 复用本机 Cosy |
| 本机空闲显存 ≥ `COSYVOICE_MIN_FREE_VRAM_MB`（默认 4200）且 env 可启 | 尝试启本机 Cosy |
| 否则 | **edge** |

默认 Cosy 型号：**300M-Instruct**（适配 ~8GB 单卡且不拆 BGE）。CosyVoice2-0.5B 仅作可选高端（通常需更多空闲显存）。

**本机状态（2026-07-17）**：conda `cosyvoice` + cu128（含 `sm_120`）+ 权重已装；启动 `.\scripts\start-cosyvoice.ps1`；端到端 `prepare`→`cosy_local` 已验。

## 禁止

- 为起 Cosy 卸载/迁走主服务 Embedding
- 把 Cosy 依赖装进 `f:\agent\.venv`（3.13）
- 假定 Cosy 一定可用（sidecar 未起则 Edge）

## 验收

1. 无 Cosy sidecar：`prepare` → `selected=edge`，面试场可播  
2. Cosy ready：`prepare` → `cosy_*`，音色非 Edge（**本机已通过**）  
3. HUD/响应里能看到实际引擎 id  
4. 启动：`.\scripts\start-cosyvoice.ps1`（关 MOCK）
