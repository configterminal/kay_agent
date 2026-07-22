<script setup>
/**
 * 全屏面试场壳 — 组装 Avatar + Voice；不直连 ASR/TTS 实现细节。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import PortraitAvatar from './avatars/PortraitAvatar.vue'
import { createInterviewSession } from '../../composables/useInterviewSession.js'

const props = defineProps({
  /** ChatBridge：学员文本 → 助手回复文本 */
  sendTurn: { type: Function, required: true },
  /** 进入时若已有开场白，优先播报，不再发 kickoff */
  openingText: { type: String, default: '' },
})

const emit = defineEmits(['exit'])

const state = ref('boot')
const audioLevel = ref(0)
const captionInterviewer = ref('')
const captionUser = ref('')
const errorDetail = ref('')
const ttsEngine = ref('')
/** 麦克风已授权且采集中 */
const micLive = ref(false)

const session = createInterviewSession({
  sendTurn: (text) => props.sendTurn(text),
  onError: (msg) => {
    errorDetail.value = msg || '未知错误'
  },
})
session.bindRefs({
  state,
  audioLevel,
  captionInterviewer,
  captionUser,
  errorDetail,
  ttsEngine,
  micLive,
})

const statusLabel = computed(() => {
  const map = {
    idle: '已结束',
    boot: '正在准备麦克风…',
    listening: '请直接说话',
    capturing: '正在听你说…',
    transcribing: '识别中…',
    thinking: '面试官思考中…',
    speaking: '面试官说话中 · 可开口打断',
    error: '出错了',
  }
  const base = map[state.value] || state.value
  if (ttsEngine.value && state.value !== 'idle' && state.value !== 'boot') {
    return `${base} · ${ttsEngine.value}`
  }
  return base
})

const voiceHint = computed(() => {
  if (state.value === 'listening') return '麦克风常开，说完稍停即可自动识别'
  if (state.value === 'capturing') return '停顿约 0.7 秒会自动提交；也可点「说完了」'
  if (state.value === 'speaking') return '想插话时直接开口即可打断'
  return ''
})

const showFinishBtn = computed(() => state.value === 'capturing')

const avatarState = computed(() => {
  if (state.value === 'transcribing') return 'thinking'
  if (state.value === 'boot') return 'idle'
  return state.value
})

onMounted(() => {
  session.start(props.openingText || '')
})

onBeforeUnmount(() => {
  session.stop()
})

watch(
  () => props.openingText,
  () => {
    /* 仅首次 start 使用；中途不重开 */
  },
)

async function onExit() {
  await session.stop()
  emit('exit')
}

async function onRetry() {
  errorDetail.value = ''
  await session.stop()
  await session.start(props.openingText || '')
}

function onFinishUtterance() {
  session.finishNow()
}

/** 仅显式打开调试时显示打字入口；默认语音主路径 */
const showDebugInput = typeof localStorage !== 'undefined'
  && localStorage.getItem('interview_debug') === '1'

const debugText = ref('')
const debugBusy = computed(() => {
  return ['thinking', 'speaking', 'transcribing', 'boot'].includes(state.value)
})

async function onDebugSend() {
  const t = debugText.value.trim()
  if (!t || debugBusy.value) return
  debugText.value = ''
  await session.submitText(t)
}

function onDebugKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onDebugSend()
  }
}
</script>

<template>
  <div class="interview-stage" role="dialog" aria-label="模拟面试">
    <div class="stage-bg" aria-hidden="true" />

    <header class="stage-top">
      <button type="button" class="btn-exit" @click="onExit">结束面试</button>
      <div class="top-right">
        <div
          class="mic-pill"
          :class="{ on: micLive, hot: state === 'capturing' || state === 'listening' }"
          :title="micLive ? '麦克风已开启' : '麦克风未就绪'"
        >
          <span class="mic-dot" aria-hidden="true" />
          {{ micLive ? '开麦中' : '麦未开' }}
        </div>
        <div class="status-hud" :data-state="state">{{ statusLabel }}</div>
      </div>
    </header>

    <main class="stage-main">
      <PortraitAvatar
        :state="avatarState"
        :audioLevel="audioLevel"
        :subtitle="captionInterviewer"
      />

      <div v-if="errorDetail" class="stage-error">
        <p>{{ errorDetail }}</p>
        <button type="button" class="btn-retry" @click="onRetry">重试</button>
      </div>

      <p v-if="voiceHint" class="voice-hint">{{ voiceHint }}</p>

      <div class="caption-user" :class="{ active: captionUser && state !== 'speaking' }">
        <span class="caption-label">你</span>
        <span class="caption-text">{{ captionUser || '（对着麦克风直接说）' }}</span>
      </div>

      <div class="level-meter" aria-hidden="true" :class="{ live: micLive && (state === 'listening' || state === 'capturing') }">
        <div class="level-fill" :style="{ width: `${Math.round(audioLevel * 100)}%` }" />
      </div>

      <button
        v-if="showFinishBtn"
        type="button"
        class="btn-finish"
        @click="onFinishUtterance"
      >
        说完了
      </button>

      <form
        v-if="showDebugInput"
        class="debug-input"
        @submit.prevent="onDebugSend"
      >
        <span class="debug-badge">DEBUG</span>
        <input
          v-model="debugText"
          type="text"
          class="debug-field"
          placeholder="调试：打字代替说话（生产构建隐藏）"
          :disabled="debugBusy"
          @keydown="onDebugKeydown"
        />
        <button
          type="submit"
          class="debug-send"
          :disabled="debugBusy || !debugText.trim()"
        >
          发送
        </button>
      </form>
    </main>

    <footer class="stage-hint">
      语音交流：开麦后直接说话，停顿自动识别；面试官说话时可开口打断。
      <template v-if="showDebugInput"> · 已开启 DEBUG 打字</template>
    </footer>
  </div>
</template>

<style scoped>
.interview-stage {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  color: #e8eef6;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.stage-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 50% at 50% 20%, #1e3a5f 0%, transparent 55%),
    linear-gradient(165deg, #0b1018 0%, #121c2a 45%, #0a0e14 100%);
  z-index: 0;
}

.stage-top,
.stage-main,
.stage-hint {
  position: relative;
  z-index: 1;
}

.stage-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
}

.btn-exit {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(0, 0, 0, 0.35);
  color: #e8eef6;
  font-size: 14px;
  cursor: pointer;
}

.btn-exit:hover {
  border-color: rgba(255, 180, 120, 0.5);
  background: rgba(40, 20, 10, 0.5);
}

.top-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mic-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(200, 210, 220, 0.65);
}

.mic-pill.on {
  color: #c8f0d8;
  border-color: rgba(80, 200, 140, 0.35);
}

.mic-pill.hot .mic-dot {
  animation: mic-pulse 1.2s ease-in-out infinite;
}

.mic-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #666;
}

.mic-pill.on .mic-dot {
  background: #3dcf8e;
  box-shadow: 0 0 0 0 rgba(61, 207, 142, 0.45);
}

@keyframes mic-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(61, 207, 142, 0.45); }
  50% { box-shadow: 0 0 0 6px rgba(61, 207, 142, 0); }
}

.status-hud {
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-size: 13px;
  letter-spacing: 0.02em;
}

.voice-hint {
  margin: 0;
  font-size: 13px;
  color: rgba(180, 210, 230, 0.75);
  letter-spacing: 0.02em;
}

.status-hud[data-state='speaking'] {
  border-color: rgba(90, 160, 220, 0.5);
}
.status-hud[data-state='capturing'],
.status-hud[data-state='listening'] {
  border-color: rgba(80, 200, 140, 0.45);
}
.status-hud[data-state='error'] {
  border-color: rgba(220, 90, 90, 0.55);
}

.stage-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 12px 20px 8px;
  min-height: 0;
}

.stage-error {
  max-width: 420px;
  text-align: center;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(80, 20, 20, 0.55);
  border: 1px solid rgba(220, 100, 100, 0.4);
  font-size: 14px;
}

.btn-retry {
  margin-top: 8px;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: transparent;
  color: #e8eef6;
  cursor: pointer;
}

.caption-user {
  max-width: min(520px, 90vw);
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  opacity: 0.55;
  transition: opacity 0.2s;
}

.caption-user.active {
  opacity: 1;
  border-color: rgba(80, 200, 140, 0.35);
}

.caption-label {
  flex-shrink: 0;
  font-size: 12px;
  color: rgba(180, 220, 200, 0.9);
  padding-top: 2px;
}

.caption-text {
  font-size: 14px;
  line-height: 1.55;
  color: #d5dde8;
}

.level-meter {
  width: min(280px, 60vw);
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.1);
  overflow: hidden;
}

.level-meter.live {
  height: 5px;
  background: rgba(80, 200, 140, 0.15);
}

.btn-finish {
  margin-top: 4px;
  padding: 10px 28px;
  border-radius: 999px;
  border: 1px solid rgba(90, 180, 140, 0.55);
  background: rgba(30, 70, 50, 0.55);
  color: #d8f5e6;
  font-size: 15px;
  cursor: pointer;
  letter-spacing: 0.04em;
}

.btn-finish:hover {
  border-color: rgba(120, 220, 170, 0.75);
  background: rgba(40, 100, 70, 0.7);
}

.level-fill {
  height: 100%;
  background: linear-gradient(90deg, #3d9a6a, #5ab4e8);
  transition: width 0.05s linear;
}

.stage-hint {
  text-align: center;
  padding: 12px 16px 20px;
  font-size: 12px;
  color: rgba(200, 210, 220, 0.55);
}

.debug-input {
  display: flex;
  align-items: center;
  gap: 8px;
  width: min(520px, 92vw);
  margin-top: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px dashed rgba(255, 200, 80, 0.45);
  background: rgba(40, 30, 10, 0.45);
}

.debug-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #f0c050;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(240, 192, 80, 0.4);
}

.debug-field {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.35);
  color: #e8eef6;
  font-size: 14px;
}

.debug-field:disabled {
  opacity: 0.5;
}

.debug-send {
  flex-shrink: 0;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid rgba(240, 192, 80, 0.4);
  background: rgba(80, 60, 20, 0.5);
  color: #f5e6b8;
  font-size: 13px;
  cursor: pointer;
}

.debug-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
