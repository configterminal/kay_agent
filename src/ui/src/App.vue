<script setup>
import { ref, reactive, onMounted, watch, computed } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatView from './components/ChatView.vue'
import InterviewStage from './components/interview/InterviewStage.vue'
import { useVoiceChat } from './composables/useVoiceChat.js'

const API_ORIGIN = 'http://127.0.0.1:8000'
const API_BASE = `${API_ORIGIN}/api`

// ── TTS 播放（全局单例）──
const { speak: ttsSpeak } = useVoiceChat()

const currentThreadId = ref(null)
const messages = ref([])
const conversationList = ref([])
const isLoading = ref(false)
const error = ref('')
const studentId = ref(1)
/** 语音模式：开启后 LLM 输出口语 + 自动 TTS */
const voiceMode = ref(false)
/** 底部 VideoDock 当前片段（与 ResumeDock 互斥） */
const videoClip = ref(null)
/** 底部 ResumeDock 当前 artifact */
const resumeArtifact = ref(null)
/** chat | interview — 全屏面试场 */
const viewMode = ref('chat')
/** 进入面试场时优先播报的开场白（最近一条助手消息） */
const interviewOpening = ref('')

const showInterview = computed(() => viewMode.value === 'interview')

function resolveMediaUrl(url) {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_ORIGIN}${url.startsWith('/') ? '' : '/'}${url}`
}

function onPlayCitation(c) {
  if (!c?.media_url || Number(c.start_sec) < 0) return
  resumeArtifact.value = null
  const captions =
    c.captions_url ||
    (String(c.media_url || '').includes('/media/')
      ? String(c.media_url).replace('/media/', '/captions/')
      : '')
  videoClip.value = {
    mediaUrl: resolveMediaUrl(c.media_url),
    captionsUrl: resolveMediaUrl(captions),
    mediaPath: c.media_path || '',
    startSec: Number(c.start_sec) || 0,
    title: c.title || '',
    source: c.source || '',
  }
}

function closeVideo() {
  videoClip.value = null
}

function onOpenResume(meta) {
  if (!meta?.artifactId) return
  videoClip.value = null
  const id = meta.artifactId
  resumeArtifact.value = {
    artifactId: id,
    mode: meta.mode || 'fact',
    title: meta.title || '',
    previewUrl: `${API_ORIGIN}/api/resume/preview/${id}`,
    pdfUrl: `${API_ORIGIN}/api/resume/pdf/${id}`,
  }
}

function closeResume() {
  resumeArtifact.value = null
}

/**
 * 进入全屏面试场（关闭 Dock）。
 * 开场白由面试场内 kickoff 生成短自我介绍，不复用聊天气泡长文。
 * @param {{ openingText?: string }} [opts]
 */
function enterInterview(opts = {}) {
  videoClip.value = null
  resumeArtifact.value = null
  // 仅允许显式传入的极短开场；默认空 → session 走 kickoff
  const fromOpt = (opts.openingText || '').trim()
  interviewOpening.value = fromOpt.length > 0 && fromOpt.length <= 80 ? fromOpt : ''
  viewMode.value = 'interview'
}

async function exitInterview() {
  viewMode.value = 'chat'
  interviewOpening.value = ''
  await loadConversations()
}

/**
 * ChatBridge：面试场一轮对话（同 thread），返回助手纯文本。
 * @param {string} text
 * @returns {Promise<string>}
 */
async function sendInterviewTurn(text) {
  const trimmed = (text || '').trim()
  if (!trimmed) throw new Error('空文本')

  if (!currentThreadId.value) {
    currentThreadId.value = makeThreadId()
    localStorage.setItem('chat_current_thread', currentThreadId.value)
  }

  messages.value = messages.value.map((m) => ({ ...m, optionsActive: false }))
  messages.value.push({ role: 'user', content: trimmed })

  const tid = currentThreadId.value
  const body = {
    message: trimmed,
    student_id: studentId.value,
    thread_id: tid,
  }
  const resp = await fetch(`${API_BASE}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = await resp.json()
  if (data.thread_id && data.thread_id !== tid) {
    currentThreadId.value = data.thread_id
    localStorage.setItem('chat_current_thread', data.thread_id)
  }
  const content = data.content || ''
  messages.value.push({
    role: 'assistant',
    content,
    source: data.source || '',
    citations: data.citations || [],
    analogy_citations: data.analogy_citations || [],
    agent: data.agent || 'interview_agent',
    options: data.options || [],
    optionsActive: false,
  })
  loadConversations()
  return content
}

const studentInfo = reactive({
  name: '',
  avatar: '👤',
  coachStyle: 'encouraging',
  level: '',
})

function makeThreadId() {
  const ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)
  return `stu_${studentId.value}_${ts}`
}

// ── localStorage ──
function storageKey(threadId) {
  return `chat_messages_${threadId}`
}

function saveMessages(threadId, msgs) {
  try {
    localStorage.setItem(storageKey(threadId), JSON.stringify(msgs))
  } catch (e) { /* ignore */ }
}

function loadMessages(threadId) {
  try {
    const raw = localStorage.getItem(storageKey(threadId))
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

/**
 * 合并 API 消息与本地缓存的 citations / analogy（API 优先，缓存兜底）。
 */
function mergeMessages(apiMsgs, cachedMsgs) {
  const cachedByKey = new Map()
  for (const m of cachedMsgs || []) {
    if (m.role !== 'assistant') continue
    const key = `${m.content || ''}::${m.created_at || ''}`
    cachedByKey.set(key, {
      citations: m.citations?.length ? m.citations : [],
      analogy_citations: m.analogy_citations?.length ? m.analogy_citations : [],
    })
  }
  return (apiMsgs || []).map((m) => {
    if (m.role !== 'assistant') return m
    const key = `${m.content || ''}::${m.created_at || ''}`
    const cached = cachedByKey.get(key) || {}
    const citations = m.citations?.length ? m.citations : (cached.citations || [])
    const analogy_citations = m.analogy_citations?.length
      ? m.analogy_citations
      : (cached.analogy_citations || [])
    return { ...m, citations, analogy_citations, optionsActive: false }
  })
}

/**
 * 将本会话 pending_options 挂到最后一条助教消息上（仅该条可点）。
 * 每个 thread 的 pending 互不干扰，由服务端 /state 权威提供。
 */
function applyPendingOptions(msgs, pendingOptions) {
  const next = (msgs || []).map((m) => ({
    ...m,
    optionsActive: false,
  }))
  if (!pendingOptions || pendingOptions.length === 0) {
    return next
  }
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].role === 'assistant') {
      next[i] = {
        ...next[i],
        options: pendingOptions,
        optionsActive: true,
      }
      break
    }
  }
  return next
}

async function fetchThreadState(threadId) {
  try {
    const resp = await fetch(`${API_BASE}/conversations/${threadId}/state`)
    if (!resp.ok) return []
    const data = await resp.json()
    return data.pending_options || []
  } catch {
    return []
  }
}

// 监听 messages 变化，按当前 thread 存
watch(messages, (val) => {
  if (currentThreadId.value) {
    saveMessages(currentThreadId.value, val)
  }
}, { deep: true })

// ── 切换会话（加载该 thread 独立状态）──
async function switchConversation(threadId) {
  if (currentThreadId.value) {
    saveMessages(currentThreadId.value, messages.value)
  }
  currentThreadId.value = threadId
  localStorage.setItem('chat_current_thread', threadId)
  videoClip.value = null
  resumeArtifact.value = null

  const cached = loadMessages(threadId)
  messages.value = cached.length > 0 ? cached : []

  try {
    const resp = await fetch(`${API_BASE}/conversations/${threadId}/messages`)
    if (resp.ok) {
      const data = await resp.json()
      const pending = await fetchThreadState(threadId)
      const merged = mergeMessages(data.messages || [], cached)
      messages.value = applyPendingOptions(merged, pending)
      saveMessages(threadId, messages.value)
    }
  } catch (e) { /* ignore */ }
}

// ── 加载 ──
async function loadConversations() {
  try {
    const resp = await fetch(`${API_BASE}/conversations/?student_id=${studentId.value}`)
    if (!resp.ok) return
    const data = await resp.json()
    conversationList.value = data.conversations || []
  } catch (e) { /* ignore */ }
}

async function loadStudentInfo() {
  try {
    const resp = await fetch(`${API_BASE}/student/${studentId.value}`)
    if (!resp.ok) return
    const data = await resp.json()
    studentInfo.name = data.display_name || ''
    studentInfo.coachStyle = data.coach_style || 'encouraging'
    studentInfo.level = data.skill_level || ''
  } catch (e) { /* ignore */ }
}

onMounted(async () => {
  await loadConversations()
  await loadStudentInfo()
  const lastThread = localStorage.getItem('chat_current_thread')
  if (lastThread) {
    await switchConversation(lastThread)
  }
})

/**
 * 发送消息（主路径：SSE 流式，边收边渲染）。
 * @param {string} text
 * @param {{ selected_option_id?: number }} [extra]
 */
async function sendMessage(text, extra = {}) {
  const trimmed = (text || '').trim()
  if ((!trimmed && extra.selected_option_id == null) || isLoading.value) return

  if (!currentThreadId.value) {
    currentThreadId.value = makeThreadId()
    localStorage.setItem('chat_current_thread', currentThreadId.value)
  }

  const displayText = trimmed || `选项 ${extra.selected_option_id}`
  // 点击/发送后立即隐藏旧选项，避免重复点
  messages.value = messages.value.map((m) => ({ ...m, optionsActive: false }))
  messages.value.push({ role: 'user', content: displayText })
  error.value = ''
  isLoading.value = true

  // 助手占位：先出状态字，再刷 token
  messages.value.push({
    role: 'assistant',
    content: '',
    streaming: true,
    statusDetail: '正在连接…',
    source: '',
    citations: [],
    analogy_citations: [],
    agent: '',
    options: [],
    optionsActive: false,
  })
  const assistantIdx = messages.value.length - 1

  const tid = currentThreadId.value
  const body = {
    message: displayText,
    student_id: studentId.value,
    thread_id: tid,
  }
  if (extra.selected_option_id != null) {
    body.selected_option_id = extra.selected_option_id
  }
  if (voiceMode.value) {
    body.voice_mode = true
  }

  const patchAssistant = (patch) => {
    const cur = messages.value[assistantIdx]
    if (!cur || cur.role !== 'assistant') return
    messages.value[assistantIdx] = { ...cur, ...patch }
  }

  try {
    const resp = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    if (!resp.body) throw new Error('无流式响应体')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let gotDone = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const block of parts) {
        const line = block.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const raw = line.slice(5).trim()
        if (!raw || raw === '[DONE]') continue
        let ev
        try {
          ev = JSON.parse(raw)
        } catch {
          continue
        }
        if (ev.type === 'status') {
          patchAssistant({
            statusDetail: ev.detail || '',
            agent: ev.agent || messages.value[assistantIdx]?.agent || '',
          })
        } else if (ev.type === 'token') {
          // 检索阶段可能先缓冲；首个 token 起清空状态字
          const cur = messages.value[assistantIdx]
          const nextContent = (cur?.content || '') + (ev.text || '')
          patchAssistant({
            content: nextContent,
            statusDetail: nextContent ? '' : (cur?.statusDetail || ''),
            streaming: true,
          })
        } else if (ev.type === 'done') {
          gotDone = true
          if (ev.thread_id && ev.thread_id !== tid) {
            currentThreadId.value = ev.thread_id
            localStorage.setItem('chat_current_thread', ev.thread_id)
          }
          const options = ev.options || []
          const resume_artifact_id = ev.resume_artifact_id || ''
          // 以服务端终稿为准，避免过程 token 残留错乱
          patchAssistant({
            content: ev.content || '',
            source: ev.source || '',
            citations: ev.citations || [],
            analogy_citations: ev.analogy_citations || [],
            resume_artifact_id,
            resume_mode: ev.resume_mode || '',
            resume_title: ev.resume_title || '',
            agent: ev.agent || '',
            options,
            optionsActive: options.length > 0,
            streaming: false,
            statusDetail: '',
          })
          if (resume_artifact_id) {
            onOpenResume({
              artifactId: resume_artifact_id,
              mode: ev.resume_mode || 'fact',
              title: ev.resume_title || '',
            })
          }
          loadConversations()
          // 语音模式：自动播报回复
          if (ev.voice_mode && ev.content) {
            ttsSpeak(ev.content).catch(e => console.warn('[TTS] 自动播放异常:', e))
          }
        } else if (ev.type === 'error') {
          throw new Error(ev.detail || '流式处理失败')
        }
      }
    }

    if (!gotDone) {
      const cur = messages.value[assistantIdx]
      if (!cur?.content) {
        throw new Error('流式结束但未收到完整回复')
      }
      patchAssistant({ streaming: false, statusDetail: '' })
    }
  } catch (e) {
    error.value = `请求失败: ${e.message}`
    const cur = messages.value[assistantIdx]
    if (cur && !cur.content) {
      messages.value.splice(assistantIdx, 1)
    } else if (cur) {
      patchAssistant({ streaming: false, statusDetail: '' })
    }
  } finally {
    isLoading.value = false
  }
}

function onSelectOption(opt) {
  if (!opt || isLoading.value) return
  sendMessage(opt.text, { selected_option_id: opt.id })
}

function createConversation() {
  if (currentThreadId.value) {
    saveMessages(currentThreadId.value, messages.value)
  }
  currentThreadId.value = null
  messages.value = []
  videoClip.value = null
  resumeArtifact.value = null
  localStorage.setItem('chat_current_thread', '')
  error.value = ''
}

async function deleteConversation(threadId) {
  try {
    await fetch(`${API_BASE}/conversations/${threadId}`, { method: 'DELETE' })
  } catch (e) { /* ignore */ }
  try { localStorage.removeItem(storageKey(threadId)) } catch (e) { /* ignore */ }
  if (currentThreadId.value === threadId) {
    currentThreadId.value = null
    messages.value = []
    localStorage.setItem('chat_current_thread', '')
  }
  loadConversations()
}
</script>

<template>
  <div class="app-layout">
    <Sidebar
      :activeView="'chat'"
      :studentInfo="studentInfo"
      :conversationList="conversationList"
      :currentThreadId="currentThreadId"
      @newChat="createConversation"
      @switchConversation="switchConversation"
      @deleteConversation="deleteConversation"
    />
    <main class="main-area">
      <ChatView
        :messages="messages"
        :isLoading="isLoading"
        :error="error"
        :videoClip="videoClip"
        :resumeArtifact="resumeArtifact"
        :voiceMode="voiceMode"
        @send="sendMessage"
        @selectOption="onSelectOption"
        @playCitation="onPlayCitation"
        @closeVideo="closeVideo"
        @openResume="onOpenResume"
        @closeResume="closeResume"
        @enterInterview="enterInterview"
        @toggleVoiceMode="voiceMode = !voiceMode"
      />
    </main>
    <InterviewStage
      v-if="showInterview"
      :sendTurn="sendInterviewTurn"
      :openingText="interviewOpening"
      @exit="exitInterview"
    />
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  width: 100%;
  height: 100%;
  min-height: 0;
  /* 换屏时 transition 易停在中间态，导致列宽/高度错位 */
}

.main-area {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}
</style>
