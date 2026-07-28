<script setup>
/**
 * HistoryView — 学习对话历史报表页面
 *
 * GET /api/student/{student_id}/topics?time_range=7d&limit=20
 * 按线程 + 日期 + 话题分组展示，支持时间范围筛选。
 */
import { ref, onMounted, watch } from 'vue'
import ThreadGroup from '../components/ThreadGroup.vue'

const API_ORIGIN = 'http://127.0.0.1:8000'
const API_BASE = `${API_ORIGIN}/api`

const props = defineProps({
  studentId: { type: Number, default: 1 },
})

const emit = defineEmits(['back'])

// ── 状态 ──
const timeRange = ref('7d')
const limit = ref(20)
const groups = ref([])
const isLoading = ref(false)
const error = ref('')
const hasMore = ref(false)

const timeRangeOptions = [
  { value: '7d', label: '最近 7 天' },
  { value: '30d', label: '最近 30 天' },
  { value: 'all', label: '全部' },
]

// ── 数据加载 ──
async function fetchTopics() {
  isLoading.value = true
  error.value = ''

  try {
    const params = new URLSearchParams({
      time_range: timeRange.value,
      limit: String(limit.value),
    })
    const resp = await fetch(
      `${API_BASE}/student/${props.studentId}/topics?${params}`,
    )
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }
    const data = await resp.json()

    // API 返回 { threads: [...], thread_count, total_topics }
    // 字段映射: thread_title→thread_label, block_id→id, topic→title, created_at→date
    groups.value = (data.threads || []).map(function(t) {
      return {
        thread_id: t.thread_id || '',
        thread_label: t.thread_title || '未命名会话',
        date: (t.created_at || '').slice(0, 10),
        topic_count: t.topic_count || 0,
        message_count: t.message_count || 0,
        is_trashed: !!(t.is_trashed),
        topics: (t.topics || []).map(function(tp) {
          return {
            id: tp.block_id,
            title: tp.topic || '无标题话题',
            summary: tp.summary || '',
            time_range: tp.time_range || '',
            message_count: tp.message_count || 0,
            created_at: tp.created_at || '',
          }
        }),
      }
    })

    hasMore.value = !!(data.has_more)
  } catch (e) {
    error.value = `加载失败: ${e.message}`
    groups.value = []
    hasMore.value = false
  } finally {
    isLoading.value = false
  }
}

async function loadMore() {
  limit.value += 20
  await fetchTopics()
}

// ── 垃圾桶操作 ──
async function restoreThread(threadId) {
  try {
    const resp = await fetch(
      `${API_BASE}/threads/${encodeURIComponent(threadId)}/trash?student_id=${props.studentId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'restore' }),
      },
    )
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  } catch (e) {
    console.error('restoreThread failed:', e)
    alert('恢复失败，请稍后重试')
  }
  await fetchTopics()
}

async function purgeThread(threadId) {
  if (!confirm('确定要彻底删除该对话吗？此操作不可撤销。')) return
  try {
    const resp = await fetch(
      `${API_BASE}/threads/${encodeURIComponent(threadId)}/trash?student_id=${props.studentId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'purge' }),
      },
    )
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  } catch (e) {
    console.error('purgeThread failed:', e)
    alert('彻底删除失败，请稍后重试')
  }
}

// 时间范围变化自动重拉
watch(timeRange, async () => {
  limit.value = 20
  await fetchTopics()
})

// ── 话题展开 ──
const expandedTopic = ref(null)     // 当前展开的话题 block
const expandedMessages = ref([])    // 该话题对应的消息列表
const expandLoading = ref(false)

async function onTopicClick(topic) {
  if (expandedTopic.value?.id === topic.id) {
    expandedTopic.value = null
    expandedMessages.value = []
    return  // 再次点击折叠
  }

  expandedTopic.value = topic
  expandLoading.value = true
  expandedMessages.value = []

  try {
    const group = groups.value.find(g =>
      g.topics.some(t => t.id === topic.id)
    )
    const threadId = group?.thread_id
    if (!threadId) return

    const resp = await fetch(
      `${API_BASE}/conversations/${encodeURIComponent(threadId)}/messages?student_id=${props.studentId}`
    )
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    expandedMessages.value = data.messages || []
  } catch (e) {
    expandedMessages.value = [{ role: 'system', content: `加载失败: ${e.message}` }]
  } finally {
    expandLoading.value = false
  }
}

onMounted(() => {
  fetchTopics()
})
</script>

<template>
  <div class="history-view">
    <!-- 顶部栏 -->
    <div class="history-topbar">
      <button class="back-btn" @click="emit('back')" title="返回聊天">
        ← 返回
      </button>
      <h1 class="page-title">📊 学习对话历史</h1>
      <div class="time-filter">
        <label class="filter-label">时间筛选</label>
        <select v-model="timeRange" class="filter-select">
          <option
            v-for="opt in timeRangeOptions"
            :key="opt.value"
            :value="opt.value"
          >{{ opt.label }}</option>
        </select>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="history-loading">
      <div class="loading-spinner" />
      <span>加载中…</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="history-error">
      <span>{{ error }}</span>
      <button class="retry-btn" @click="fetchTopics">重试</button>
    </div>

    <!-- 空态 -->
    <div v-else-if="groups.length === 0" class="history-empty">
      <span class="empty-icon">📭</span>
      <p>暂无历史话题记录</p>
    </div>

    <!-- 内容区 -->
    <div v-else class="history-content">
      <ThreadGroup
        v-for="group in groups"
        :key="`${group.thread_label}-${group.date}`"
        :group="group"
        @topic-click="onTopicClick"
        @restore="restoreThread"
        @purge="purgeThread"
      />

      <!-- 加载更多 -->
      <div v-if="hasMore" class="load-more-area">
        <button class="load-more-btn" @click="loadMore" :disabled="isLoading">
          加载更多
        </button>
      </div>
    </div>

    <!-- 话题展开模态 -->
    <Teleport to="body">
      <div v-if="expandedTopic" class="modal-overlay" @click.self="onTopicClick(expandedTopic)">
        <div class="modal-panel">
          <div class="modal-header">
            <h2 class="modal-title">{{ expandedTopic.title }}</h2>
            <span class="modal-meta">{{ expandedTopic.time_range }} · {{ expandedTopic.message_count }} 条消息</span>
            <button class="modal-close" @click="onTopicClick(expandedTopic)">✕</button>
          </div>
          <div class="modal-body">
            <div v-if="expandLoading" class="modal-loading">
              <div class="loading-spinner" />
              <span>加载消息中…</span>
            </div>
            <div v-else class="modal-messages">
              <div
                v-for="(msg, idx) in expandedMessages"
                :key="idx"
                class="modal-msg"
                :class="msg.role"
              >
                <span class="msg-role">{{ msg.role === 'user' ? '👤' : msg.role === 'assistant' ? '🤖' : '📋' }}</span>
                <span class="msg-text">{{ typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content) }}</span>
              </div>
              <div v-if="expandedMessages.length === 0" class="modal-empty">
                暂无消息
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.history-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-primary);
}

/* ── 顶部栏 ── */
.history-topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
  flex-shrink: 0;
}

.back-btn {
  font-size: 13px;
  color: var(--text-secondary);
  background: transparent;
  padding: 6px 10px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
  flex-shrink: 0;
}

.back-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.page-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
}

.time-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.filter-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.filter-select {
  padding: 6px 28px 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%23888' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 6px center;
  background-size: 16px 16px;
}

.filter-select:hover {
  border-color: var(--accent);
}

.filter-select:focus {
  outline: none;
  border-color: var(--accent);
}

/* ── 内容区 ── */
.history-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
}

/* ── Loading ── */
.history-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  color: var(--text-secondary);
  font-size: 14px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Error ── */
.history-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  color: var(--danger);
  font-size: 14px;
}

.retry-btn {
  padding: 8px 20px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  transition: background 0.15s;
}

.retry-btn:hover {
  background: var(--accent-hover);
}

/* ── 空态 ── */
.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  color: var(--text-secondary);
  font-size: 14px;
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

/* ── 加载更多 ── */
.load-more-area {
  display: flex;
  justify-content: center;
  padding: 16px 0 8px;
}

.load-more-btn {
  padding: 8px 24px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 13px;
  transition: border-color 0.15s, background 0.15s;
}

.load-more-btn:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.load-more-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 话题展开模态 ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-panel {
  background: var(--bg-surface);
  border-radius: 14px;
  border: 1px solid var(--border-color);
  width: 90vw;
  max-width: 720px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.45);
}

.modal-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.modal-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
}

.modal-meta {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  align-self: center;
}

.modal-close {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  line-height: 1;
  flex-shrink: 0;
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.modal-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 0;
  color: var(--text-secondary);
}

.modal-messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.modal-msg {
  display: flex;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.55;
}

.modal-msg.user {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
}

.modal-msg.assistant {
  background: rgba(126, 87, 194, 0.06);
  border: 1px solid rgba(126, 87, 194, 0.15);
}

.msg-role {
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.msg-text {
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.modal-empty {
  text-align: center;
  padding: 24px;
  color: var(--text-secondary);
}
</style>
