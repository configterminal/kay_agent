<script setup>
/**
 * 面试官 Avatar P0 — 立绘 + CSS 状态动效。
 * 可整文件替换为 Live2D 等，props 契约保持不变。
 */
defineProps({
  /** idle | listening | capturing | thinking | speaking | error */
  state: { type: String, default: 'idle' },
  /** 0~1，P1 口型用；P0 仅作轻微缩放 */
  audioLevel: { type: Number, default: 0 },
  subtitle: { type: String, default: '' },
  /** 立绘资源，可换 */
  src: { type: String, default: '/interview/portrait.svg' },
})
</script>

<template>
  <div
    class="avatar"
    :class="[`is-${state}`]"
    :style="{ '--level': Math.min(1, Math.max(0, audioLevel)) }"
  >
    <div class="avatar-glow" aria-hidden="true" />
    <img class="avatar-img" :src="src" alt="面试官" draggable="false" />
    <div v-if="subtitle && state === 'speaking'" class="avatar-bubble">
      {{ subtitle.length > 80 ? subtitle.slice(0, 80) + '…' : subtitle }}
    </div>
  </div>
</template>

<style scoped>
.avatar {
  position: relative;
  width: min(320px, 70vw);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.avatar-glow {
  position: absolute;
  inset: 8% 12% 18%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(90, 160, 220, 0.35), transparent 70%);
  opacity: 0;
  transition: opacity 0.35s;
  pointer-events: none;
  z-index: 0;
}

.avatar-img {
  position: relative;
  z-index: 1;
  width: 100%;
  height: auto;
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  transition: transform 0.25s ease, filter 0.25s;
  transform: scale(1);
  filter: saturate(0.95);
}

.is-speaking .avatar-glow {
  opacity: 1;
  animation: pulse-glow 1.4s ease-in-out infinite;
}

.is-speaking .avatar-img {
  transform: scale(calc(1.02 + var(--level) * 0.03));
  filter: saturate(1.05) brightness(1.05);
}

.is-listening .avatar-img,
.is-capturing .avatar-img {
  animation: idle-breathe 3.2s ease-in-out infinite;
}

.is-capturing .avatar-glow {
  opacity: 0.55;
  background: radial-gradient(circle, rgba(80, 200, 140, 0.4), transparent 70%);
}

.is-thinking .avatar-img {
  filter: brightness(0.92);
  animation: think-nod 1.8s ease-in-out infinite;
}

.is-error .avatar-img {
  filter: grayscale(0.4) brightness(0.85);
}

.avatar-bubble {
  margin-top: 14px;
  max-width: 100%;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(20, 28, 40, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #e8eef6;
  font-size: 13px;
  line-height: 1.5;
  text-align: center;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.06); }
}

@keyframes idle-breathe {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

@keyframes think-nod {
  0%, 100% { transform: rotate(0deg); }
  40% { transform: rotate(-1.5deg); }
  70% { transform: rotate(1deg); }
}
</style>
