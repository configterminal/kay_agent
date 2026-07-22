# 模拟面试多模态（全屏游戏态）

> 状态：**P0 已落地**；**语音主路径（开麦 + VAD + WAV ASR）已切**；TTS 默认 Edge | 最后更新：2026-07-18  
> Agent：[interview.md](../agents/interview.md) · 推理插拔：[inference-services.md](../inference-services.md)

## 1. 原则

- **全屏游戏态**：进入后面试盖住侧栏与聊天；结束后退回聊天
- **开麦常听** + VAD 切句；**交流打断**（无跳过按钮）
- **虚拟面试官**：表现层插槽，本期 P0 氛围人像；可整模块替换
- ASR/TTS：`src/speech/` Provider（SenseVoice + Edge / **可选 CosyVoice sidecar**）；Agent 只吃文本

## 2. 产品形态

| 项 | 决定 |
|----|------|
| 形态 | 全屏 `InterviewStage`（`fixed; inset: 0`） |
| 进入 | WelcomeCard「模拟面试」/ 助手气泡「进入面试」；先 `speech/ready` + 授权麦；**开场 TTS 仅为短自我介绍**（不念聊天气泡里的设定/画像长文） |
| 退出 | 「结束面试」→ 停麦停播 → 回聊天 |
| 会话 | 同一 `thread_id`；字幕同步进 messages |
| 数字人 | P0 立绘/CSS；Avatar 契约稳定后可换 P1/P2 |

```
┌──────────────────────────────────────────────────────────┐
│  [结束面试]                                    状态 HUD   │
│              ┌─────────────────────┐                     │
│              │   PortraitAvatar    │                     │
│              └─────────────────────┘                     │
│         「面试官字幕…」 / 学员识别字幕                     │
│              ~~~~ 电平 ~~~~                              │
│   [DEBUG] 打字代替说话…（仅开发态，见 §7）                │
└──────────────────────────────────────────────────────────┘
```

## 3. 模块封装（禁止跨模块直连实现）

```
Stage → VoiceSession → ChatBridge
Stage → Avatar（只传 state / audioLevel / subtitle）
Avatar ✗→ Voice / Chat
Voice ✗→ Avatar DOM
```

| 模块 | 路径 | 契约 | 可替换 |
|------|------|------|--------|
| Stage | `components/interview/InterviewStage.vue` | open/close；HUD/字幕 | 场景皮肤 |
| Avatar | `components/interview/avatars/PortraitAvatar.vue` | `state` / `audioLevel?` / `subtitle?` | 整文件换 Live2D 等 |
| Voice | `composables/useInterviewSession.js` | `start` / `stop` / `submitText`；state | VAD/录音实现 |
| ChatBridge | App 注入 `sendInterviewTurn(text)→assistantText` | 同 thread `/api/chat` | 以后 SSE |

### Avatar props

```text
state: idle | listening | capturing | thinking | speaking | error
audioLevel?: number  # 0~1
subtitle?: string
```

### 渲染技术（本期）

Vue 3 + CSS；Avatar 用 `<img>`/`<video>` + CSS；Web Audio `AnalyserNode`；`MediaRecorder` + `HTMLAudioElement`。  
不用 Three.js / Live2D / WebGL（留给 Avatar P2）。

## 4. 状态机

```
Boot → Ready → Speaking ⇄ Listening → Capturing → Transcribing → Thinking → Speaking
                 ↑______________ barge-in ______________________|
Ready/Speaking/Thinking → Exit → 回聊天
```

- Speaking：麦开着，阈值防回声；命中则停 TTS → Capturing  
- Thinking：不向 ASR 交句  
- **调试文字**：`submitText(text)` 跳过 ASR，直接 Thinking → Speaking（与口说同链路）

## 5. 后端 API（已通）

| 接口 | 作用 |
|------|------|
| `GET /api/interview/speech/ready` | ASR/TTS 探测 |
| `GET /api/interview/speech/engines` | **发现**可用 TTS 引擎目录 |
| `POST /api/interview/speech/prepare` | 发现 → 必要时启本机 Cosy → 选定引擎 |
| `POST /api/interview/speech/release` | 停本场拉起的本机 Cosy（不碰 Embedding） |
| `POST /api/interview/asr` | 音频 → 文本（SenseVoice；剥离事件标签） |
| `POST /api/interview/tts` | 文本 → 音频（走 prepare 选定引擎；默认可 Edge） |

配置：`ASR_*` / `TTS_*` / `TTS_ENGINES` / `COSYVOICE_*`（见 `SpeechSettings`）。  
Skill：[`skills/interview-speech-lifecycle/`](../../skills/interview-speech-lifecycle/SKILL.md)。

## 6. 实现与联调状态（2026-07-17）

| 项 | 状态 |
|----|------|
| speech Provider + API | **已通** |
| SenseVoice 标签清洗 | **已修** |
| 全屏 Stage + 四模块 | **已落地** |
| 调试文字入口 | **默认关闭**；仅 `localStorage.interview_debug=1`（见 §7） |
| 开麦语音主路径 | **已切**：PCM→WAV→ASR；HUD「开麦中」；停顿自动切句 |
| TTS 引擎发现 / prepare / release | **已通**（默认 Edge；Cosy 后续再开） |
| CosyVoice sidecar（300M-Instruct，Py3.10） | **本机已试用**；**当前产品默认改回 Edge**（Cosy 细节后续再开） |
| Cosy 实测 | `prepare`→`cosy_local`；面试官短句 TTS ~49s / ~450KB wav；独显约 4GB 占用；启动 `.\scripts\start-cosyvoice.ps1` |
| Embedding 迁 CPU 腾显存 | **禁止（不做）** |
| 跳过播报按钮 | 不做 |

## 7. 调试方案

目的：联调 Agent / TTS / 字幕时**不必依赖麦克风与 ASR**。

| 方式 | 何时出现 | 行为 |
|------|----------|------|
| 默认 | 任意环境 | **不渲染**打字框；开麦直接说话 |
| 临时 DEBUG | `localStorage.setItem('interview_debug','1')` 后刷新 | 打字 → `submitText` → chat → TTS |
| 关闭调试 | `localStorage.removeItem('interview_debug')` | 回到纯语音 |

实现位置：

- UI：[`InterviewStage.vue`](../../src/ui/src/components/interview/InterviewStage.vue)（`showDebugInput`）
- 会话：[`useInterviewSession.js`](../../src/ui/src/composables/useInterviewSession.js) → `submitText`

建议联调顺序：

1. `GET /api/interview/speech/ready` → ASR/TTS 就绪  
2. `POST /api/interview/speech/prepare` → `selected=edge`  
3. 进入面试场 → 授权麦 → HUD「开麦中」  
4. 说一句 → 字幕 → 回复 → TTS；开口可打断  
5. （可选）`interview_debug=1` 打字对照 Agent

## 8. CosyVoice 与引擎发现（分布式预留）

- **主应用 3.13**；Cosy **conda 3.10 sidecar**（`services/cosyvoice_tts/` + `scripts/start-cosyvoice.ps1`）  
- 默认型号：**300M-Instruct**（本机 RTX 5070 8GB + cu128 torch / `sm_120` 已跑通）；2-0.5B 仍可选高端  
- **禁止**为腾显存把 Embedding/Rerank 迁 CPU  
- sidecar 未起或空闲不够 → **Edge**（预期行为）  
- 引擎目录：`TTS_ENGINES=edge,cosy_local`；以后可加 `cosy_gpu2` + URL  
- 运维说明：[README](../../../services/cosyvoice_tts/README.md) · Skill [`interview-speech-lifecycle`](../../../skills/interview-speech-lifecycle/SKILL.md)

## 9. 下一阶段任务包（按需选做）

> 更新：2026-07-17。**A（真 Cosy 300M）已完成试用**；其余候选不并行乱开。

| 包 | 目标 | 状态 / 验收 |
|----|------|-------------|
| **A. Cosy 正式音色** | conda `cosyvoice` + 300M-Instruct；非 MOCK | **已完成（试用）**：`prepare`→`cosy_local`；样例 `tmp/cosy_tts_demo.wav`；首句偏慢可接受 |
| **B. 真机麦 / VAD** | 开麦切句与 barge-in；补 ASR 验收 | **已切语音主路径**（WAV ASR）；请本机说一句验收 |
| **C. Avatar P1** | 口型/表情随 `state`+`audioLevel` | 待做 |
| **D. Avatar P2** | Live2D / 轻量 3D（可选） | 待做（P1 后） |
| **E. 产品体验（跨模块）** | QA 双重检索跳过等，见 [performance.md](../performance.md) | **下一优先**：约省 3～4s/问答 |

**推荐顺序（单卡日常开发）**

```
默认 TTS = Edge；面试输入 = 开麦语音（当前）
E（性能 P0）→ C（Avatar P1）→ D
（Cosy 云端/本机优化：搁置，后续再开）
```

**明确不做**

- Embedding/Rerank 迁 CPU 腾显存  
- 跳过播报按钮  
- 把 Cosy 依赖装进主 venv 3.13
