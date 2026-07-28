<script setup>
const API_ORIGIN = 'http://127.0.0.1:8000'

const props = defineProps({
  activeView: String,
  studentInfo: Object,
  conversationList: Array,
  currentThreadId: String,
})

const emit = defineEmits(['newChat', 'switchConversation', 'enterHistory', 'refreshConversations'])

function truncateTitle(title) {
  if (!title) return '新对话'
  return title.length > 18 ? title.slice(0, 18) + '...' : title
}

async function trashConversation(threadId) {
  try {
    const resp = await fetch(
      `${API_ORIGIN}/api/threads/${encodeURIComponent(threadId)}/trash?student_id=${props.studentInfo?.id || 1}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'trash' }),
      },
    )
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  } catch (e) {
    console.error('trash failed:', e)
  }
  emit('refreshConversations')
}
</script>

<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="sidebar-header">
      <div class="logo">
        <span class="logo-icon">🎓</span>
        <span class="logo-text">AI 助教</span>
      </div>
    </div>

    <!-- New Chat Button -->
    <div class="sidebar-actions">
      <button class="btn-new-chat" @click="emit('newChat')">
        <span class="btn-icon">+</span>
        <span>新对话</span>
      </button>
    </div>

    <!-- History -->
    <div class="sidebar-history">
      <div class="nav-label">历史对话</div>
      <button
        v-for="item in conversationList"
        :key="item.thread_id"
        class="history-item"
        :class="{ active: item.thread_id === currentThreadId }"
        @click="emit('switchConversation', item.thread_id)"
      >
        <span class="history-icon">💬</span>
        <span class="history-title">{{ truncateTitle(item.title) }}</span>
        <span
          class="history-delete"
          title="删除会话"
          @click.stop="trashConversation(item.thread_id)"
        >🗑️</span>
      </button>
      <div v-if="!conversationList || conversationList.length === 0" class="history-empty">
        暂无历史对话
      </div>
    </div>

    <!-- 底部导航 -->
    <div class="sidebar-nav-bottom">
      <button
        class="nav-item"
        :class="{ active: activeView === 'history' }"
        @click="emit('enterHistory')"
      >
        <span class="nav-icon">📊</span>
        <span>对话历史</span>
      </button>
    </div>

    <!-- Student Info -->
    <div class="sidebar-footer">
      <div class="student-card">
        <div class="student-avatar">{{ studentInfo.avatar }}</div>
        <div class="student-info">
          <div class="student-name">{{ studentInfo.name }}</div>
          <div class="student-meta">{{ studentInfo.coachStyle }} · {{ studentInfo.level }}</div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-color);
  overflow: hidden;
}

.sidebar-header {
  padding: 16px 16px 12px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.sidebar-actions {
  padding: 0 12px 8px;
}

.btn-new-chat {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.15s;
}

.btn-new-chat:hover {
  background: var(--accent-hover);
}

.btn-icon {
  font-size: 18px;
  font-weight: 300;
}

.sidebar-history {
  flex: 1 1 auto;
  min-height: 0;
  padding: 0 12px;
  overflow-y: auto;
}

.nav-label {
  padding: 8px 12px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
  transition: background 0.15s;
  overflow: hidden;
  margin-bottom: 2px;
}

.history-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.history-item.active {
  background: var(--bg-hover);
  color: var(--accent);
}

.history-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.history-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.history-delete {
  flex-shrink: 0;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s;
  cursor: pointer;
}

.history-item:hover .history-delete {
  opacity: 0.6;
}

.history-item:hover .history-delete:hover {
  opacity: 1;
}

.history-empty {
  padding: 12px;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: center;
}

/* ── 底部导航 ── */
.sidebar-nav-bottom {
  padding: 8px 12px;
  border-top: 1px solid var(--border-color);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
  transition: background 0.15s, color 0.15s;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--bg-hover);
  color: var(--accent);
}

.nav-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border-color);
}

.student-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  transition: background 0.15s;
}

.student-card:hover {
  background: var(--bg-hover);
}

.student-avatar {
  font-size: 28px;
  flex-shrink: 0;
}

.student-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.student-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 1px;
}
</style>
