<script setup>
/**
 * TopicCard — 单张学习话题卡片
 *
 * 展示一个话题的标题、摘要、时间和消息数。
 * 悬停上浮 + 点击预留跳转。
 */

defineProps({
  topic: {
    type: Object,
    required: true,
  },
})

defineEmits(['click'])

// 取标题首字 emoji，无则默认 💬
function topicEmoji(title) {
  if (!title) return '💬'
  // 尝试匹配开头的 emoji（包括组合 emoji）
  const emojiRe = /^(\p{Emoji_Presentation}|\p{Emoji}️|\p{Extended_Pictographic})(\p{Emoji_Modifier})?/u
  const m = title.match(emojiRe)
  return m ? m[0] : '💬'
}
</script>

<template>
  <div class="topic-card" @click="$emit('click', topic)">
    <div class="card-icon">{{ topicEmoji(topic.title) }}</div>
    <div class="card-body">
      <h3 class="card-topic">{{ topic.title }}</h3>
      <p class="card-summary">{{ topic.summary }}</p>
      <div class="card-meta">
        <span class="meta-time">{{ topic.time_range }}</span>
        <span class="meta-msg">{{ topic.message_count }} 条消息</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.topic-card {
  display: flex;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s;
}

.topic-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
  border-color: var(--accent);
}

.card-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--bg-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  border: 1px solid var(--border-color);
}

.card-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 6px;
}

.card-topic {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  /* 最多两行 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-summary {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.meta-time {
  flex-shrink: 0;
}

.meta-msg {
  flex-shrink: 0;
}
</style>
