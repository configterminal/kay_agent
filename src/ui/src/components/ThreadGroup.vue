<script setup>
/**
 * ThreadGroup — 一个线程下的学习话题卡片组
 *
 * 按日期 + 课程线程标签分组，展示该组内所有 TopicCard。
 * 垃圾桶状态支持恢复/彻底删除操作。
 */
import TopicCard from './TopicCard.vue'

defineProps({
  group: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['topic-click', 'restore', 'purge'])
</script>

<template>
  <div class="thread-group" :class="{ 'is-trashed': group.is_trashed }">
    <!-- 分组头部：线程标签 + 日期 + 统计 + 垃圾桶操作 -->
    <div class="group-header">
      <span class="group-label">{{ group.thread_label }}</span>
      <span class="group-date">📅 {{ group.date }}</span>
      <span class="group-stats">共 {{ group.topic_count }} 个话题 · {{ group.message_count }} 条消息</span>
      <!-- 垃圾桶操作按钮 -->
      <span v-if="group.is_trashed" class="trash-badge">🗑️</span>
      <button
        v-if="group.is_trashed"
        class="trash-action-btn restore-btn"
        title="恢复对话"
        @click="emit('restore', group.thread_id)"
      >恢复</button>
      <button
        v-if="group.is_trashed"
        class="trash-action-btn purge-btn"
        title="彻底删除"
        @click="emit('purge', group.thread_id)"
      >彻底删除</button>
    </div>

    <!-- 卡片网格：桌面 3 列，平板 2 列，手机 1 列 -->
    <div class="card-grid">
      <TopicCard
        v-for="topic in group.topics"
        :key="topic.id"
        :topic="topic"
        @click="$emit('topic-click', topic)"
      />
    </div>
  </div>
</template>

<style scoped>
.thread-group {
  margin-bottom: 28px;
}

/* ── 垃圾桶状态 ── */
.thread-group.is-trashed {
  opacity: 0.6;
}

.thread-group.is-trashed .group-label {
  text-decoration: line-through;
  background: rgba(120, 120, 120, 0.12);
  color: var(--text-secondary);
}

.group-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  padding: 0 4px;
  flex-wrap: wrap;
}

.group-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
  background: rgba(126, 87, 194, 0.12);
  padding: 4px 12px;
  border-radius: 6px;
}

.group-date {
  font-size: 13px;
  color: var(--text-secondary);
}

.group-stats {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: auto;
}

/* ── 垃圾桶操作 ── */
.trash-badge {
  font-size: 14px;
  flex-shrink: 0;
}

.trash-action-btn {
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 6px;
  transition: background 0.15s, color 0.15s;
  flex-shrink: 0;
}

.restore-btn {
  background: rgba(46, 204, 113, 0.12);
  color: #2ecc71;
}

.restore-btn:hover {
  background: rgba(46, 204, 113, 0.22);
}

.purge-btn {
  background: rgba(231, 76, 60, 0.12);
  color: #e74c3c;
}

.purge-btn:hover {
  background: rgba(231, 76, 60, 0.22);
}

/* ── 响应式网格 ── */
.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

@media (max-width: 1024px) {
  .card-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .card-grid {
    grid-template-columns: 1fr;
  }
}
</style>
