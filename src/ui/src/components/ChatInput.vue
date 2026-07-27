<script setup>
import { ref, computed, nextTick } from 'vue'
import { useVoiceChat } from '../composables/useVoiceChat.js'

const props = defineProps({
  disabled: Boolean,
  voiceMode: Boolean,
})

const emit = defineEmits(['send', 'toggleVoiceMode'])

const text = ref('')
const textareaRef = ref(null)

// ── 语音 ──
const { isRecording, audioLevel, startRecording, stopRecording } = useVoiceChat({
  onError: (msg) => console.warn('[语音]', msg),
})

/** 点击麦克风：开始/停止录音，识别文本自动填入输入框 */
async function toggleRecording() {
  if (isRecording.value) {
    const result = await stopRecording()
    if (result) {
      text.value = result
      autoResize()
    }
  } else {
    const result = await startRecording()
    if (result) {
      text.value = result
      autoResize()
    }
  }
}

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    }
  })
}

function onInput() {
  autoResize()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function sendMessage() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled) return
  emit('send', trimmed)
  text.value = ''
  nextTick(autoResize)
}

const placeholderText = computed(() => {
  if (isRecording.value) return '正在聆听…'
  if (props.voiceMode) return '语音模式已开启，输入问题…'
  return '输入你的问题…'
})
</script>

<template>
  <div class="chat-input">
    <div class="input-wrapper">
      <!-- 语音模式切换 -->
      <button
        class="voice-mode-btn"
        :class="{ active: voiceMode }"
        @click="emit('toggleVoiceMode')"
        :title="voiceMode ? '关闭语音模式' : '开启语音模式（助教将用语音回复）'"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
          <path v-if="voiceMode" d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
          <line v-if="!voiceMode" x1="23" y1="9" x2="17" y2="15"></line>
          <line v-if="!voiceMode" x1="17" y1="9" x2="23" y2="15"></line>
        </svg>
      </button>
      <textarea
        ref="textareaRef"
        v-model="text"
        class="input-textarea"
        :disabled="disabled || isRecording"
        :placeholder="placeholderText"
        rows="1"
        @input="onInput"
        @keydown="onKeydown"
      ></textarea>
      <button
        class="mic-btn"
        :class="{ recording: isRecording }"
        :disabled="disabled"
        @click="toggleRecording"
        :title="isRecording ? '点击停止录音' : '语音输入'"
      >
        <svg v-if="!isRecording" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
          <line x1="12" y1="19" x2="12" y2="23"></line>
          <line x1="8" y1="23" x2="16" y2="23"></line>
        </svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="2"></rect>
        </svg>
      </button>
      <button
        class="send-btn"
        :class="{ disabled: !text.trim() || disabled }"
        :disabled="!text.trim() || disabled"
        @click="sendMessage"
        title="发送 (Enter)"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="19" x2="12" y2="5"></line>
          <polyline points="5 12 12 5 19 12"></polyline>
        </svg>
      </button>
    </div>
    <!-- 录音音量指示条 -->
    <div v-if="isRecording" class="audio-bar-wrap">
      <div class="audio-bar" :style="{ width: (audioLevel * 100) + '%' }"></div>
    </div>
    <p v-else class="input-hint">Enter 发送，Shift+Enter 换行</p>
  </div>
</template>

<style scoped>
.chat-input {
  flex-shrink: 0;
  padding: 12px 16px 16px;
  background: var(--bg-primary);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 768px;
  margin: 0 auto;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.15s;
}

.input-wrapper:focus-within {
  border-color: var(--accent);
}

.input-textarea {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 15px;
  line-height: 1.5;
  padding: 4px 0;
  max-height: 200px;
  resize: none;
}

.input-textarea::placeholder {
  color: var(--text-secondary);
}

.input-textarea:disabled {
  opacity: 0.5;
}

.voice-mode-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, color 0.15s;
}

.voice-mode-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.voice-mode-btn.active {
  background: rgba(74, 144, 217, 0.15);
  color: var(--accent);
}

.mic-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, color 0.15s;
}

.mic-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.mic-btn.recording {
  background: #e53e3e;
  color: #fff;
  animation: mic-pulse 1.2s ease-in-out infinite;
}

@keyframes mic-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0.5); }
  50% { box-shadow: 0 0 0 6px rgba(229, 62, 62, 0); }
}

.send-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, opacity 0.15s;
}

.send-btn:hover:not(.disabled) {
  background: var(--accent-hover);
}

.send-btn.disabled {
  background: var(--bg-hover);
  color: var(--text-secondary);
  cursor: not-allowed;
}

.audio-bar-wrap {
  max-width: 768px;
  margin: 6px auto 0;
  height: 3px;
  background: var(--bg-surface);
  border-radius: 2px;
  overflow: hidden;
}

.audio-bar {
  height: 100%;
  background: #e53e3e;
  border-radius: 2px;
  transition: width 0.08s linear;
}

.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 8px;
  max-width: 768px;
  margin-left: auto;
  margin-right: auto;
}
</style>
