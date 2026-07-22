<script setup>
const emit = defineEmits(['send', 'enterInterview'])

const suggestions = [
  {
    icon: '📚',
    title: '学习进度报告',
    desc: '查看你的学习进度和成绩分析',
    query: '给我一份完整的学习报告',
  },
  {
    icon: '💡',
    title: '推荐下一课',
    desc: 'AI 为你推荐最适合的学习内容',
    query: '我接下来该学什么？',
  },
  {
    icon: '💬',
    title: '模拟面试',
    desc: '全屏面试场，对着虚拟面试官开麦练习',
    action: 'interview',
  },
]

function onCard(card) {
  if (card.action === 'interview') {
    emit('enterInterview', {})
    return
  }
  emit('send', card.query)
}
</script>

<template>
  <div class="welcome">
    <h1 class="welcome-heading">有什么可以帮你的？</h1>
    <p class="welcome-sub">我是你的专属 AI 助教，可以帮你分析学习进度、推荐课程、匹配岗位、模拟面试。</p>
    <div class="suggestion-cards">
      <button
        v-for="card in suggestions"
        :key="card.title"
        class="suggestion-card"
        @click="onCard(card)"
      >
        <span class="card-icon">{{ card.icon }}</span>
        <span class="card-title">{{ card.title }}</span>
        <span class="card-desc">{{ card.desc }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 48px 24px;
  text-align: center;
}

.welcome-heading {
  font-size: 32px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.welcome-sub {
  font-size: 15px;
  color: var(--text-secondary);
  max-width: 480px;
  margin-bottom: 40px;
  line-height: 1.7;
}

.suggestion-cards {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: center;
}

.suggestion-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  width: 220px;
  padding: 20px;
  border-radius: 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  transition: border-color 0.15s, transform 0.15s;
  color: var(--text-primary);
}

.suggestion-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}

.card-icon {
  font-size: 28px;
  margin-bottom: 12px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}

.card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}
</style>
