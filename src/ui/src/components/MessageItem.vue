<script setup>
import { computed, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import { useVoiceChat } from '../composables/useVoiceChat.js'

const props = defineProps({
  message: {
    type: Object,
    required: true,
    // { role, content, source, timestamp, options?, optionsActive? }
  },
})

const emit = defineEmits(['selectOption', 'playCitation', 'openResume', 'enterInterview'])

// ── TTS 播放 ──
const { isSpeaking: ttsSpeaking, speak: ttsSpeak, stopSpeaking: ttsStop } = useVoiceChat({
  onError: (msg) => console.warn('[TTS]', msg),
})

function toggleTts() {
  if (ttsSpeaking.value) {
    ttsStop()
  } else {
    ttsSpeak(props.message.content).catch(() => {})
  }
}

/** 仅面试相关助手消息显示「进入面试」 */
const showInterviewEnter = computed(() => {
  if (props.message.role !== 'assistant') return false
  if (props.message.agent === 'interview_agent') return true
  const t = props.message.content || ''
  return /模拟面试|面试场|面试官|开始面试/.test(t)
})

function onEnterInterview() {
  // 不把整段聊天气泡当开场白朗读（避免念设定/画像文档）
  emit('enterInterview', {})
}

function canPlay(c) {
  return Boolean(c?.media_url) && Number(c?.start_sec) >= 0
}

function onPlayCitation(c) {
  if (!canPlay(c)) return
  emit('playCitation', c)
}

const hasResume = computed(() => {
  return (
    props.message.role === 'assistant'
    && Boolean(props.message.resume_artifact_id)
  )
})

const resumeBtnLabel = computed(() => {
  return props.message.resume_mode === 'target' ? '查看蓝图简历' : '查看优化简历'
})

function onOpenResume() {
  if (!hasResume.value) return
  emit('openResume', {
    artifactId: props.message.resume_artifact_id,
    mode: props.message.resume_mode || 'fact',
    title: props.message.resume_title || '',
  })
}

function citationLabel(c) {
  if (c?.source) return c.source
  const sec = Number(c?.start_sec)
  const time = Number.isFinite(sec) && sec >= 0
    ? ` @${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`
    : ''
  return `${c?.section || ''} ${c?.title || '来源'}${time}`.trim()
}

function citationSub(c) {
  return c?.kp_title || ''
}

const showOptions = computed(() => {
  return (
    props.message.role === 'assistant'
    && props.message.optionsActive
    && Array.isArray(props.message.options)
    && props.message.options.length > 0
  )
})

function onSelectOption(opt) {
  emit('selectOption', opt)
}

// Configure marked with highlight.js
marked.setOptions({
  highlight: function (code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch (e) {
        // fall through
      }
    }
    try {
      return hljs.highlightAuto(code).value
    } catch (e) {
      return code
    }
  },
  breaks: true,
})

const renderedContent = computed(() => {
  if (props.message.role === 'assistant') {
    const raw = marked.parse(props.message.content || '')
    return DOMPurify.sanitize(raw)
  }
  return null
})

const timeStr = computed(() => {
  if (!props.message.timestamp) return ''
  const d = new Date(props.message.timestamp)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})

// Action buttons state
const copied = ref(false)
const liked = ref(false)
const disliked = ref(false)

function copyContent() {
  navigator.clipboard.writeText(props.message.content).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  })
}

function toggleLike() {
  liked.value = !liked.value
  if (liked.value) disliked.value = false
}

function toggleDislike() {
  disliked.value = !disliked.value
  if (disliked.value) liked.value = false
}
</script>

<template>
  <div class="message" :class="`message--${message.role}`">
    <!-- Avatar -->
    <div class="message-avatar">
      {{ message.role === 'user' ? '👤' : '🤖' }}
    </div>

    <!-- Content -->
    <div class="message-body">
      <div class="message-content">
        <!-- User message: plain text -->
        <p v-if="message.role === 'user'" class="user-text">{{ message.content }}</p>

        <!-- Assistant message: markdown rendered -->
        <div
          v-else
          class="markdown-body"
          :class="{ streaming: message.streaming }"
          v-html="renderedContent"
        ></div>
        <p
          v-if="message.role === 'assistant' && message.streaming && message.statusDetail"
          class="stream-status"
        >
          {{ message.statusDetail }}
        </p>
        <span
          v-if="message.role === 'assistant' && message.streaming && message.content"
          class="stream-cursor"
          aria-hidden="true"
        />
      </div>

      <!-- 主课 Citations：可点跳转视频 -->
      <div
        v-if="message.role === 'assistant' && message.citations?.length"
        class="message-citations"
      >
        <button
          v-for="(c, idx) in message.citations"
          :key="`main-${c.media_path || c.source}-${idx}`"
          type="button"
          class="citation-btn"
          :class="{ playable: canPlay(c) }"
          :disabled="!canPlay(c)"
          :title="canPlay(c) ? '点击跳转到视频' : '无对应视频'"
          @click="onPlayCitation(c)"
        >
          <span class="citation-prefix">📎</span>
          <span class="citation-text">
            <span class="citation-label">{{ citationLabel(c) }}</span>
            <span v-if="citationSub(c)" class="citation-sub">{{ citationSub(c) }}</span>
          </span>
        </button>
      </div>
      <div
        v-else-if="message.role === 'assistant' && message.source"
        class="message-source"
      >
        📎 {{ message.source }}
      </div>

      <!-- 简历终稿：打开 ResumeDock -->
      <div v-if="hasResume" class="message-resume">
        <button type="button" class="resume-open-btn" @click="onOpenResume">
          📄 {{ resumeBtnLabel }}
        </button>
      </div>

      <!-- 全屏面试场入口 -->
      <div v-if="showInterviewEnter" class="message-interview">
        <button type="button" class="interview-enter-btn" @click="onEnterInterview">
          进入面试
        </button>
      </div>

      <!-- 类比课程：独立弱样式区，不与主课混排 -->
      <div
        v-if="message.role === 'assistant' && message.analogy_citations?.length"
        class="message-analogy"
      >
        <div class="analogy-label">类比课程</div>
        <div class="message-citations analogy-list">
          <button
            v-for="(c, idx) in message.analogy_citations"
            :key="`ana-${c.media_path || c.source}-${idx}`"
            type="button"
            class="citation-btn analogy-btn"
            :class="{ playable: canPlay(c) }"
            :disabled="!canPlay(c)"
            :title="canPlay(c) ? '对照复习：跳转视频' : '无对应视频'"
            @click="onPlayCitation(c)"
          >
            📎 {{ citationLabel(c) }}
          </button>
        </div>
      </div>

      <!-- 结构化选项：仅当前会话最新 pending 可点 -->
      <div v-if="showOptions" class="message-options">
        <button
          v-for="opt in message.options"
          :key="opt.id"
          type="button"
          class="option-btn"
          @click="onSelectOption(opt)"
        >
          <span class="option-id">{{ opt.id }}</span>
          <span class="option-text">{{ opt.text }}</span>
        </button>
      </div>

      <!-- Actions + time row -->
      <div class="message-footer">
        <span class="message-time">{{ timeStr }}</span>
        <div v-if="message.role === 'assistant'" class="message-actions">
          <button
            class="action-btn"
            :class="{ active: ttsSpeaking }"
            @click="toggleTts"
            :title="ttsSpeaking ? '停止朗读' : '朗读回复'"
          >
            {{ ttsSpeaking ? '🔊' : '🔈' }}
          </button>
          <button
            class="action-btn"
            :class="{ active: copied }"
            @click="copyContent"
            :title="copied ? '已复制' : '复制'"
          >
            {{ copied ? '✓ 已复制' : '📋' }}
          </button>
          <button
            class="action-btn"
            :class="{ active: liked }"
            @click="toggleLike"
            title="有帮助"
          >
            👍
          </button>
          <button
            class="action-btn"
            :class="{ active: disliked }"
            @click="toggleDislike"
            title="没帮助"
          >
            👎
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message {
  display: flex;
  gap: 12px;
  padding: 16px 0;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.message--user {
  flex-direction: row-reverse;
  /* 靠右排布，避免宽屏下气泡与头像被撑开成「中间一大块空」 */
  justify-content: flex-start;
}

.message--user .message-body {
  align-items: flex-end;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
}

.message-body {
  display: flex;
  flex-direction: column;
  max-width: 85%;
  min-width: 0;
}

.message-content {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.65;
  position: relative;
}

.stream-status {
  margin: 0;
  padding: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent, #5ab4e8);
  animation: stream-blink 1s step-end infinite;
}

@keyframes stream-blink {
  50% { opacity: 0; }
}

.markdown-body.streaming {
  min-height: 1.2em;
}

.message--assistant .message-content {
  background: var(--bg-surface);
  border-top-left-radius: 4px;
  color: var(--text-primary);
}

.message--user .message-content {
  background: var(--accent);
  border-top-right-radius: 4px;
  color: #fff;
}

.user-text {
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-source {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 0 4px;
}

.message-citations {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding: 0 2px;
}

.message-resume {
  margin-top: 8px;
  padding: 0 2px;
}

.resume-open-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  font-size: 13px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
}

.resume-open-btn:hover {
  border-color: var(--accent-color, #4a90d9);
  background: var(--bg-hover);
}

.message-interview {
  margin-top: 8px;
  padding: 0 2px;
}

.interview-enter-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  font-size: 13px;
  border: 1px solid rgba(90, 160, 220, 0.45);
  border-radius: 8px;
  background: rgba(40, 80, 120, 0.2);
  color: var(--text-primary);
  cursor: pointer;
}

.interview-enter-btn:hover {
  border-color: rgba(90, 180, 240, 0.7);
  background: rgba(50, 100, 150, 0.3);
}

.message-analogy {
  margin-top: 10px;
  padding: 8px 6px 4px;
  border-top: 1px dashed var(--border-color);
}

.analogy-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  letter-spacing: 0.02em;
}

.analogy-list {
  margin-top: 0;
}

.citation-btn.analogy-btn.playable {
  opacity: 0.85;
  background: transparent;
}

.citation-btn {
  text-align: left;
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 6px 8px;
  cursor: default;
}

.citation-btn.playable {
  cursor: pointer;
  border-color: var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
}

.citation-btn.playable:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.citation-btn:disabled {
  opacity: 0.75;
}

.citation-prefix {
  flex-shrink: 0;
  margin-right: 4px;
}

.citation-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.citation-label {
  font-size: 12px;
  line-height: 1.4;
}

.citation-sub {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.3;
  margin-top: 1px;
}

.message-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  padding: 0 4px;
}

.message-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.message-actions {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.action-btn {
  padding: 4px 8px;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}

.action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.action-btn.active {
  color: var(--accent);
}

.message-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding: 0 2px;
}

.option-btn {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.option-btn:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.option-id {
  flex-shrink: 0;
  min-width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}

.option-text {
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
}
</style>
