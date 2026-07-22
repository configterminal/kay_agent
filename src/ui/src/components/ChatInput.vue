<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  disabled: Boolean,
})

const emit = defineEmits(['send'])

const text = ref('')
const textareaRef = ref(null)

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
</script>

<template>
  <div class="chat-input">
    <div class="input-wrapper">
      <textarea
        ref="textareaRef"
        v-model="text"
        class="input-textarea"
        :disabled="disabled"
        placeholder="输入你的问题..."
        rows="1"
        @input="onInput"
        @keydown="onKeydown"
      ></textarea>
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
    <p class="input-hint">Enter 发送，Shift+Enter 换行</p>
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
