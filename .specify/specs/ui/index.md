# Web UI — ChatGPT 风格界面

> Vue 3 + Vite 构建  
> 语音 I/O：`useVoiceChat` 适配层，不侵入对话逻辑。🎤 输入经 ASR 转文字 → 送入 LLM；语音模式下 LLM 直接输出口语 → TTS 自动朗读（口语转换是 LLM 职责，非前端清洗）。

## 整体布局

```
┌──────────────────────────────────────────────────────────────────┐
│                       AI 助教                                    │
├──────────────┬───────────────────────────────────────────────────┤
│              │                                                   │
│  💬 新对话    │  有什么可以帮你的？                                 │
│  📋 学习报告   │                                                   │
│  💡 课程推荐   │  建议卡片：                                       │
│  🎯 岗位匹配   │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  💬 模拟面试   │  │ 📚 学习    │ │ 💡 推荐   │ │ 💬 面试   │       │
│              │  │ 进度报告   │ │ 下一课     │ │ 模拟练习   │       │
│  ──────────  │  └──────────┘ └──────────┘ └──────────┘       │
│  历史对话     │                                                   │
│  · 刚 学习报告 │  ┌─────────────────────────────────────────┐    │
│  · 昨 RAG     │  │ [🎧] 输入问题...              [🎤] [↑]   │    │
│  · 周 哈希     │  └─────────────────────────────────────────┘    │
│              │   AI 助教仅供参考，关键信息以课程内容为准。          │
│ ──────────   │                                                   │
│ 👤 学员 001   │  ┌─ VideoDock（点 citation 后展开）─────────┐   │
│ 温柔鼓励型    │  │ <video>  seek 到 start_sec                 │   │
│              │  └───────────────────────────────────────────┘   │
└──────────────┴───────────────────────────────────────────────────┘
```

- 🎧 = 语音模式开关（点击切换，开启后助教回复自动 TTS 朗读）
- 🎤 = 麦克风按钮（录音 → ASR → 文本填入输入框）  
- 🔊 = 每条助理消息底部喇叭按钮（手动朗读该条回复）

答案跳转课程视频（citations → `/media` → seek）见 [video-jump.md](video-jump.md)。  
简历优化结果 A4/PDF 预览与下载见 [resume-pdf.md](resume-pdf.md)。  
模拟面试见 [interview-multimodal.md](interview-multimodal.md)：**全屏游戏态 P0 已联调**；开发态有 DEBUG 文字入口，生产默认隐藏。  
端到端延迟与优化见 [性能问题](../performance.md)。

## 跨屏 / DPI 布局

**根因（已用 Playwright 实测）**：浏览器窗口拖到另一块屏后，Chrome/Windows
会出现 `outerWidth >> innerWidth`（例：窗口约 2554，页面仍按 1280 排版），
布局视口卡住 → 内容只占一角，其余空白/发白，侧栏与输入看起来错位。

**对策**（`src/ui/src/viewport.js`）：

1. `#app`：`position: fixed; inset: 0`
2. 写入 `--app-width` / `--app-height`，供 ResumeDock 等使用
3. 检测 stale（outer 远大于 inner）→ **zoom nudge** 逼 Chromium 重算视口
4. 仍失败则 **session 内整页刷新一次**（防死循环）
5. 派发 `app-viewport-change`（VideoDock → Plyr `resize`）

## 页面状态

### 1. 新对话（空状态）

- 左侧「新对话」高亮
- 主区域显示问候语 + 3 个建议卡片
- 建议卡片点击 → 自动填入输入框并发送

### 2. 对话中

- 主区域显示对话历史（Markdown 渲染）
- 每条助手回复带：来源标注 + 复制/点赞/踩按钮
- 左侧历史列表实时更新标题

### 3. 功能入口（学习报告/课程推荐/岗位匹配/模拟面试）

- 点击左侧入口 → 自动发送对应预设指令
- 指令被 Supervisor 路由到对应 Agent
- Agent 返回结构化数据 → 前端渲染为卡片样式

## 交互细节

| 交互 | 实现 |
|------|------|
| 输入 | Enter 发送，Shift+Enter 换行，自动调整高度 |
| 语音输入 | 🎤 点击录音 → VAD 自动切句 → ASR → 文本填入输入框 |
| 语音模式 | 🎧 一键切换；开启后 LLM 直接输出口语（无 Markdown/Emoji），回复完毕自动 TTS 朗读 |
| 手动朗读 | 每条助理消息底部 🔈 按钮，点击朗读该条回复（非语音模式下可用） |
| 发送中 | 按钮禁用 + 打字指示器 |
| Markdown | 助手回复支持代码块、列表、加粗 |
| 反馈 | 点赞/踩 → 写入后端 |
| 来源标注 | `citations` 列表；可点项跳转视频（见 [video-jump.md](video-jump.md)） |
| 点来源 | 底部 VideoDock 打开对应 mp4 并 seek 到 `start_sec` |
| 历史恢复 | 点击左侧历史项 → 加载对应 thread（服务端历史暂无 citations） |
| 指令前缀 | `/报告` `/推荐` `/岗位` `/面试` `/切换人格` |

## 技术栈

| 层 | 选型 |
|------|------|
| 前端框架 | Vue 3 + Composition API |
| 构建工具 | Vite |
| 后端 API | FastAPI（待实现） |
| 通信 | SSE（流式输出）/ REST |

## 组件树

```
App.vue                         ← voiceMode 状态；流式完成自动 ttsSpeak()
├── Sidebar.vue
├── ChatView.vue                ← 转发 voiceMode prop + toggleVoiceMode event
│   ├── WelcomeCard.vue         # 可「进入面试」
│   ├── MessageItem.vue         # citations / 简历 / 进入面试 CTA / 🔈 手动朗读
│   ├── VideoDock.vue
│   ├── ResumeDock.vue
│   └── ChatInput.vue           # 🎧语音模式 + 🎤录音 + ↑发送
└── InterviewStage.vue          # 全屏游戏态（与聊天互斥；DEV 下 DEBUG 文字入口）
    ├── PortraitAvatar.vue      # Avatar 插槽 P0
    └── useInterviewSession     # Voice（含 submitText 调试）
```

### 语音相关 composable

| 模块 | 用途 |
|------|------|
| `useVoiceChat.js` | 聊天语音 I/O：录音（VAD→ASR→文本）+ TTS 播放（直接送 TTS，不本地清洗——口语由 LLM 生成时保证） |
| `useInterviewSession.js` | 面试场语音：开麦常听 / VAD 切句 / barge-in / 相同 ASR/TTS 端点 |

两个 composable 复用同一套后端 ASR/TTS 端点（`/interview/asr`、`/interview/tts`），但 `useVoiceChat` 的 TTS 部分（`isSpeaking`、`speak`、`stopSpeaking`）是**模块级单例**——所有 MessageItem 共享同一个播放状态。
